"""Owner-scoped API contracts for durable workflow-run lifecycle resources."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.commands import WorkflowLifecycleCommandKind


class WorkflowRunApiStatus(StrEnum):
    """Stable owner-safe outcomes exposed by workflow lifecycle endpoints."""

    RUN_CREATED = "RUN_CREATED"
    COMMAND_APPLIED = "COMMAND_APPLIED"
    COMMAND_ALREADY_APPLIED = "COMMAND_ALREADY_APPLIED"
    NOT_FOUND = "NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"
    ILLEGAL_STATE = "ILLEGAL_STATE"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class WorkflowRunCreateCommand:
    """Explicit command for creating one owner-scoped draft workflow run."""

    run_id: UUID
    project_mode: ProjectMode
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkflowRunLifecycleCommand:
    """Exact lifecycle command translated from an authenticated HTTP request."""

    command_id: UUID
    project_id: UUID
    kind: WorkflowLifecycleCommandKind
    expected_state_version: int
    expected_checkpoint_sequence: int
    occurred_at: datetime
    reason: str | None
    authorization_reference: UUID | None


@dataclass(frozen=True, slots=True)
class WorkflowRunApiCommandResult:
    """Command result containing a snapshot only when it remains owner-visible."""

    status: WorkflowRunApiStatus
    snapshot: dict[str, JsonValue] | None
    message: str

    def __post_init__(self) -> None:
        if not self.message or self.message != " ".join(self.message.split()):
            raise ValueError("workflow API command message must be normalized")
        visible = self.status is not WorkflowRunApiStatus.NOT_FOUND
        if visible != (self.snapshot is not None):
            raise ValueError("workflow API command result shape is inconsistent")


class WorkflowRunApiService(Protocol):
    """Application port preserving owner scope and optimistic concurrency."""

    async def create_run(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        command: WorkflowRunCreateCommand,
    ) -> WorkflowRunApiCommandResult: ...

    async def list_runs(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> dict[str, JsonValue] | None: ...

    async def checkpoints(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def events(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        after_sequence: int,
        limit: int,
    ) -> tuple[dict[str, JsonValue], ...]: ...

    async def apply_lifecycle_command(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
        command: WorkflowRunLifecycleCommand,
    ) -> WorkflowRunApiCommandResult: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateWorkflowRunBody(ApiModel):
    run_id: UUID
    project_mode: ProjectMode
    created_at: datetime

    def to_command(self) -> WorkflowRunCreateCommand:
        return WorkflowRunCreateCommand(
            run_id=self.run_id,
            project_mode=self.project_mode,
            created_at=self.created_at,
        )


class WorkflowLifecycleBody(ApiModel):
    command_id: UUID
    project_id: UUID
    expected_state_version: int = Field(gt=0)
    expected_checkpoint_sequence: int = Field(ge=0)
    occurred_at: datetime
    reason: str | None = Field(default=None, min_length=1, max_length=2_000)
    authorization_reference: UUID | None = None

    def to_command(
        self,
        kind: WorkflowLifecycleCommandKind,
    ) -> WorkflowRunLifecycleCommand:
        return WorkflowRunLifecycleCommand(
            command_id=self.command_id,
            project_id=self.project_id,
            kind=kind,
            expected_state_version=self.expected_state_version,
            expected_checkpoint_sequence=self.expected_checkpoint_sequence,
            occurred_at=self.occurred_at,
            reason=self.reason,
            authorization_reference=self.authorization_reference,
        )


class SnapshotResponse(ApiModel):
    snapshot: dict[str, JsonValue]


class SnapshotListResponse(ApiModel):
    items: tuple[dict[str, JsonValue], ...]


class WorkflowCommandResponse(ApiModel):
    status: WorkflowRunApiStatus
    snapshot: dict[str, JsonValue]
    message: str


def workflow_run_api_service_dependency(request: Request) -> WorkflowRunApiService:
    service = getattr(request.app.state, "workflow_run_api_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "WORKFLOW_RUN_API_SERVICE_UNAVAILABLE"},
        )
    return service


def create_workflow_run_router() -> APIRouter:
    """Create authenticated workflow run resource and command routes."""
    router = APIRouter(tags=["workflow-runs"])

    @router.post(
        "/projects/{project_id}/runs",
        response_model=WorkflowCommandResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createWorkflowRun",
    )
    async def create_run(
        project_id: UUID,
        body: CreateWorkflowRunBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
    ) -> WorkflowCommandResponse:
        return _command_response(
            await service.create_run(
                owner_user_id=user.id,
                project_id=project_id,
                command=body.to_command(),
            )
        )

    @router.get(
        "/projects/{project_id}/runs",
        response_model=SnapshotListResponse,
        operation_id="listWorkflowRuns",
    )
    async def list_runs(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        return SnapshotListResponse(
            items=await service.list_runs(
                owner_user_id=user.id,
                project_id=project_id,
            )
        )

    @router.get(
        "/runs/{run_id}",
        response_model=SnapshotResponse,
        operation_id="getWorkflowRun",
    )
    async def get_run(
        run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
    ) -> SnapshotResponse:
        return SnapshotResponse(
            snapshot=_required_snapshot(await service.run(owner_user_id=user.id, run_id=run_id))
        )

    @router.get(
        "/runs/{run_id}/checkpoints",
        response_model=SnapshotListResponse,
        operation_id="listWorkflowRunCheckpoints",
    )
    async def list_checkpoints(
        run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
    ) -> SnapshotListResponse:
        if await service.run(owner_user_id=user.id, run_id=run_id) is None:
            raise _not_found()
        return SnapshotListResponse(
            items=await service.checkpoints(owner_user_id=user.id, run_id=run_id)
        )

    @router.get(
        "/runs/{run_id}/events",
        response_class=StreamingResponse,
        operation_id="streamWorkflowRunEvents",
        responses={
            200: {
                "content": {"text/event-stream": {}},
                "description": "Replayable ordered workflow events.",
            }
        },
    )
    async def stream_events(
        run_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
        after_sequence: Annotated[int | None, Query(ge=0)] = None,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        if await service.run(owner_user_id=user.id, run_id=run_id) is None:
            raise _not_found()
        cursor = _event_cursor(
            after_sequence=after_sequence,
            last_event_id=last_event_id,
        )
        events = await service.events(
            owner_user_id=user.id,
            run_id=run_id,
            after_sequence=cursor,
            limit=500,
        )
        return StreamingResponse(
            _event_stream(events),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    _add_lifecycle_route(router, "/runs/{run_id}/pause", WorkflowLifecycleCommandKind.PAUSE)
    _add_lifecycle_route(router, "/runs/{run_id}/resume", WorkflowLifecycleCommandKind.RESUME)
    _add_lifecycle_route(router, "/runs/{run_id}/cancel", WorkflowLifecycleCommandKind.CANCEL)

    return router


def _add_lifecycle_route(
    router: APIRouter,
    path: str,
    kind: WorkflowLifecycleCommandKind,
) -> None:
    operation_id = {
        WorkflowLifecycleCommandKind.PAUSE: "pauseWorkflowRun",
        WorkflowLifecycleCommandKind.RESUME: "resumeWorkflowRun",
        WorkflowLifecycleCommandKind.CANCEL: "cancelWorkflowRun",
    }[kind]

    async def apply_command(
        run_id: UUID,
        body: WorkflowLifecycleBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            WorkflowRunApiService,
            Depends(workflow_run_api_service_dependency),
        ],
    ) -> WorkflowCommandResponse:
        return _command_response(
            await service.apply_lifecycle_command(
                owner_user_id=user.id,
                run_id=run_id,
                command=body.to_command(kind),
            )
        )

    router.add_api_route(
        path,
        apply_command,
        methods=["POST"],
        response_model=WorkflowCommandResponse,
        operation_id=operation_id,
    )


def _required_snapshot(
    snapshot: dict[str, JsonValue] | None,
) -> dict[str, JsonValue]:
    if snapshot is None:
        raise _not_found()
    return snapshot


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "WORKFLOW_RUN_NOT_FOUND"},
    )


def _command_response(result: WorkflowRunApiCommandResult) -> WorkflowCommandResponse:
    if result.snapshot is not None and result.status in {
        WorkflowRunApiStatus.RUN_CREATED,
        WorkflowRunApiStatus.COMMAND_APPLIED,
        WorkflowRunApiStatus.COMMAND_ALREADY_APPLIED,
    }:
        return WorkflowCommandResponse(
            status=result.status,
            snapshot=result.snapshot,
            message=result.message,
        )
    if result.status is WorkflowRunApiStatus.NOT_FOUND:
        raise _not_found()
    status_code = {
        WorkflowRunApiStatus.STATE_CONFLICT: status.HTTP_409_CONFLICT,
        WorkflowRunApiStatus.ILLEGAL_STATE: status.HTTP_409_CONFLICT,
        WorkflowRunApiStatus.AUTHORIZATION_REQUIRED: status.HTTP_409_CONFLICT,
    }.get(result.status, status.HTTP_409_CONFLICT)
    raise HTTPException(
        status_code=status_code,
        detail={"status": result.status.value, "message": result.message},
    )


def _event_cursor(
    *,
    after_sequence: int | None,
    last_event_id: str | None,
) -> int:
    header_cursor: int | None = None
    if last_event_id is not None:
        normalized = last_event_id.strip()
        try:
            header_cursor = int(normalized)
        except ValueError as error:
            raise _invalid_event_cursor() from error
        if header_cursor < 0 or normalized != str(header_cursor):
            raise _invalid_event_cursor()
    if (
        after_sequence is not None
        and header_cursor is not None
        and (after_sequence != header_cursor)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "WORKFLOW_EVENT_CURSOR_CONFLICT"},
        )
    return after_sequence if after_sequence is not None else (header_cursor or 0)


def _invalid_event_cursor() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "WORKFLOW_EVENT_CURSOR_INVALID"},
    )


async def _event_stream(
    events: tuple[dict[str, JsonValue], ...],
) -> AsyncIterator[str]:
    for event in events:
        sequence = event.get("sequence_number")
        event_type = event.get("event_type")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("workflow SSE event requires a positive sequence number")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("workflow SSE event requires an event type")
        data = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        yield f"id: {sequence}\nevent: {event_type}\ndata: {data}\n\n"
