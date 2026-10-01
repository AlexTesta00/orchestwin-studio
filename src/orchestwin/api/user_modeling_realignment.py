from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.twins.realignment import UserModelingRealignment
from orchestwin.twins.realignment_service import (
    USER_TWINS_NOT_FOUND,
    UserModelingAlignment,
    UserModelingRealignmentFailure,
    UserModelingRealignmentService,
)

USER_MODELING_REALIGNMENT_API_PREFIX: Final = (
    "/projects/{project_id}/user-modeling/context-alignment"
)
_NOT_FOUND_CODES: Final = frozenset({USER_TWINS_NOT_FOUND})


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UserModelingAlignmentPayload(ApiModel):
    aligned: bool
    issue: str | None
    snapshot_version_number: int | None
    brief_version_number: int | None
    team_version_number: int | None

    @classmethod
    def from_domain(cls, alignment: UserModelingAlignment) -> UserModelingAlignmentPayload:
        return cls(
            aligned=alignment.aligned,
            issue=alignment.issue,
            snapshot_version_number=alignment.snapshot_version_number,
            brief_version_number=alignment.brief_version_number,
            team_version_number=alignment.team_version_number,
        )


class UserModelingRealignmentPayload(ApiModel):
    snapshot_version_id: UUID
    snapshot_version_number: int
    based_on_version_number: int | None
    content_hash: str
    twin_count: int
    gate_approval_required: bool

    @classmethod
    def from_domain(cls, realignment: UserModelingRealignment) -> UserModelingRealignmentPayload:
        version = realignment.snapshot_version
        return cls(
            snapshot_version_id=version.id,
            snapshot_version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            twin_count=version.snapshot.twin_count,
            gate_approval_required=True,
        )


def user_modeling_realignment_service_dependency(
    request: Request,
) -> UserModelingRealignmentService:
    service = getattr(request.app.state, "user_modeling_realignment_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "USER_MODELING_REALIGNMENT_SERVICE_UNAVAILABLE"},
        )

    return service


def user_modeling_realignment_failure(error: UserModelingRealignmentFailure) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if error.code in _NOT_FOUND_CODES else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=status_code, detail={"code": error.code})


def create_user_modeling_realignment_router() -> APIRouter:
    router = APIRouter(prefix=USER_MODELING_REALIGNMENT_API_PREFIX, tags=["user-modeling"])

    @router.get(
        "",
        response_model=UserModelingAlignmentPayload,
        operation_id="getUserModelingContextAlignment",
    )
    async def alignment_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            UserModelingRealignmentService,
            Depends(user_modeling_realignment_service_dependency),
        ],
    ) -> UserModelingAlignmentPayload:
        alignment = await service.status(owner_user_id=user.id, project_id=project_id)
        return UserModelingAlignmentPayload.from_domain(alignment)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=UserModelingRealignmentPayload,
        operation_id="realignUserModelingToContext",
    )
    async def realign_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            UserModelingRealignmentService,
            Depends(user_modeling_realignment_service_dependency),
        ],
    ) -> UserModelingRealignmentPayload:
        try:
            realignment = await service.realign(owner_user_id=user.id, project_id=project_id)
        except UserModelingRealignmentFailure as error:
            raise user_modeling_realignment_failure(error) from error

        return UserModelingRealignmentPayload.from_domain(realignment)

    return router


__all__ = [
    "USER_MODELING_REALIGNMENT_API_PREFIX",
    "UserModelingAlignmentPayload",
    "UserModelingRealignmentPayload",
    "create_user_modeling_realignment_router",
    "user_modeling_realignment_failure",
    "user_modeling_realignment_service_dependency",
]
