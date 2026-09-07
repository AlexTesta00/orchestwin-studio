"""Owner-scoped append-only persistence for QLoRA training run evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy import (
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
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_manifests import DatasetManifestReference
from orchestwin.training.persistence import TrainingDatasetVersionRecord
from orchestwin.training.unsloth_adapter import (
    QloraTrainingOutcome,
    QloraTrainingStatus,
    TrainingCheckpointEvidence,
)


class TrainingRunRecord(OrmBase):
    """One immutable final QLoRA training run projection and snapshot."""

    __tablename__ = "training_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dataset_id", "dataset_version_number", "owner_user_id"],
            [
                "training_dataset_versions.dataset_id",
                "training_dataset_versions.version_number",
                "training_dataset_versions.owner_user_id",
            ],
            name="fk_training_runs_dataset_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("request_sha256 ~ '^[0-9a-f]{64}$'", name="request_hash_valid"),
        CheckConstraint(
            "configuration_sha256 ~ '^[0-9a-f]{64}$'",
            name="configuration_hash_valid",
        ),
        CheckConstraint(
            "dataset_content_hash ~ '^[0-9a-f]{64}$'",
            name="dataset_hash_valid",
        ),
        CheckConstraint(
            "package_lock_sha256 ~ '^[0-9a-f]{64}$'",
            name="package_lock_hash_valid",
        ),
        CheckConstraint(
            "environment_sha256 ~ '^[0-9a-f]{64}$'",
            name="environment_hash_valid",
        ),
        CheckConstraint(
            "process_log_sha256 ~ '^[0-9a-f]{64}$'",
            name="process_log_hash_valid",
        ),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_valid"),
        CheckConstraint("duration_milliseconds >= 0", name="duration_non_negative"),
        CheckConstraint(
            "peak_gpu_memory_mb IS NULL OR peak_gpu_memory_mb >= 0",
            name="peak_memory_non_negative",
        ),
        CheckConstraint("metric_count >= 0", name="metric_count_non_negative"),
        CheckConstraint("checkpoint_count >= 0", name="checkpoint_count_non_negative"),
        CheckConstraint("char_length(outcome_snapshot_json) > 0", name="snapshot_required"),
        UniqueConstraint("id", "owner_user_id", name="uq_training_runs_owner_scope"),
        Index("ix_training_runs_owner_started", "owner_user_id", "started_at"),
        Index(
            "ix_training_runs_owner_dataset",
            "owner_user_id",
            "dataset_id",
            "dataset_version_number",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    dataset_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    dataset_version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    package_lock_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    process_log_relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    process_log_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_milliseconds: Mapped[int] = mapped_column(Integer, nullable=False)
    peak_gpu_memory_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metric_count: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_count: Mapped[int] = mapped_column(Integer, nullable=False)
    adapter_relative_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    adapter_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    outcome_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)


class TrainingRunCheckpointRecord(OrmBase):
    """Content-addressed checkpoint evidence tied to one exact training run."""

    __tablename__ = "training_run_checkpoints"
    __table_args__ = (
        ForeignKeyConstraint(
            ["training_run_id", "owner_user_id"],
            ["training_runs.id", "training_runs.owner_user_id"],
            name="fk_training_run_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        CheckConstraint("step >= 1", name="step_positive"),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="content_hash_valid",
        ),
        UniqueConstraint(
            "training_run_id",
            "relative_path",
            name="uq_training_run_checkpoints_path",
        ),
        Index(
            "ix_training_run_checkpoints_owner_run",
            "owner_user_id",
            "training_run_id",
        ),
    )

    training_run_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    step: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


@dataclass(frozen=True, slots=True)
class StoredTrainingCheckpoint:
    """Queryable immutable checkpoint projection."""

    step: int
    relative_path: str
    content_sha256: str

    def __post_init__(self) -> None:
        validate_positive_integer(self.step, label="stored training checkpoint step")
        if not self.relative_path:
            raise ValueError("stored training checkpoint path must not be empty")
        validate_sha256(self.content_sha256, label="stored training checkpoint digest")

    @classmethod
    def from_evidence(cls, evidence: TrainingCheckpointEvidence) -> StoredTrainingCheckpoint:
        return cls(
            step=evidence.step,
            relative_path=evidence.relative_path,
            content_sha256=evidence.content_sha256,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "step": self.step,
            "relative_path": self.relative_path,
            "content_sha256": self.content_sha256,
        }


@dataclass(frozen=True, slots=True)
class StoredTrainingRun:
    """Owner-safe projection retaining exact reproducibility and outcome evidence."""

    run_id: UUID
    owner_user_id: UUID
    dataset_reference: DatasetManifestReference
    request_sha256: str
    configuration_sha256: str
    package_lock_sha256: str
    environment_sha256: str
    process_log_relative_path: str
    process_log_sha256: str
    status: QloraTrainingStatus
    started_at: datetime
    completed_at: datetime
    duration_milliseconds: int
    peak_gpu_memory_mb: int | None
    metric_count: int
    adapter_relative_path: str | None
    adapter_sha256: str | None
    failure_kind: str | None
    failure_message: str | None
    content_hash: str
    checkpoints: tuple[StoredTrainingCheckpoint, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.request_sha256, "stored training request digest"),
            (self.configuration_sha256, "stored training configuration digest"),
            (self.package_lock_sha256, "stored training package lock digest"),
            (self.environment_sha256, "stored training environment digest"),
            (self.process_log_sha256, "stored training process log digest"),
            (self.content_hash, "stored training outcome digest"),
        ):
            validate_sha256(value, label=label)
        if self.started_at.tzinfo is None or self.completed_at.tzinfo is None:
            raise ValueError("stored training timestamps must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("stored training completion cannot precede its start")
        if self.duration_milliseconds < 0 or self.metric_count < 0:
            raise ValueError("stored training counts and duration must be non-negative")
        canonical = tuple(
            sorted(self.checkpoints, key=lambda item: (item.step, item.relative_path))
        )
        if canonical != self.checkpoints:
            raise ValueError("stored training checkpoints must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "owner_user_id": str(self.owner_user_id),
            "dataset_reference": self.dataset_reference.to_snapshot(),
            "request_sha256": self.request_sha256,
            "configuration_sha256": self.configuration_sha256,
            "package_lock_sha256": self.package_lock_sha256,
            "environment_sha256": self.environment_sha256,
            "process_log_relative_path": self.process_log_relative_path,
            "process_log_sha256": self.process_log_sha256,
            "status": self.status.value,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_milliseconds": self.duration_milliseconds,
            "peak_gpu_memory_mb": self.peak_gpu_memory_mb,
            "metric_count": self.metric_count,
            "adapter_relative_path": self.adapter_relative_path,
            "adapter_sha256": self.adapter_sha256,
            "failure_kind": self.failure_kind,
            "failure_message": self.failure_message,
            "content_hash": self.content_hash,
            "checkpoints": [item.to_snapshot() for item in self.checkpoints],
        }


class TrainingRunStoreStatus(StrEnum):
    """Typed append outcomes without cross-owner resource disclosure."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    OWNER_NOT_FOUND = "OWNER_NOT_FOUND"
    DATASET_NOT_FOUND = "DATASET_NOT_FOUND"
    CONTENT_CONFLICT = "CONTENT_CONFLICT"


@dataclass(frozen=True, slots=True)
class TrainingRunStoreResult:
    """Append result carrying evidence only for successful outcomes."""

    status: TrainingRunStoreStatus
    training_run: StoredTrainingRun | None

    def __post_init__(self) -> None:
        successful = self.status in {
            TrainingRunStoreStatus.APPENDED,
            TrainingRunStoreStatus.ALREADY_PRESENT,
        }
        if successful != (self.training_run is not None):
            raise ValueError("training run store result shape is inconsistent")


class TrainingRunRepository(Protocol):
    """Owner-bound append-only training run repository."""

    async def append(self, outcome: QloraTrainingOutcome) -> TrainingRunStoreResult: ...

    async def get_owned(self, *, run_id: UUID) -> StoredTrainingRun | None: ...

    async def history(self) -> tuple[StoredTrainingRun, ...]: ...


class InMemoryTrainingRunRepository:
    """Deterministic repository for ordinary tests and smoke journeys."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        dataset_references: frozenset[tuple[UUID, int, str]],
        owner_exists: bool = True,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._dataset_references = dataset_references
        self._owner_exists = owner_exists
        self._outcomes: dict[UUID, QloraTrainingOutcome] = {}

    async def append(self, outcome: QloraTrainingOutcome) -> TrainingRunStoreResult:
        if not self._owner_exists or outcome.owner_user_id != self._owner_user_id:
            return TrainingRunStoreResult(TrainingRunStoreStatus.OWNER_NOT_FOUND, None)
        if _dataset_key(outcome.dataset_reference) not in self._dataset_references:
            return TrainingRunStoreResult(TrainingRunStoreStatus.DATASET_NOT_FOUND, None)
        existing = self._outcomes.get(outcome.run_id)
        if existing is not None:
            if existing.content_hash == outcome.content_hash:
                return TrainingRunStoreResult(
                    TrainingRunStoreStatus.ALREADY_PRESENT,
                    stored_training_run(existing),
                )
            return TrainingRunStoreResult(TrainingRunStoreStatus.CONTENT_CONFLICT, None)
        self._outcomes[outcome.run_id] = outcome
        return TrainingRunStoreResult(
            TrainingRunStoreStatus.APPENDED,
            stored_training_run(outcome),
        )

    async def get_owned(self, *, run_id: UUID) -> StoredTrainingRun | None:
        outcome = self._outcomes.get(run_id)
        return None if outcome is None else stored_training_run(outcome)

    async def history(self) -> tuple[StoredTrainingRun, ...]:
        ordered = sorted(
            self._outcomes.values(),
            key=lambda item: (item.started_at, item.run_id.hex),
        )
        return tuple(stored_training_run(item) for item in ordered)


class SqlAlchemyTrainingRunRepository:
    """PostgreSQL adapter bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(self, outcome: QloraTrainingOutcome) -> TrainingRunStoreResult:
        if outcome.owner_user_id != self._owner_user_id:
            return TrainingRunStoreResult(TrainingRunStoreStatus.OWNER_NOT_FOUND, None)
        owner_exists = await self._session.scalar(
            select(UserRecord.id).where(UserRecord.id == self._owner_user_id)
        )
        if owner_exists is None:
            return TrainingRunStoreResult(TrainingRunStoreStatus.OWNER_NOT_FOUND, None)
        dataset_exists = await self._session.scalar(
            select(TrainingDatasetVersionRecord.dataset_id).where(
                TrainingDatasetVersionRecord.dataset_id == outcome.dataset_reference.dataset_id,
                TrainingDatasetVersionRecord.version_number
                == outcome.dataset_reference.version_number,
                TrainingDatasetVersionRecord.owner_user_id == self._owner_user_id,
                TrainingDatasetVersionRecord.content_hash == outcome.dataset_reference.content_hash,
            )
        )
        if dataset_exists is None:
            return TrainingRunStoreResult(TrainingRunStoreStatus.DATASET_NOT_FOUND, None)
        existing = await self.get_owned(run_id=outcome.run_id)
        if existing is not None:
            if existing.content_hash == outcome.content_hash:
                return TrainingRunStoreResult(
                    TrainingRunStoreStatus.ALREADY_PRESENT,
                    existing,
                )
            return TrainingRunStoreResult(TrainingRunStoreStatus.CONTENT_CONFLICT, None)
        try:
            async with self._session.begin_nested():
                self._session.add(training_run_to_record(outcome))
                await self._session.flush()
                for checkpoint in outcome.checkpoints:
                    self._session.add(
                        training_checkpoint_to_record(
                            run_id=outcome.run_id,
                            owner_user_id=outcome.owner_user_id,
                            checkpoint=checkpoint,
                        )
                    )
                await self._session.flush()
        except IntegrityError:
            return TrainingRunStoreResult(TrainingRunStoreStatus.CONTENT_CONFLICT, None)
        return TrainingRunStoreResult(
            TrainingRunStoreStatus.APPENDED,
            stored_training_run(outcome),
        )

    async def get_owned(self, *, run_id: UUID) -> StoredTrainingRun | None:
        record = await self._session.scalar(
            select(TrainingRunRecord).where(
                TrainingRunRecord.id == run_id,
                TrainingRunRecord.owner_user_id == self._owner_user_id,
            )
        )
        if record is None:
            return None
        checkpoints = await self._checkpoint_history(run_id=run_id)
        return stored_training_run_from_record(record, checkpoints)

    async def history(self) -> tuple[StoredTrainingRun, ...]:
        records = (
            await self._session.scalars(
                select(TrainingRunRecord)
                .where(TrainingRunRecord.owner_user_id == self._owner_user_id)
                .order_by(TrainingRunRecord.started_at, TrainingRunRecord.id)
            )
        ).all()
        values: list[StoredTrainingRun] = []
        for record in records:
            checkpoints = await self._checkpoint_history(run_id=record.id)
            values.append(stored_training_run_from_record(record, checkpoints))
        return tuple(values)

    async def _checkpoint_history(
        self,
        *,
        run_id: UUID,
    ) -> tuple[StoredTrainingCheckpoint, ...]:
        records = (
            await self._session.scalars(
                select(TrainingRunCheckpointRecord)
                .where(
                    TrainingRunCheckpointRecord.training_run_id == run_id,
                    TrainingRunCheckpointRecord.owner_user_id == self._owner_user_id,
                )
                .order_by(
                    TrainingRunCheckpointRecord.step,
                    TrainingRunCheckpointRecord.relative_path,
                )
            )
        ).all()
        return tuple(
            StoredTrainingCheckpoint(
                step=record.step,
                relative_path=record.relative_path,
                content_sha256=record.content_sha256,
            )
            for record in records
        )


def training_run_to_record(outcome: QloraTrainingOutcome) -> TrainingRunRecord:
    """Map an exact final outcome to its immutable persistence record."""
    return TrainingRunRecord(
        id=outcome.run_id,
        owner_user_id=outcome.owner_user_id,
        dataset_id=outcome.dataset_reference.dataset_id,
        dataset_version_number=outcome.dataset_reference.version_number,
        dataset_content_hash=outcome.dataset_reference.content_hash,
        request_sha256=outcome.request_sha256,
        configuration_sha256=outcome.configuration_sha256,
        package_lock_sha256=outcome.package_lock_sha256,
        environment_sha256=outcome.environment_sha256,
        process_log_relative_path=outcome.process_log_relative_path,
        process_log_sha256=outcome.process_log_sha256,
        status=outcome.status.value,
        started_at=outcome.started_at,
        completed_at=outcome.completed_at,
        duration_milliseconds=outcome.duration_milliseconds,
        peak_gpu_memory_mb=outcome.peak_gpu_memory_mb,
        metric_count=len(outcome.metrics),
        checkpoint_count=len(outcome.checkpoints),
        adapter_relative_path=outcome.adapter_relative_path,
        adapter_sha256=outcome.adapter_sha256,
        failure_kind=None if outcome.failure_kind is None else outcome.failure_kind.value,
        failure_message=outcome.failure_message,
        content_hash=outcome.content_hash,
        outcome_snapshot_json=canonical_json(outcome.to_snapshot()),
    )


def training_checkpoint_to_record(
    *,
    run_id: UUID,
    owner_user_id: UUID,
    checkpoint: TrainingCheckpointEvidence,
) -> TrainingRunCheckpointRecord:
    return TrainingRunCheckpointRecord(
        training_run_id=run_id,
        step=checkpoint.step,
        owner_user_id=owner_user_id,
        relative_path=checkpoint.relative_path,
        content_sha256=checkpoint.content_sha256,
    )


def stored_training_run(outcome: QloraTrainingOutcome) -> StoredTrainingRun:
    return StoredTrainingRun(
        run_id=outcome.run_id,
        owner_user_id=outcome.owner_user_id,
        dataset_reference=outcome.dataset_reference,
        request_sha256=outcome.request_sha256,
        configuration_sha256=outcome.configuration_sha256,
        package_lock_sha256=outcome.package_lock_sha256,
        environment_sha256=outcome.environment_sha256,
        process_log_relative_path=outcome.process_log_relative_path,
        process_log_sha256=outcome.process_log_sha256,
        status=outcome.status,
        started_at=outcome.started_at,
        completed_at=outcome.completed_at,
        duration_milliseconds=outcome.duration_milliseconds,
        peak_gpu_memory_mb=outcome.peak_gpu_memory_mb,
        metric_count=len(outcome.metrics),
        adapter_relative_path=outcome.adapter_relative_path,
        adapter_sha256=outcome.adapter_sha256,
        failure_kind=None if outcome.failure_kind is None else outcome.failure_kind.value,
        failure_message=outcome.failure_message,
        content_hash=outcome.content_hash,
        checkpoints=tuple(
            StoredTrainingCheckpoint.from_evidence(item) for item in outcome.checkpoints
        ),
    )


def stored_training_run_from_record(
    record: TrainingRunRecord,
    checkpoints: tuple[StoredTrainingCheckpoint, ...],
) -> StoredTrainingRun:
    if len(checkpoints) != record.checkpoint_count:
        raise ValueError("stored training checkpoint count does not match its run")
    return StoredTrainingRun(
        run_id=record.id,
        owner_user_id=record.owner_user_id,
        dataset_reference=DatasetManifestReference(
            dataset_id=record.dataset_id,
            version_number=record.dataset_version_number,
            content_hash=record.dataset_content_hash,
        ),
        request_sha256=record.request_sha256,
        configuration_sha256=record.configuration_sha256,
        package_lock_sha256=record.package_lock_sha256,
        environment_sha256=record.environment_sha256,
        process_log_relative_path=record.process_log_relative_path,
        process_log_sha256=record.process_log_sha256,
        status=QloraTrainingStatus(record.status),
        started_at=record.started_at,
        completed_at=record.completed_at,
        duration_milliseconds=record.duration_milliseconds,
        peak_gpu_memory_mb=record.peak_gpu_memory_mb,
        metric_count=record.metric_count,
        adapter_relative_path=record.adapter_relative_path,
        adapter_sha256=record.adapter_sha256,
        failure_kind=record.failure_kind,
        failure_message=record.failure_message,
        content_hash=record.content_hash,
        checkpoints=checkpoints,
    )


def _dataset_key(reference: DatasetManifestReference) -> tuple[UUID, int, str]:
    return (
        reference.dataset_id,
        reference.version_number,
        reference.content_hash,
    )
