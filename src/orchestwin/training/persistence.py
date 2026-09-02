"""Owner-scoped append-only persistence for dataset versions and quality reports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

from orchestwin.identity.persistence.models import UserRecord
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_manifests import (
    DatasetBuildManifest,
    DatasetManifestReference,
)
from orchestwin.training.deduplication import DatasetDeduplicationResult
from orchestwin.training.filtering import DatasetFilteringResult
from orchestwin.training.splitting import DatasetSplit, DatasetSplitResult


class TrainingDatasetVersionRecord(OrmBase):
    """One immutable owner-scoped evaluator dataset version."""

    __tablename__ = "training_dataset_versions"
    __table_args__ = (
        CheckConstraint("version_number >= 1", name="version_positive"),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_valid",
        ),
        CheckConstraint(
            "policy_content_hash ~ '^[0-9a-f]{64}$'",
            name="policy_content_hash_valid",
        ),
        CheckConstraint(
            "examples_digest ~ '^[0-9a-f]{64}$'",
            name="examples_digest_valid",
        ),
        CheckConstraint("example_count >= 1", name="example_count_positive"),
        CheckConstraint("char_length(manifest_snapshot_json) > 0", name="snapshot_required"),
        UniqueConstraint(
            "dataset_id",
            "version_number",
            "owner_user_id",
            name="uq_training_dataset_versions_scope",
        ),
        Index(
            "ix_training_dataset_versions_owner_created",
            "owner_user_id",
            "created_at",
        ),
        Index(
            "ix_training_dataset_versions_owner_hash",
            "owner_user_id",
            "content_hash",
        ),
    )

    dataset_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    version_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    based_on_version_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    examples_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    example_count: Mapped[int] = mapped_column(Integer, nullable=False)
    publishable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    manifest_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TrainingDatasetQualityReportRecord(OrmBase):
    """Immutable quality evidence tied to one exact dataset version."""

    __tablename__ = "training_dataset_quality_reports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "dataset_version_number", "owner_user_id"],
            [
                "training_dataset_versions.dataset_id",
                "training_dataset_versions.version_number",
                "training_dataset_versions.owner_user_id",
            ],
            name="fk_training_dataset_quality_reports_dataset_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="content_hash_valid",
        ),
        CheckConstraint("candidate_count >= 1", name="candidate_count_positive"),
        CheckConstraint("accepted_count >= 1", name="accepted_count_positive"),
        CheckConstraint("duplicate_count >= 0", name="duplicate_count_non_negative"),
        CheckConstraint("excluded_count >= 0", name="excluded_count_non_negative"),
        CheckConstraint("leakage_issue_count >= 0", name="leakage_count_non_negative"),
        CheckConstraint("char_length(report_snapshot_json) > 0", name="snapshot_required"),
        UniqueConstraint(
            "dataset_id",
            "dataset_version_number",
            name="uq_training_dataset_quality_reports_dataset_version",
        ),
        Index(
            "ix_training_dataset_quality_reports_owner_created",
            "owner_user_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    dataset_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_count: Mapped[int] = mapped_column(Integer, nullable=False)
    leakage_issue_count: Mapped[int] = mapped_column(Integer, nullable=False)
    publishable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    report_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class DatasetBuildQualityReport:
    """Complete filtering, deduplication, split, and leakage evidence."""

    id: UUID
    dataset_reference: DatasetManifestReference
    owner_user_id: UUID
    filtering_result_hash: str
    deduplication_result_hash: str
    split_result_hash: str
    candidate_count: int
    accepted_count: int
    duplicate_count: int
    excluded_count: int
    leakage_issue_count: int
    publishable: bool
    content_hash: str
    created_at: datetime

    def __post_init__(self) -> None:
        for value, label in (
            (self.filtering_result_hash, "quality filtering result hash"),
            (self.deduplication_result_hash, "quality deduplication result hash"),
            (self.split_result_hash, "quality split result hash"),
            (self.content_hash, "dataset quality report content hash"),
        ):
            validate_sha256(value, label=label)
        for value, label, allow_zero in (
            (self.candidate_count, "quality candidate count", False),
            (self.accepted_count, "quality accepted count", False),
            (self.duplicate_count, "quality duplicate count", True),
            (self.excluded_count, "quality excluded count", True),
            (self.leakage_issue_count, "quality leakage issue count", True),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < int(not allow_zero):
                raise ValueError(f"{label} has an invalid value")
        if self.accepted_count > self.candidate_count:
            raise ValueError("quality accepted count cannot exceed candidate count")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("dataset quality report timestamp must be timezone-aware")
        if self.publishable != (self.leakage_issue_count == 0):
            raise ValueError("dataset quality report publishable state is inconsistent")
        expected_hash = dataset_quality_report_hash(
            report_id=self.id,
            dataset_reference=self.dataset_reference,
            owner_user_id=self.owner_user_id,
            filtering_result_hash=self.filtering_result_hash,
            deduplication_result_hash=self.deduplication_result_hash,
            split_result_hash=self.split_result_hash,
            candidate_count=self.candidate_count,
            accepted_count=self.accepted_count,
            duplicate_count=self.duplicate_count,
            excluded_count=self.excluded_count,
            leakage_issue_count=self.leakage_issue_count,
            publishable=self.publishable,
        )
        if self.content_hash != expected_hash:
            raise ValueError("dataset quality report content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "dataset_reference": self.dataset_reference.to_snapshot(),
            "owner_user_id": str(self.owner_user_id),
            "filtering_result_hash": self.filtering_result_hash,
            "deduplication_result_hash": self.deduplication_result_hash,
            "split_result_hash": self.split_result_hash,
            "candidate_count": self.candidate_count,
            "accepted_count": self.accepted_count,
            "duplicate_count": self.duplicate_count,
            "excluded_count": self.excluded_count,
            "leakage_issue_count": self.leakage_issue_count,
            "publishable": self.publishable,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class StoredTrainingDatasetVersion:
    """Queryable projection without duplicating every example payload."""

    dataset_id: UUID
    version_number: int
    owner_user_id: UUID
    based_on_version_number: int | None
    content_hash: str
    policy_content_hash: str
    examples_digest: str
    example_count: int
    publishable: bool
    created_at: datetime

    def __post_init__(self) -> None:
        validate_positive_integer(self.version_number, label="stored dataset version number")
        for value, label in (
            (self.content_hash, "stored dataset content hash"),
            (self.policy_content_hash, "stored dataset policy hash"),
            (self.examples_digest, "stored dataset examples digest"),
        ):
            validate_sha256(value, label=label)
        validate_positive_integer(self.example_count, label="stored dataset example count")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("stored dataset timestamp must be timezone-aware")


class TrainingDatasetStoreStatus(StrEnum):
    """Owner-safe append outcomes."""

    CREATED = "CREATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    OWNER_NOT_FOUND = "OWNER_NOT_FOUND"
    QUALITY_REPORT_MISMATCH = "QUALITY_REPORT_MISMATCH"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class TrainingDatasetStoreResult:
    """Append result with a projection only for successful outcomes."""

    status: TrainingDatasetStoreStatus
    dataset: StoredTrainingDatasetVersion | None

    def __post_init__(self) -> None:
        successful = self.status in {
            TrainingDatasetStoreStatus.CREATED,
            TrainingDatasetStoreStatus.ALREADY_PRESENT,
        }
        if successful != (self.dataset is not None):
            raise ValueError("training dataset store result shape is inconsistent")


class TrainingDatasetRepository(Protocol):
    """Owner-bound append-only dataset repository port."""

    async def append(
        self,
        manifest: DatasetBuildManifest,
        quality_report: DatasetBuildQualityReport,
    ) -> TrainingDatasetStoreResult: ...

    async def get_owned(
        self,
        *,
        dataset_id: UUID,
        version_number: int,
    ) -> StoredTrainingDatasetVersion | None: ...


class InMemoryTrainingDatasetRepository:
    """Deterministic repository for ordinary tests."""

    def __init__(self, *, owner_user_id: UUID, owner_exists: bool = True) -> None:
        self._owner_user_id = owner_user_id
        self._owner_exists = owner_exists
        self._datasets: dict[
            tuple[UUID, int],
            tuple[DatasetBuildManifest, DatasetBuildQualityReport],
        ] = {}

    async def append(
        self,
        manifest: DatasetBuildManifest,
        quality_report: DatasetBuildQualityReport,
    ) -> TrainingDatasetStoreResult:
        mismatch = _quality_report_mismatch(manifest, quality_report, self._owner_user_id)
        if mismatch:
            return TrainingDatasetStoreResult(
                TrainingDatasetStoreStatus.QUALITY_REPORT_MISMATCH,
                None,
            )
        if not self._owner_exists:
            return TrainingDatasetStoreResult(TrainingDatasetStoreStatus.OWNER_NOT_FOUND, None)
        key = (manifest.dataset_id, manifest.version_number)
        existing = self._datasets.get(key)
        if existing is not None:
            if existing == (manifest, quality_report):
                return TrainingDatasetStoreResult(
                    TrainingDatasetStoreStatus.ALREADY_PRESENT,
                    _stored_dataset(manifest, quality_report),
                )
            return TrainingDatasetStoreResult(TrainingDatasetStoreStatus.CONTENT_CONFLICT, None)
        self._datasets[key] = (manifest, quality_report)
        return TrainingDatasetStoreResult(
            TrainingDatasetStoreStatus.CREATED,
            _stored_dataset(manifest, quality_report),
        )

    async def get_owned(
        self,
        *,
        dataset_id: UUID,
        version_number: int,
    ) -> StoredTrainingDatasetVersion | None:
        stored = self._datasets.get((dataset_id, version_number))
        if stored is None:
            return None
        manifest, quality_report = stored
        if manifest.owner_user_id != self._owner_user_id:
            return None
        return _stored_dataset(manifest, quality_report)


class SqlAlchemyTrainingDatasetRepository:
    """PostgreSQL adapter bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(
        self,
        manifest: DatasetBuildManifest,
        quality_report: DatasetBuildQualityReport,
    ) -> TrainingDatasetStoreResult:
        if _quality_report_mismatch(manifest, quality_report, self._owner_user_id):
            return TrainingDatasetStoreResult(
                TrainingDatasetStoreStatus.QUALITY_REPORT_MISMATCH,
                None,
            )
        owner_exists = await self._session.scalar(
            select(UserRecord.id).where(UserRecord.id == self._owner_user_id)
        )
        if owner_exists is None:
            return TrainingDatasetStoreResult(TrainingDatasetStoreStatus.OWNER_NOT_FOUND, None)

        existing = await self.get_owned(
            dataset_id=manifest.dataset_id,
            version_number=manifest.version_number,
        )
        if existing is not None:
            if (
                existing.content_hash == manifest.content_hash
                and existing.publishable == quality_report.publishable
            ):
                return TrainingDatasetStoreResult(
                    TrainingDatasetStoreStatus.ALREADY_PRESENT,
                    existing,
                )
            return TrainingDatasetStoreResult(TrainingDatasetStoreStatus.CONTENT_CONFLICT, None)

        try:
            async with self._session.begin_nested():
                self._session.add(dataset_manifest_to_record(manifest, quality_report))
                self._session.add(dataset_quality_report_to_record(quality_report))
                await self._session.flush()
        except IntegrityError:
            return TrainingDatasetStoreResult(TrainingDatasetStoreStatus.CONTENT_CONFLICT, None)
        return TrainingDatasetStoreResult(
            TrainingDatasetStoreStatus.CREATED,
            _stored_dataset(manifest, quality_report),
        )

    async def get_owned(
        self,
        *,
        dataset_id: UUID,
        version_number: int,
    ) -> StoredTrainingDatasetVersion | None:
        record = await self._session.scalar(
            select(TrainingDatasetVersionRecord).where(
                TrainingDatasetVersionRecord.dataset_id == dataset_id,
                TrainingDatasetVersionRecord.version_number == version_number,
                TrainingDatasetVersionRecord.owner_user_id == self._owner_user_id,
            )
        )
        return None if record is None else dataset_record_to_projection(record)


def create_dataset_quality_report(
    *,
    report_id: UUID,
    manifest: DatasetBuildManifest,
    filtering: DatasetFilteringResult,
    deduplication: DatasetDeduplicationResult,
    split: DatasetSplitResult,
    created_at: datetime,
) -> DatasetBuildQualityReport:
    """Bind quality evidence to the exact published manifest."""
    filtered_hashes = {example.content_hash for example in filtering.accepted}
    dedup_input_hashes = {decision.example.content_hash for decision in deduplication.decisions}
    if filtered_hashes != dedup_input_hashes:
        raise ValueError("deduplication input must match accepted filtering output")

    kept_hashes = {example.content_hash for example in deduplication.kept}
    split_input_hashes = {assignment.example.content_hash for assignment in split.assignments}
    if kept_hashes != split_input_hashes:
        raise ValueError("split input must match deduplicated examples")

    active_example_ids = {
        assignment.example.example_id
        for assignment in split.assignments
        if assignment.split is not DatasetSplit.EXCLUDED
    }
    manifest_example_ids = {entry.example_id for entry in manifest.entries}
    if active_example_ids != manifest_example_ids:
        raise ValueError("dataset manifest must contain exactly the active split examples")

    excluded_count = len(split.examples_for(DatasetSplit.EXCLUDED))
    leakage_issue_count = len(split.leakage_issues)
    publishable = leakage_issue_count == 0
    content_hash = dataset_quality_report_hash(
        report_id=report_id,
        dataset_reference=manifest.reference,
        owner_user_id=manifest.owner_user_id,
        filtering_result_hash=filtering.content_hash,
        deduplication_result_hash=deduplication.content_hash,
        split_result_hash=split.content_hash,
        candidate_count=len(filtering.decisions),
        accepted_count=len(filtering.accepted),
        duplicate_count=len(deduplication.duplicates),
        excluded_count=excluded_count,
        leakage_issue_count=leakage_issue_count,
        publishable=publishable,
    )
    return DatasetBuildQualityReport(
        id=report_id,
        dataset_reference=manifest.reference,
        owner_user_id=manifest.owner_user_id,
        filtering_result_hash=filtering.content_hash,
        deduplication_result_hash=deduplication.content_hash,
        split_result_hash=split.content_hash,
        candidate_count=len(filtering.decisions),
        accepted_count=len(filtering.accepted),
        duplicate_count=len(deduplication.duplicates),
        excluded_count=excluded_count,
        leakage_issue_count=leakage_issue_count,
        publishable=publishable,
        content_hash=content_hash,
        created_at=created_at,
    )


def dataset_quality_report_hash(
    *,
    report_id: UUID,
    dataset_reference: DatasetManifestReference,
    owner_user_id: UUID,
    filtering_result_hash: str,
    deduplication_result_hash: str,
    split_result_hash: str,
    candidate_count: int,
    accepted_count: int,
    duplicate_count: int,
    excluded_count: int,
    leakage_issue_count: int,
    publishable: bool,
) -> str:
    return snapshot_content_hash(
        {
            "id": str(report_id),
            "dataset_reference": dataset_reference.to_snapshot(),
            "owner_user_id": str(owner_user_id),
            "filtering_result_hash": filtering_result_hash,
            "deduplication_result_hash": deduplication_result_hash,
            "split_result_hash": split_result_hash,
            "candidate_count": candidate_count,
            "accepted_count": accepted_count,
            "duplicate_count": duplicate_count,
            "excluded_count": excluded_count,
            "leakage_issue_count": leakage_issue_count,
            "publishable": publishable,
        }
    )


def dataset_manifest_to_record(
    manifest: DatasetBuildManifest,
    quality_report: DatasetBuildQualityReport,
) -> TrainingDatasetVersionRecord:
    return TrainingDatasetVersionRecord(
        dataset_id=manifest.dataset_id,
        version_number=manifest.version_number,
        owner_user_id=manifest.owner_user_id,
        based_on_version_number=(
            None if manifest.based_on is None else manifest.based_on.version_number
        ),
        content_hash=manifest.content_hash,
        policy_content_hash=manifest.policy.content_hash,
        examples_digest=manifest.examples_digest,
        example_count=len(manifest.entries),
        publishable=quality_report.publishable,
        manifest_snapshot_json=canonical_json(manifest.to_snapshot()),
        created_at=manifest.created_at,
    )


def dataset_quality_report_to_record(
    report: DatasetBuildQualityReport,
) -> TrainingDatasetQualityReportRecord:
    return TrainingDatasetQualityReportRecord(
        id=report.id,
        dataset_id=report.dataset_reference.dataset_id,
        dataset_version_number=report.dataset_reference.version_number,
        owner_user_id=report.owner_user_id,
        content_hash=report.content_hash,
        candidate_count=report.candidate_count,
        accepted_count=report.accepted_count,
        duplicate_count=report.duplicate_count,
        excluded_count=report.excluded_count,
        leakage_issue_count=report.leakage_issue_count,
        publishable=report.publishable,
        report_snapshot_json=canonical_json(report.to_snapshot()),
        created_at=report.created_at,
    )


def dataset_record_to_projection(
    record: TrainingDatasetVersionRecord,
) -> StoredTrainingDatasetVersion:
    return StoredTrainingDatasetVersion(
        dataset_id=record.dataset_id,
        version_number=record.version_number,
        owner_user_id=record.owner_user_id,
        based_on_version_number=record.based_on_version_number,
        content_hash=record.content_hash,
        policy_content_hash=record.policy_content_hash,
        examples_digest=record.examples_digest,
        example_count=record.example_count,
        publishable=record.publishable,
        created_at=record.created_at,
    )


def _quality_report_mismatch(
    manifest: DatasetBuildManifest,
    report: DatasetBuildQualityReport,
    owner_user_id: UUID,
) -> bool:
    return (
        manifest.owner_user_id != owner_user_id
        or report.owner_user_id != owner_user_id
        or report.dataset_reference != manifest.reference
    )


def _stored_dataset(
    manifest: DatasetBuildManifest,
    report: DatasetBuildQualityReport,
) -> StoredTrainingDatasetVersion:
    return StoredTrainingDatasetVersion(
        dataset_id=manifest.dataset_id,
        version_number=manifest.version_number,
        owner_user_id=manifest.owner_user_id,
        based_on_version_number=(
            None if manifest.based_on is None else manifest.based_on.version_number
        ),
        content_hash=manifest.content_hash,
        policy_content_hash=manifest.policy.content_hash,
        examples_digest=manifest.examples_digest,
        example_count=len(manifest.entries),
        publishable=report.publishable,
        created_at=manifest.created_at,
    )
