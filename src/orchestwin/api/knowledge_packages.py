from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from orchestwin.api.auth import current_user_dependency
from orchestwin.identity.domain import UserAccount
from orchestwin.knowledge.export import KnowledgeExportError
from orchestwin.knowledge.layout import STAGES, present_stages
from orchestwin.knowledge.package_service import (
    DEFAULT_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
    KnowledgePackageService,
)
from orchestwin.knowledge.packages import KnowledgePackageVersion

KNOWLEDGE_PACKAGES_API_PREFIX = "/projects/{project_id}/knowledge-packages"
_NOT_FOUND_CODES = frozenset({"PROJECT_NOT_FOUND", "KNOWLEDGE_PACKAGE_NOT_FOUND"})
_INTERNAL_CODES = frozenset({"KNOWLEDGE_FOLDER_INVALID", "KNOWLEDGE_PACKAGE_CORRUPTED"})


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PackageStagePayload(ApiModel):
    stage: str
    label: str
    version_number: int
    content_hash: str


class PackageTwinPayload(ApiModel):
    twin_id: UUID
    name: str
    slug: str
    version_number: int
    document: str


class PackageFeedbackPayload(ApiModel):
    reviews: int
    findings: int
    decisions: int
    discussions: int
    insights: int
    change_reviews: int
    test_runs: int | None = Field(default=None, exclude_if=lambda value: value is None)


class PackageProgressPayload(ApiModel):
    approved: tuple[str, ...]
    pending: str | None
    complete: bool

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, object]) -> PackageProgressPayload:
        progress = manifest.get("progress")
        if isinstance(progress, Mapping):
            return cls(
                approved=tuple(progress["approved"]),
                pending=progress["pending"],
                complete=progress["complete"],
            )
        approved = present_stages(manifest)
        pending = None if len(approved) == len(STAGES) else STAGES[len(approved)]
        return cls(approved=approved, pending=pending, complete=pending is None)


class PackageStatePayload(ApiModel):
    changes: int
    pending_changes: int
    aligned_commit: str | None
    open_tasks: int

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, object]) -> PackageStatePayload:
        state = manifest.get("state")
        if not isinstance(state, Mapping):
            return cls(changes=0, pending_changes=0, aligned_commit=None, open_tasks=0)
        return cls(
            changes=state["changes"],
            pending_changes=state["pending_changes"],
            aligned_commit=state["aligned_commit"],
            open_tasks=state["open_tasks"],
        )


class KnowledgePackageVersionPayload(ApiModel):
    id: UUID
    project_id: UUID
    project_name: str
    version_number: int
    schema_version: int
    content_hash: str
    archive_hash: str
    file_name: str
    file_count: int
    archive_size: int
    created_at: datetime
    stages: tuple[PackageStagePayload, ...]
    progress: PackageProgressPayload
    state: PackageStatePayload
    twins: tuple[PackageTwinPayload, ...]
    feedback: PackageFeedbackPayload
    diagram_count: int
    table_count: int
    entries: tuple[str, ...]

    @classmethod
    def from_domain(cls, version: KnowledgePackageVersion) -> KnowledgePackageVersionPayload:
        manifest = version.manifest
        views: Mapping[str, Mapping[str, object]] = manifest["views"]
        feedback = manifest["feedback"]
        return cls(
            id=version.id,
            project_id=version.project_id,
            project_name=manifest["project"]["name"],
            version_number=version.version_number,
            schema_version=version.schema_version,
            content_hash=version.content_hash,
            archive_hash=version.archive_hash,
            file_name=version.file_name,
            file_count=version.file_count,
            archive_size=version.archive_size,
            created_at=version.created_at,
            stages=tuple(
                PackageStagePayload(
                    stage=stage,
                    label=entry["label"],
                    version_number=entry["version_number"],
                    content_hash=entry["content_hash"],
                )
                for stage, entry in (
                    (name, manifest["stages"][name]) for name in present_stages(manifest)
                )
            ),
            progress=PackageProgressPayload.from_manifest(manifest),
            state=PackageStatePayload.from_manifest(manifest),
            twins=tuple(
                PackageTwinPayload(
                    twin_id=twin["twin_id"],
                    name=twin["name"],
                    slug=twin["slug"],
                    version_number=twin["version_number"],
                    document=twin["document"],
                )
                for twin in manifest["twins"]
            ),
            feedback=PackageFeedbackPayload(
                reviews=feedback["reviews"],
                findings=feedback["findings"],
                decisions=feedback["decisions"],
                discussions=feedback["discussions"],
                insights=feedback["insights"],
                change_reviews=feedback.get("change_reviews", 0),
                test_runs=feedback.get("test_runs"),
            ),
            diagram_count=sum(len(view["diagrams"]) for view in views.values()),
            table_count=sum(len(view["tables"]) for view in views.values()),
            entries=version.entries,
        )


class KnowledgePackagePublicationPayload(ApiModel):
    reused: bool
    version: KnowledgePackageVersionPayload


class KnowledgePackageHistoryPayload(ApiModel):
    project_id: UUID
    versions: tuple[KnowledgePackageVersionPayload, ...]


def knowledge_package_service_dependency(request: Request) -> KnowledgePackageService:
    service = getattr(request.app.state, "knowledge_package_service", None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "KNOWLEDGE_PACKAGE_SERVICE_UNAVAILABLE"},
        )

    return service


def knowledge_export_failure(error: KnowledgeExportError) -> HTTPException:
    if error.code in _NOT_FOUND_CODES:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in _INTERNAL_CODES:
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        status_code = status.HTTP_409_CONFLICT
    return HTTPException(status_code=status_code, detail={"code": error.code})


def create_knowledge_package_router() -> APIRouter:
    router = APIRouter(prefix=KNOWLEDGE_PACKAGES_API_PREFIX, tags=["knowledge"])

    @router.post(
        "",
        response_model=KnowledgePackagePublicationPayload,
        operation_id="publishKnowledgePackage",
    )
    async def publish_endpoint(
        project_id: UUID,
        response: Response,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[KnowledgePackageService, Depends(knowledge_package_service_dependency)],
    ) -> KnowledgePackagePublicationPayload:
        try:
            publication = await service.publish(owner_user_id=user.id, project_id=project_id)
        except KnowledgeExportError as error:
            raise knowledge_export_failure(error) from error

        response.status_code = status.HTTP_200_OK if publication.reused else status.HTTP_201_CREATED
        return KnowledgePackagePublicationPayload(
            reused=publication.reused,
            version=KnowledgePackageVersionPayload.from_domain(publication.version),
        )

    @router.get(
        "",
        response_model=KnowledgePackageHistoryPayload,
        operation_id="listKnowledgePackages",
    )
    async def history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[KnowledgePackageService, Depends(knowledge_package_service_dependency)],
        limit: Annotated[int, Query(ge=1, le=MAX_HISTORY_LIMIT)] = DEFAULT_HISTORY_LIMIT,
    ) -> KnowledgePackageHistoryPayload:
        try:
            versions = await service.history(
                owner_user_id=user.id, project_id=project_id, limit=limit
            )
        except KnowledgeExportError as error:
            raise knowledge_export_failure(error) from error

        return KnowledgePackageHistoryPayload(
            project_id=project_id,
            versions=tuple(KnowledgePackageVersionPayload.from_domain(item) for item in versions),
        )

    @router.get(
        "/{version_number}/archive",
        response_class=Response,
        operation_id="downloadKnowledgePackage",
    )
    async def archive_endpoint(
        project_id: UUID,
        version_number: Annotated[int, Path(ge=1)],
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[KnowledgePackageService, Depends(knowledge_package_service_dependency)],
    ) -> Response:
        try:
            archive = await service.archive(
                owner_user_id=user.id,
                project_id=project_id,
                version_number=version_number,
            )
        except KnowledgeExportError as error:
            raise knowledge_export_failure(error) from error

        return Response(
            content=archive.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{archive.file_name}"',
                "X-Content-SHA256": archive.archive_hash,
            },
        )

    return router


__all__ = [
    "KNOWLEDGE_PACKAGES_API_PREFIX",
    "KnowledgePackageHistoryPayload",
    "KnowledgePackagePublicationPayload",
    "KnowledgePackageVersionPayload",
    "create_knowledge_package_router",
    "knowledge_export_failure",
    "knowledge_package_service_dependency",
]
