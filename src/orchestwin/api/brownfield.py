"""FastAPI boundary for safe brownfield source intake and capability review."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, JsonValue

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeIssueCode,
    BrownfieldSourceIntakeResult,
    BrownfieldSourceIntakeStatus,
)
from orchestwin.projects.brownfield_persistence import PersistedBrownfieldIntakeVersion
from orchestwin.projects.execution_capabilities import CapabilityNegotiationRequest
from orchestwin.sandbox.execution_profiles import ExecutionTarget

BROWNFIELD_API_PREFIX = "/projects/{project_id}"
DEFAULT_MAXIMUM_UPLOAD_BYTES = 25 * 1024 * 1024
_UPLOAD_CHUNK_SIZE = 1024 * 1024


class BrownfieldApiService(Protocol):
    """Owner-scoped use cases required by the brownfield HTTP boundary."""

    async def ingest(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        archive_path: Path,
        capability_request: CapabilityNegotiationRequest,
    ) -> BrownfieldSourceIntakeResult: ...

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]: ...

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None: ...


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExecutionProfileReferenceResponse(ApiModel):
    profile_id: str
    profile_version: str
    content_hash: str


class BrownfieldIntakeSummaryResponse(ApiModel):
    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    archive_sha256: str
    archive_size_bytes: int
    archive_storage_key: str
    inventory_content_hash: str
    capability_status: str
    effective_capability_status: str
    selected_profile_reference: ExecutionProfileReferenceResponse | None
    created_by_user_id: UUID
    created_at: str

    @classmethod
    def from_domain(
        cls,
        version: PersistedBrownfieldIntakeVersion,
    ) -> BrownfieldIntakeSummaryResponse:
        selected = version.selected_profile_reference
        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            archive_sha256=version.archive_sha256,
            archive_size_bytes=version.archive_size_bytes,
            archive_storage_key=version.archive_storage_key,
            inventory_content_hash=version.inventory_content_hash,
            capability_status=version.capability_status.value,
            effective_capability_status=version.effective_capability_status.value,
            selected_profile_reference=(
                None
                if selected is None
                else ExecutionProfileReferenceResponse(**selected.to_snapshot())
            ),
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at.isoformat(),
        )


class BrownfieldIntakeListResponse(ApiModel):
    items: tuple[BrownfieldIntakeSummaryResponse, ...]


class BrownfieldInventoryResponse(ApiModel):
    intake: BrownfieldIntakeSummaryResponse
    inventory: dict[str, JsonValue]


class BrownfieldCapabilityResponse(ApiModel):
    intake: BrownfieldIntakeSummaryResponse
    capability: dict[str, JsonValue]


class BrownfieldValidationFailureResponse(ApiModel):
    issue: str
    failure_message: str
    validation_report: dict[str, JsonValue] | None = None


def brownfield_service_dependency(request: Request) -> BrownfieldApiService:
    service = getattr(request.app.state, "brownfield_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "BROWNFIELD_SERVICE_UNAVAILABLE"},
        )
    return service


def maximum_upload_bytes_dependency(request: Request) -> int:
    value = getattr(
        request.app.state,
        "source_archive_maximum_upload_bytes",
        DEFAULT_MAXIMUM_UPLOAD_BYTES,
    )
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "SOURCE_ARCHIVE_UPLOAD_POLICY_UNAVAILABLE"},
        )
    return value


def create_brownfield_router() -> APIRouter:
    router = APIRouter(prefix=BROWNFIELD_API_PREFIX, tags=["brownfield"])

    @router.post(
        "/source-archives",
        response_model=BrownfieldIntakeSummaryResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createBrownfieldSourceArchive",
    )
    async def upload_source_archive(
        project_id: UUID,
        archive: Annotated[UploadFile, File(description="A validated source ZIP")],
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[BrownfieldApiService, Depends(brownfield_service_dependency)],
        maximum_upload_bytes: Annotated[int, Depends(maximum_upload_bytes_dependency)],
        requested_target: Annotated[ExecutionTarget | None, Query()] = None,
        available_runner: Annotated[list[str] | None, Query()] = None,
    ) -> BrownfieldIntakeSummaryResponse:
        suffix = Path(archive.filename or "source.zip").suffix.casefold()
        if suffix != ".zip":
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"code": "SOURCE_ARCHIVE_ZIP_REQUIRED"},
            )
        temporary_path = await _persist_bounded_upload(
            archive,
            maximum_bytes=maximum_upload_bytes,
        )
        try:
            result = await service.ingest(
                owner_user_id=user.id,
                project_id=project_id,
                archive_path=temporary_path,
                capability_request=CapabilityNegotiationRequest(
                    requested_target=requested_target,
                    available_runners=tuple(sorted(set(available_runner or []))),
                    approved_experimental_profiles=(),
                ),
            )
        finally:
            with contextlib.suppress(OSError):
                temporary_path.unlink(missing_ok=True)
            await archive.close()
        if result.status not in {
            BrownfieldSourceIntakeStatus.CREATED,
            BrownfieldSourceIntakeStatus.REUSED,
        }:
            raise _intake_error(result)
        if result.version is None:
            raise RuntimeError("successful brownfield intake is missing its version")
        return BrownfieldIntakeSummaryResponse.from_domain(result.version)

    @router.get(
        "/source-archives",
        response_model=BrownfieldIntakeListResponse,
        operation_id="listBrownfieldSourceArchives",
    )
    async def list_source_archives(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[BrownfieldApiService, Depends(brownfield_service_dependency)],
    ) -> BrownfieldIntakeListResponse:
        history = await service.history(owner_user_id=user.id, project_id=project_id)
        return BrownfieldIntakeListResponse(
            items=tuple(BrownfieldIntakeSummaryResponse.from_domain(item) for item in history)
        )

    @router.get(
        "/source-archives/{intake_id}",
        response_model=BrownfieldIntakeSummaryResponse,
        operation_id="getBrownfieldSourceArchive",
    )
    async def get_source_archive(
        project_id: UUID,
        intake_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[BrownfieldApiService, Depends(brownfield_service_dependency)],
    ) -> BrownfieldIntakeSummaryResponse:
        version = await _owned_intake(
            service,
            owner_user_id=user.id,
            project_id=project_id,
            intake_id=intake_id,
        )
        return BrownfieldIntakeSummaryResponse.from_domain(version)

    @router.get(
        "/source-archives/{intake_id}/inventory",
        response_model=BrownfieldInventoryResponse,
        operation_id="getBrownfieldSourceInventory",
    )
    async def get_source_inventory(
        project_id: UUID,
        intake_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[BrownfieldApiService, Depends(brownfield_service_dependency)],
    ) -> BrownfieldInventoryResponse:
        version = await _owned_intake(
            service,
            owner_user_id=user.id,
            project_id=project_id,
            intake_id=intake_id,
        )
        inventory = version.snapshot.get("inventory")
        if not isinstance(inventory, dict):
            raise RuntimeError("persisted brownfield inventory snapshot is missing")
        return BrownfieldInventoryResponse(
            intake=BrownfieldIntakeSummaryResponse.from_domain(version),
            inventory=inventory,
        )

    @router.get(
        "/capabilities",
        response_model=BrownfieldCapabilityResponse,
        operation_id="getBrownfieldCapabilities",
    )
    async def get_capabilities(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[BrownfieldApiService, Depends(brownfield_service_dependency)],
    ) -> BrownfieldCapabilityResponse:
        version = await service.current(owner_user_id=user.id, project_id=project_id)
        if version is None:
            raise _not_found()
        capability = version.snapshot.get("capability")
        if not isinstance(capability, dict):
            raise RuntimeError("persisted brownfield capability snapshot is missing")
        return BrownfieldCapabilityResponse(
            intake=BrownfieldIntakeSummaryResponse.from_domain(version),
            capability=capability,
        )

    return router


async def _persist_bounded_upload(
    upload: UploadFile,
    *,
    maximum_bytes: int,
) -> Path:
    descriptor, name = tempfile.mkstemp(prefix="orchestwin-upload-", suffix=".zip")
    path = Path(name)
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as target:
            while True:
                chunk = await upload.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={"code": "SOURCE_ARCHIVE_TOO_LARGE"},
                    )
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        if total == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "SOURCE_ARCHIVE_EMPTY"},
            )
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def _owned_intake(
    service: BrownfieldApiService,
    *,
    owner_user_id: UUID,
    project_id: UUID,
    intake_id: UUID,
) -> PersistedBrownfieldIntakeVersion:
    history = await service.history(owner_user_id=owner_user_id, project_id=project_id)
    version = next((item for item in history if item.id == intake_id), None)
    if version is None:
        raise _not_found()
    return version


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "BROWNFIELD_INTAKE_NOT_FOUND"},
    )


def _intake_error(result: BrownfieldSourceIntakeResult) -> HTTPException:
    issue = result.issue or BrownfieldSourceIntakeIssueCode.PERSISTENCE_CONFLICT
    status_code = (
        status.HTTP_404_NOT_FOUND
        if issue is BrownfieldSourceIntakeIssueCode.PROJECT_NOT_FOUND
        else status.HTTP_409_CONFLICT
        if issue is BrownfieldSourceIntakeIssueCode.PERSISTENCE_CONFLICT
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    report = result.validation_report
    safe_report = None
    if report is not None:
        safe_report = {
            "status": report.status.value,
            "archive_size_bytes": report.archive_size_bytes,
            "archive_sha256": report.archive_sha256,
            "total_uncompressed_bytes": report.total_uncompressed_bytes,
            "issues": [item.code.value for item in report.issues],
        }
    payload = BrownfieldValidationFailureResponse(
        issue=issue.value,
        failure_message=result.failure_message or "Brownfield source intake failed.",
        validation_report=safe_report,
    )
    return HTTPException(status_code=status_code, detail=payload.model_dump(mode="json"))
