"""SQLAlchemy records for human-gate state and audit events."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase


class HumanGateRecord(OrmBase):
    """Persisted current state of one human-gate iteration."""

    __tablename__ = "human_gates"
    __table_args__ = (
        CheckConstraint(
            "gate_type IN ('PROJECT_BRIEF', 'AGENT_TEAM', 'USER_MODELING', 'REQUIREMENTS', 'DESIGN', 'ARCHITECTURE', 'HIGH_IMPACT_OPERATION')",
            name="gate_type_valid",
        ),
        CheckConstraint(
            "artifact_version >= 1",
            name="artifact_version_positive",
        ),
        CheckConstraint(
            "char_length(artifact_hash) = 64",
            name="artifact_hash_length",
        ),
        CheckConstraint(
            "max_iterations >= 1",
            name="max_iterations_positive",
        ),
        CheckConstraint(
            "iteration BETWEEN 1 AND max_iterations",
            name="iteration_within_limit",
        ),
        CheckConstraint(
            "event_sequence >= 0",
            name="event_sequence_non_negative",
        ),
        CheckConstraint(
            "status IN ("
            "'DRAFT', "
            "'PENDING_APPROVAL', "
            "'APPROVED', "
            "'REJECTED', "
            "'REVISION_REQUESTED', "
            "'PAUSED', "
            "'CANCELLED', "
            "'STALE', "
            "'PAUSED_NEEDS_HUMAN'"
            ")",
            name="status_valid",
        ),
        CheckConstraint(
            "("
            "status = 'PAUSED' "
            "AND resume_status IN ("
            "'DRAFT', "
            "'PENDING_APPROVAL'"
            ")"
            ") OR ("
            "status <> 'PAUSED' "
            "AND resume_status IS NULL"
            ")",
            name="resume_state_consistent",
        ),
        UniqueConstraint(
            "project_id",
            "gate_type",
            "iteration",
            name=("uq_human_gates_project_id_gate_type_iteration"),
        ),
        UniqueConstraint(
            "project_id",
            "gate_type",
            "artifact_id",
            "artifact_version",
            name=("uq_human_gates_project_gate_artifact_version"),
        ),
        Index(
            "ix_human_gates_project_gate_type",
            "project_id",
            "gate_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    gate_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    artifact_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    artifact_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    iteration: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    max_iterations: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    resume_status: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    event_sequence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class HumanGateEventRecord(OrmBase):
    """Append-only audit event emitted by a human-gate transition."""

    __tablename__ = "human_gate_events"
    __table_args__ = (
        CheckConstraint(
            "sequence_number >= 1",
            name="sequence_number_positive",
        ),
        CheckConstraint(
            "gate_type IN ('PROJECT_BRIEF', 'AGENT_TEAM', 'USER_MODELING', 'REQUIREMENTS', 'DESIGN', 'ARCHITECTURE', 'HIGH_IMPACT_OPERATION')",
            name="gate_type_valid",
        ),
        CheckConstraint(
            "kind IN ("
            "'SUBMIT', "
            "'APPROVE', "
            "'REJECT', "
            "'REQUEST_REVISION', "
            "'PAUSE', "
            "'RESUME', "
            "'CANCEL', "
            "'ARTIFACT_SUPERSEDED'"
            ")",
            name="kind_valid",
        ),
        CheckConstraint(
            "previous_status IN ("
            "'DRAFT', "
            "'PENDING_APPROVAL', "
            "'APPROVED', "
            "'REJECTED', "
            "'REVISION_REQUESTED', "
            "'PAUSED', "
            "'CANCELLED', "
            "'STALE', "
            "'PAUSED_NEEDS_HUMAN'"
            ")",
            name="previous_status_valid",
        ),
        CheckConstraint(
            "resulting_status IN ("
            "'DRAFT', "
            "'PENDING_APPROVAL', "
            "'APPROVED', "
            "'REJECTED', "
            "'REVISION_REQUESTED', "
            "'PAUSED', "
            "'CANCELLED', "
            "'STALE', "
            "'PAUSED_NEEDS_HUMAN'"
            ")",
            name="resulting_status_valid",
        ),
        CheckConstraint(
            "previous_status <> resulting_status",
            name="status_changes",
        ),
        CheckConstraint(
            "artifact_version >= 1",
            name="artifact_version_positive",
        ),
        CheckConstraint(
            "char_length(artifact_hash) = 64",
            name="artifact_hash_length",
        ),
        CheckConstraint(
            "reason IS NULL OR char_length(btrim(reason)) BETWEEN 1 AND 2000",
            name="reason_length",
        ),
        CheckConstraint(
            "("
            "kind = 'ARTIFACT_SUPERSEDED' "
            "AND actor_user_id IS NULL"
            ") OR ("
            "kind <> 'ARTIFACT_SUPERSEDED' "
            "AND actor_user_id IS NOT NULL"
            ")",
            name="actor_state_consistent",
        ),
        CheckConstraint(
            "kind NOT IN ('REJECT', 'REQUEST_REVISION') OR reason IS NOT NULL",
            name="decision_reason_required",
        ),
        UniqueConstraint(
            "gate_id",
            "sequence_number",
            name=("uq_human_gate_events_gate_id_sequence_number"),
        ),
        Index(
            "ix_human_gate_events_gate_id",
            "gate_id",
        ),
        Index(
            "ix_human_gate_events_project_id",
            "project_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    gate_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "human_gates.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    gate_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    previous_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    resulting_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    artifact_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    artifact_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    artifact_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
