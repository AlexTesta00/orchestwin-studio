from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import (
    DesignPackagePayload,
    create_design_router,
)
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_gate import (
    DesignGateDecisionResult,
    DesignGateDecisionStatus,
    DesignGateSubmissionResult,
    DesignGateSubmissionStatus,
    DesignReadinessResult,
    DesignWorkflowReadiness,
    design_artifact_reference,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_revision_application import (
    DesignRevisionResult,
    DesignRevisionStatus,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignRevisionDecision,
    decide_design_revision,
    propose_design_revision,
)
from orchestwin.artifacts.visual_directions import (
    DirectionColour,
    DirectionDensity,
    DirectionLayout,
    DirectionShape,
    DirectionType,
)
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.design import DesignProposalIssueCode
from orchestwin.projects.design_application import (
    DesignGenerationIssueCode,
    DesignGenerationResult,
    DesignGenerationStatus,
    DesignVersionAppendStatus,
)
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionState
from orchestwin.projects.sections_service import SectionsFailure
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from src.test.python.api.test_design_context import sections_port
from src.test.python.artifacts.test_design_package_extension import (
    ASSERTIONS,
    VERDICTS,
    fixture_package,
)
from src.test.python.artifacts.test_visual_directions import directed_package, direction

FIXTURE_PATH = Path(__file__).resolve().parents[1] / "artifacts" / "design_fixtures.py"
DIFF_ID = UUID("00000000-0000-4000-8000-000000000701")
GATE_ID = UUID("00000000-0000-4000-8000-000000000702")
NOW = datetime(2026, 8, 20, 15, 0, tzinfo=UTC)


def load_design_fixtures() -> ModuleType:
    """Load the shared Sprint 06 fixtures without production imports."""
    spec = importlib.util.spec_from_file_location(
        "design_api_fixtures",
        FIXTURE_PATH,
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load Design API fixtures")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


FIXTURES = load_design_fixtures()
PROJECT_ID: UUID = FIXTURES.PROJECT_ID
OWNER_ID: UUID = FIXTURES.OWNER_ID


def design_version() -> DesignPackageVersion:
    """Create one ready immutable Design Package version."""
    return FIXTURES.design_version()


def user() -> UserAccount:
    """Create one authenticated project owner."""
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def proposed_diff(version: DesignPackageVersion) -> DesignPackageDiff:
    """Create one valid owner-reviewable Design Package replacement."""
    package = replace(
        version.package,
        open_questions=(
            *version.package.open_questions,
            "Should expert shortcuts be visible in the prototype?",
        ),
    )
    proposal = propose_design_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=version,
        proposed_package=package,
        created_at=NOW + timedelta(minutes=1),
    )

    assert proposal.diff is not None

    return proposal.diff


def approved_gate(
    version: DesignPackageVersion,
) -> tuple[HumanGate, HumanGateEvent]:
    """Create one approved Gate 5 and its approval event."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.DESIGN,
        artifact=design_artifact_reference(version),
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=1),
        event_id=UUID(int=801),
    )
    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=NOW + timedelta(minutes=2),
        event_id=UUID(int=802),
    )

    assert approved.event is not None

    return approved.gate, approved.event


class FakeGenerationService:
    """Return one generated Design Package version."""

    def __init__(self, version: DesignPackageVersion) -> None:
        self.version = version
        self.calls: list[tuple[UUID, UUID]] = []
        self.refusal: DesignGenerationResult | None = None

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignGenerationResult:
        self.calls.append((owner_user_id, project_id))

        if self.refusal is not None:
            return self.refusal

        return DesignGenerationResult(
            status=DesignGenerationStatus.CREATED,
            version=self.version,
        )


class FakeQueryService:
    """Return configurable versions and revision diffs."""

    def __init__(self, version: DesignPackageVersion, diff: DesignPackageDiff) -> None:
        self.version: DesignPackageVersion | None = version
        self.diffs: list[DesignPackageDiff] = [diff]

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignPackageVersion | None:
        del owner_user_id, project_id
        return self.version

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[DesignPackageVersion, ...]:
        del owner_user_id, project_id
        return () if self.version is None else (self.version,)

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> DesignPackageDiff | None:
        del owner_user_id, project_id
        return next((diff for diff in self.diffs if diff.id == diff_id), None)

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[DesignPackageDiff, ...]:
        del owner_user_id, project_id
        return tuple(self.diffs)


class FakeRevisionService:
    """Capture complete package replacements and owner decisions."""

    def __init__(self, version: DesignPackageVersion, diff: DesignPackageDiff) -> None:
        self.version = version
        self.diff = diff
        self.proposed = None
        self.decisions: list[tuple[UUID, DesignRevisionDecision, str | None]] = []

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_package,
    ) -> DesignRevisionResult:
        del owner_user_id, project_id
        self.proposed = proposed_package

        return DesignRevisionResult(
            status=DesignRevisionStatus.CREATED,
            diff=self.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: DesignRevisionDecision,
        reason: str | None = None,
    ) -> DesignRevisionResult:
        del project_id
        self.decisions.append((diff_id, decision, reason))
        domain = decide_design_revision(
            diff=self.diff,
            current_version=self.version,
            decision=decision,
            actor_user_id=owner_user_id,
            occurred_at=NOW + timedelta(minutes=3),
            resulting_version_id=(
                UUID(int=803) if decision is DesignRevisionDecision.APPROVE else None
            ),
            reason=reason,
        )

        return DesignRevisionResult(
            status=DesignRevisionStatus.APPLIED,
            diff=domain.diff,
            version=domain.version,
        )


class FakeGateService:
    """Return an approved Gate 5 fixture."""

    def __init__(self, version: DesignPackageVersion) -> None:
        self.version = version
        self.gate, self.event = approved_gate(version)
        self.decisions: list[tuple[HumanGateAction, str | None]] = []

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignGateSubmissionResult:
        del project_id, owner_user_id
        return DesignGateSubmissionResult(
            status=DesignGateSubmissionStatus.ALREADY_APPROVED,
            gate=self.gate,
        )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> DesignGateDecisionResult:
        del project_id, owner_user_id
        self.decisions.append((action, reason))
        return DesignGateDecisionResult(
            status=DesignGateDecisionStatus.APPLIED,
            gate=self.gate,
            event=self.event,
        )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignReadinessResult:
        del project_id, owner_user_id
        return DesignReadinessResult(
            status=DesignWorkflowReadiness.READY_FOR_ARCHITECTURE_PLANNING,
            version=self.version,
            gate=self.gate,
        )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate:
        del project_id, owner_user_id
        return self.gate

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        del project_id, owner_user_id, gate_id
        return (self.event,)


def client_fixture():
    """Create an isolated Design API app and its service doubles."""
    version = design_version()
    diff = proposed_diff(version)
    generation = FakeGenerationService(version)
    queries = FakeQueryService(version, diff)
    revisions = FakeRevisionService(version, diff)
    gates = FakeGateService(version)
    app = FastAPI()
    app.state.design_generation_service = generation
    app.state.design_query_service = queries
    app.state.design_revision_service = revisions
    app.state.design_gate_service = gates
    app.include_router(create_design_router())
    app.dependency_overrides[current_user_dependency] = user

    return TestClient(app), generation, queries, revisions, gates


def path(suffix: str = "") -> str:
    """Return one project-scoped Design API path."""
    return f"/projects/{PROJECT_ID}/design{suffix}"


def test_design_package_payload_round_trips_the_canonical_domain_snapshot() -> None:
    """Preserve every typed design, critique, provenance, and prototype field."""
    package = design_version().package

    payload = DesignPackagePayload.from_domain(package)

    assert payload.to_domain() == package
    assert payload.critiques[0].epistemic_status.value == "MODEL_INFERRED"
    assert payload.critiques[0].human_validation.value == "REQUIRED"
    assert payload.prototype is not None


def test_design_package_payload_exposes_an_absent_approach_as_null_both_ways() -> None:
    stored = design_version().package
    package = replace(
        stored,
        alternatives=tuple(replace(item, approach=None) for item in stored.alternatives),
    )

    dumped = DesignPackagePayload.from_domain(package).model_dump(mode="json")
    omitted = {
        **dumped,
        "alternatives": [
            {key: value for key, value in item.items() if key != "approach"}
            for item in dumped["alternatives"]
        ],
    }
    stored_payload = DesignPackagePayload.from_domain(stored)

    assert [item["approach"] for item in dumped["alternatives"]] == [None, None]
    assert DesignPackagePayload.model_validate(dumped).to_domain() == package
    assert DesignPackagePayload.model_validate(omitted).to_domain() == package
    assert all("approach" not in item for item in package.to_snapshot()["alternatives"])
    assert [item.approach.value for item in stored_payload.alternatives] == [
        "GUIDED_WORKFLOW",
        "DASHBOARD_FIRST",
    ]
    assert stored_payload.to_domain().content_hash == stored.content_hash


def test_generation_and_current_version_are_owner_scoped() -> None:
    """Expose deterministic generation and the current immutable package."""
    client, generation, _queries, _revisions, _gates = client_fixture()

    generated = client.post(path("/proposals"))
    current = client.get(path("/current"))

    assert generated.status_code == 201
    assert generated.json()["version"]["id"] == str(design_version().id)
    assert current.status_code == 200
    assert current.json()["ready_for_gate"] is True
    assert current.json()["package"]["prototype"]["code"] == "PRT-001"
    assert generation.calls == [(OWNER_ID, PROJECT_ID)]


def refused(issue: DesignGenerationIssueCode | None, **reasons) -> DesignGenerationResult:
    return DesignGenerationResult(status=DesignGenerationStatus.REJECTED, issue=issue, **reasons)


@pytest.mark.parametrize(
    ("result", "status_code", "detail"),
    [
        (
            refused(
                DesignGenerationIssueCode.PROPOSAL_REJECTED,
                proposal_issue=DesignProposalIssueCode.UX_DESIGNER_REQUIRED,
            ),
            409,
            {"code": "PROPOSAL_REJECTED", "proposal_issue": "UX_DESIGNER_REQUIRED"},
        ),
        (
            refused(
                DesignGenerationIssueCode.PROPOSAL_REJECTED,
                proposal_issue=DesignProposalIssueCode.INVALID_PROVIDER_OUTPUT,
            ),
            409,
            {"code": "PROPOSAL_REJECTED", "proposal_issue": "INVALID_PROVIDER_OUTPUT"},
        ),
        (refused(DesignGenerationIssueCode.PROPOSAL_REJECTED), 409, {"code": "PROPOSAL_REJECTED"}),
        (
            refused(
                DesignGenerationIssueCode.PERSISTENCE_REJECTED,
                persistence_status=DesignVersionAppendStatus.VERSION_CONFLICT,
            ),
            409,
            {"code": "PERSISTENCE_REJECTED"},
        ),
        (
            refused(DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED),
            409,
            {"code": "REQUIREMENTS_APPROVAL_REQUIRED"},
        ),
        (refused(DesignGenerationIssueCode.PROJECT_NOT_FOUND), 404, {"code": "PROJECT_NOT_FOUND"}),
        (refused(None), 409, {"code": "DESIGN_GENERATION_REJECTED"}),
    ],
    ids=["designer", "provider", "no-reason", "persistence", "approval", "project", "unknown"],
)
def test_a_refused_proposal_names_the_reason_of_the_generator_only_when_it_has_one(
    result, status_code, detail
) -> None:
    client, generation, _queries, _revisions, _gates = client_fixture()
    generation.refusal = result

    response = client.post(path("/proposals"))

    assert response.status_code == status_code
    assert response.json() == {"detail": detail}
    assert generation.calls == [(OWNER_ID, PROJECT_ID)]


def test_revision_endpoint_accepts_a_complete_typed_design_package() -> None:
    """Forward a complete owner replacement through domain validation."""
    client, _generation, _queries, revisions, _gates = client_fixture()
    proposed = replace(
        design_version().package,
        open_questions=(
            *design_version().package.open_questions,
            "Should expert shortcuts be visible in the prototype?",
        ),
    )
    payload = DesignPackagePayload.from_domain(proposed).model_dump(mode="json")

    response = client.post(path("/revisions"), json={"package": payload})

    assert response.status_code == 201
    assert response.json()["diff"]["status"] == "PROPOSED"
    assert revisions.proposed == proposed


def test_revision_decision_preserves_owner_reason() -> None:
    """Forward one explicit owner Design Package diff decision."""
    client, _generation, _queries, revisions, _gates = client_fixture()

    response = client.post(
        path(f"/revisions/{DIFF_ID}/decision"),
        json={
            "decision": "APPROVE",
            "reason": "Reviewed the selected design and declarative prototype.",
        },
    )

    assert response.status_code == 200
    assert revisions.decisions == [
        (
            DIFF_ID,
            DesignRevisionDecision.APPROVE,
            "Reviewed the selected design and declarative prototype.",
        )
    ]


def test_archetype_edit_refuses_design_proposal_and_approval_before_service_mutation():
    client, _generation, _queries, revisions, _gates = client_fixture()
    service = sections_port(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        states={ProjectStage.USER_TWINS: SectionState.TO_UPDATE},
    )
    client.app.state.application_runtime = SimpleNamespace(sections_service=service)
    payload = DesignPackagePayload.from_domain(design_version().package).model_dump(mode="json")
    with client:
        proposed = client.post(path("/revisions"), json={"package": payload})
        approved = client.post(path(f"/revisions/{DIFF_ID}/decision"), json={"decision": "APPROVE"})
        historical = client.get(path("/revisions"))
    for response in (proposed, approved):
        assert response.status_code == 409
        assert response.json()["detail"] == {"code": "DESIGN_CONTEXT_CHANGED"}
    assert revisions.proposed is None and revisions.decisions == []
    assert historical.status_code == 200
    assert len(service.calls) == 2


def test_outdated_context_can_reject_pending_design_revision_to_unblock_it():
    client, _generation, _queries, revisions, _gates = client_fixture()
    service = sections_port(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        states={ProjectStage.USER_TWINS: SectionState.TO_UPDATE},
    )
    client.app.state.application_runtime = SimpleNamespace(sections_service=service)
    with client:
        response = client.post(
            path(f"/revisions/{DIFF_ID}/decision"),
            json={"decision": "REJECT", "reason": "The archetypes changed."},
        )
    assert response.status_code == 200
    assert revisions.decisions == [
        (DIFF_ID, DesignRevisionDecision.REJECT, "The archetypes changed.")
    ]
    assert service.calls == []


@pytest.mark.parametrize("code,status", [("PROJECT_NOT_FOUND", 404), ("PERSISTENCE_REJECTED", 409)])
def test_unavailable_or_foreign_project_context_is_controlled_before_revision_mutation(
    code, status
):
    client, _generation, _queries, revisions, _gates = client_fixture()
    calls = []

    async def current(**scope):
        assert scope == {"owner_user_id": OWNER_ID, "project_id": PROJECT_ID}
        calls.append(scope)
        raise SectionsFailure(code)

    client.app.state.application_runtime = SimpleNamespace(
        sections_service=SimpleNamespace(current=current)
    )
    payload = DesignPackagePayload.from_domain(design_version().package).model_dump(mode="json")
    with client:
        proposed = client.post(path("/revisions"), json={"package": payload})
        approved = client.post(path(f"/revisions/{DIFF_ID}/decision"), json={"decision": "APPROVE"})
    for response in (proposed, approved):
        assert response.status_code == status
        assert response.json()["detail"] == {"code": code}
    assert revisions.proposed is None and revisions.decisions == []
    assert len(calls) == 2


def test_gate_and_readiness_endpoints_expose_exact_design_approval() -> None:
    """Expose Gate 5 state, audit events, and architecture readiness."""
    client, _generation, _queries, _revisions, _gates = client_fixture()

    gate = client.get(path("/gate"))
    events = client.get(path("/gate/events"))
    readiness = client.get(path("/readiness"))

    assert gate.status_code == 200
    assert gate.json()["gate_type"] == "DESIGN"
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert readiness.status_code == 200
    assert readiness.json()["approved_current_package"] is True
    assert readiness.json()["package_ready_for_gate"] is True
    assert readiness.json()["status"] == "READY_FOR_ARCHITECTURE_PLANNING"


def test_history_revision_lookup_and_gate_commands_preserve_typed_state() -> None:
    """Expose version history, diffs, submission, and explicit Gate 5 decisions."""
    client, _generation, _queries, _revisions, gates = client_fixture()

    history = client.get(path())
    revisions = client.get(path("/revisions"))
    revision = client.get(path(f"/revisions/{DIFF_ID}"))
    submission = client.post(path("/gate/submit"))
    decision = client.post(
        path("/gate/decision"),
        json={
            "action": "APPROVE",
            "reason": "The exact Design Package is ready for architecture planning.",
        },
    )

    assert history.status_code == 200
    assert [item["version_number"] for item in history.json()] == [1]
    assert revisions.status_code == 200
    assert revisions.json()[0]["id"] == str(DIFF_ID)
    assert revision.status_code == 200
    assert revision.json()["proposal_hash"] == proposed_diff(design_version()).proposal_hash
    assert submission.status_code == 200
    assert submission.json()["status"] == "ALREADY_APPROVED"
    assert decision.status_code == 200
    assert gates.decisions == [
        (
            HumanGateAction.APPROVE,
            "The exact Design Package is ready for architecture planning.",
        )
    ]


def test_missing_current_package_returns_non_disclosing_404() -> None:
    """Do not distinguish missing and foreign owner-scoped Design state."""
    client, _generation, queries, _revisions, _gates = client_fixture()
    queries.version = None

    response = client.get(path("/current"))

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "DESIGN_PACKAGE_NOT_FOUND",
        }
    }


def test_application_factory_registers_design_routes_and_state_slots() -> None:
    """Mount the public Design surface without silently constructing adapters."""
    settings = ApplicationSettings(
        application_name="OrchesTwin Design API Test",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix="/api/v1",
        _env_file=None,
    )
    application = create_app(settings, runtime=ApplicationRuntime())
    paths = application.openapi()["paths"]

    assert "/api/v1/projects/{project_id}/design/proposals" in paths
    assert "/api/v1/projects/{project_id}/design/gate/decision" in paths
    assert application.state.design_generation_service is None
    assert application.state.design_revision_service is None
    assert application.state.design_query_service is None
    assert application.state.design_gate_service is None


def test_design_package_payload_round_trips_the_mockup_the_assertions_and_the_verdicts() -> None:
    package = fixture_package()

    payload = DesignPackagePayload.from_domain(package)
    dumped = payload.model_dump(mode="json")

    assert payload.generated_mockup is not None
    assert payload.generated_mockup.mockup.design_alternative_id == (
        package.owner_selected_alternative_id
    )
    assert [screen.code for screen in payload.generated_mockup.mockup.screens] == [
        screen.code for screen in package.generated_mockup.mockup.screens
    ]
    assert payload.generated_mockup.requirement_ids_by_code == dict(
        package.generated_mockup.requirement_ids_by_code
    )
    assert payload.owner_assertions == ASSERTIONS
    assert [(item.verdict, item.quote) for item in payload.critiques] == list(VERDICTS)
    assert dumped["generated_mockup"] == package.to_snapshot()["generated_mockup"]
    assert payload.to_domain() == package
    assert DesignPackagePayload.model_validate(dumped).to_domain() == package
    assert DesignPackagePayload.model_validate(dumped).to_domain().content_hash == (
        package.content_hash
    )


def test_design_package_payload_exposes_absent_additions_as_null_and_empty() -> None:
    package = design_version().package
    dumped = DesignPackagePayload.from_domain(package).model_dump(mode="json")
    omitted = {
        **{
            key: value
            for key, value in dumped.items()
            if key not in {"generated_mockup", "owner_assertions"}
        },
        "critiques": [
            {key: value for key, value in item.items() if key not in {"verdict", "quote"}}
            for item in dumped["critiques"]
        ],
    }

    assert dumped["generated_mockup"] is None
    assert dumped["owner_assertions"] == []
    assert all((item["verdict"], item["quote"]) == (None, None) for item in dumped["critiques"])
    assert DesignPackagePayload.model_validate(dumped).to_domain() == package
    assert DesignPackagePayload.model_validate(omitted).to_domain() == package
    assert DesignPackagePayload.model_validate(dumped).to_domain().content_hash == (
        package.content_hash
    )


def test_revision_endpoint_accepts_a_package_with_a_generated_mockup() -> None:
    client, _generation, _queries, revisions, _gates = client_fixture()
    proposed = fixture_package()
    payload = DesignPackagePayload.from_domain(proposed).model_dump(mode="json")

    response = client.post(path("/revisions"), json={"package": payload})

    assert response.status_code == 201
    assert revisions.proposed == proposed


def test_revision_endpoint_validates_a_client_mockup_like_the_output_of_a_model() -> None:
    client, _generation, _queries, revisions, _gates = client_fixture()
    dumped = DesignPackagePayload.from_domain(fixture_package()).model_dump(mode="json")

    def variant(change) -> dict:
        value = json.loads(json.dumps(dumped))
        change(value)
        return value

    def script(value) -> None:
        screen = value["generated_mockup"]["mockup"]["screens"][0]
        screen["markup"] += "<script>alert(1)</script>"

    def remote_style(value) -> None:
        value["generated_mockup"]["mockup"]["styles"] += ".x{background:url(https://x.invalid)}"

    def unused_code(value) -> None:
        value["generated_mockup"]["requirement_ids_by_code"]["REQ-042"] = str(UUID(int=42))

    def lone_verdict(value) -> None:
        value["critiques"][0]["quote"] = None

    def too_many_assertions(value) -> None:
        value["owner_assertions"] = [f"Asserzione numero {index}" for index in range(21)]

    for change in (script, remote_style, unused_code, lone_verdict, too_many_assertions):
        response = client.post(path("/revisions"), json={"package": variant(change)})

        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "INVALID_DESIGN_PACKAGE"}}

    assert revisions.proposed is None


def test_openapi_describes_the_mockup_the_assertions_and_the_verdicts() -> None:
    app = FastAPI()
    app.include_router(create_design_router())
    schemas = app.openapi()["components"]["schemas"]
    dumped = DesignPackagePayload.from_domain(fixture_package()).model_dump(mode="json")
    bound = dumped["generated_mockup"]

    def named(model: str) -> list[dict]:
        found = [
            schema
            for name, schema in schemas.items()
            if name == model or name.startswith(f"{model}-")
        ]
        assert found
        return found

    for model, sample in (
        ("DesignPackagePayload", dumped),
        ("SyntheticDesignCritiquePayload", dumped["critiques"][0]),
        ("BoundGeneratedMockupPayload", bound),
        ("GeneratedMockupPayload", bound["mockup"]),
        ("GeneratedScreenPayload", bound["mockup"]["screens"][0]),
    ):
        for schema in named(model):
            assert set(schema["properties"]) == set(sample)

    for schema in named("BoundGeneratedMockupPayload"):
        assert schema["properties"]["requirement_ids_by_code"]["additionalProperties"] == {
            "type": "string",
            "format": "uuid",
        }

    assert {
        "CRITIQUE_VERDICT",
        "GENERATED_MOCKUP",
        "GENERATED_SCREEN",
        "GENERATED_STYLES",
        "OWNER_ASSERTION",
        "OWNER_ASSERTION_ORDER",
    } <= set(schemas["DesignArtifactKind"]["enum"])


def test_router_freezes_the_sprint_six_design_http_surface() -> None:
    """Expose every planned Design Exploration and Gate 5 endpoint."""
    router = create_design_router()
    paths = {route.path for route in router.routes if hasattr(route, "path")}
    prefix = "/projects/{project_id}/design"

    assert {
        f"{prefix}/proposals",
        f"{prefix}/current",
        prefix,
        f"{prefix}/revisions",
        f"{prefix}/revisions/{{diff_id}}",
        f"{prefix}/revisions/{{diff_id}}/decision",
        f"{prefix}/gate/submit",
        f"{prefix}/gate/decision",
        f"{prefix}/gate",
        f"{prefix}/gate/events",
        f"{prefix}/readiness",
    }.issubset(paths)


def visual_languages(package: dict) -> list[dict]:
    return [
        item["visual_language"]
        for item in package["alternatives"]
        if item["visual_language"] is not None
    ]


def test_the_current_design_without_directions_answers_null_and_converts_back() -> None:
    client, _generation, _queries, _revisions, _gates = client_fixture()
    package = design_version().package

    body = client.get(path("/current")).json()["package"]
    omitted = json.loads(json.dumps(body))
    for language in visual_languages(omitted):
        del language["direction"]

    assert [language["direction"] for language in visual_languages(body)] == [None]
    assert DesignPackagePayload.model_validate(body).to_domain() == package
    assert DesignPackagePayload.model_validate(body).to_domain().content_hash == (
        package.content_hash
    )
    assert DesignPackagePayload.model_validate(omitted).to_domain() == package


def test_a_package_with_a_visual_direction_round_trips_through_the_revision_endpoint() -> None:
    client, _generation, _queries, revisions, _gates = client_fixture()
    proposed = directed_package(design_version().package)
    dumped = DesignPackagePayload.from_domain(proposed).model_dump(mode="json")

    def variant(change) -> dict:
        value = json.loads(json.dumps(dumped))
        change(visual_languages(value)[0]["direction"])
        return value

    def unknown_layout(value) -> None:
        value["axes"]["layout"] = "NEON"

    def extra_key(value) -> None:
        value["motion"] = "CALM"

    def two_rules(value) -> None:
        value["rules"] = value["rules"][:2]

    def typicality_out_of_range(value) -> None:
        value["typicality"] = 101

    for change in (unknown_layout, extra_key):
        response = client.post(path("/revisions"), json={"package": variant(change)})

        assert response.status_code == 422

    for change in (two_rules, typicality_out_of_range):
        response = client.post(path("/revisions"), json={"package": variant(change)})

        assert response.status_code == 422
        assert response.json() == {"detail": {"code": "INVALID_DESIGN_PACKAGE"}}

    assert revisions.proposed is None

    response = client.post(path("/revisions"), json={"package": dumped})

    assert [language["direction"] for language in visual_languages(dumped)] == [
        direction().to_snapshot()
    ]
    assert DesignPackagePayload.model_validate(dumped).to_domain() == proposed
    assert DesignPackagePayload.model_validate(dumped).to_domain().content_hash == (
        proposed.content_hash
    )
    assert response.status_code == 201
    assert revisions.proposed == proposed


def test_openapi_describes_the_visual_direction_of_a_visual_language() -> None:
    app = FastAPI()
    app.include_router(create_design_router())
    schemas = app.openapi()["components"]["schemas"]
    plain = visual_languages(
        DesignPackagePayload.from_domain(design_version().package).model_dump(mode="json")
    )[0]
    directed = visual_languages(
        DesignPackagePayload.from_domain(directed_package(design_version().package)).model_dump(
            mode="json"
        )
    )[0]

    def named(model: str) -> list[dict]:
        found = [
            schema
            for name, schema in schemas.items()
            if name == model or name.startswith(f"{model}-")
        ]
        assert found
        return found

    for model, sample in (
        ("VisualLanguagePayload", plain),
        ("VisualLanguagePayload", directed),
        ("VisualDirectionPayload", directed["direction"]),
        ("DirectionAxesPayload", directed["direction"]["axes"]),
    ):
        for schema in named(model):
            assert set(schema["properties"]) == set(sample)

    for enum in (DirectionLayout, DirectionShape, DirectionType, DirectionColour, DirectionDensity):
        assert schemas[enum.__name__]["enum"] == [item.value for item in enum]
