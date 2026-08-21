"""SQLAlchemy persistence for human gates and audit events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.persistence.models import (
    ProjectRecord,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateEvent,
    HumanGateEventKind,
    HumanGateStatus,
    HumanGateType,
)
from orchestwin.workflow.persistence.models import (
    HumanGateEventRecord,
    HumanGateRecord,
)
from orchestwin.workflow.repository import (
    HumanGateStateConflict,
)


def gate_record_to_domain(
    record: HumanGateRecord,
) -> HumanGate:
    """Translate a persisted gate into immutable domain state."""
    gate_type = HumanGateType(record.gate_type)

    return HumanGate(
        id=record.id,
        project_id=record.project_id,
        owner_user_id=record.owner_user_id,
        gate_type=gate_type,
        artifact=GateArtifactReference(
            project_id=record.project_id,
            gate_type=gate_type,
            artifact_id=record.artifact_id,
            version=record.artifact_version,
            content_hash=record.artifact_hash,
        ),
        iteration=record.iteration,
        max_iterations=record.max_iterations,
        status=HumanGateStatus(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
        event_sequence=record.event_sequence,
        resume_status=(
            HumanGateStatus(record.resume_status) if record.resume_status is not None else None
        ),
    )


def event_record_to_domain(
    record: HumanGateEventRecord,
) -> HumanGateEvent:
    """Translate a persisted audit event into domain state."""
    gate_type = HumanGateType(record.gate_type)

    return HumanGateEvent(
        id=record.id,
        gate_id=record.gate_id,
        sequence_number=record.sequence_number,
        kind=HumanGateEventKind(record.kind),
        previous_status=HumanGateStatus(record.previous_status),
        resulting_status=HumanGateStatus(record.resulting_status),
        artifact=GateArtifactReference(
            project_id=record.project_id,
            gate_type=gate_type,
            artifact_id=record.artifact_id,
            version=record.artifact_version,
            content_hash=record.artifact_hash,
        ),
        occurred_at=record.occurred_at,
        actor_user_id=record.actor_user_id,
        reason=record.reason,
    )


def gate_to_record(
    gate: HumanGate,
) -> HumanGateRecord:
    """Create a SQLAlchemy record from immutable gate state."""
    return HumanGateRecord(
        id=gate.id,
        project_id=gate.project_id,
        owner_user_id=gate.owner_user_id,
        gate_type=gate.gate_type.value,
        artifact_id=gate.artifact.artifact_id,
        artifact_version=(gate.artifact.version),
        artifact_hash=(gate.artifact.content_hash),
        iteration=gate.iteration,
        max_iterations=gate.max_iterations,
        status=gate.status.value,
        resume_status=(gate.resume_status.value if gate.resume_status is not None else None),
        event_sequence=gate.event_sequence,
        created_at=gate.created_at,
        updated_at=gate.updated_at,
    )


def event_to_record(
    event: HumanGateEvent,
) -> HumanGateEventRecord:
    """Create an append-only record from a gate event."""
    return HumanGateEventRecord(
        id=event.id,
        gate_id=event.gate_id,
        project_id=(event.artifact.project_id),
        gate_type=(event.artifact.gate_type.value),
        sequence_number=(event.sequence_number),
        kind=event.kind.value,
        previous_status=(event.previous_status.value),
        resulting_status=(event.resulting_status.value),
        artifact_id=(event.artifact.artifact_id),
        artifact_version=(event.artifact.version),
        artifact_hash=(event.artifact.content_hash),
        actor_user_id=(event.actor_user_id),
        reason=event.reason,
        occurred_at=event.occurred_at,
    )


def owned_gates_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    gate_type: HumanGateType,
) -> Select[tuple[HumanGateRecord]]:
    """Build the canonical owner-scoped human-gate query."""
    return (
        select(HumanGateRecord)
        .join(
            ProjectRecord,
            ProjectRecord.id == HumanGateRecord.project_id,
        )
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
            HumanGateRecord.gate_type == gate_type.value,
        )
    )


def latest_owned_gate_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    gate_type: HumanGateType,
) -> Select[tuple[HumanGateRecord]]:
    """Build the latest-iteration query for an owned project."""
    return (
        owned_gates_statement(
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_type=gate_type,
        )
        .order_by(
            HumanGateRecord.iteration.desc(),
            HumanGateRecord.created_at.desc(),
            HumanGateRecord.id.desc(),
        )
        .limit(1)
    )


def owned_gate_events_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    gate_id: UUID,
) -> Select[tuple[HumanGateEventRecord]]:
    """Build an owner-scoped gate-event history query."""
    return (
        select(HumanGateEventRecord)
        .join(
            HumanGateRecord,
            HumanGateRecord.id == HumanGateEventRecord.gate_id,
        )
        .join(
            ProjectRecord,
            ProjectRecord.id == HumanGateRecord.project_id,
        )
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
            HumanGateRecord.id == gate_id,
        )
        .order_by(HumanGateEventRecord.sequence_number)
    )


class SqlAlchemyHumanGateRepository:
    """Owner-scoped SQLAlchemy human-gate repository."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Insert a submitted gate before its first audit event."""
        self._validate_event(
            gate=gate,
            event=event,
        )

        gate_record = gate_to_record(gate)
        event_record = event_to_record(event)

        self._session.add(gate_record)

        await self._session.flush()

        self._session.add(event_record)
        await self._session.flush()

        return gate_record_to_domain(gate_record)

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        """Lock and return the latest owner-scoped gate."""
        record = await self._session.scalar(
            latest_owned_gate_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=gate_type,
            ).with_for_update()
        )

        if record is None:
            return None

        return gate_record_to_domain(record)

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist a compare-and-set state transition and its event."""
        if previous_gate.id != updated_gate.id:
            raise ValueError("gate transition must preserve gate identity")

        if (
            previous_gate.project_id != updated_gate.project_id
            or previous_gate.gate_type is not updated_gate.gate_type
        ):
            raise ValueError("gate transition must preserve gate scope")

        self._validate_event(
            gate=updated_gate,
            event=event,
        )

        result = await self._session.execute(
            update(HumanGateRecord)
            .where(
                HumanGateRecord.id == previous_gate.id,
                HumanGateRecord.status == previous_gate.status.value,
                HumanGateRecord.event_sequence == previous_gate.event_sequence,
            )
            .values(
                status=updated_gate.status.value,
                resume_status=(
                    updated_gate.resume_status.value
                    if updated_gate.resume_status is not None
                    else None
                ),
                event_sequence=(updated_gate.event_sequence),
                updated_at=(updated_gate.updated_at),
            )
        )

        if result.rowcount != 1:
            raise HumanGateStateConflict("human gate changed concurrently")

        self._session.add(event_to_record(event))
        await self._session.flush()

        return updated_gate

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return an owned gate's append-only event history."""
        result = await self._session.scalars(
            owned_gate_events_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_id=gate_id,
            )
        )

        return tuple(event_record_to_domain(record) for record in result.all())

    @staticmethod
    def _validate_event(
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> None:
        """Ensure one event is the latest event of its gate."""
        if event.gate_id != gate.id:
            raise ValueError("gate event must reference its gate")

        if event.sequence_number != gate.event_sequence:
            raise ValueError("gate event sequence must match the current gate sequence")

        if (
            event.artifact.project_id != gate.project_id
            or event.artifact.gate_type is not gate.gate_type
        ):
            raise ValueError("gate event artifact must match the gate scope")
