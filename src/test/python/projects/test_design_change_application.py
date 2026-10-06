from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    DesignRevisionApplicationIssueCode,
    DesignRevisionStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignPackageDiffStatus,
)
from orchestwin.models.design_change import INSTRUCTION, PURPOSE, TASK
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.design_change_application import (
    DesignChangeApplication,
    DesignChangeIssueCode,
    DesignChangeStatus,
)
from orchestwin.projects.requirements_primitives import snapshot_content_hash
from src.test.python.api.test_code_changes_api import BRIEF, FakeGenerator, MemoryEvidence
from src.test.python.api.test_design_api import proposed_diff
from src.test.python.artifacts.design_fixtures import (
    ALTERNATIVE_ONE_ID,
    ALTERNATIVE_TWO_ID,
    OWNER_ID,
    PROJECT_ID,
    design_package,
    design_version,
    requirements_version,
)

DIFF_ID = UUID("00000000-0000-4000-8000-000000000d10")
NOW = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
LOCALE = "en-US"
OWNER_REQUEST = "Add a confirmation step before the reservation is saved."
CHANGE = "The guided flow asks for a confirmation before saving the reservation."
CONFIRMATION = "Confirm the reservation."
SUMMARY = "Guide the receptionist through one decision at a time and confirm before saving."
MISSING = object()


def returning(value):
    async def answer(**_scope):
        return value

    return answer


def chosen_alternative(version=None):
    version = design_version() if version is None else version
    package = version.package
    return next(
        item for item in package.alternatives if item.id == package.owner_selected_alternative_id
    )


def change_answer(**values):
    alternative = chosen_alternative()
    answer = {
        "accessibility_considerations": list(alternative.accessibility_considerations),
        "advantages": list(alternative.advantages),
        "assumptions": list(alternative.assumptions),
        "changes": [CHANGE],
        "information_architecture": list(alternative.information_architecture),
        "open_questions": list(alternative.open_questions),
        "rationale": alternative.rationale,
        "security_considerations": list(alternative.security_considerations),
        "summary": alternative.summary,
        "trade_offs": list(alternative.trade_offs),
        "workflows": [
            {
                "code": item.code,
                "requirement_codes": ["REQ-001"],
                "steps": list(item.steps),
                "title": item.title,
            }
            for item in alternative.workflows
        ],
    }
    answer.update(values)
    return answer


def confirmed_answer(**values):
    [workflow] = chosen_alternative().workflows
    return change_answer(
        summary=SUMMARY,
        workflows=[
            {
                "code": workflow.code,
                "requirement_codes": ["REQ-001"],
                "steps": [*workflow.steps, CONFIRMATION],
                "title": workflow.title,
            }
        ],
        **values,
    )


def blank_step_answer():
    [workflow] = chosen_alternative().workflows
    return change_answer(
        workflows=[
            {
                "code": workflow.code,
                "requirement_codes": ["REQ-001"],
                "steps": [*workflow.steps, "   "],
                "title": workflow.title,
            }
        ]
    )


class Packages:
    def __init__(self, current):
        self.value = current

    async def current(self, *, project_id):
        if self.value is None or self.value.project_id != project_id:
            return None
        return self.value

    async def append(self, version):
        raise AssertionError("a design change proposes a revision and appends no version")


class Diffs:
    def __init__(self):
        self.value = None
        self.created = []

    async def create(self, diff):
        self.value = diff
        self.created.append(diff)
        return DesignDiffPersistenceStatus.CREATED

    async def get(self, *, project_id, diff_id):
        if self.value is None or self.value.id != diff_id or self.value.project_id != project_id:
            return None
        return self.value

    async def current_proposed(self, *, project_id, base_version_id):
        if (
            self.value is not None
            and self.value.project_id == project_id
            and self.value.base_version_id == base_version_id
            and self.value.status is DesignPackageDiffStatus.PROPOSED
        ):
            return self.value
        return None

    async def history(self, *, project_id):
        return () if self.value is None else (self.value,)

    async def save_decision(self, diff):
        self.value = diff
        return DesignDiffPersistenceStatus.UPDATED


class UnitOfWork:
    def __init__(self, factory):
        self.factory = factory
        self.packages = factory.packages
        self.diffs = factory.diffs

    async def __aenter__(self):
        self.factory.open += 1
        return self

    async def __aexit__(self, *_):
        self.factory.open -= 1

    async def commit(self):
        self.factory.commits += 1

    async def rollback(self):
        return None


class UowFactory:
    def __init__(self, packages, diffs):
        self.packages = packages
        self.diffs = diffs
        self.open = 0
        self.commits = 0

    def __call__(self, *, owner_user_id):
        assert owner_user_id == OWNER_ID
        return UnitOfWork(self)


class RacingGenerator(FakeGenerator):
    def __init__(self, during, *outcomes):
        super().__init__(*outcomes)
        self.during = during

    async def generate(self, **kwargs):
        self.during()
        return await super().generate(**kwargs)


class Harness:
    def __init__(
        self,
        *outcomes,
        version=MISSING,
        brief=BRIEF,
        requirements=MISSING,
        generator=MISSING,
        evidence=True,
        pending=None,
    ):
        self.version = design_version() if version is MISSING else version
        self.packages = Packages(self.version)
        self.diffs = Diffs()
        if pending is not None:
            self.diffs.value = pending
        self.factory = UowFactory(self.packages, self.diffs)
        self.generator = FakeGenerator(*outcomes) if generator is MISSING else generator
        self.evidence = MemoryEvidence() if evidence else None
        self.revisions = LocalDesignRevisionService(
            uow_factory=self.factory, uuid_factory=lambda: DIFF_ID, clock=lambda: NOW
        )
        self.service = DesignChangeApplication(
            proposal_evidence_store=self.evidence,
            generator=self.generator,
            project_service=SimpleNamespace(
                current_brief=returning(None if brief is None else SimpleNamespace(brief=brief))
            ),
            requirements_query_service=SimpleNamespace(
                current=returning(
                    requirements_version() if requirements is MISSING else requirements
                )
            ),
            uow_factory=self.factory,
            revisions=self.revisions,
        )

    @property
    def calls(self):
        return [] if self.generator is None else self.generator.calls

    def run(self, owner_request=OWNER_REQUEST, **values):
        return asyncio.run(
            self.service.request_change(
                owner_user_id=OWNER_ID,
                project_id=PROJECT_ID,
                owner_request=owner_request,
                **values,
            )
        )


def test_a_change_proposes_a_revision_with_the_changed_alternative_only():
    harness = Harness(confirmed_answer())

    result = harness.run(locale=LOCALE)

    assert result.status is DesignChangeStatus.CREATED
    assert result.issue is None
    assert result.changes == (CHANGE,)
    revision = result.revision
    diff = revision.diff
    assert revision.status is DesignRevisionStatus.CREATED
    assert (diff.id, diff.status, diff.base_version_id) == (
        DIFF_ID,
        DesignPackageDiffStatus.PROPOSED,
        harness.version.id,
    )
    [change] = diff.changes
    assert (change.kind, change.artifact_kind, change.artifact_id) == (
        DesignChangeKind.REPLACE,
        DesignArtifactKind.ALTERNATIVE,
        ALTERNATIVE_ONE_ID,
    )
    proposed = {item.id: item for item in diff.proposed_package.alternatives}
    current = {item.id: item for item in harness.version.package.alternatives}
    changed = proposed[ALTERNATIVE_ONE_ID]
    assert proposed[ALTERNATIVE_TWO_ID] == current[ALTERNATIVE_TWO_ID]
    assert changed.summary == SUMMARY
    assert changed.workflows[0].steps == (
        *current[ALTERNATIVE_ONE_ID].workflows[0].steps,
        CONFIRMATION,
    )
    assert changed.workflows[0].id == current[ALTERNATIVE_ONE_ID].workflows[0].id
    assert (changed.title, changed.approach, changed.visual_language) == (
        current[ALTERNATIVE_ONE_ID].title,
        current[ALTERNATIVE_ONE_ID].approach,
        current[ALTERNATIVE_ONE_ID].visual_language,
    )
    assert diff.proposed_package.prototype == harness.version.package.prototype
    assert harness.diffs.created == [diff]
    assert (harness.factory.open, harness.factory.commits) == (0, 1)
    [call] = harness.calls
    assert (call["task"], call["instruction"], call["retry_schema_errors"]) == (
        TASK,
        INSTRUCTION,
        False,
    )
    context = call["context"]
    assert (context["purpose"], context["locale"], context["owner_request"]) == (
        PURPOSE,
        LOCALE,
        OWNER_REQUEST,
    )
    assert context["project_brief"]["name"] == "Lista ospiti"
    assert context["alternative"]["code"] == "DES-001"
    assert [item["code"] for item in context["alternative"]["workflows"]] == ["FLOW-001"]
    assert [item["code"] for item in context["screens"]] == ["SCR-001", "SCR-002"]
    assert list(context["requirements"]) == ["requirements", "stories", "criteria"]
    evidence = harness.evidence
    assert evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]
    assert evidence.payloads("ADAPTER_ACCEPTED") == [
        {
            "result": changed.to_snapshot(),
            "generated_content_hashes": {PURPOSE: [snapshot_content_hash(changed.to_snapshot())]},
        }
    ]
    assert evidence.payloads("APPLICATION_RESULT") == [{"status": "CREATED", "issue": None}]


def test_an_unchanged_alternative_is_refused_after_the_model_answers():
    harness = Harness(change_answer())

    result = harness.run(locale=LOCALE)

    assert result.status is DesignChangeStatus.REJECTED
    assert result.issue is DesignChangeIssueCode.UNCHANGED
    assert result.issue.value == "DESIGN_UNCHANGED"
    assert (result.revision, result.changes) == (None, ())
    assert len(harness.calls) == 1
    assert harness.diffs.created == []
    current = chosen_alternative().to_snapshot()
    assert harness.evidence.kinds() == [(0, "ADAPTER_ACCEPTED"), (0, "APPLICATION_RESULT")]
    assert harness.evidence.payloads("ADAPTER_ACCEPTED")[0]["result"] == current
    assert harness.evidence.payloads("APPLICATION_RESULT") == [
        {"status": "REJECTED", "issue": "DESIGN_UNCHANGED"}
    ]


def test_the_locale_defaults_to_italian():
    harness = Harness(change_answer(changes=["Il flusso resta uguale."]))

    result = harness.run()

    assert result.issue is DesignChangeIssueCode.UNCHANGED
    [call] = harness.calls
    assert call["context"]["locale"] == "it-IT"


@pytest.mark.parametrize(
    ("settings", "issue", "code"),
    [
        ({"brief": None}, DesignChangeIssueCode.PROJECT_NOT_FOUND, "PROJECT_NOT_FOUND"),
        ({"version": None}, DesignChangeIssueCode.DESIGN_NOT_FOUND, "DESIGN_PACKAGE_NOT_FOUND"),
        (
            {"version": design_version(package=design_package(selected=False))},
            DesignChangeIssueCode.ALTERNATIVE_NOT_CHOSEN,
            "DESIGN_ALTERNATIVE_NOT_CHOSEN",
        ),
        (
            {"pending": proposed_diff(design_version())},
            DesignChangeIssueCode.REVISION_PENDING,
            "DESIGN_REVISION_PENDING",
        ),
        (
            {"requirements": None},
            DesignChangeIssueCode.SPECIFICATION_NOT_FOUND,
            "REQUIREMENTS_SPECIFICATION_NOT_FOUND",
        ),
        (
            {"generator": None},
            DesignChangeIssueCode.MODEL_NOT_CONFIGURED,
            "DESIGN_CHANGE_MODEL_NOT_CONFIGURED",
        ),
        (
            {"evidence": False},
            DesignChangeIssueCode.MODEL_NOT_CONFIGURED,
            "DESIGN_CHANGE_MODEL_NOT_CONFIGURED",
        ),
        (
            {"version": design_version(package=design_package(include_prototype=False))},
            DesignChangeIssueCode.PROTOTYPE_REQUIRED,
            "DESIGN_PROTOTYPE_REQUIRED",
        ),
    ],
    ids=[
        "project",
        "design",
        "alternative",
        "pending",
        "requirements",
        "model",
        "evidence",
        "prototype",
    ],
)
def test_a_change_is_refused_before_the_model_when_the_project_is_not_ready(settings, issue, code):
    harness = Harness(confirmed_answer(), **settings)

    result = harness.run(locale=LOCALE)

    assert result.status is DesignChangeStatus.REJECTED
    assert result.issue is issue
    assert result.issue.value == code
    assert (result.revision, result.changes) == (None, ())
    assert harness.calls == []
    assert harness.diffs.created == []
    assert harness.factory.open == 0


def test_an_invalid_answer_is_asked_once_more():
    harness = Harness(blank_step_answer(), confirmed_answer())

    result = harness.run(locale=LOCALE)

    assert result.status is DesignChangeStatus.CREATED
    assert len(harness.calls) == 2
    assert harness.calls[0]["context"] == harness.calls[1]["context"]
    evidence = harness.evidence
    assert evidence.kinds() == [
        (0, "ADAPTER_REJECTED"),
        (0, "APPLICATION_RESULT"),
        (1, "ADAPTER_ACCEPTED"),
        (1, "APPLICATION_RESULT"),
    ]
    [rejected] = evidence.payloads("ADAPTER_REJECTED")
    assert rejected["code"] == "DESIGN_CHANGE_INVALID"
    assert evidence.payloads("APPLICATION_RESULT")[0] == {
        "status": "DESIGN_CHANGE_REJECTED",
        "design_version_id": str(harness.version.id),
    }
    [accepted] = evidence.payloads("ADAPTER_ACCEPTED")
    assert [(item["role"], item["code"]) for item in accepted["related_generations"]] == [
        ("DESIGN_CHANGE", "DESIGN_CHANGE_REJECTED")
    ]


@pytest.mark.parametrize(
    ("outcomes", "code", "calls"),
    [
        ((blank_step_answer(), blank_step_answer()), "INVALID_PROVIDER_OUTPUT", 2),
        (
            (ProposalGenerationError("RESPONSE_SCHEMA_ERROR"), blank_step_answer()),
            "INVALID_PROVIDER_OUTPUT",
            2,
        ),
        ((ProposalGenerationError("TIMEOUT"),), "TIMEOUT", 1),
        ((ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),), "GENERATION_BUDGET_EXCEEDED", 1),
    ],
    ids=["twice-invalid", "schema-then-invalid", "timeout", "budget"],
)
def test_a_failed_generation_propagates_and_stores_nothing(outcomes, code, calls):
    harness = Harness(*outcomes)

    with pytest.raises(ProposalGenerationError) as error:
        harness.run(locale=LOCALE)

    assert error.value.code == code
    assert len(harness.calls) == calls
    assert harness.diffs.created == []
    assert harness.factory.open == 0
    assert harness.evidence.events[-1][2] == {"status": "FAILED", "code": code}


def test_a_revision_proposed_while_the_model_writes_wins():
    pending = proposed_diff(design_version())
    harness = Harness(generator=None)
    harness.generator = RacingGenerator(
        lambda: setattr(harness.diffs, "value", pending), confirmed_answer()
    )
    harness.service._generator = harness.generator

    result = harness.run(locale=LOCALE)

    assert result.status is DesignChangeStatus.REJECTED
    assert result.issue is DesignChangeIssueCode.REVISION_PENDING
    assert result.revision.issue is DesignRevisionApplicationIssueCode.DIFF_ALREADY_PENDING
    assert result.revision.diff == pending
    assert result.changes == (CHANGE,)
    assert harness.diffs.created == []
    assert harness.evidence.payloads("APPLICATION_RESULT") == [
        {"status": "REJECTED", "issue": "DESIGN_REVISION_PENDING"}
    ]
