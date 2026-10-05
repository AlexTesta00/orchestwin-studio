from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.why import WhyError, explain_why


class WhyQueryService(Protocol):
    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> dict | None: ...


def why_query_service_dependency(request: Request) -> WhyQueryService:
    service = getattr(request.app.state, "why_query_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail={"code": "WHY_SERVICE_UNAVAILABLE"})
    return service


def create_artifact_why_router() -> APIRouter:
    router = APIRouter(prefix="/projects/{project_id}/artifacts/why", tags=["artifacts"])

    async def document(project_id, user, service):
        result = await service.current(owner_user_id=user.id, project_id=project_id)
        if result is None:
            raise HTTPException(status_code=404, detail={"code": "PROJECT_NOT_FOUND"})
        return result

    @router.get("/document", operation_id="getWhyDocument")
    async def document_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WhyQueryService, Depends(why_query_service_dependency)],
    ) -> dict:
        return await document(project_id, user, service)

    @router.get("", operation_id="getArtifactWhy")
    async def explain_endpoint(
        project_id: UUID,
        code: str,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WhyQueryService, Depends(why_query_service_dependency)],
    ) -> dict:
        result = await document(project_id, user, service)
        try:
            return explain_why(result, code)
        except WhyError as error:
            status = {
                "WHY_CODE_INVALID": 422,
                "WHY_CODE_NOT_FOUND": 404,
                "WHY_CODE_AMBIGUOUS": 409,
            }[error.code]
            detail = {"code": error.code}
            if error.candidates:
                detail["candidates"] = list(error.candidates)
            raise HTTPException(status_code=status, detail=detail) from None

    return router


__all__ = ["WhyQueryService", "create_artifact_why_router", "why_query_service_dependency"]
