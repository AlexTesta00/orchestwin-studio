from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Protocol
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException

from orchestwin.activity import ActivityError
from orchestwin.api.auth import CurrentUser
from orchestwin.api.dependencies import app_service


class ProjectActivityService(Protocol):
    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None: ...
    async def session(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None: ...
    async def start_session(
        self, *, owner_user_id: UUID, project_id: UUID, session_code: str
    ) -> dict: ...
    async def end_session(
        self, *, owner_user_id: UUID, project_id: UUID, session_code: str
    ) -> dict: ...
    async def append_events(
        self, *, owner_user_id: UUID, project_id: UUID, request: Mapping
    ) -> dict: ...


activity_service_dependency = app_service(
    "activity_service", {"code": "ACTIVITY_SERVICE_UNAVAILABLE"}
)
ActivityService = Annotated[ProjectActivityService, Depends(activity_service_dependency)]
Payload = Annotated[Any, Body()]
_CONFLICTS = frozenset(
    {
        "ACTIVITY_SESSION_ACTIVE",
        "ACTIVITY_SESSION_CODE_USED",
        "ACTIVITY_SESSION_NOT_ACTIVE",
        "ACTIVITY_JOURNAL_FULL",
    }
)


def _failure(code):
    status = 404 if code == "PROJECT_NOT_FOUND" else 409 if code in _CONFLICTS else 422
    raise HTTPException(status_code=status, detail={"code": code}) from None


def _found(result):
    if result is None:
        _failure("PROJECT_NOT_FOUND")
    return result


def create_activity_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/activity", tags=["activity"])

    @router.get("", operation_id="getProjectActivity")
    async def activity(project_id: UUID, user: CurrentUser, service: ActivityService) -> dict:
        try:
            return _found(await service.current(owner_user_id=user.id, project_id=project_id))
        except ActivityError as error:
            _failure(error.code)

    @router.get("/session", operation_id="getActivitySession")
    async def session(project_id: UUID, user: CurrentUser, service: ActivityService) -> dict:
        try:
            return _found(await service.session(owner_user_id=user.id, project_id=project_id))
        except ActivityError as error:
            _failure(error.code)

    @router.post("/sessions", operation_id="startActivitySession", status_code=201)
    async def start(
        project_id: UUID, user: CurrentUser, service: ActivityService, payload: Payload = None
    ) -> dict:
        if not isinstance(payload, dict) or set(payload) != {"session_code"}:
            _failure("ACTIVITY_INPUT_INVALID")
        try:
            return await service.start_session(
                owner_user_id=user.id, project_id=project_id, session_code=payload["session_code"]
            )
        except ActivityError as error:
            _failure(error.code)

    @router.post("/sessions/{session_code}/end", operation_id="endActivitySession")
    async def end(
        project_id: UUID, session_code: str, user: CurrentUser, service: ActivityService
    ) -> dict:
        try:
            return await service.end_session(
                owner_user_id=user.id, project_id=project_id, session_code=session_code
            )
        except ActivityError as error:
            _failure(error.code)

    @router.post("/events", operation_id="recordActivityEvents", status_code=202)
    async def record(
        project_id: UUID, user: CurrentUser, service: ActivityService, payload: Payload = None
    ) -> dict:
        try:
            return await service.append_events(
                owner_user_id=user.id, project_id=project_id, request=payload
            )
        except ActivityError as error:
            _failure(error.code)

    return router


__all__ = [
    "ProjectActivityService",
    "activity_service_dependency",
    "create_activity_router",
]
