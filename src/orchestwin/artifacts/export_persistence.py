"""Owner-scoped append-only persistence for deterministic final export bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.artifacts.export_archive import BuiltFinalExportArchive
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.requirements_primitives import canonical_json, validate_sha256


class ExportBundleRecord(OrmBase):
    """Append-only metadata for one stored deterministic export archive."""

    __tablename__ = "export_bundles"
    __table_args__ = (
        CheckConstraint("manifest_hash ~ '^[0-9a-f]{64}$'", name="manifest_hash_valid"),
        CheckConstraint("archive_hash ~ '^[0-9a-f]{64}$'", name="archive_hash_valid"),
        CheckConstraint("archive_size_bytes > 0", name="archive_size_positive"),
        CheckConstraint("char_length(storage_ref) > 0", name="storage_ref_required"),
        CheckConstraint("char_length(bundle_snapshot_json) > 0", name="snapshot_required"),
        ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_export_bundles_workflow_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("manifest_id", name="uq_export_bundles_manifest"),
        UniqueConstraint("workflow_run_id", "archive_hash", name="uq_export_bundles_run_hash"),
        Index("ix_export_bundles_project_created", "project_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    workflow_run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    manifest_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    manifest_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_review_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    final_review_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    final_approval_gate_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    final_approval_event_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    archive_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bundle_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


@dataclass(frozen=True, slots=True)
class StoredExportBundle:
    """Safe downloadable projection of an immutable export archive."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    owner_user_id: UUID
    manifest_id: UUID
    manifest_hash: str
    final_review_id: UUID
    final_review_hash: str
    final_approval_gate_id: UUID
    final_approval_event_id: UUID
    archive_hash: str
    archive_size_bytes: int
    storage_ref: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_sha256(self.manifest_hash, label="stored export manifest hash")
        validate_sha256(self.final_review_hash, label="stored final review hash")
        validate_sha256(self.archive_hash, label="stored export archive hash")
        if isinstance(self.archive_size_bytes, bool) or self.archive_size_bytes < 1:
            raise ValueError("stored export archive size must be positive")
        if not self.storage_ref.strip() or self.storage_ref != " ".join(self.storage_ref.split()):
            raise ValueError("stored export reference must be normalized")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("stored export timestamp must be timezone-aware")

    @classmethod
    def from_archive(
        cls,
        archive: BuiltFinalExportArchive,
        *,
        storage_ref: str,
    ) -> StoredExportBundle:
        manifest = archive.manifest
        return cls(
            id=archive.id,
            project_id=manifest.project_id,
            workflow_run_id=manifest.workflow_run_id,
            owner_user_id=manifest.owner_user_id,
            manifest_id=manifest.id,
            manifest_hash=manifest.content_hash,
            final_review_id=manifest.final_review_id,
            final_review_hash=manifest.final_review_hash,
            final_approval_gate_id=manifest.final_approval_gate_id,
            final_approval_event_id=manifest.final_approval_event_id,
            archive_hash=archive.archive_hash,
            archive_size_bytes=archive.size_bytes,
            storage_ref=storage_ref,
            created_at=archive.created_at,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "workflow_run_id": str(self.workflow_run_id),
            "owner_user_id": str(self.owner_user_id),
            "manifest_id": str(self.manifest_id),
            "manifest_hash": self.manifest_hash,
            "final_review_id": str(self.final_review_id),
            "final_review_hash": self.final_review_hash,
            "final_approval_gate_id": str(self.final_approval_gate_id),
            "final_approval_event_id": str(self.final_approval_event_id),
            "archive_hash": self.archive_hash,
            "archive_size_bytes": self.archive_size_bytes,
            "storage_ref": self.storage_ref,
            "created_at": self.created_at.isoformat(),
        }


class ExportBundlePersistenceConflict(RuntimeError):
    """Raised when append-only export identity or content conflicts."""


class ExportBundleRepository(Protocol):
    """Owner-scoped append-only export metadata port."""

    async def append(self, bundle: StoredExportBundle) -> StoredExportBundle: ...

    async def get_owned(
        self,
        *,
        export_id: UUID,
        owner_user_id: UUID,
    ) -> StoredExportBundle | None: ...


class InMemoryExportBundleRepository:
    """Deterministic repository for unit, API, and workflow tests."""

    def __init__(self) -> None:
        self._bundles: dict[UUID, StoredExportBundle] = {}

    async def append(self, bundle: StoredExportBundle) -> StoredExportBundle:
        existing = self._bundles.get(bundle.id)
        if existing is not None:
            if existing == bundle:
                return existing
            raise ExportBundlePersistenceConflict("export bundle identity already exists")
        if any(item.manifest_id == bundle.manifest_id for item in self._bundles.values()):
            raise ExportBundlePersistenceConflict("export manifest is already stored")
        self._bundles[bundle.id] = bundle
        return bundle

    async def get_owned(
        self,
        *,
        export_id: UUID,
        owner_user_id: UUID,
    ) -> StoredExportBundle | None:
        bundle = self._bundles.get(export_id)
        if bundle is None or bundle.owner_user_id != owner_user_id:
            return None
        return bundle


class SqlAlchemyExportBundleRepository:
    """PostgreSQL-backed append-only export metadata repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, bundle: StoredExportBundle) -> StoredExportBundle:
        self._session.add(export_bundle_to_record(bundle))
        try:
            await self._session.flush()
        except IntegrityError as error:
            raise ExportBundlePersistenceConflict(
                "export bundle identity, scope, or content conflicts"
            ) from error
        return bundle

    async def get_owned(
        self,
        *,
        export_id: UUID,
        owner_user_id: UUID,
    ) -> StoredExportBundle | None:
        record = await self._session.scalar(
            select(ExportBundleRecord).where(
                ExportBundleRecord.id == export_id,
                ExportBundleRecord.owner_user_id == owner_user_id,
            )
        )
        return export_bundle_record_to_domain(record) if record is not None else None


def export_bundle_to_record(bundle: StoredExportBundle) -> ExportBundleRecord:
    return ExportBundleRecord(
        id=bundle.id,
        project_id=bundle.project_id,
        workflow_run_id=bundle.workflow_run_id,
        owner_user_id=bundle.owner_user_id,
        manifest_id=bundle.manifest_id,
        manifest_hash=bundle.manifest_hash,
        final_review_id=bundle.final_review_id,
        final_review_hash=bundle.final_review_hash,
        final_approval_gate_id=bundle.final_approval_gate_id,
        final_approval_event_id=bundle.final_approval_event_id,
        archive_hash=bundle.archive_hash,
        archive_size_bytes=bundle.archive_size_bytes,
        storage_ref=bundle.storage_ref,
        created_at=bundle.created_at,
        bundle_snapshot_json=canonical_json(bundle.to_snapshot()),
    )


def export_bundle_record_to_domain(record: ExportBundleRecord) -> StoredExportBundle:
    snapshot = json.loads(record.bundle_snapshot_json)
    return StoredExportBundle(
        id=UUID(snapshot["id"]),
        project_id=UUID(snapshot["project_id"]),
        workflow_run_id=UUID(snapshot["workflow_run_id"]),
        owner_user_id=UUID(snapshot["owner_user_id"]),
        manifest_id=UUID(snapshot["manifest_id"]),
        manifest_hash=snapshot["manifest_hash"],
        final_review_id=UUID(snapshot["final_review_id"]),
        final_review_hash=snapshot["final_review_hash"],
        final_approval_gate_id=UUID(snapshot["final_approval_gate_id"]),
        final_approval_event_id=UUID(snapshot["final_approval_event_id"]),
        archive_hash=snapshot["archive_hash"],
        archive_size_bytes=snapshot["archive_size_bytes"],
        storage_ref=snapshot["storage_ref"],
        created_at=datetime.fromisoformat(snapshot["created_at"]),
    )
