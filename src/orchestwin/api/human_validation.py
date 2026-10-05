from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.validation import ValidationError


class HumanValidationService(Protocol):
    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None: ...
    async def walkthrough(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        scenario_key: str,
        alternative_id: str | None = None,
        document_hash: str | None = None,
    ) -> dict | None: ...
    async def save_hypothesis(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        request: Mapping,
        hypothesis_id: UUID | None = None,
    ) -> dict: ...
    async def record_outcome(
        self, *, owner_user_id: UUID, project_id: UUID, request: Mapping
    ) -> dict: ...


def human_validation_service_dependency(request: Request) -> HumanValidationService:
    service = getattr(request.app.state, "human_validation_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "VALIDATION_SERVICE_UNAVAILABLE"})
    return service


CurrentUser = Annotated[UserAccount, Depends(current_user_dependency)]
ValidationService = Annotated[HumanValidationService, Depends(human_validation_service_dependency)]


def _failure(error):
    code = error.code
    status = (
        404
        if code in {"PROJECT_NOT_FOUND", "HYPOTHESIS_NOT_FOUND", "VALIDATION_SOURCE_NOT_FOUND"}
        else 409
        if code
        in {
            "VALIDATION_CONTEXT_CHANGED",
            "HYPOTHESIS_VERSION_CONFLICT",
            "VALIDATION_SOURCE_RETIRED",
            "VALIDATION_SOURCE_TEXT_UNAVAILABLE",
        }
        else 422
    )
    raise HTTPException(status_code=status, detail={"code": code}) from None


def create_human_validation_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/validation", tags=["validation"])

    @router.get("", operation_id="getHumanValidation")
    async def overview(project_id: UUID, user: CurrentUser, service: ValidationService) -> dict:
        result = await service.current(owner_user_id=user.id, project_id=project_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
        return result

    @router.get("/walkthrough", operation_id="getScenarioWalkthrough")
    async def walkthrough(
        project_id: UUID,
        scenario_key: str,
        user: CurrentUser,
        service: ValidationService,
        alternative_id: str | None = None,
        document_hash: str | None = None,
    ) -> dict:
        try:
            result = await service.walkthrough(
                owner_user_id=user.id,
                project_id=project_id,
                scenario_key=scenario_key,
                alternative_id=alternative_id,
                document_hash=document_hash,
            )
        except ValidationError as error:
            _failure(error)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
        return result

    @router.post("/hypotheses", operation_id="saveValidationHypothesis", status_code=201)
    async def save(
        project_id: UUID,
        user: CurrentUser,
        service: ValidationService,
        payload: Annotated[dict, Body()],
    ) -> dict:
        try:
            return await service.save_hypothesis(
                owner_user_id=user.id, project_id=project_id, request=payload
            )
        except ValidationError as error:
            _failure(error)

    @router.post(
        "/hypotheses/{hypothesis_id}/versions",
        operation_id="reviseValidationHypothesis",
        status_code=201,
    )
    async def revise(
        project_id: UUID,
        hypothesis_id: UUID,
        user: CurrentUser,
        service: ValidationService,
        payload: Annotated[dict, Body()],
    ) -> dict:
        try:
            return await service.save_hypothesis(
                owner_user_id=user.id,
                project_id=project_id,
                hypothesis_id=hypothesis_id,
                request=payload,
            )
        except ValidationError as error:
            _failure(error)

    @router.post("/outcomes", operation_id="recordValidationOutcome", status_code=201)
    async def record(
        project_id: UUID,
        user: CurrentUser,
        service: ValidationService,
        payload: Annotated[dict, Body()],
    ) -> dict:
        try:
            return await service.record_outcome(
                owner_user_id=user.id, project_id=project_id, request=payload
            )
        except ValidationError as error:
            _failure(error)

    return router


__all__ = [
    "HumanValidationService",
    "create_human_validation_router",
    "human_validation_service_dependency",
]
