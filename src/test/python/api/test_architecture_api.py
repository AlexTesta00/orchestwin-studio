from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.architecture import (
    ArchitecturePackagePayload,
    create_architecture_router,
)
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.architecture_gate import (
    ArchitectureGateDecisionResult,
    ArchitectureGateDecisionStatus,
    ArchitectureGateSubmissionResult,
    ArchitectureGateSubmissionStatus,
    ArchitectureReadinessResult,
    ArchitectureWorkflowReadiness,
    architecture_artifact_reference,
)
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
)
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureRevisionResult,
    ArchitectureRevisionStatus,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitecturePackageDiff,
    ArchitectureRevisionDecision,
    decide_architecture_revision,
    propose_architecture_revision,
)
from orchestwin.config import ApplicationSettings, LogLevel, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.architecture_application import (
    ArchitectureGenerationResult,
    ArchitectureGenerationStatus,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"
FIXTURE_PACKAGE_NAME = "architecture_api_fixtures"
DIFF_ID = UUID("00000000-0000-4000-8000-000000000701")
GATE_ID = UUID("00000000-0000-4000-8000-000000000702")
NOW = datetime(2026, 8, 21, 15, 0, tzinfo=UTC)


def load_architecture_fixtures() -> ModuleType:
    """Load package-local architecture fixtures without production imports."""
    package = ModuleType(FIXTURE_PACKAGE_NAME)
    package.__path__ = [str(FIXTURE_DIRECTORY)]
    sys.modules[FIXTURE_PACKAGE_NAME] = package

    module_name = f"{FIXTURE_PACKAGE_NAME}.architecture_fixtures"
    spec = importlib.util.spec_from_file_location(
        module_name,
        FIXTURE_DIRECTORY / "architecture_fixtures.py",
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load Architecture API fixtures")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    return module


FIXTURES = load_architecture_fixtures()
PROJECT_ID: UUID = FIXTURES.PROJECT_ID
OWNER_ID: UUID = FIXTURES.OWNER_ID


def architecture_version() -> ArchitecturePackageVersion:
    """Create one ready immutable Architecture Package version."""
    return FIXTURES.architecture_version()


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


def proposed_diff(version: ArchitecturePackageVersion) -> ArchitecturePackageDiff:
    """Create one valid owner-reviewable Architecture Package replacement."""
    package = replace(
        version.package,
        open_questions=(
            *version.package.open_questions,
            "Which execution profile should verify the approved test strategy?",
        ),
    )
    proposal = propose_architecture_revision(
        diff_id=DIFF_ID,
        owner_user_id=OWNER_ID,
        base_version=version,
        proposed_package=package,
        created_at=NOW + timedelta(minutes=1),
    )

    assert proposal.diff is not None

    return proposal.diff


def approved_gate(
    version: ArchitecturePackageVersion,
) -> tuple[HumanGate, HumanGateEvent]:
    """Create one approved Gate 6 and its approval event."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.ARCHITECTURE,
        artifact=architecture_artifact_reference(version),
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
    """Return one generated Architecture Package version."""

    def __init__(self, version: ArchitecturePackageVersion) -> None:
        self.version = version
        self.calls: list[tuple[UUID, UUID]] = []

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitectureGenerationResult:
        self.calls.append((owner_user_id, project_id))

        return ArchitectureGenerationResult(
            status=ArchitectureGenerationStatus.CREATED,
            version=self.version,
        )


class FakeQueryService:
    """Return configurable versions and revision diffs."""

    def __init__(self, version: ArchitecturePackageVersion, diff: ArchitecturePackageDiff) -> None:
        self.version: ArchitecturePackageVersion | None = version
        self.diffs: list[ArchitecturePackageDiff] = [diff]

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        del owner_user_id, project_id
        return self.version

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageVersion, ...]:
        del owner_user_id, project_id
        return () if self.version is None else (self.version,)

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        del owner_user_id, project_id
        return next((diff for diff in self.diffs if diff.id == diff_id), None)

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageDiff, ...]:
        del owner_user_id, project_id
        return tuple(self.diffs)


class FakeRevisionService:
    """Capture complete package replacements and owner decisions."""

    def __init__(self, version: ArchitecturePackageVersion, diff: ArchitecturePackageDiff) -> None:
        self.version = version
        self.diff = diff
        self.proposed = None
        self.decisions: list[tuple[UUID, ArchitectureRevisionDecision, str | None]] = []

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_package: ArchitecturePlanningPackage,
    ) -> ArchitectureRevisionResult:
        del owner_user_id, project_id
        self.proposed = proposed_package

        return ArchitectureRevisionResult(
            status=ArchitectureRevisionStatus.CREATED,
            diff=self.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ArchitectureRevisionDecision,
        reason: str | None = None,
    ) -> ArchitectureRevisionResult:
        del project_id
        self.decisions.append((diff_id, decision, reason))
        domain = decide_architecture_revision(
            diff=self.diff,
            current_version=self.version,
            decision=decision,
            actor_user_id=owner_user_id,
            occurred_at=NOW + timedelta(minutes=3),
            resulting_version_id=(
                UUID(int=803) if decision is ArchitectureRevisionDecision.APPROVE else None
            ),
            reason=reason,
        )

        return ArchitectureRevisionResult(
            status=ArchitectureRevisionStatus.APPLIED,
            diff=domain.diff,
            version=domain.version,
        )


class FakeGateService:
    """Return an approved Gate 6 fixture."""

    def __init__(self, version: ArchitecturePackageVersion) -> None:
        self.version = version
        self.gate, self.event = approved_gate(version)
        self.decisions: list[tuple[HumanGateAction, str | None]] = []

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureGateSubmissionResult:
        del project_id, owner_user_id
        return ArchitectureGateSubmissionResult(
            status=ArchitectureGateSubmissionStatus.ALREADY_APPROVED,
            gate=self.gate,
        )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> ArchitectureGateDecisionResult:
        del project_id, owner_user_id
        self.decisions.append((action, reason))
        return ArchitectureGateDecisionResult(
            status=ArchitectureGateDecisionStatus.APPLIED,
            gate=self.gate,
            event=self.event,
        )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureReadinessResult:
        del project_id, owner_user_id
        return ArchitectureReadinessResult(
            status=ArchitectureWorkflowReadiness.READY_FOR_IMPLEMENTATION,
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
    """Create an isolated Architecture API app and its service doubles."""
    version = architecture_version()
    diff = proposed_diff(version)
    generation = FakeGenerationService(version)
    queries = FakeQueryService(version, diff)
    revisions = FakeRevisionService(version, diff)
    gates = FakeGateService(version)
    app = FastAPI()
    app.state.architecture_generation_service = generation
    app.state.architecture_query_service = queries
    app.state.architecture_revision_service = revisions
    app.state.architecture_gate_service = gates
    app.include_router(create_architecture_router())
    app.dependency_overrides[current_user_dependency] = user

    return TestClient(app), generation, queries, revisions, gates


def path(suffix: str = "") -> str:
    """Return one project-scoped Architecture API path."""
    return f"/projects/{PROJECT_ID}/architecture{suffix}"


def test_architecture_package_payload_round_trips_the_canonical_domain_snapshot() -> None:
    """Preserve architecture, test-plan, grounding, and traceability fields."""
    package = architecture_version().package

    payload = ArchitecturePackagePayload.from_domain(package)

    assert payload.to_domain() == package
    assert payload.architecture.code == "ARC-001"
    assert payload.architecture.components[0].code == "CMP-001"
    assert payload.test_plan.test_cases[0].code == "TST-001"


def test_generation_and_current_version_are_owner_scoped() -> None:
    """Expose deterministic generation and the current immutable package."""
    client, generation, _queries, _revisions, _gates = client_fixture()

    generated = client.post(path("/proposals"))
    current = client.get(path("/current"))

    assert generated.status_code == 201
    assert generated.json()["version"]["id"] == str(architecture_version().id)
    assert current.status_code == 200
    assert current.json()["package"]["architecture"]["code"] == "ARC-001"
    assert current.json()["package"]["test_plan"]["code"] == "TPL-001"
    assert generation.calls == [(OWNER_ID, PROJECT_ID)]


def test_revision_endpoint_accepts_a_complete_typed_architecture_package() -> None:
    """Forward a complete owner replacement through domain validation."""
    client, _generation, _queries, revisions, _gates = client_fixture()
    proposed = replace(
        architecture_version().package,
        open_questions=(
            *architecture_version().package.open_questions,
            "Which execution profile should verify the approved test strategy?",
        ),
    )
    payload = ArchitecturePackagePayload.from_domain(proposed).model_dump(mode="json")

    response = client.post(path("/revisions"), json={"package": payload})

    assert response.status_code == 201
    assert response.json()["diff"]["status"] == "PROPOSED"
    assert revisions.proposed == proposed


def test_revision_decision_preserves_owner_reason() -> None:
    """Forward one explicit owner Architecture Package diff decision."""
    client, _generation, _queries, revisions, _gates = client_fixture()

    response = client.post(
        path(f"/revisions/{DIFF_ID}/decision"),
        json={
            "decision": "APPROVE",
            "reason": "Reviewed the architecture, test plan, and unresolved questions.",
        },
    )

    assert response.status_code == 200
    assert revisions.decisions == [
        (
            DIFF_ID,
            ArchitectureRevisionDecision.APPROVE,
            "Reviewed the architecture, test plan, and unresolved questions.",
        )
    ]


def test_gate_and_readiness_endpoints_expose_exact_architecture_approval() -> None:
    """Expose Gate 6 state, audit events, and implementation readiness."""
    client, _generation, _queries, _revisions, _gates = client_fixture()

    gate = client.get(path("/gate"))
    events = client.get(path("/gate/events"))
    readiness = client.get(path("/readiness"))

    assert gate.status_code == 200
    assert gate.json()["gate_type"] == "ARCHITECTURE"
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert readiness.status_code == 200
    assert readiness.json()["approved_current_package"] is True
    assert readiness.json()["status"] == "READY_FOR_IMPLEMENTATION"


def test_history_revision_lookup_and_gate_commands_preserve_typed_state() -> None:
    """Expose version history, diffs, submission, and explicit Gate 6 decisions."""
    client, _generation, _queries, _revisions, gates = client_fixture()

    history = client.get(path())
    revisions = client.get(path("/revisions"))
    revision = client.get(path(f"/revisions/{DIFF_ID}"))
    submission = client.post(path("/gate/submit"))
    decision = client.post(
        path("/gate/decision"),
        json={
            "action": "APPROVE",
            "reason": "The exact Architecture Package is ready for implementation.",
        },
    )

    assert history.status_code == 200
    assert [item["version_number"] for item in history.json()] == [1]
    assert revisions.status_code == 200
    assert revisions.json()[0]["id"] == str(DIFF_ID)
    assert revision.status_code == 200
    assert revision.json()["proposal_hash"] == proposed_diff(architecture_version()).proposal_hash
    assert submission.status_code == 200
    assert submission.json()["status"] == "ALREADY_APPROVED"
    assert decision.status_code == 200
    assert gates.decisions == [
        (
            HumanGateAction.APPROVE,
            "The exact Architecture Package is ready for implementation.",
        )
    ]


def test_missing_current_package_returns_non_disclosing_404() -> None:
    """Do not distinguish missing and foreign owner-scoped Architecture state."""
    client, _generation, queries, _revisions, _gates = client_fixture()
    queries.version = None

    response = client.get(path("/current"))

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "code": "ARCHITECTURE_PACKAGE_NOT_FOUND",
        }
    }


def test_application_factory_registers_architecture_routes_and_state_slots() -> None:
    """Mount the public Architecture surface without silently constructing adapters."""
    settings = ApplicationSettings(
        application_name="OrchesTwin Architecture API Test",
        environment=RuntimeEnvironment.TEST,
        debug=False,
        log_level=LogLevel.INFO,
        api_prefix="/api/v1",
        _env_file=None,
    )
    application = create_app(settings, runtime=ApplicationRuntime())
    paths = application.openapi()["paths"]

    assert "/api/v1/projects/{project_id}/architecture/proposals" in paths
    assert "/api/v1/projects/{project_id}/architecture/gate/decision" in paths
    assert application.state.architecture_generation_service is None
    assert application.state.architecture_revision_service is None
    assert application.state.architecture_query_service is None
    assert application.state.architecture_gate_service is None


def test_router_freezes_the_sprint_six_architecture_http_surface() -> None:
    """Expose every planned Architecture Planning and Gate 6 endpoint."""
    router = create_architecture_router()
    paths = {route.path for route in router.routes if hasattr(route, "path")}
    prefix = "/projects/{project_id}/architecture"

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
