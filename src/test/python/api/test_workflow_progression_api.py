"""API contract tests for explicit governed workflow progression commands."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.workflow_runs import (
    WorkflowRunAdvanceCommand,
    WorkflowRunApiCommandResult,
    WorkflowRunApiStatus,
    WorkflowRunGateResumeCommand,
    WorkflowRunStartCommand,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.workflow.runs import WorkflowStage

OWNER_ID = UUID("00000000-0000-4000-8000-000000012001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000012002")
RUN_ID = UUID("00000000-0000-4000-8000-000000012003")
COMMAND_ID = UUID("00000000-0000-4000-8000-000000012004")
GATE_ID = UUID("00000000-0000-4000-8000-000000012005")
DECISION_ID = UUID("00000000-0000-4000-8000-000000012006")
NOW = datetime(2026, 9, 10, 20, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("workflow-progression@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(
    *,
    stage: str = "INTAKE",
    run_status: str = "RUNNING",
    state_version: int = 2,
    checkpoint_sequence: int = 1,
) -> dict[str, JsonValue]:
    return {
        "id": str(RUN_ID),
        "project_id": str(PROJECT_ID),
        "owner_user_id": str(OWNER_ID),
        "project_mode": "GREENFIELD_GENERATION",
        "current_stage": stage,
        "status": run_status,
        "state_version": state_version,
        "checkpoint_sequence": checkpoint_sequence,
    }


class _ProgressionService:
    def __init__(self) -> None:
        self.start_commands: list[WorkflowRunStartCommand] = []
        self.advance_commands: list[WorkflowRunAdvanceCommand] = []
        self.resume_commands: list[WorkflowRunGateResumeCommand] = []
        self.result = WorkflowRunApiCommandResult(
            status=WorkflowRunApiStatus.COMMAND_APPLIED,
            snapshot=_snapshot(),
            message="COMMAND_APPLIED",
        )

    async def start_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunStartCommand,
    ) -> WorkflowRunApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        self.start_commands.append(command)
        return self.result

    async def advance_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunAdvanceCommand,
    ) -> WorkflowRunApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        self.advance_commands.append(command)
        return self.result

    async def resume_after_gate(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunGateResumeCommand,
    ) -> WorkflowRunApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        self.resume_commands.append(command)
        return self.result


def _client(service: _ProgressionService) -> TestClient:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=ApplicationRuntime(workflow_run_api_service=service),
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = _user
    return TestClient(application)


def _base_body() -> dict[str, object]:
    return {
        "command_id": str(COMMAND_ID),
        "project_id": str(PROJECT_ID),
        "expected_state_version": 1,
        "expected_checkpoint_sequence": 0,
    }


def test_start_route_translates_exact_optimistic_command() -> None:
    service = _ProgressionService()
    response = _client(service).post(
        f"/api/v1/runs/{RUN_ID}/start",
        json=_base_body(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMMAND_APPLIED"
    assert service.start_commands == [
        WorkflowRunStartCommand(
            command_id=COMMAND_ID,
            project_id=PROJECT_ID,
            expected_state_version=1,
            expected_checkpoint_sequence=0,
        )
    ]


def test_advance_route_carries_exact_stage_and_gate_identity() -> None:
    service = _ProgressionService()
    body = {
        **_base_body(),
        "next_stage": "BRIEF_APPROVAL",
        "pending_gate_id": str(GATE_ID),
    }
    response = _client(service).post(
        f"/api/v1/runs/{RUN_ID}/advance",
        json=body,
    )

    assert response.status_code == 200
    assert service.advance_commands == [
        WorkflowRunAdvanceCommand(
            command_id=COMMAND_ID,
            project_id=PROJECT_ID,
            expected_state_version=1,
            expected_checkpoint_sequence=0,
            next_stage=WorkflowStage.BRIEF_APPROVAL,
            pending_gate_id=GATE_ID,
        )
    ]


def test_resume_gate_route_requires_the_exact_persisted_decision_identity() -> None:
    service = _ProgressionService()
    body = {
        "project_id": str(PROJECT_ID),
        "expected_state_version": 3,
        "expected_checkpoint_sequence": 2,
        "gate_id": str(GATE_ID),
        "decision_id": str(DECISION_ID),
    }
    response = _client(service).post(
        f"/api/v1/runs/{RUN_ID}/resume-gate",
        json=body,
    )

    assert response.status_code == 200
    assert service.resume_commands == [
        WorkflowRunGateResumeCommand(
            project_id=PROJECT_ID,
            expected_state_version=3,
            expected_checkpoint_sequence=2,
            gate_id=GATE_ID,
            decision_id=DECISION_ID,
        )
    ]


def test_progression_validation_and_authorization_fail_closed() -> None:
    service = _ProgressionService()
    client = _client(service)

    invalid = client.post(
        f"/api/v1/runs/{RUN_ID}/advance",
        json={
            **_base_body(),
            "next_stage": "NOT_A_WORKFLOW_STAGE",
            "pending_gate_id": None,
        },
    )
    assert invalid.status_code == 422
    assert service.advance_commands == []

    service.result = WorkflowRunApiCommandResult(
        status=WorkflowRunApiStatus.AUTHORIZATION_REQUIRED,
        snapshot=_snapshot(run_status="WAITING_FOR_HUMAN", state_version=3),
        message="AUTHORIZATION_REQUIRED",
    )
    denied = client.post(
        f"/api/v1/runs/{RUN_ID}/resume-gate",
        json={
            "project_id": str(PROJECT_ID),
            "expected_state_version": 3,
            "expected_checkpoint_sequence": 2,
            "gate_id": str(GATE_ID),
            "decision_id": str(DECISION_ID),
        },
    )
    assert denied.status_code == 409
    assert denied.json()["detail"]["status"] == "AUTHORIZATION_REQUIRED"
