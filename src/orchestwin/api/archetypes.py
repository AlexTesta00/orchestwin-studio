from __future__ import annotations

from typing import Annotated, Self
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.twins.archetypes import ArchetypeFailure, ArchetypeIssue, ArchetypeService
from orchestwin.twins.personas import PersonaConfirmationStatus, PersonaSource
from orchestwin.twins.representation import ArchetypeInput, archetype_payload


class ArchetypePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    persona_id: UUID
    version_id: UUID
    version_number: int
    name: str
    description: str | None
    role: str | None
    goals: tuple[str, ...]
    context: str | None
    source: PersonaSource
    confirmation_status: PersonaConfirmationStatus
    archived: bool


class ArchetypeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str
    description: str
    role: str
    goals: list[str] = Field(default_factory=list)
    context: str | None = None

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        self.to_domain()
        return self

    def to_domain(self) -> ArchetypeInput:
        return ArchetypeInput(
            name=self.name,
            description=self.description,
            role=self.role,
            goals=tuple(self.goals),
            context=self.context,
        )


class ArchetypeEditRequest(ArchetypeRequest):
    based_on_version_number: int = Field(ge=1, strict=True)


class ArchetypeArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    based_on_version_number: int = Field(ge=1, strict=True)


def archetype_service_dependency(request: Request) -> ArchetypeService:
    service = getattr(request.app.state, "archetype_service", None)
    if service is None:
        raise HTTPException(503, detail={"code": "ARCHETYPE_SERVICE_UNAVAILABLE"})
    return service


def _failure(error: ArchetypeFailure) -> HTTPException:
    code = error.issue
    status = (
        404
        if code in {ArchetypeIssue.PROJECT_NOT_FOUND, ArchetypeIssue.ARCHETYPE_NOT_FOUND}
        else 409
    )
    return HTTPException(status, detail={"code": code.value})


def create_archetypes_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/user-modeling", tags=["user-modeling"])

    @router.get("/archetypes", response_model=tuple[ArchetypePayload, ...])
    async def list_archetypes(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ArchetypeService, Depends(archetype_service_dependency)],
    ):
        try:
            versions = await service.list_current(owner_user_id=user.id, project_id=project_id)
        except ArchetypeFailure as error:
            raise _failure(error) from None
        return tuple(ArchetypePayload.model_validate(archetype_payload(item)) for item in versions)

    @router.post("/archetypes", response_model=ArchetypePayload, status_code=201)
    async def create_archetype(
        project_id: UUID,
        body: ArchetypeRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ArchetypeService, Depends(archetype_service_dependency)],
    ):
        try:
            version = await service.create(
                owner_user_id=user.id, project_id=project_id, data=body.to_domain()
            )
        except ArchetypeFailure as error:
            raise _failure(error) from None
        return ArchetypePayload.model_validate(archetype_payload(version))

    @router.patch("/archetypes/{persona_id}", response_model=ArchetypePayload)
    async def edit_archetype(
        project_id: UUID,
        persona_id: UUID,
        body: ArchetypeEditRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ArchetypeService, Depends(archetype_service_dependency)],
    ):
        try:
            version = await service.edit(
                owner_user_id=user.id,
                project_id=project_id,
                persona_id=persona_id,
                based_on_version_number=body.based_on_version_number,
                data=body.to_domain(),
            )
        except ArchetypeFailure as error:
            raise _failure(error) from None
        return ArchetypePayload.model_validate(archetype_payload(version))

    @router.delete("/archetypes/{persona_id}", response_model=ArchetypePayload)
    async def archive_archetype(
        project_id: UUID,
        persona_id: UUID,
        body: ArchetypeArchiveRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ArchetypeService, Depends(archetype_service_dependency)],
    ):
        try:
            version = await service.archive(
                owner_user_id=user.id,
                project_id=project_id,
                persona_id=persona_id,
                based_on_version_number=body.based_on_version_number,
            )
        except ArchetypeFailure as error:
            raise _failure(error) from None
        return ArchetypePayload.model_validate(archetype_payload(version))

    return router
