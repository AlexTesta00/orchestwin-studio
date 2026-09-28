from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.archive import MAX_ARCHIVE_SIZE
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.project_import import FolderOrigin
from orchestwin.knowledge.project_import_persistence import ProjectImportRecord
from orchestwin.knowledge.project_import_service import (
    PROJECT_NAME_INVALID,
    ProjectImportError,
    ProjectImportResult,
    ProjectImportService,
)
from orchestwin.projects.domain import ProjectMode

PROJECT_IMPORTS_PATH: Final = "/project-imports"
PROJECT_IMPORT_ORIGIN_PATH: Final = "/projects/{project_id}/import"
FOLDER_ARCHIVE_TOO_LARGE: Final = "FOLDER_ARCHIVE_TOO_LARGE"
PROJECT_IMPORT_NOT_FOUND: Final = "PROJECT_IMPORT_NOT_FOUND"
PROJECT_IMPORT_SERVICE_UNAVAILABLE: Final = "PROJECT_IMPORT_SERVICE_UNAVAILABLE"
_FOLDER_CODE_PREFIX: Final = "FOLDER_"


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImportedProjectPayload(ApiModel):
    id: UUID
    display_name: str
    mode: ProjectMode
    created_at: datetime


class FolderOriginPayload(ApiModel):
    project_id: UUID
    project_name: str
    package_version: int
    package_content_hash: str
    schema_version: int

    @classmethod
    def from_domain(cls, origin: FolderOrigin) -> FolderOriginPayload:
        return cls.model_validate(origin.to_snapshot())


class ImportedStagePayload(ApiModel):
    version_id: UUID
    version_number: int
    content_hash: str


class ImportedTwinPayload(ApiModel):
    twin_id: UUID
    name: str


def _stage_payloads(record: ProjectImportRecord) -> dict[str, ImportedStagePayload]:
    return {
        stage: ImportedStagePayload.model_validate(dict(record.stage_versions[stage]))
        for stage in STAGES
    }


class ProjectImportPayload(ApiModel):
    project: ImportedProjectPayload
    origin: FolderOriginPayload
    stages: dict[str, ImportedStagePayload]
    twins: tuple[ImportedTwinPayload, ...]
    imported_at: datetime
    approval_required: tuple[str, ...]

    @classmethod
    def from_result(cls, result: ProjectImportResult) -> ProjectImportPayload:
        project = result.project
        return cls(
            project=ImportedProjectPayload(
                id=project.id,
                display_name=project.display_name,
                mode=project.mode,
                created_at=project.created_at,
            ),
            origin=FolderOriginPayload.from_domain(result.plan.origin),
            stages=_stage_payloads(result.record),
            twins=tuple(
                ImportedTwinPayload(twin_id=twin.twin_id, name=twin.profile.name)
                for twin in result.plan.twins
            ),
            imported_at=result.record.imported_at,
            approval_required=STAGES,
        )


class ProjectImportOriginPayload(ApiModel):
    origin: FolderOriginPayload
    stages: dict[str, ImportedStagePayload]
    imported_at: datetime
    archive_hash: str

    @classmethod
    def from_record(cls, record: ProjectImportRecord) -> ProjectImportOriginPayload:
        return cls(
            origin=FolderOriginPayload.from_domain(record.origin),
            stages=_stage_payloads(record),
            imported_at=record.imported_at,
            archive_hash=record.archive_hash,
        )


def project_import_problem(
    status_code: int, code: str, location: str | None = None
) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "location": location})


def project_import_status(code: str) -> int:
    if code == FOLDER_ARCHIVE_TOO_LARGE:
        return status.HTTP_413_CONTENT_TOO_LARGE
    if code.startswith(_FOLDER_CODE_PREFIX) or code == PROJECT_NAME_INVALID:
        return status.HTTP_422_UNPROCESSABLE_CONTENT
    return status.HTTP_409_CONFLICT


def project_import_failure(error: ProjectImportError) -> HTTPException:
    return project_import_problem(project_import_status(error.code), error.code, error.detail)


def project_import_service_dependency(request: Request) -> ProjectImportService:
    service = getattr(request.app.state, "project_import_service", None)

    if service is None:
        raise project_import_problem(
            status.HTTP_503_SERVICE_UNAVAILABLE, PROJECT_IMPORT_SERVICE_UNAVAILABLE
        )

    return service


def create_project_import_router() -> APIRouter:
    router = APIRouter(tags=["knowledge"])

    @router.post(
        PROJECT_IMPORTS_PATH,
        response_model=ProjectImportPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="importProjectFromKnowledgeFolder",
    )
    async def import_endpoint(
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ProjectImportService, Depends(project_import_service_dependency)],
        archive: Annotated[UploadFile, File()],
        display_name: Annotated[str | None, Form()] = None,
    ) -> ProjectImportPayload:
        content = await archive.read(MAX_ARCHIVE_SIZE + 1)
        if len(content) > MAX_ARCHIVE_SIZE:
            raise project_import_problem(
                status.HTTP_413_CONTENT_TOO_LARGE, FOLDER_ARCHIVE_TOO_LARGE
            )
        try:
            result = await service.import_archive(
                owner_user_id=user.id, content=content, display_name=display_name
            )
        except ProjectImportError as error:
            raise project_import_failure(error) from error

        return ProjectImportPayload.from_result(result)

    @router.get(
        PROJECT_IMPORT_ORIGIN_PATH,
        response_model=ProjectImportOriginPayload,
        operation_id="getProjectImportOrigin",
    )
    async def origin_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[ProjectImportService, Depends(project_import_service_dependency)],
    ) -> ProjectImportOriginPayload:
        record = await service.origin(owner_user_id=user.id, project_id=project_id)
        if record is None:
            raise project_import_problem(status.HTTP_404_NOT_FOUND, PROJECT_IMPORT_NOT_FOUND)

        return ProjectImportOriginPayload.from_record(record)

    return router


__all__ = [
    "FOLDER_ARCHIVE_TOO_LARGE",
    "PROJECT_IMPORTS_PATH",
    "PROJECT_IMPORT_NOT_FOUND",
    "PROJECT_IMPORT_ORIGIN_PATH",
    "PROJECT_IMPORT_SERVICE_UNAVAILABLE",
    "FolderOriginPayload",
    "ImportedProjectPayload",
    "ImportedStagePayload",
    "ImportedTwinPayload",
    "ProjectImportOriginPayload",
    "ProjectImportPayload",
    "create_project_import_router",
    "project_import_failure",
    "project_import_problem",
    "project_import_service_dependency",
    "project_import_status",
]
