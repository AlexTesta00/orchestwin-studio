"""Authenticated project-owner access to immutable model proposal evidence."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount


def _store(request: Request):
    store = request.app.state.proposal_evidence_store
    if store is None:
        raise HTTPException(503, detail={"code": "PROPOSAL_EVIDENCE_UNAVAILABLE"})
    return store


def create_proposal_evidence_router() -> APIRouter:
    router = APIRouter(
        prefix="/projects/{project_id}/model-generations", tags=["model-generations"]
    )

    @router.get("")
    async def generations(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        before: UUID | None = None,
    ):
        rows = await _store(request).list_owned(
            owner_user_id=user.id,
            project_id=project_id,
            limit=limit,
            before=before,
        )
        if rows is None:
            raise HTTPException(404, detail={"code": "PROJECT_NOT_FOUND"})
        return {"generations": rows}

    @router.get("/{generation_id}")
    async def generation(
        project_id: UUID,
        generation_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
    ):
        record = await _store(request).get_owned(
            owner_user_id=user.id,
            project_id=project_id,
            generation_id=generation_id,
        )
        if record is None:
            raise HTTPException(404, detail={"code": "GENERATION_NOT_FOUND"})
        return record

    return router
