from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.design_realignment import DesignRealignmentIssue
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.design_realignment_service import (
    DESIGN_NOT_FOUND,
    DesignAlignment,
    DesignRealignment,
    DesignRealignmentFailure,
    DesignRealignmentService,
)

DESIGN_REALIGNMENT_API_PREFIX: Final = "/projects/{project_id}/design/requirements-alignment"
_NOT_FOUND_CODES: Final = frozenset({DESIGN_NOT_FOUND})
_MISSING_CODES_ISSUE: Final = DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE.value


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignAlignmentPayload(ApiModel):
    aligned: bool
    issue: str | None
    design_version_number: int | None
    grounded_requirements_version_number: int | None
    requirements_version_number: int | None
    missing_codes: list[str]
    uncovered_codes: list[str]

    @classmethod
    def from_domain(cls, alignment: DesignAlignment) -> DesignAlignmentPayload:
        return cls(
            aligned=alignment.aligned,
            issue=alignment.issue,
            design_version_number=alignment.design_version_number,
            grounded_requirements_version_number=alignment.grounded_requirements_version_number,
            requirements_version_number=alignment.requirements_version_number,
            missing_codes=list(alignment.missing_codes),
            uncovered_codes=list(alignment.uncovered_codes),
        )


class DesignRealignmentPayload(ApiModel):
    version_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    requirements_version_number: int
    gate_approval_required: bool
    uncovered_codes: list[str]

    @classmethod
    def from_domain(cls, realignment: DesignRealignment) -> DesignRealignmentPayload:
        version = realignment.version
        return cls(
            version_id=version.id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            requirements_version_number=realignment.requirements_version_number,
            gate_approval_required=True,
            uncovered_codes=list(realignment.uncovered_codes),
        )


def design_realignment_service_dependency(request: Request) -> DesignRealignmentService:
    service = getattr(request.app.state, "design_realignment_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DESIGN_REALIGNMENT_SERVICE_UNAVAILABLE"},
        )

    return service


def design_realignment_failure(error: DesignRealignmentFailure) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if error.code in _NOT_FOUND_CODES else status.HTTP_409_CONFLICT
    )
    detail: dict[str, object] = {"code": error.code}
    if error.code == _MISSING_CODES_ISSUE:
        detail["missing_codes"] = list(error.missing_codes)
    return HTTPException(status_code=status_code, detail=detail)


def create_design_realignment_router() -> APIRouter:
    router = APIRouter(prefix=DESIGN_REALIGNMENT_API_PREFIX, tags=["design"])

    @router.get(
        "",
        response_model=DesignAlignmentPayload,
        operation_id="getDesignRequirementsAlignment",
    )
    async def alignment_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignRealignmentService,
            Depends(design_realignment_service_dependency),
        ],
    ) -> DesignAlignmentPayload:
        alignment = await service.status(owner_user_id=user.id, project_id=project_id)
        return DesignAlignmentPayload.from_domain(alignment)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=DesignRealignmentPayload,
        operation_id="realignDesignToRequirements",
    )
    async def realign_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignRealignmentService,
            Depends(design_realignment_service_dependency),
        ],
    ) -> DesignRealignmentPayload:
        try:
            realignment = await service.realign(owner_user_id=user.id, project_id=project_id)
        except DesignRealignmentFailure as error:
            raise design_realignment_failure(error) from error

        return DesignRealignmentPayload.from_domain(realignment)

    return router


__all__ = [
    "DESIGN_REALIGNMENT_API_PREFIX",
    "DesignAlignmentPayload",
    "DesignRealignmentPayload",
    "create_design_realignment_router",
    "design_realignment_failure",
    "design_realignment_service_dependency",
]
