"""Owner-scoped append-only persistence for ordered workflow events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
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
    func,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase
from orchestwin.workflow.events import (
    WorkflowEvent,
    WorkflowEventType,
    deserialize_workflow_event_payload,
    serialize_workflow_event_payload,
    workflow_event_payload_hash,
)
from orchestwin.workflow.run_persistence import WorkflowRunRecord

_EVENT_TYPES = ", ".join(f"'{event_type.value}'" for event_type in WorkflowEventType)


class WorkflowEventRecord(OrmBase):
    """Append-only event row ordered within one owned workflow run."""

    __tablename__ = "workflow_events"
    __table_args__ = (
        CheckConstraint("sequence_number >= 1", name="sequence_positive"),
        CheckConstraint(f"event_type IN ({_EVENT_TYPES})", name="event_type_valid"),
        CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="payload_hash_valid"),
        CheckConstraint("char_length(payload_json) > 0", name="payload_required"),
        ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_workflow_events_run_scope",
            ondelete="CASCADE",
        ),
        UniqueConstraint("run_id", "sequence_number", name="uq_workflow_events_sequence"),
        UniqueConstraint("run_id", "id", name="uq_workflow_events_run_id"),
        Index("ix_workflow_events_run_sequence", "run_id", "sequence_number"),
        Index("ix_workflow_events_project_occurred", "project_id", "occurred_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    run_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    project_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    owner_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class WorkflowEventAppendStatus(StrEnum):
    """Owner-safe outcomes of an append operation."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    RUN_NOT_FOUND = "RUN_NOT_FOUND"
    SEQUENCE_CONFLICT = "SEQUENCE_CONFLICT"


@dataclass(frozen=True, slots=True)
class WorkflowEventAppendResult:
    """Append result exposing an event only for successful outcomes."""

    status: WorkflowEventAppendStatus
    event: WorkflowEvent | None

    def __post_init__(self) -> None:
        successful = self.status in {
            WorkflowEventAppendStatus.APPENDED,
            WorkflowEventAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.event is not None):
            raise ValueError("workflow event append result shape is inconsistent")


class WorkflowEventRepository(Protocol):
    """Owner-bound event persistence port used by workflow services and SSE."""

    async def append(
        self,
        event: WorkflowEvent,
        *,
        expected_previous_sequence: int,
    ) -> WorkflowEventAppendResult: ...

    async def list_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[WorkflowEvent, ...]: ...


class InMemoryWorkflowEventRepository:
    """Deterministic owner-scoped event repository for ordinary tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        run_projects: dict[UUID, UUID],
    ) -> None:
        self._owner_user_id = owner_user_id
        self._run_projects = dict(run_projects)
        self._events: dict[UUID, list[WorkflowEvent]] = {}

    async def append(
        self,
        event: WorkflowEvent,
        *,
        expected_previous_sequence: int,
    ) -> WorkflowEventAppendResult:
        if not _expected_sequence_is_valid(event, expected_previous_sequence):
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )
        if (
            event.owner_user_id != self._owner_user_id
            or self._run_projects.get(event.run_id) != event.project_id
        ):
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.RUN_NOT_FOUND,
                None,
            )

        events = self._events.setdefault(event.run_id, [])
        existing = next((item for item in events if item.id == event.id), None)
        if existing is not None:
            if existing == event:
                return WorkflowEventAppendResult(
                    WorkflowEventAppendStatus.ALREADY_PRESENT,
                    existing,
                )
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )
        current_sequence = events[-1].sequence_number if events else 0
        if current_sequence != expected_previous_sequence:
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )
        events.append(event)
        return WorkflowEventAppendResult(WorkflowEventAppendStatus.APPENDED, event)

    async def list_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[WorkflowEvent, ...]:
        _validate_cursor(after_sequence=after_sequence, limit=limit)
        if run_id not in self._run_projects:
            return ()
        return tuple(
            event
            for event in self._events.get(run_id, ())
            if event.sequence_number > after_sequence
        )[:limit]


class SqlAlchemyWorkflowEventRepository:
    """PostgreSQL append-only event repository bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(
        self,
        event: WorkflowEvent,
        *,
        expected_previous_sequence: int,
    ) -> WorkflowEventAppendResult:
        if not _expected_sequence_is_valid(event, expected_previous_sequence):
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )
        if event.owner_user_id != self._owner_user_id:
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.RUN_NOT_FOUND,
                None,
            )
        run_exists = await self._session.scalar(
            select(WorkflowRunRecord.id).where(
                WorkflowRunRecord.id == event.run_id,
                WorkflowRunRecord.project_id == event.project_id,
                WorkflowRunRecord.owner_user_id == self._owner_user_id,
            )
        )
        if run_exists is None:
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.RUN_NOT_FOUND,
                None,
            )

        existing_record = await self._session.scalar(
            select(WorkflowEventRecord).where(
                WorkflowEventRecord.id == event.id,
                WorkflowEventRecord.run_id == event.run_id,
                WorkflowEventRecord.owner_user_id == self._owner_user_id,
            )
        )
        if existing_record is not None:
            existing = workflow_event_record_to_domain(existing_record)
            if existing == event:
                return WorkflowEventAppendResult(
                    WorkflowEventAppendStatus.ALREADY_PRESENT,
                    existing,
                )
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )

        current_sequence = await self._session.scalar(
            select(func.max(WorkflowEventRecord.sequence_number)).where(
                WorkflowEventRecord.run_id == event.run_id,
                WorkflowEventRecord.project_id == event.project_id,
                WorkflowEventRecord.owner_user_id == self._owner_user_id,
            )
        )
        if (current_sequence or 0) != expected_previous_sequence:
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )

        try:
            async with self._session.begin_nested():
                self._session.add(workflow_event_to_record(event))
                await self._session.flush()
        except IntegrityError:
            return WorkflowEventAppendResult(
                WorkflowEventAppendStatus.SEQUENCE_CONFLICT,
                None,
            )
        return WorkflowEventAppendResult(WorkflowEventAppendStatus.APPENDED, event)

    async def list_after(
        self,
        *,
        run_id: UUID,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[WorkflowEvent, ...]:
        _validate_cursor(after_sequence=after_sequence, limit=limit)
        records = await self._session.scalars(
            select(WorkflowEventRecord)
            .join(WorkflowRunRecord, WorkflowRunRecord.id == WorkflowEventRecord.run_id)
            .where(
                WorkflowEventRecord.run_id == run_id,
                WorkflowEventRecord.owner_user_id == self._owner_user_id,
                WorkflowRunRecord.owner_user_id == self._owner_user_id,
                WorkflowEventRecord.sequence_number > after_sequence,
            )
            .order_by(WorkflowEventRecord.sequence_number)
            .limit(limit)
        )
        return tuple(workflow_event_record_to_domain(record) for record in records.all())


def workflow_event_to_record(event: WorkflowEvent) -> WorkflowEventRecord:
    """Translate one immutable event into its append-only persistence record."""
    return WorkflowEventRecord(
        id=event.id,
        run_id=event.run_id,
        project_id=event.project_id,
        owner_user_id=event.owner_user_id,
        sequence_number=event.sequence_number,
        event_type=event.event_type.value,
        occurred_at=event.occurred_at,
        payload_json=serialize_workflow_event_payload(event.payload),
        payload_hash=event.payload_hash,
    )


def workflow_event_record_to_domain(record: WorkflowEventRecord) -> WorkflowEvent:
    """Restore and verify one canonical workflow event record."""
    payload = deserialize_workflow_event_payload(record.payload_json)
    if workflow_event_payload_hash(payload) != record.payload_hash:
        raise ValueError("persisted workflow event payload hash is inconsistent")
    event = WorkflowEvent(
        id=record.id,
        run_id=record.run_id,
        project_id=record.project_id,
        owner_user_id=record.owner_user_id,
        sequence_number=record.sequence_number,
        event_type=WorkflowEventType(record.event_type),
        occurred_at=record.occurred_at,
        payload=payload,
        payload_hash=record.payload_hash,
    )
    return event


def _expected_sequence_is_valid(
    event: WorkflowEvent,
    expected_previous_sequence: int,
) -> bool:
    return (
        not isinstance(expected_previous_sequence, bool)
        and expected_previous_sequence >= 0
        and event.sequence_number == expected_previous_sequence + 1
    )


def _validate_cursor(*, after_sequence: int, limit: int) -> None:
    if isinstance(after_sequence, bool) or after_sequence < 0:
        raise ValueError("workflow event cursor must not be negative")
    if isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("workflow event page limit must be between 1 and 500")
