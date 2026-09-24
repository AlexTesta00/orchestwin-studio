from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from orchestwin.api.auth import current_user_dependency
from orchestwin.artifacts.design_package_export import (
    DesignPackageExportError,
    DesignPackageExportService,
)
from orchestwin.identity.domain import UserAccount

DESIGN_PACKAGE_API_PREFIX = "/projects/{project_id}"


def design_package_export_service_dependency(request: Request) -> DesignPackageExportService:
    service = getattr(request.app.state, "design_package_export_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "DESIGN_PACKAGE_SERVICE_UNAVAILABLE"},
        )

    return service


def create_design_package_router() -> APIRouter:
    router = APIRouter(prefix=DESIGN_PACKAGE_API_PREFIX, tags=["design"])

    @router.get(
        "/design-package",
        response_class=Response,
        operation_id="exportDesignPackage",
    )
    async def export_design_package_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignPackageExportService,
            Depends(design_package_export_service_dependency),
        ],
    ) -> Response:
        try:
            archive = await service.export(owner_user_id=user.id, project_id=project_id)
        except DesignPackageExportError as error:
            status_code = (
                status.HTTP_404_NOT_FOUND
                if error.code == "PROJECT_NOT_FOUND"
                else status.HTTP_409_CONFLICT
            )
            raise HTTPException(status_code=status_code, detail={"code": error.code}) from error

        return Response(
            content=archive.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{archive.file_name}"',
                "X-Content-SHA256": archive.content_hash,
            },
        )

    return router


__all__ = [
    "DESIGN_PACKAGE_API_PREFIX",
    "create_design_package_router",
    "design_package_export_service_dependency",
]
