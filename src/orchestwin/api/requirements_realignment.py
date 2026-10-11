from __future__ import annotations

from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import CurrentUser
from orchestwin.api.dependencies import app_service
from orchestwin.api.refusals import refusal
from orchestwin.projects.requirements_realignment_service import (
    RequirementsAlignment,
    RequirementsRealignmentFailure,
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion

REQUIREMENTS_REALIGNMENT_API_PREFIX: Final = "/projects/{project_id}/requirements/twin-alignment"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementsAlignmentPayload(ApiModel):
    aligned: bool
    issue: str | None
    requirements_version_number: int | None
    snapshot_version_number: int | None
    twins_approved: bool

    @classmethod
    def from_domain(cls, alignment: RequirementsAlignment) -> RequirementsAlignmentPayload:
        return cls(
            aligned=alignment.aligned,
            issue=alignment.issue,
            requirements_version_number=alignment.requirements_version_number,
            snapshot_version_number=alignment.snapshot_version_number,
            twins_approved=alignment.twins_approved,
        )


class RequirementsRealignmentPayload(ApiModel):
    version_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    user_modeling_version_number: int
    twin_count: int
    gate_approval_required: bool

    @classmethod
    def from_domain(
        cls, version: RequirementsSpecificationVersion
    ) -> RequirementsRealignmentPayload:
        specification = version.specification
        return cls(
            version_id=version.id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            user_modeling_version_number=specification.user_modeling_reference.version_number,
            twin_count=len(specification.user_twin_references),
            gate_approval_required=True,
        )


requirements_realignment_service_dependency = app_service(
    "requirements_realignment_service", {"code": "REQUIREMENTS_REALIGNMENT_SERVICE_UNAVAILABLE"}
)


def requirements_realignment_failure(error: RequirementsRealignmentFailure) -> HTTPException:
    return refusal(404 if error.code == "REQUIREMENTS_NOT_FOUND" else 409, error.code)


def create_requirements_realignment_router() -> APIRouter:
    router = APIRouter(prefix=REQUIREMENTS_REALIGNMENT_API_PREFIX, tags=["requirements"])

    @router.get(
        "",
        response_model=RequirementsAlignmentPayload,
        operation_id="getRequirementsTwinAlignment",
    )
    async def alignment_endpoint(
        project_id: UUID,
        user: CurrentUser,
        service: Annotated[
            RequirementsRealignmentService,
            Depends(requirements_realignment_service_dependency),
        ],
    ) -> RequirementsAlignmentPayload:
        alignment = await service.status(owner_user_id=user.id, project_id=project_id)
        return RequirementsAlignmentPayload.from_domain(alignment)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=RequirementsRealignmentPayload,
        operation_id="realignRequirementsToTwins",
    )
    async def realign_endpoint(
        project_id: UUID,
        user: CurrentUser,
        service: Annotated[
            RequirementsRealignmentService,
            Depends(requirements_realignment_service_dependency),
        ],
    ) -> RequirementsRealignmentPayload:
        try:
            version = await service.realign(owner_user_id=user.id, project_id=project_id)
        except RequirementsRealignmentFailure as error:
            raise requirements_realignment_failure(error) from error

        return RequirementsRealignmentPayload.from_domain(version)

    return router


__all__ = [
    "REQUIREMENTS_REALIGNMENT_API_PREFIX",
    "RequirementsAlignmentPayload",
    "RequirementsRealignmentPayload",
    "create_requirements_realignment_router",
    "requirements_realignment_failure",
    "requirements_realignment_service_dependency",
]
