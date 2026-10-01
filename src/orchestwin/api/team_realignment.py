from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from orchestwin.agents.realignment_service import TeamRealignmentFailure, TeamRealignmentService
from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount

TEAM_REALIGNMENT_API_PREFIX = "/projects/{project_id}/team/context-alignment"


class TeamAlignmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aligned: bool
    issue: str | None
    team_version_number: int | None
    brief_version_number: int | None


class TeamRealignmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: UUID
    version_number: int
    based_on_version_number: int
    content_hash: str
    gate_approval_required: bool


def team_realignment_service_dependency(request: Request) -> TeamRealignmentService:
    service = getattr(request.app.state, "team_realignment_service", None)
    if service is None:
        raise HTTPException(
            status_code=503, detail={"code": "TEAM_REALIGNMENT_SERVICE_UNAVAILABLE"}
        )
    return service


def create_team_realignment_router() -> APIRouter:
    router = APIRouter(prefix=TEAM_REALIGNMENT_API_PREFIX, tags=["agent-team"])

    @router.get("", response_model=TeamAlignmentPayload, operation_id="getTeamContextAlignment")
    async def status_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TeamRealignmentService, Depends(team_realignment_service_dependency)],
    ) -> TeamAlignmentPayload:
        result = await service.status(owner_user_id=user.id, project_id=project_id)
        return TeamAlignmentPayload(
            aligned=result.aligned,
            issue=result.issue,
            team_version_number=result.team_version_number,
            brief_version_number=result.brief_version_number,
        )

    @router.post("", response_model=TeamRealignmentPayload, operation_id="realignTeamContext")
    async def realign_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TeamRealignmentService, Depends(team_realignment_service_dependency)],
    ) -> TeamRealignmentPayload:
        try:
            version = await service.realign(owner_user_id=user.id, project_id=project_id)
        except TeamRealignmentFailure as error:
            raise HTTPException(
                status_code=404 if error.code == "TEAM_NOT_FOUND" else 409,
                detail={"code": error.code},
            ) from None
        return TeamRealignmentPayload(
            version_id=version.id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            gate_approval_required=True,
        )

    return router


__all__ = [
    "TEAM_REALIGNMENT_API_PREFIX",
    "TeamAlignmentPayload",
    "TeamRealignmentPayload",
    "create_team_realignment_router",
    "team_realignment_service_dependency",
]
