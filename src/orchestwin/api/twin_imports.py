from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Final
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.twin_import import TwinImportError
from orchestwin.knowledge.twin_import_service import (
    ImportableTwin,
    TwinImportResult,
    TwinImportService,
    TwinImportSource,
)
from orchestwin.knowledge.twin_import_sources import TwinImportCandidate

TWIN_IMPORTS_API_PREFIX: Final = "/projects/{project_id}/user-modeling/twin-imports"
TWIN_IMPORT_REQUEST_INVALID: Final = "TWIN_IMPORT_REQUEST_INVALID"
_NOT_FOUND_CODES: Final = frozenset(
    {"PROJECT_NOT_FOUND", "SOURCE_PROJECT_NOT_FOUND", "SOURCE_TWIN_NOT_FOUND"}
)
_INVALID_DOCUMENT_CODES: Final = frozenset({"TWIN_DOCUMENT_INVALID", "TWIN_DOCUMENT_UNSUPPORTED"})
_UNAVAILABLE_CODES: Final = frozenset({"TWIN_IMPORT_SOURCES_UNAVAILABLE"})


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TwinImportCandidatePayload(ApiModel):
    project_id: UUID
    project_name: str
    snapshot_version_number: int
    approved_at: datetime
    twin_names: tuple[str, ...]

    @classmethod
    def from_domain(cls, candidate: TwinImportCandidate) -> TwinImportCandidatePayload:
        return cls(
            project_id=candidate.project_id,
            project_name=candidate.project_name,
            snapshot_version_number=candidate.snapshot_version_number,
            approved_at=candidate.approved_at,
            twin_names=candidate.twin_names,
        )


class TwinImportSourcesPayload(ApiModel):
    sources: tuple[TwinImportCandidatePayload, ...]

    @classmethod
    def from_domain(cls, candidates: tuple[TwinImportCandidate, ...]) -> TwinImportSourcesPayload:
        return cls(
            sources=tuple(
                TwinImportCandidatePayload.from_domain(candidate) for candidate in candidates
            )
        )


class ImportableTwinPayload(ApiModel):
    twin_id: UUID
    name: str
    version_number: int
    content_hash: str
    validation_status: str
    summary: str | None
    issue: str | None

    @classmethod
    def from_domain(cls, twin: ImportableTwin) -> ImportableTwinPayload:
        return cls(
            twin_id=twin.twin_id,
            name=twin.name,
            version_number=twin.version_number,
            content_hash=twin.content_hash,
            validation_status=twin.validation_status,
            summary=twin.summary,
            issue=twin.issue,
        )


class TwinImportSourcePayload(ApiModel):
    project_id: UUID
    project_name: str
    snapshot_version_number: int
    approved_at: datetime
    twins: tuple[ImportableTwinPayload, ...]

    @classmethod
    def from_domain(cls, source: TwinImportSource) -> TwinImportSourcePayload:
        return cls(
            project_id=source.project_id,
            project_name=source.project_name,
            snapshot_version_number=source.snapshot_version_number,
            approved_at=source.approved_at,
            twins=tuple(ImportableTwinPayload.from_domain(twin) for twin in source.twins),
        )


class ImportedTwinPayload(ApiModel):
    twin_id: UUID
    version_id: UUID
    version_number: int
    name: str
    content_hash: str
    validation_status: str


class ImportedPersonaPayload(ApiModel):
    persona_id: UUID
    version_id: UUID
    version_number: int
    name: str


class ImportedSnapshotPayload(ApiModel):
    version_id: UUID
    version_number: int
    content_hash: str
    twin_count: int


class TwinOriginPayload(ApiModel):
    project_id: UUID
    project_name: str
    twin_id: UUID
    twin_version_number: int
    twin_content_hash: str
    persona_id: UUID
    persona_version_number: int
    persona_content_hash: str


class TwinImportPayload(ApiModel):
    status: str
    twin: ImportedTwinPayload
    persona: ImportedPersonaPayload
    snapshot: ImportedSnapshotPayload
    origin: TwinOriginPayload
    gate_approval_required: bool

    @classmethod
    def from_domain(cls, result: TwinImportResult) -> TwinImportPayload:
        imported = result.imported
        twin = imported.twin_version
        persona = imported.persona_version
        snapshot = imported.snapshot_version
        return cls(
            status=result.status.value,
            twin=ImportedTwinPayload(
                twin_id=twin.twin_id,
                version_id=twin.id,
                version_number=twin.version_number,
                name=twin.profile.name,
                content_hash=twin.content_hash,
                validation_status=twin.profile.validation_status.value,
            ),
            persona=ImportedPersonaPayload(
                persona_id=persona.persona_id,
                version_id=persona.id,
                version_number=persona.version_number,
                name=persona.profile.name,
            ),
            snapshot=ImportedSnapshotPayload(
                version_id=snapshot.id,
                version_number=snapshot.version_number,
                content_hash=snapshot.content_hash,
                twin_count=snapshot.snapshot.twin_count,
            ),
            origin=TwinOriginPayload.model_validate(imported.origin.to_snapshot()),
            gate_approval_required=True,
        )


class TwinImportFromProjectRequest(ApiModel):
    source_project_id: UUID
    twin_id: UUID


class TwinImportDocumentRequest(ApiModel):
    document: dict[str, object]


_REQUEST: Final = TypeAdapter(TwinImportFromProjectRequest | TwinImportDocumentRequest)
_REQUEST_BODY: Final = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "oneOf": [
                    TwinImportFromProjectRequest.model_json_schema(),
                    TwinImportDocumentRequest.model_json_schema(),
                ]
            }
        }
    },
}


def twin_import_service_dependency(request: Request) -> TwinImportService:
    service = getattr(request.app.state, "twin_import_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "TWIN_IMPORT_SERVICE_UNAVAILABLE"},
        )

    return service


def twin_import_failure(error: TwinImportError) -> HTTPException:
    if error.code in _NOT_FOUND_CODES:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in _INVALID_DOCUMENT_CODES:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    elif error.code in _UNAVAILABLE_CODES:
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        status_code = status.HTTP_409_CONFLICT
    detail = {"code": error.code}
    if error.detail:
        detail["location"] = error.detail
    return HTTPException(status_code=status_code, detail=detail)


async def twin_import_request(
    request: Request,
) -> TwinImportFromProjectRequest | TwinImportDocumentRequest:
    try:
        return _REQUEST.validate_python(json.loads(await request.body()))
    except (ValueError, ValidationError) as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": TWIN_IMPORT_REQUEST_INVALID},
        ) from error


def create_twin_import_router() -> APIRouter:
    router = APIRouter(prefix=TWIN_IMPORTS_API_PREFIX, tags=["user-modeling"])

    @router.get(
        "/sources",
        response_model=TwinImportSourcesPayload,
        operation_id="listTwinImportSources",
    )
    async def sources_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TwinImportService, Depends(twin_import_service_dependency)],
    ) -> TwinImportSourcesPayload:
        try:
            candidates = await service.sources(owner_user_id=user.id, project_id=project_id)
        except TwinImportError as error:
            raise twin_import_failure(error) from error

        return TwinImportSourcesPayload.from_domain(candidates)

    @router.get(
        "/sources/{source_project_id}",
        response_model=TwinImportSourcePayload,
        operation_id="getTwinImportSource",
    )
    async def source_endpoint(
        project_id: UUID,
        source_project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TwinImportService, Depends(twin_import_service_dependency)],
    ) -> TwinImportSourcePayload:
        try:
            source = await service.source(
                owner_user_id=user.id,
                project_id=project_id,
                source_project_id=source_project_id,
            )
        except TwinImportError as error:
            raise twin_import_failure(error) from error

        return TwinImportSourcePayload.from_domain(source)

    @router.post(
        "",
        status_code=status.HTTP_201_CREATED,
        response_model=TwinImportPayload,
        operation_id="importUserTwin",
        openapi_extra={"requestBody": _REQUEST_BODY},
    )
    async def import_endpoint(
        project_id: UUID,
        request: Request,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[TwinImportService, Depends(twin_import_service_dependency)],
    ) -> TwinImportPayload:
        command = await twin_import_request(request)
        try:
            if isinstance(command, TwinImportDocumentRequest):
                result = await service.import_document(
                    owner_user_id=user.id,
                    project_id=project_id,
                    document=command.document,
                )
            else:
                result = await service.import_from_project(
                    owner_user_id=user.id,
                    project_id=project_id,
                    source_project_id=command.source_project_id,
                    twin_id=command.twin_id,
                )
        except TwinImportError as error:
            raise twin_import_failure(error) from error

        return TwinImportPayload.from_domain(result)

    return router


__all__ = [
    "TWIN_IMPORTS_API_PREFIX",
    "TWIN_IMPORT_REQUEST_INVALID",
    "ImportableTwinPayload",
    "TwinImportCandidatePayload",
    "TwinImportDocumentRequest",
    "TwinImportFromProjectRequest",
    "TwinImportPayload",
    "TwinImportSourcePayload",
    "TwinImportSourcesPayload",
    "create_twin_import_router",
    "twin_import_failure",
    "twin_import_request",
    "twin_import_service_dependency",
]
