from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_application import (
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
    RequirementsDiffPersistenceStatus,
    RequirementsRevisionDecision,
    RequirementsRevisionIssueCode,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffOperationKind,
    RequirementsDiffProposalIssueCode,
    RequirementsDiffProposalStatus,
    RequirementsDiffStatus,
    propose_requirements_diff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
BASE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000070")
DIFF_ID = UUID("00000000-0000-4000-8000-000000000080")
NEXT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000090")
STALE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000091")
CREATED_AT = datetime(2026, 8, 18, 11, 0, tzinfo=UTC)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def source() -> RequirementSourceReference:
    """Create one exact Project Brief source."""
    return RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )


def specification(
    statement: str = "The system must create reservations.",
):
    """Create one complete specification with a replaceable requirement."""
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement=statement,
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source(),),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )

    return create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )


def base_version() -> RequirementsSpecificationVersion:
    """Create immutable requirements version one."""
    value = specification()

    return RequirementsSpecificationVersion(
        id=BASE_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=value,
        content_hash=value.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )


class InMemorySpecifications:
    """Minimal append-only specification repository."""

    def __init__(self, *versions: RequirementsSpecificationVersion) -> None:
        self.versions = list(versions)

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        values = [value for value in self.versions if value.project_id == project_id]
        return values[-1] if values else None

    async def append(
        self,
        version: RequirementsSpecificationVersion,
    ) -> RequirementsVersionAppendStatus:
        self.versions.append(version)
        return RequirementsVersionAppendStatus.APPENDED


class InMemoryDiffs:
    """Minimal reviewable-diff repository."""

    def __init__(self) -> None:
        self.values = {}

    async def create(self, diff):
        self.values[diff.id] = diff
        return RequirementsDiffPersistenceStatus.CREATED

    async def get(self, *, project_id: UUID, diff_id: UUID):
        value = self.values.get(diff_id)
        return value if value is not None and value.project_id == project_id else None

    async def current_proposed(self, *, project_id: UUID, base_version_id: UUID):
        return next(
            (
                value
                for value in self.values.values()
                if value.project_id == project_id
                and value.base_version_id == base_version_id
                and value.status is RequirementsDiffStatus.PROPOSED
            ),
            None,
        )

    async def save_decision(self, diff):
        current = self.values.get(diff.id)

        if current is None or current.status is not RequirementsDiffStatus.PROPOSED:
            return RequirementsDiffPersistenceStatus.CONFLICT

        self.values[diff.id] = diff
        return RequirementsDiffPersistenceStatus.UPDATED


class InMemoryUnitOfWork:
    """Share specification and diff state across transactions."""

    def __init__(self, specifications, diffs) -> None:
        self.specifications = specifications
        self.diffs = diffs

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class InMemoryUowFactory:
    """Create Units of Work over shared state."""

    def __init__(self, specifications, diffs) -> None:
        self.specifications = specifications
        self.diffs = diffs

    def __call__(self, *, owner_user_id: UUID):
        assert owner_user_id == OWNER_ID
        return InMemoryUnitOfWork(self.specifications, self.diffs)


def revision_service(
    specifications: InMemorySpecifications,
    diffs: InMemoryDiffs,
) -> LocalRequirementsRevisionService:
    """Create a service with deterministic IDs and time."""
    identifiers = iter((DIFF_ID, NEXT_VERSION_ID))

    return LocalRequirementsRevisionService(
        uow_factory=InMemoryUowFactory(specifications, diffs),
        uuid_factory=lambda: next(identifiers),
        clock=lambda: CREATED_AT + timedelta(minutes=5),
    )


def test_domain_diff_preserves_before_after_and_stable_identity() -> None:
    """Represent a content change as one explicit replacement operation."""
    base = base_version()
    proposal = propose_requirements_diff(
        base_version=base,
        proposed_specification=specification(
            "The system must create, update, and cancel reservations."
        ),
        diff_id=DIFF_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert proposal.status is RequirementsDiffProposalStatus.CREATED
    assert proposal.diff is not None
    assert len(proposal.diff.operations) == 1

    operation = proposal.diff.operations[0]

    assert operation.operation is RequirementsDiffOperationKind.REPLACE
    assert operation.before is not None
    assert operation.after is not None
    assert operation.before.id == operation.after.id == REQUIREMENT_ID
    assert operation.before.code == operation.after.code == "REQ-001"


def test_domain_diff_rejects_display_code_identity_changes() -> None:
    """Keep readable codes bound to the same immutable identity."""
    base = base_version()
    changed_requirement = replace(
        base.specification.requirements[0],
        code="REQ-002",
    )
    proposed = replace(
        base.specification,
        requirements=(changed_requirement,),
    )

    result = propose_requirements_diff(
        base_version=base,
        proposed_specification=proposed,
        diff_id=DIFF_ID,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=1),
    )

    assert result.status is RequirementsDiffProposalStatus.REJECTED
    assert result.issue is RequirementsDiffProposalIssueCode.IDENTITY_CHANGED


def test_application_approval_creates_version_two_without_mutating_version_one() -> None:
    """Apply an approved diff as a new immutable specification version."""
    base = base_version()
    specifications = InMemorySpecifications(base)
    diffs = InMemoryDiffs()
    service = revision_service(specifications, diffs)
    proposed_specification = specification(
        "The system must create, update, and cancel reservations."
    )

    proposal = asyncio.run(
        service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_specification=proposed_specification,
        )
    )
    decision = asyncio.run(
        service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=DIFF_ID,
            decision=RequirementsRevisionDecision.APPROVE,
        )
    )

    assert proposal.status is RequirementsRevisionStatus.CREATED
    assert decision.status is RequirementsRevisionStatus.APPLIED
    assert decision.diff is not None
    assert decision.diff.status is RequirementsDiffStatus.APPROVED
    assert decision.version is not None
    assert decision.version.id == NEXT_VERSION_ID
    assert decision.version.version_number == 2
    assert decision.version.based_on_version_number == 1
    assert specifications.versions[0] == base
    assert specifications.versions[0].specification.requirements[0].statement == (
        "The system must create reservations."
    )
    assert specifications.versions[1] == decision.version


def test_rejection_requires_reason_and_creates_no_version() -> None:
    """Reject an owner diff only with explicit rationale."""
    specifications = InMemorySpecifications(base_version())
    diffs = InMemoryDiffs()
    service = revision_service(specifications, diffs)

    proposal = asyncio.run(
        service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_specification=specification("The system must create and cancel reservations."),
        )
    )
    assert proposal.diff is not None

    decision = asyncio.run(
        service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=RequirementsRevisionDecision.REJECT,
            reason=None,
        )
    )

    assert decision.status is RequirementsRevisionStatus.REJECTED
    assert decision.issue is RequirementsRevisionIssueCode.DECISION_REJECTED
    assert len(specifications.versions) == 1


def test_approval_rejects_a_diff_when_the_base_version_is_no_longer_current() -> None:
    """Prevent a stale owner proposal from overwriting a newer baseline."""
    base = base_version()
    specifications = InMemorySpecifications(base)
    diffs = InMemoryDiffs()
    service = revision_service(specifications, diffs)

    proposal = asyncio.run(
        service.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_specification=specification("The system must create and cancel reservations."),
        )
    )
    assert proposal.diff is not None

    stale_specification = specification("The system must create and archive reservations.")
    specifications.versions.append(
        RequirementsSpecificationVersion(
            id=STALE_VERSION_ID,
            project_id=PROJECT_ID,
            version_number=2,
            based_on_version_number=1,
            specification=stale_specification,
            content_hash=stale_specification.content_hash,
            created_by_user_id=OWNER_ID,
            created_at=CREATED_AT + timedelta(minutes=3),
        )
    )

    decision = asyncio.run(
        service.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=RequirementsRevisionDecision.APPROVE,
        )
    )

    assert decision.status is RequirementsRevisionStatus.REJECTED
    assert decision.issue is RequirementsRevisionIssueCode.CONTEXT_CHANGED
    assert len(specifications.versions) == 2
