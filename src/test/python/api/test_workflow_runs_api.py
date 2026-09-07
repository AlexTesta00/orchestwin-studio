"""API contract tests for owner-scoped durable workflow-run resources."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import JsonValue

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.workflow_runs import (
    WorkflowRunApiCommandResult,
    WorkflowRunApiStatus,
    WorkflowRunCreateCommand,
    WorkflowRunLifecycleCommand,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.workflow.commands import WorkflowLifecycleCommandKind

OWNER_ID = UUID("00000000-0000-4000-8000-000000011001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000011002")
RUN_ID = UUID("00000000-0000-4000-8000-000000011003")
COMMAND_ID = UUID("00000000-0000-4000-8000-000000011004")
NOW = datetime(2026, 8, 30, 13, 30, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("workflow-owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _run_snapshot(status: str = "RUNNING") -> dict[str, JsonValue]:
    return {
        "id": str(RUN_ID),
        "project_id": str(PROJECT_ID),
        "owner_user_id": str(OWNER_ID),
        "project_mode": "GREENFIELD_GENERATION",
        "current_stage": "INTAKE",
        "status": status,
        "state_version": 2,
        "checkpoint_sequence": 1,
    }


class _WorkflowService:
    def __init__(self) -> None:
        self.create_command: WorkflowRunCreateCommand | None = None
        self.lifecycle_commands: list[WorkflowRunLifecycleCommand] = []
        self.result = WorkflowRunApiCommandResult(
            WorkflowRunApiStatus.COMMAND_APPLIED,
            _run_snapshot(),
            "Workflow command applied.",
        )
        self.visible = True

    async def create_run(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WorkflowRunCreateCommand,
    ) -> WorkflowRunApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        self.create_command = command
        return WorkflowRunApiCommandResult(
            WorkflowRunApiStatus.RUN_CREATED,
            _run_snapshot("DRAFT"),
            "Workflow run created.",
        )

    async def list_runs(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        assert owner_user_id == OWNER_ID
        return (_run_snapshot(),) if project_id == PROJECT_ID and self.visible else ()

    async def run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        if owner_user_id != OWNER_ID or run_id != RUN_ID or not self.visible:
            return None
        return _run_snapshot()

    async def checkpoints(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        return (
            {
                "id": "00000000-0000-4000-8000-000000011005",
                "run_id": str(RUN_ID),
                "sequence_number": 1,
                "state_version": 2,
            },
        )

    async def apply_lifecycle_command(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunLifecycleCommand,
    ) -> WorkflowRunApiCommandResult:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        self.lifecycle_commands.append(command)
        return self.result


def _client(service: _WorkflowService | None) -> TestClient:
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


def _lifecycle_body() -> dict[str, object]:
    return {
        "command_id": str(COMMAND_ID),
        "project_id": str(PROJECT_ID),
        "expected_state_version": 2,
        "expected_checkpoint_sequence": 1,
        "occurred_at": NOW.isoformat(),
        "reason": "Owner requested an explicit pause.",
        "authorization_reference": None,
    }


def test_workflow_run_resources_preserve_owner_scope_and_exact_commands() -> None:
    service = _WorkflowService()
    client = _client(service)

    created = client.post(
        f"/api/v1/projects/{PROJECT_ID}/runs",
        json={
            "run_id": str(RUN_ID),
            "project_mode": "GREENFIELD_GENERATION",
            "created_at": NOW.isoformat(),
        },
    )
    listing = client.get(f"/api/v1/projects/{PROJECT_ID}/runs")
    detail = client.get(f"/api/v1/runs/{RUN_ID}")
    checkpoints = client.get(f"/api/v1/runs/{RUN_ID}/checkpoints")

    assert created.status_code == 201
    assert created.json()["status"] == "RUN_CREATED"
    assert service.create_command is not None
    assert service.create_command.run_id == RUN_ID
    assert listing.json()["items"][0]["id"] == str(RUN_ID)
    assert detail.json()["snapshot"]["owner_user_id"] == str(OWNER_ID)
    assert checkpoints.json()["items"][0]["sequence_number"] == 1


def test_pause_resume_and_cancel_translate_to_distinct_typed_commands() -> None:
    service = _WorkflowService()
    client = _client(service)

    for action in ("pause", "resume", "cancel"):
        response = client.post(f"/api/v1/runs/{RUN_ID}/{action}", json=_lifecycle_body())
        assert response.status_code == 200

    assert [command.kind for command in service.lifecycle_commands] == [
        WorkflowLifecycleCommandKind.PAUSE,
        WorkflowLifecycleCommandKind.RESUME,
        WorkflowLifecycleCommandKind.CANCEL,
    ]
    assert all(command.expected_state_version == 2 for command in service.lifecycle_commands)


def test_workflow_run_failures_are_typed_and_owner_safe() -> None:
    service = _WorkflowService()
    service.visible = False
    client = _client(service)

    missing = client.get(f"/api/v1/runs/{RUN_ID}")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "WORKFLOW_RUN_NOT_FOUND"

    service.visible = True
    service.result = WorkflowRunApiCommandResult(
        WorkflowRunApiStatus.STATE_CONFLICT,
        _run_snapshot(),
        "Workflow state changed before this command.",
    )
    conflict = client.post(f"/api/v1/runs/{RUN_ID}/pause", json=_lifecycle_body())
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["status"] == "STATE_CONFLICT"

    unavailable = _client(None).get(f"/api/v1/runs/{RUN_ID}")
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "WORKFLOW_RUN_API_SERVICE_UNAVAILABLE"
