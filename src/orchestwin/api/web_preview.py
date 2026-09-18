"""Authenticated source download; generated code is never served as application HTML."""

import base64
import io
import zipfile
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.web_execution import WebSourceApiService, web_source_api_service_dependency
from orchestwin.identity.domain import UserAccount


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
