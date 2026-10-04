from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.design import DESIGN_API_PREFIX
from orchestwin.api.design_mockups import ModelMockupApplication
from orchestwin.artifacts.design_distance import (
    AdherenceStatus,
    DistanceVerdict,
    StructureDifference,
    StyleDifference,
    design_distance_report,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.generated_mockups import GeneratedMockup
from orchestwin.identity.domain import UserAccount
from orchestwin.models.generated_mockup_instructions import GENERATED_MOCKUP_PURPOSES


class DistanceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeclaredDistancePayload(DistanceModel):
    score: int | None
    axes_different: int | None
    axes: tuple[str, ...]
    choices_different: int | None
    choices_total: int
    primary_colour_distance: float | None


class StyleDistancePayload(DistanceModel):
    available: bool
    score: int | None
    differences: tuple[StyleDifference, ...]


class StructureDistancePayload(DistanceModel):
    available: bool
    score: int | None
    differences: tuple[StructureDifference, ...]


class DistancePairPayload(DistanceModel):
    first: str
    second: str
    declared: DeclaredDistancePayload
    styles: StyleDistancePayload
    structure: StructureDistancePayload
    verdict: DistanceVerdict


class DirectionAdherencePayload(DistanceModel):
    available: bool
    axes: dict[str, AdherenceStatus]


class AlternativeDistancePayload(DistanceModel):
    code: str
    direction: str | None
    adherence: DirectionAdherencePayload


class DesignDistancePayload(DistanceModel):
    distance_version: int
    design_version_id: UUID
    design_content_hash: str
    pairs: tuple[DistancePairPayload, ...]
    alternatives: tuple[AlternativeDistancePayload, ...]


async def kept_mockups(
    application: ModelMockupApplication,
    owner_user_id: UUID,
    project_id: UUID,
    version: DesignPackageVersion,
) -> dict[UUID, GeneratedMockup]:
    applied = version.package.generated_mockup
    mockups: dict[UUID, GeneratedMockup] = {}
    for alternative in version.package.alternatives:
        if applied is not None and applied.design_alternative_id == alternative.id:
            mockups[alternative.id] = applied.mockup
            continue
        found = await application.newest_accepted(
            owner_user_id, project_id, version, alternative.id, GENERATED_MOCKUP_PURPOSES
        )
        bound = None if found is None else found[1].generated_mockup
        if bound is not None:
            mockups[alternative.id] = bound.mockup
    return mockups


def create_design_distance_router() -> APIRouter:
    router = APIRouter(prefix=DESIGN_API_PREFIX, tags=["design"])

    @router.get(
        "/distance",
        response_model=DesignDistancePayload,
        operation_id="getDesignDistance",
    )
    async def design_distance_endpoint(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        application = ModelMockupApplication(request.app.state.application_runtime)
        version = await application.current(user.id, project_id)
        mockups = await kept_mockups(application, user.id, project_id, version)
        return design_distance_report(version, mockups)

    return router


__all__ = [
    "AlternativeDistancePayload",
    "DeclaredDistancePayload",
    "DesignDistancePayload",
    "DirectionAdherencePayload",
    "DistancePairPayload",
    "StructureDistancePayload",
    "StyleDistancePayload",
    "create_design_distance_router",
    "kept_mockups",
]
