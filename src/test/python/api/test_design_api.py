from __future__ import annotations

import importlib.util
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID

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
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.design_application import (
    DesignGenerationResult,
    DesignGenerationStatus,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

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

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignGenerationResult:
        self.calls.append((owner_user_id, project_id))

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
