from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount

MODEL_USAGE_ITEMS = 200


def _store(request: Request):
    store = getattr(request.app.state.application_runtime, "proposal_evidence_store", None)
    if store is None:
        raise HTTPException(503, detail={"code": "PROPOSAL_EVIDENCE_UNAVAILABLE"})
    return store


def create_model_usage_router() -> APIRouter:
    router = APIRouter(tags=["model-usage"])

    @router.get("/projects/{project_id}/model-usage")
    async def model_usage(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        usage = await _store(request).model_usage(
            owner_user_id=user.id, project_id=project_id, limit=MODEL_USAGE_ITEMS
        )
        if usage is None:
            raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
        return usage

    @router.get("/model-runtime/budget")
    async def budget(
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        real = getattr(request.app.state.application_runtime, "real_model_runtime", None)
        if real is None:
            raise HTTPException(503, detail={"code": "REAL_MODEL_RUNTIME_NOT_CONFIGURED"})
        ceilings = getattr(real, "budget", None)
        if ceilings is None:
            raise HTTPException(503, detail={"code": "GENERATION_BUDGET_NOT_CONFIGURED"})
        spent = await _store(request).spent_microusd(since=ceilings.period_start)
        return ceilings.report(spent)

    return router


__all__ = ["MODEL_USAGE_ITEMS", "create_model_usage_router"]
