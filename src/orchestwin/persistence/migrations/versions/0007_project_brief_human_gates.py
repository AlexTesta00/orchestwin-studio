"""Create persistent human gates and append-only gate events.

Revision ID: 0007_project_brief_human_gates
Revises: 0006_clarification_rounds_assumptions
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_project_brief_human_gates"
down_revision: str | Sequence[str] | None = "0006_clarification_rounds_assumptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create human-gate state and immutable audit events."""
    op.create_table(
        "human_gates",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "gate_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "artifact_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "artifact_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "iteration",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_iterations",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "resume_status",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "event_sequence",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "gate_type IN ('PROJECT_BRIEF', 'AGENT_TEAM')",
            name=("ck_human_gates_gate_type_valid"),
        ),
        sa.CheckConstraint(
            "artifact_version >= 1",
            name=("ck_human_gates_artifact_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(artifact_hash) = 64",
            name=("ck_human_gates_artifact_hash_length"),
        ),
        sa.CheckConstraint(
            "max_iterations >= 1",
            name=("ck_human_gates_max_iterations_positive"),
        ),
        sa.CheckConstraint(
            "iteration BETWEEN 1 AND max_iterations",
            name=("ck_human_gates_iteration_within_limit"),
        ),
        sa.CheckConstraint(
            "event_sequence >= 0",
            name=("ck_human_gates_event_sequence_non_negative"),
        ),
        sa.CheckConstraint(
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
            name=("ck_human_gates_status_valid"),
        ),
        sa.CheckConstraint(
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
            name=("ck_human_gates_resume_state_consistent"),
        ),
        sa.ForeignKeyConstraint(
            [
                "owner_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_human_gates_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_human_gates_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_human_gates",
        ),
        sa.UniqueConstraint(
            "project_id",
            "gate_type",
            "iteration",
            name=("uq_human_gates_project_id_gate_type_iteration"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "gate_type",
            "artifact_id",
            "artifact_version",
            name=("uq_human_gates_project_gate_artifact_version"),
        ),
    )
    op.create_index(
        "ix_human_gates_project_gate_type",
        "human_gates",
        [
            "project_id",
            "gate_type",
        ],
        unique=False,
    )

    op.create_table(
        "human_gate_events",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "gate_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "gate_type",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "sequence_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "previous_status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "resulting_status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "artifact_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "artifact_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name=("ck_human_gate_events_sequence_number_positive"),
        ),
        sa.CheckConstraint(
            "gate_type IN ('PROJECT_BRIEF', 'AGENT_TEAM')",
            name=("ck_human_gate_events_gate_type_valid"),
        ),
        sa.CheckConstraint(
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
            name=("ck_human_gate_events_kind_valid"),
        ),
        sa.CheckConstraint(
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
            name=("ck_human_gate_events_previous_status_valid"),
        ),
        sa.CheckConstraint(
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
            name=("ck_human_gate_events_resulting_status_valid"),
        ),
        sa.CheckConstraint(
            "previous_status <> resulting_status",
            name=("ck_human_gate_events_status_changes"),
        ),
        sa.CheckConstraint(
            "artifact_version >= 1",
            name=("ck_human_gate_events_artifact_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(artifact_hash) = 64",
            name=("ck_human_gate_events_artifact_hash_length"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR char_length(btrim(reason)) BETWEEN 1 AND 2000",
            name=("ck_human_gate_events_reason_length"),
        ),
        sa.CheckConstraint(
            "("
            "kind = 'ARTIFACT_SUPERSEDED' "
            "AND actor_user_id IS NULL"
            ") OR ("
            "kind <> 'ARTIFACT_SUPERSEDED' "
            "AND actor_user_id IS NOT NULL"
            ")",
            name=("ck_human_gate_events_actor_state_consistent"),
        ),
        sa.CheckConstraint(
            "kind NOT IN ('REJECT', 'REQUEST_REVISION') OR reason IS NOT NULL",
            name=("ck_human_gate_events_decision_reason_required"),
        ),
        sa.ForeignKeyConstraint(
            [
                "actor_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_human_gate_events_actor_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "gate_id",
            ],
            [
                "human_gates.id",
            ],
            name=("fk_human_gate_events_gate_id_human_gates"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_human_gate_events_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_human_gate_events",
        ),
        sa.UniqueConstraint(
            "gate_id",
            "sequence_number",
            name=("uq_human_gate_events_gate_id_sequence_number"),
        ),
    )
    op.create_index(
        "ix_human_gate_events_gate_id",
        "human_gate_events",
        [
            "gate_id",
        ],
        unique=False,
    )
    op.create_index(
        "ix_human_gate_events_project_id",
        "human_gate_events",
        [
            "project_id",
        ],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_human_gate_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Human gate events are append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER
            trg_human_gate_events_append_only
        BEFORE UPDATE OR DELETE
        ON human_gate_events
        FOR EACH ROW
        EXECUTE FUNCTION
            reject_human_gate_event_mutation();
        """
    )


def downgrade() -> None:
    """Remove human gates and their append-only audit log."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_human_gate_events_append_only
        ON human_gate_events;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            reject_human_gate_event_mutation();
        """
    )

    op.drop_index(
        "ix_human_gate_events_project_id",
        table_name="human_gate_events",
    )
    op.drop_index(
        "ix_human_gate_events_gate_id",
        table_name="human_gate_events",
    )
    op.drop_table("human_gate_events")

    op.drop_index(
        "ix_human_gates_project_gate_type",
        table_name="human_gates",
    )
    op.drop_table("human_gates")
