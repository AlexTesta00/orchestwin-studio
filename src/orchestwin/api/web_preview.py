"""Authenticated source download; generated code is never served as application HTML."""

import base64
import io
import zipfile
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.web_execution import WebSourceApiService, web_source_api_service_dependency
from orchestwin.identity.domain import UserAccount


class WebSourceEditFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    normalized_path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=32768)
    media_type: str = Field(min_length=1, max_length=80)


class WebSourceEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_revision_content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str = Field(min_length=1, max_length=1000)
    files: list[WebSourceEditFile] = Field(min_length=1, max_length=48)
    mockup_generation_id: UUID | None = None


def create_web_preview_router():
    router = APIRouter(tags=["web-source-preview"])

    async def files(project_id, revision_id, user, service):
        operation = getattr(service, "source_files", None)
        if operation is None:
            raise HTTPException(503, detail={"code": "WEB_SOURCE_CONTENT_UNAVAILABLE"})
        result = await operation(
            owner_user_id=user.id, project_id=project_id, revision_id=revision_id
        )
        if result is None:
            raise HTTPException(404, detail={"code": "WEB_SOURCE_NOT_FOUND"})
        return result

    @router.post("/projects/{project_id}/web-source-revisions/{revision_id}/edits")
    async def edit(
        project_id: UUID,
        revision_id: UUID,
        body: WebSourceEditBody,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WebSourceApiService, Depends(web_source_api_service_dependency)],
    ):
        operation = getattr(service, "edit_source_revision", None)
        if operation is None:
            raise HTTPException(503, detail={"code": "WEB_SOURCE_EDIT_UNAVAILABLE"})
        result = await operation(
            owner_user_id=user.id,
            project_id=project_id,
            revision_id=revision_id,
            command=body,
        )
        return JSONResponse(
            status_code={
                "SOURCE_REVISION_CREATED": 201,
                "NOT_FOUND": 404,
                "INVALID": 422,
            }.get(result.status.value, 409),
            content={
                "status": result.status.value,
                "snapshot": result.snapshot,
                "message": result.message,
            },
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/projects/{project_id}/web-source-revisions/{revision_id}/content")
    async def content(
        project_id: UUID,
        revision_id: UUID,
        response: Response,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WebSourceApiService, Depends(web_source_api_service_dependency)],
    ):
        snapshot, entries = await files(project_id, revision_id, user, service)
        if snapshot["target_selection"]["target"] != "WEB_STATIC":
            raise HTTPException(409, detail={"code": "PREVIEW_REQUIRES_STATIC_WEB"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return {
            "revision_id": str(revision_id),
            "content_hash": snapshot["content_hash"],
            "files": [
                {
                    "path": name,
                    "media_type": media,
                    "base64": base64.b64encode(data).decode("ascii"),
                }
                for name, media, data in entries
            ],
        }

    @router.get("/projects/{project_id}/web-source-revisions/{revision_id}/design-reference")
    async def design_reference(
        project_id: UUID,
        revision_id: UUID,
        response: Response,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WebSourceApiService, Depends(web_source_api_service_dependency)],
    ):
        operation = getattr(service, "source_design_reference", None)
        if operation is None:
            raise HTTPException(503, detail={"code": "WEB_SOURCE_DESIGN_REFERENCE_UNAVAILABLE"})
        result = await operation(
            owner_user_id=user.id, project_id=project_id, revision_id=revision_id
        )
        if result is None:
            raise HTTPException(404, detail={"code": "WEB_SOURCE_NOT_FOUND"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return result

    @router.get("/projects/{project_id}/web-source-revisions/{revision_id}/download")
    async def download(
        project_id: UUID,
        revision_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[WebSourceApiService, Depends(web_source_api_service_dependency)],
    ):
        _, entries = await files(project_id, revision_id, user, service)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, _, data in entries:
                archive.writestr(name, data)
        return Response(
            stream.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="web-source-{revision_id}.zip"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return router
