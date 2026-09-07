"""SSE contract tests for ordered and replayable workflow events."""

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
    WorkflowRunCreateCommand,
    WorkflowRunLifecycleCommand,
)
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount

OWNER_ID = UUID("00000000-0000-4000-8000-000000012001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000012002")
RUN_ID = UUID("00000000-0000-4000-8000-000000012003")
NOW = datetime(2026, 8, 30, 14, 0, tzinfo=UTC)


def _user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("event-owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class _EventService:
    def __init__(self) -> None:
        self.after_sequence: int | None = None
        self.visible = True

    async def create_run(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WorkflowRunCreateCommand,
    ) -> WorkflowRunApiCommandResult:
        raise AssertionError((owner_user_id, project_id, command))

    async def list_runs(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        raise AssertionError((owner_user_id, project_id))

    async def run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> dict[str, JsonValue] | None:
        if owner_user_id != OWNER_ID or run_id != RUN_ID or not self.visible:
            return None
        return {"id": str(RUN_ID), "project_id": str(PROJECT_ID)}

    async def checkpoints(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]:
        raise AssertionError((owner_user_id, run_id))

    async def events(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> tuple[dict[str, JsonValue], ...]:
        assert owner_user_id == OWNER_ID
        assert run_id == RUN_ID
        assert limit == 500
        self.after_sequence = after_sequence
        return tuple(
            {
                "id": f"00000000-0000-4000-8000-{sequence:012d}",
                "run_id": str(RUN_ID),
                "project_id": str(PROJECT_ID),
                "sequence_number": sequence,
                "event_type": event_type,
                "occurred_at": NOW.isoformat(),
                "payload": {"state_version": sequence},
            }
            for sequence, event_type in (
                (2, "workflow.waiting_for_human"),
                (3, "workflow.resumed"),
            )
            if sequence > after_sequence
        )

    async def apply_lifecycle_command(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunLifecycleCommand,
    ) -> WorkflowRunApiCommandResult:
        raise AssertionError((owner_user_id, run_id, command))


def _client(service: _EventService) -> TestClient:
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


def test_sse_stream_replays_events_after_the_standard_cursor() -> None:
    service = _EventService()
    response = _client(service).get(
        f"/api/v1/runs/{RUN_ID}/events",
        headers={"Last-Event-ID": "1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert service.after_sequence == 1
    assert "id: 2\nevent: workflow.waiting_for_human\ndata: " in response.text
    assert "id: 3\nevent: workflow.resumed\ndata: " in response.text
    assert response.text.index("id: 2") < response.text.index("id: 3")


def test_query_cursor_is_supported_and_conflicts_are_rejected() -> None:
    service = _EventService()
    client = _client(service)

    replay = client.get(f"/api/v1/runs/{RUN_ID}/events", params={"after_sequence": 2})
    assert replay.status_code == 200
    assert service.after_sequence == 2
    assert "id: 2" not in replay.text
    assert "id: 3" in replay.text

    conflict = client.get(
        f"/api/v1/runs/{RUN_ID}/events",
        params={"after_sequence": 2},
        headers={"Last-Event-ID": "1"},
    )
    assert conflict.status_code == 400
    assert conflict.json()["detail"]["code"] == "WORKFLOW_EVENT_CURSOR_CONFLICT"

    invalid = client.get(
        f"/api/v1/runs/{RUN_ID}/events",
        headers={"Last-Event-ID": "not-a-sequence"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["detail"]["code"] == "WORKFLOW_EVENT_CURSOR_INVALID"


def test_sse_stream_hides_cross_owner_or_missing_runs() -> None:
    service = _EventService()
    service.visible = False

    response = _client(service).get(f"/api/v1/runs/{RUN_ID}/events")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "WORKFLOW_RUN_NOT_FOUND"
