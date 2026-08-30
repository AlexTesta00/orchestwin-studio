"""Persist ordered append-only workflow events.

Revision ID: 0025_workflow_events
Revises: 0024_workflow_runs_checkpoints
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_workflow_events"
down_revision: str | None = "0024_workflow_runs_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVENTS = "workflow_events"
_FUNCTION = "reject_workflow_event_mutation"
_TRIGGER = "trg_workflow_events_immutable"
_EVENT_TYPES = (
    "'workflow.run.started', "
    "'workflow.stage.changed', "
    "'workflow.waiting_for_human', "
    "'workflow.paused', "
    "'workflow.resumed', "
    "'workflow.cancelled', "
    "'workflow.failed', "
    "'workflow.completed', "
    "'workflow.approved', "
    "'workflow.checkpoint.created', "
    "'budget.warning', "
    "'budget.exhausted'"
)


def upgrade() -> None:
    """Create owner-scoped, replayable, append-only workflow events."""
    op.create_table(
        _EVENTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_events"),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_workflow_events_run_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_workflow_events_sequence",
        ),
        sa.UniqueConstraint("run_id", "id", name="uq_workflow_events_run_id"),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_workflow_events_sequence",
        ),
        sa.CheckConstraint(
            f"event_type IN ({_EVENT_TYPES})",
            name="ck_workflow_events_event_type",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_workflow_events_payload_hash",
        ),
        sa.CheckConstraint(
            "char_length(payload_json) > 0",
            name="ck_workflow_events_payload",
        ),
    )
    op.create_index(
        "ix_workflow_events_run_sequence",
        _EVENTS,
        ["run_id", "sequence_number"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_events_project_occurred",
        _EVENTS,
        ["project_id", "occurred_at"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'workflow events are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_EVENTS}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )


def downgrade() -> None:
    """Remove ordered workflow events after dropping the mutation guard."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_EVENTS};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_workflow_events_project_occurred", table_name=_EVENTS)
    op.drop_index("ix_workflow_events_run_sequence", table_name=_EVENTS)
    op.drop_table(_EVENTS)
