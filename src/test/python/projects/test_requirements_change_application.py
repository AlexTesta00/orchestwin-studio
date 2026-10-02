from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from types import TracebackType
from uuid import UUID

import pytest

from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.models.model_proposals import ModelRequirementsAdapter
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.requirements import (
    RequirementsProposalIssueCode,
    RequirementsProposalProviderKind,
    RequirementsProposalResult,
    RequirementsProposalStatus,
)
from orchestwin.models.requirements_drafts import requirements_context
from orchestwin.projects.requirements_change_application import (
    LocalRequirementsChangeService,
    RequirementsChangeIssueCode,
    RequirementsChangeStatus,
)
from orchestwin.projects.requirements_primitives import RequirementsContextKind
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
    RequirementsRevisionIssueCode,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffOperationKind,
    RequirementsDiffStatus,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.workflow.gates import HumanGateType
from src.test.python.models.test_proposal_evidence import MemoryEvidence, audited_generator
from src.test.python.projects.test_requirements_application import (
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    FakeGovernance,
    approved_gate,
    context_reference,
    governed_context,
)
from src.test.python.projects.test_requirements_journeys import journey_specification
from src.test.python.projects.test_requirements_revisions import (
    InMemoryDiffs,
    InMemorySpecifications,
)

VERSION_ID = UUID("00000000-0000-4000-8000-000000000600")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000601")
NEWER_VERSION_ID = UUID("00000000-0000-4000-8000-000000000602")
PENDING_DIFF_ID = UUID("00000000-0000-4000-8000-000000000603")
OWNER_REQUEST = "Aggiungi l'esportazione delle prenotazioni in PDF"
EDITED_STATEMENT = "The system creates, updates and cancels reservations."


def current_version(context=None):
    context = governed_context() if context is None else context
    proposal = asyncio.run(
        FakeDeterministicRequirementsAdapter().propose(context.to_proposal_request())
    )
    specification = proposal.specification
    return RequirementsSpecificationVersion(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


def pending_diff(version):
    first, *others = version.specification.requirements
    proposed = replace(
        version.specification,
        requirements=(replace(first, title="Create guest reservations"), *others),
    )
    proposal = propose_requirements_diff(
        base_version=version,
        proposed_specification=proposed,
        diff_id=PENDING_DIFF_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    return proposal.diff


def scripted(status=RequirementsProposalStatus.PROPOSED, *, issue=None, specification=None):
    def answer(request):
        proposed = None if specification is None else specification(request)
        return RequirementsProposalResult(
            status=status,
            provider_kind=RequirementsProposalProviderKind.MODEL_ADAPTER,
            provider_id="scripted-requirements",
            provider_version=1,
            specification=proposed,
            issue=issue,
        )

    return answer


class TrackedUnitOfWork:
    def __init__(self, factory):
        self.factory = factory
        self.specifications = factory.specifications
        self.diffs = factory.diffs

    async def __aenter__(self):
        self.factory.open += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.factory.open -= 1

    async def commit(self) -> None:
        self.factory.commits += 1

    async def rollback(self) -> None:
        return None


class TrackedUowFactory:
    def __init__(self, specifications, diffs):
        self.specifications = specifications
        self.diffs = diffs
        self.open = 0
        self.commits = 0

    def __call__(self, *, owner_user_id: UUID):
        assert owner_user_id == OWNER_ID
        return TrackedUnitOfWork(self)


class RecordingPort:
    def __init__(self, factory, outcome=None):
        self.factory = factory
        self.outcome = outcome
        self.during = None
        self.requests = []
        self.open_transactions = []

    async def propose(self, request):
        self.requests.append(request)
        self.open_transactions.append(self.factory.open)
        if self.during is not None:
            self.during()
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if self.outcome is not None:
            return self.outcome(request)
        return await FakeDeterministicRequirementsAdapter().propose(request)


class Harness:
    def __init__(self, *contexts, versions=None, outcome=None, port=None, store=None):
        self.governance = FakeGovernance(*(contexts or (governed_context(),)))
        self.version = current_version()
        self.specifications = InMemorySpecifications(
            *((self.version,) if versions is None else versions)
        )
        self.diffs = InMemoryDiffs()
        self.factory = TrackedUowFactory(self.specifications, self.diffs)
        self.port = RecordingPort(self.factory, outcome)
        self.service = LocalRequirementsChangeService(
            proposal_evidence_store=store,
            governance=self.governance,
            proposals=self.port if port is None else port,
            uow_factory=self.factory,
            revisions=LocalRequirementsRevisionService(
                uow_factory=self.factory,
                uuid_factory=lambda: DIFF_ID,
                clock=lambda: CREATED_AT + timedelta(minutes=5),
            ),
        )

    def run(self, owner_request=OWNER_REQUEST):
        return asyncio.run(
            self.service.request_change(
                owner_user_id=OWNER_ID,
                project_id=PROJECT_ID,
                owner_request=owner_request,
            )
        )


def test_a_change_request_stores_a_proposed_revision_with_its_operations():
    harness = Harness()

    result = harness.run()
    revision = result.revision
    diff = revision.diff
    current = harness.version.specification
    [request] = harness.port.requests
    [operation] = diff.operations

    assert result.status is RequirementsChangeStatus.CREATED
    assert result.issue is None
    assert revision.status is RequirementsRevisionStatus.CREATED
    assert revision.version is None
    assert diff.id == DIFF_ID
    assert diff.status is RequirementsDiffStatus.PROPOSED
    assert diff.base_version_id == VERSION_ID
    assert (operation.operation, operation.display_code) == (
        RequirementsDiffOperationKind.REPLACE,
        "REQ-001",
    )
    assert operation.after.statement == f"{current.requirements[0].statement} ({OWNER_REQUEST})"
    assert harness.diffs.values == {DIFF_ID: diff}
    assert harness.specifications.versions == [harness.version]
    assert request.current_specification == current
    assert request.owner_request == OWNER_REQUEST
    assert request.brief == governed_context().brief
    assert harness.port.open_transactions == [0]
    assert harness.factory.open == 0
    assert harness.governance.calls == 2


def test_explicit_journey_request_uses_current_context_and_keeps_one_pending_revision():
    harness = Harness(
        outcome=scripted(
            specification=lambda request: journey_specification(request.current_specification)
        )
    )
    result = asyncio.run(
        harness.service.request_change(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            owner_request="Richiedi journey per gli scenari correnti.",
            include_journeys=True,
        )
    )
    assert result.status is RequirementsChangeStatus.CREATED
    [request] = harness.port.requests
    assert request.include_journeys is True
    assert request.current_specification == harness.version.specification
    assert request.to_snapshot()["include_journeys"] is True
    assert result.revision.diff.status is RequirementsDiffStatus.PROPOSED
    assert all(
        operation.artifact_kind.value == "JOURNEY"
        and operation.operation is RequirementsDiffOperationKind.ADD
        for operation in result.revision.diff.operations
    )
    assert harness.specifications.versions == [harness.version]
    assert len(harness.diffs.values) == 1


def test_ordinary_change_request_omits_the_journey_flag_in_model_snapshot():
    harness = Harness()
    harness.run()
    [request] = harness.port.requests
    assert request.include_journeys is False
    assert "include_journeys" not in request.to_snapshot()


def test_explicit_journey_request_respects_the_existing_pending_revision_guard():
    harness = Harness()
    pending = pending_diff(harness.version)
    harness.diffs.values[pending.id] = pending
    result = asyncio.run(
        harness.service.request_change(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            owner_request="Richiedi journey.",
            include_journeys=True,
        )
    )
    assert result.issue is RequirementsChangeIssueCode.REVISION_PENDING
    assert harness.port.requests == []


@pytest.mark.parametrize(
    ("context", "code"),
    [
        (None, "PROJECT_NOT_FOUND"),
        (replace(governed_context(), brief_gate=None), "BRIEF_APPROVAL_REQUIRED"),
        (replace(governed_context(), team_gate=None), "TEAM_APPROVAL_REQUIRED"),
        (replace(governed_context(), user_modeling_gate=None), "USER_MODELING_APPROVAL_REQUIRED"),
    ],
    ids=["project", "brief", "team", "user-modeling"],
)
def test_a_change_keeps_the_refusals_of_the_generation(context, code):
    harness = Harness(context)

    result = harness.run()

    assert result.status is RequirementsChangeStatus.REJECTED
    assert result.issue is RequirementsChangeIssueCode(code)
    assert result.issue.value == code
    assert harness.port.requests == []
    assert harness.diffs.values == {}


def test_a_project_without_requirements_is_refused_before_the_model():
    harness = Harness(versions=())

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.SPECIFICATION_NOT_FOUND
    assert result.issue.value == "REQUIREMENTS_SPECIFICATION_NOT_FOUND"
    assert harness.port.requests == []


def test_a_pending_revision_is_refused_before_the_model():
    harness = Harness()
    pending = pending_diff(harness.version)
    harness.diffs.values[pending.id] = pending

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.REVISION_PENDING
    assert result.issue.value == "REQUIREMENTS_REVISION_PENDING"
    assert harness.port.requests == []
    assert harness.diffs.values == {PENDING_DIFF_ID: pending}


def test_requirements_written_for_an_older_context_are_refused_before_the_model():
    context = governed_context()
    reference = context_reference(RequirementsContextKind.PROJECT_BRIEF, 14)
    newer = replace(
        context,
        brief=replace(context.brief, reference=reference),
        brief_gate=approved_gate(HumanGateType.PROJECT_BRIEF, reference),
    )
    harness = Harness(newer)

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.CONTEXT_CHANGED
    assert result.issue.value == "REQUIREMENTS_CONTEXT_CHANGED"
    assert harness.port.requests == []


def test_a_context_changed_while_the_model_writes_stores_nothing():
    initial = governed_context()
    changed = replace(initial, brief=replace(initial.brief, name="Changed Hotel Operations"))
    harness = Harness(initial, changed)

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.CONTEXT_CHANGED
    assert len(harness.port.requests) == 1
    assert harness.diffs.values == {}


def test_requirements_changed_while_the_model_writes_store_nothing():
    harness = Harness()
    newer = replace(
        harness.version,
        id=NEWER_VERSION_ID,
        version_number=2,
        based_on_version_number=1,
    )
    harness.port.during = lambda: harness.specifications.versions.append(newer)

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.CONTEXT_CHANGED
    assert harness.diffs.values == {}


def test_a_revision_proposed_while_the_model_writes_wins():
    harness = Harness()
    pending = pending_diff(harness.version)
    harness.port.during = lambda: harness.diffs.values.setdefault(pending.id, pending)

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.REVISION_PENDING
    assert result.revision.issue is RequirementsRevisionIssueCode.DIFF_ALREADY_PENDING
    assert harness.diffs.values == {PENDING_DIFF_ID: pending}


def test_a_specification_equal_to_the_current_one_is_refused_and_not_stored():
    harness = Harness(outcome=scripted(specification=lambda request: request.current_specification))

    result = harness.run()

    assert result.status is RequirementsChangeStatus.REJECTED
    assert result.issue is RequirementsChangeIssueCode.UNCHANGED
    assert result.issue.value == "REQUIREMENTS_UNCHANGED"
    assert harness.diffs.values == {}


def test_a_rejected_proposal_keeps_the_issue_of_the_provider():
    harness = Harness(
        outcome=scripted(
            RequirementsProposalStatus.REJECTED,
            issue=RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED,
        )
    )

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.PROPOSAL_REJECTED
    assert result.proposal_issue is RequirementsProposalIssueCode.GROUNDED_INPUT_REQUIRED
    assert harness.diffs.values == {}


def test_a_proposal_grounded_in_another_context_is_invalid():
    harness = Harness(
        outcome=scripted(
            specification=lambda request: replace(
                request.current_specification,
                project_brief_reference=context_reference(
                    RequirementsContextKind.PROJECT_BRIEF,
                    14,
                ),
            )
        )
    )

    result = harness.run()

    assert result.issue is RequirementsChangeIssueCode.INVALID_PROPOSAL
    assert harness.diffs.values == {}


def test_a_provider_failure_propagates_and_stores_nothing():
    harness = Harness(outcome=ProposalGenerationError("TIMEOUT"))

    with pytest.raises(ProposalGenerationError, match="TIMEOUT"):
        harness.run()

    assert harness.diffs.values == {}
    assert harness.factory.open == 0


@pytest.mark.parametrize(
    ("edit", "status", "issue"),
    [(True, "CREATED", None), (False, "REJECTED", "REQUIREMENTS_UNCHANGED")],
    ids=["changed", "unchanged"],
)
def test_the_generation_of_a_change_is_recorded_with_its_own_purpose(tmp_path, edit, status, issue):
    context = governed_context()
    version = current_version(context)
    change = replace(
        context.to_proposal_request(),
        current_specification=version.specification,
        owner_request=OWNER_REQUEST,
    )
    model_context, _, _ = requirements_context(change)
    answer = deepcopy(model_context["current_requirements"])
    if edit:
        answer["requirements"][0]["statement"] = EDITED_STATEMENT
    generator, _ = audited_generator(tmp_path, answer)
    store = MemoryEvidence()
    harness = Harness(port=ModelRequirementsAdapter(generator), store=store)

    result = harness.run()
    [(generation, scope)] = store.requests.values()
    events = store.events[generation.request_id]

    assert result.status.value == status
    assert [kind for kind, _, _ in events] == [
        "HTTP_REQUEST",
        "HTTP_RESPONSE",
        "PROVIDER_RESULT",
        "ADAPTER_ACCEPTED",
        "APPLICATION_RESULT",
    ]
    assert events[-1][1] == {"status": status, "issue": issue}
    assert scope == {"owner_user_id": OWNER_ID, "project_id": PROJECT_ID}
    assert generation.task_id == "proposal-requirements-v1"
    assert json.loads(generation.input_payload_json)["context"]["purpose"] == (
        "REQUIREMENTS_CHANGE"
    )
    if edit:
        [operation] = result.revision.diff.operations
        assert operation.after.statement == EDITED_STATEMENT
        assert operation.after.id == version.specification.requirements[0].id
