"""Owner-scoped persistence for mutable workflow runs and immutable checkpoints."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    column,
    select,
    table,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase
from orchestwin.workflow.checkpoints import (
    WorkflowCheckpoint,
    WorkflowCheckpointCreation,
    deserialize_workflow_run,
    serialize_workflow_run,
    workflow_run_content_hash,
)
from orchestwin.workflow.runs import WorkflowRun

_RUN_STATUSES = (
    "'DRAFT', 'RUNNING', 'WAITING_FOR_HUMAN', 'PAUSED', "
    "'PAUSED_NEEDS_HUMAN', 'BLOCKED', 'FAILED', 'CANCELLED', "
    "'COMPLETED_PENDING_FINAL_APPROVAL', 'APPROVED'"
)

_PROJECTS = table(
    "projects",
    column("id", Uuid),
    column("owner_user_id", Uuid),
    column("archived_at", DateTime(timezone=True)),
)

_WORKFLOW_STAGES = (
    "'INTAKE', 'SOURCE_INGESTION', 'STACK_DETECTION', 'ARCHITECTURE_RECOVERY', "
    "'REQUIREMENTS_INFERENCE', 'BASELINE_EXECUTION', 'BRIEF_APPROVAL', "
    "'TEAM_SELECTION', 'TEAM_APPROVAL', 'USER_MODELING', 'USER_TWIN_APPROVAL', "
    "'REQUIREMENTS', 'REQUIREMENTS_APPROVAL', 'DESIGN_EXPLORATION', "
    "'PATCH_PLANNING', 'DESIGN_APPROVAL', 'ARCHITECTURE_AND_TEST_PLAN', "
    "'ARCHITECTURE_APPROVAL', 'IMPLEMENTATION', 'EXECUTION', "
    "'SYNTHETIC_EVALUATION', 'REVISION_DECISION', 'FINAL_REVIEW', "
    "'FINAL_APPROVAL', 'EXPORT'"
)


class WorkflowRunRecord(OrmBase):
    """Current compare-and-set projection of one durable workflow run."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint(
            "project_mode IN ('GREENFIELD_GENERATION', 'BROWNFIELD_ASSESSMENT')",
            name="project_mode_valid",
        ),
        CheckConstraint(f"current_stage IN ({_WORKFLOW_STAGES})", name="stage_valid"),
        CheckConstraint(f"status IN ({_RUN_STATUSES})", name="status_valid"),
        CheckConstraint(
            f"resume_status IS NULL OR resume_status IN ({_RUN_STATUSES})",
            name="resume_status_valid",
        ),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint("checkpoint_sequence >= 0", name="checkpoint_sequence_non_negative"),
        CheckConstraint("state_hash ~ '^[0-9a-f]{64}$'", name="state_hash_valid"),
        CheckConstraint("char_length(state_snapshot_json) > 0", name="snapshot_required"),
        CheckConstraint(
            "(status IN ('PAUSED', 'PAUSED_NEEDS_HUMAN') AND "
            "resume_status IN ('RUNNING', 'WAITING_FOR_HUMAN')) OR "
            "(status NOT IN ('PAUSED', 'PAUSED_NEEDS_HUMAN') AND resume_status IS NULL)",
            name="resume_state_consistent",
        ),
        CheckConstraint(
            "((status = 'WAITING_FOR_HUMAN' OR resume_status = 'WAITING_FOR_HUMAN') "
            "AND pending_gate_id IS NOT NULL) OR "
            "((status <> 'WAITING_FOR_HUMAN' AND "
            "(resume_status IS NULL OR resume_status <> 'WAITING_FOR_HUMAN')) "
            "AND pending_gate_id IS NULL)",
            name="pending_gate_consistent",
        ),
        UniqueConstraint("id", "project_id", "owner_user_id", name="uq_workflow_runs_scope"),
        Index("ix_workflow_runs_project_updated", "project_id", "updated_at"),
        Index("ix_workflow_runs_owner_status", "owner_user_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    project_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    current_stage: Mapped[str] = mapped_column(String(48), nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    resume_status: Mapped[str | None] = mapped_column(String(48), nullable=True)
    pending_gate_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    state_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowCheckpointRecord(OrmBase):
    """Append-only canonical application checkpoint."""

    __tablename__ = "workflow_checkpoints"
    __table_args__ = (
        CheckConstraint("sequence_number >= 1", name="sequence_positive"),
        CheckConstraint("schema_version >= 1", name="schema_version_positive"),
        CheckConstraint("state_version >= 1", name="state_version_positive"),
        CheckConstraint("state_hash ~ '^[0-9a-f]{64}$'", name="state_hash_valid"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_valid"),
        CheckConstraint("char_length(payload_json) > 0", name="payload_required"),
        CheckConstraint(
            "(sequence_number = 1 AND parent_checkpoint_id IS NULL) OR "
            "(sequence_number > 1 AND parent_checkpoint_id IS NOT NULL)",
            name="linear_lineage",
        ),
        ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_workflow_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["run_id", "parent_checkpoint_id"],
            ["workflow_checkpoints.run_id", "workflow_checkpoints.id"],
            name="fk_workflow_checkpoints_parent",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("run_id", "sequence_number", name="uq_workflow_checkpoints_sequence"),
        UniqueConstraint("run_id", "id", name="uq_workflow_checkpoints_run_id"),
        Index("ix_workflow_checkpoints_run_sequence", "run_id", "sequence_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_checkpoint_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowRunStoreStatus(StrEnum):
    """Owner-safe outcomes of workflow-run persistence operations."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    STATE_CONFLICT = "STATE_CONFLICT"


@dataclass(frozen=True, slots=True)
class WorkflowRunStoreResult:
    """Persistence result containing state only for successful outcomes."""

    status: WorkflowRunStoreStatus
    run: WorkflowRun | None

    def __post_init__(self) -> None:
        successful = self.status in {
            WorkflowRunStoreStatus.CREATED,
            WorkflowRunStoreStatus.UPDATED,
            WorkflowRunStoreStatus.ALREADY_PRESENT,
        }
        if successful != (self.run is not None):
            raise ValueError("workflow run store result shape is inconsistent")


class WorkflowRunRepository(Protocol):
    """Owner-bound workflow persistence port."""

    async def create(self, run: WorkflowRun) -> WorkflowRunStoreResult: ...

    async def get_owned(self, *, run_id: UUID) -> WorkflowRun | None: ...

    async def save_checkpoint(
        self,
        *,
        previous_run: WorkflowRun,
        creation: WorkflowCheckpointCreation,
    ) -> WorkflowRunStoreResult: ...

    async def list_checkpoints(
        self,
        *,
        run_id: UUID,
    ) -> tuple[WorkflowCheckpoint, ...]: ...


class InMemoryWorkflowRunRepository:
    """Deterministic owner-scoped repository for ordinary tests."""

    def __init__(self, *, owner_user_id: UUID, project_ids: frozenset[UUID]) -> None:
        self._owner_user_id = owner_user_id
        self._project_ids = project_ids
        self._runs: dict[UUID, WorkflowRun] = {}
        self._checkpoints: dict[UUID, list[WorkflowCheckpoint]] = {}

    async def create(self, run: WorkflowRun) -> WorkflowRunStoreResult:
        if run.owner_user_id != self._owner_user_id or run.project_id not in self._project_ids:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.PROJECT_NOT_FOUND, None)
        existing = self._runs.get(run.id)
        if existing is not None:
            if workflow_run_content_hash(existing) == workflow_run_content_hash(run):
                return WorkflowRunStoreResult(WorkflowRunStoreStatus.ALREADY_PRESENT, existing)
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        self._runs[run.id] = run
        self._checkpoints[run.id] = []
        return WorkflowRunStoreResult(WorkflowRunStoreStatus.CREATED, run)

    async def get_owned(self, *, run_id: UUID) -> WorkflowRun | None:
        run = self._runs.get(run_id)
        if run is None or run.owner_user_id != self._owner_user_id:
            return None
        return run

    async def save_checkpoint(
        self,
        *,
        previous_run: WorkflowRun,
        creation: WorkflowCheckpointCreation,
    ) -> WorkflowRunStoreResult:
        if not _checkpoint_update_is_consistent(previous_run, creation):
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        current = await self.get_owned(run_id=previous_run.id)
        if current != previous_run:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        history = self._checkpoints[previous_run.id]
        if history and creation.checkpoint.parent_checkpoint_id != history[-1].id:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        if not history and creation.checkpoint.parent_checkpoint_id is not None:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        self._runs[previous_run.id] = creation.run
        history.append(creation.checkpoint)
        return WorkflowRunStoreResult(WorkflowRunStoreStatus.UPDATED, creation.run)

    async def list_checkpoints(self, *, run_id: UUID) -> tuple[WorkflowCheckpoint, ...]:
        if await self.get_owned(run_id=run_id) is None:
            return ()
        return tuple(self._checkpoints[run_id])


class SqlAlchemyWorkflowRunRepository:
    """PostgreSQL workflow repository bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(self, run: WorkflowRun) -> WorkflowRunStoreResult:
        if run.owner_user_id != self._owner_user_id:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.PROJECT_NOT_FOUND, None)
        project_exists = await self._session.scalar(
            select(_PROJECTS.c.id).where(
                _PROJECTS.c.id == run.project_id,
                _PROJECTS.c.owner_user_id == self._owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
        )
        if project_exists is None:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.PROJECT_NOT_FOUND, None)

        existing = await self.get_owned(run_id=run.id)
        if existing is not None:
            if workflow_run_content_hash(existing) == workflow_run_content_hash(run):
                return WorkflowRunStoreResult(WorkflowRunStoreStatus.ALREADY_PRESENT, existing)
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)

        try:
            async with self._session.begin_nested():
                self._session.add(workflow_run_to_record(run))
                await self._session.flush()
        except IntegrityError:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        return WorkflowRunStoreResult(WorkflowRunStoreStatus.CREATED, run)

    async def get_owned(self, *, run_id: UUID) -> WorkflowRun | None:
        record = await self._session.scalar(
            select(WorkflowRunRecord)
            .join(_PROJECTS, _PROJECTS.c.id == WorkflowRunRecord.project_id)
            .where(
                WorkflowRunRecord.id == run_id,
                WorkflowRunRecord.owner_user_id == self._owner_user_id,
                _PROJECTS.c.owner_user_id == self._owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
        )
        return None if record is None else workflow_run_record_to_domain(record)

    async def save_checkpoint(
        self,
        *,
        previous_run: WorkflowRun,
        creation: WorkflowCheckpointCreation,
    ) -> WorkflowRunStoreResult:
        if previous_run.owner_user_id != self._owner_user_id:
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        if not _checkpoint_update_is_consistent(previous_run, creation):
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)

        values = _workflow_run_values(creation.run)
        try:
            async with self._session.begin_nested():
                result = await self._session.execute(
                    update(WorkflowRunRecord)
                    .where(
                        WorkflowRunRecord.id == previous_run.id,
                        WorkflowRunRecord.project_id == previous_run.project_id,
                        WorkflowRunRecord.owner_user_id == self._owner_user_id,
                        WorkflowRunRecord.state_version == previous_run.state_version,
                        WorkflowRunRecord.checkpoint_sequence == previous_run.checkpoint_sequence,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise _WorkflowStateConflict
                self._session.add(checkpoint_to_record(creation.checkpoint))
                await self._session.flush()
        except (_WorkflowStateConflict, IntegrityError):
            return WorkflowRunStoreResult(WorkflowRunStoreStatus.STATE_CONFLICT, None)
        return WorkflowRunStoreResult(WorkflowRunStoreStatus.UPDATED, creation.run)

    async def list_checkpoints(self, *, run_id: UUID) -> tuple[WorkflowCheckpoint, ...]:
        rows = await self._session.scalars(
            select(WorkflowCheckpointRecord)
            .join(WorkflowRunRecord, WorkflowRunRecord.id == WorkflowCheckpointRecord.run_id)
            .join(_PROJECTS, _PROJECTS.c.id == WorkflowRunRecord.project_id)
            .where(
                WorkflowCheckpointRecord.run_id == run_id,
                WorkflowCheckpointRecord.owner_user_id == self._owner_user_id,
                WorkflowRunRecord.owner_user_id == self._owner_user_id,
                _PROJECTS.c.owner_user_id == self._owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
            .order_by(WorkflowCheckpointRecord.sequence_number)
        )
        return tuple(checkpoint_record_to_domain(record) for record in rows.all())


class _WorkflowStateConflict(Exception):
    """Internal savepoint rollback signal for failed compare-and-set updates."""


def workflow_run_to_record(run: WorkflowRun) -> WorkflowRunRecord:
    """Translate immutable domain state into its current persistence projection."""
    return WorkflowRunRecord(id=run.id, project_id=run.project_id, **_workflow_run_values(run))


def workflow_run_record_to_domain(record: WorkflowRunRecord) -> WorkflowRun:
    """Restore and verify the canonical state snapshot against projected columns."""
    run = deserialize_workflow_run(record.state_snapshot_json)
    if workflow_run_content_hash(run) != record.state_hash:
        raise ValueError("persisted workflow run state hash is inconsistent")
    projections = (
        run.id == record.id,
        run.project_id == record.project_id,
        run.owner_user_id == record.owner_user_id,
        run.project_mode.value == record.project_mode,
        run.current_stage.value == record.current_stage,
        run.status.value == record.status,
        (run.resume_status.value if run.resume_status else None) == record.resume_status,
        run.pending_gate_id == record.pending_gate_id,
        run.state_version == record.state_version,
        run.checkpoint_sequence == record.checkpoint_sequence,
        run.created_at == record.created_at,
        run.updated_at == record.updated_at,
        run.started_at == record.started_at,
        run.completed_at == record.completed_at,
    )
    if not all(projections):
        raise ValueError("persisted workflow run projections are inconsistent")
    return run


def checkpoint_to_record(checkpoint: WorkflowCheckpoint) -> WorkflowCheckpointRecord:
    """Translate one immutable checkpoint into an append-only record."""
    return WorkflowCheckpointRecord(
        id=checkpoint.id,
        run_id=checkpoint.run_id,
        project_id=checkpoint.project_id,
        owner_user_id=checkpoint.owner_user_id,
        sequence_number=checkpoint.sequence_number,
        schema_version=checkpoint.schema_version,
        parent_checkpoint_id=checkpoint.parent_checkpoint_id,
        state_version=checkpoint.state_version,
        state_hash=checkpoint.state_hash,
        payload_json=checkpoint.payload_json,
        payload_hash=checkpoint.payload_hash,
        created_at=checkpoint.created_at,
    )


def checkpoint_record_to_domain(record: WorkflowCheckpointRecord) -> WorkflowCheckpoint:
    """Translate one append-only record into its immutable checkpoint envelope."""
    return WorkflowCheckpoint(
        id=record.id,
        run_id=record.run_id,
        project_id=record.project_id,
        owner_user_id=record.owner_user_id,
        sequence_number=record.sequence_number,
        schema_version=record.schema_version,
        parent_checkpoint_id=record.parent_checkpoint_id,
        state_version=record.state_version,
        state_hash=record.state_hash,
        payload_json=record.payload_json,
        payload_hash=record.payload_hash,
        created_at=record.created_at,
    )


def _workflow_run_values(run: WorkflowRun) -> dict[str, object]:
    return {
        "owner_user_id": run.owner_user_id,
        "project_mode": run.project_mode.value,
        "current_stage": run.current_stage.value,
        "status": run.status.value,
        "resume_status": run.resume_status.value if run.resume_status else None,
        "pending_gate_id": run.pending_gate_id,
        "state_version": run.state_version,
        "checkpoint_sequence": run.checkpoint_sequence,
        "state_hash": workflow_run_content_hash(run),
        "state_snapshot_json": serialize_workflow_run(run),
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


def _checkpoint_update_is_consistent(
    previous_run: WorkflowRun,
    creation: WorkflowCheckpointCreation,
) -> bool:
    checkpoint = creation.checkpoint
    return (
        creation.run.id == previous_run.id == checkpoint.run_id
        and creation.run.project_id == previous_run.project_id == checkpoint.project_id
        and creation.run.owner_user_id == previous_run.owner_user_id == checkpoint.owner_user_id
        and _state_progression_is_valid(previous_run, creation.run)
        and creation.run.checkpoint_sequence == previous_run.checkpoint_sequence + 1
        and checkpoint.state_version == creation.run.state_version
        and checkpoint.sequence_number == creation.run.checkpoint_sequence
    )


def _state_progression_is_valid(
    previous_run: WorkflowRun,
    updated_run: WorkflowRun,
) -> bool:
    if updated_run.state_version == previous_run.state_version + 1:
        return True
    if updated_run.state_version != previous_run.state_version:
        return False
    return (
        replace(
            updated_run,
            checkpoint_sequence=previous_run.checkpoint_sequence,
        )
        == previous_run
    )
