"""Persist final-review versions and enable Gate 8 final output approval.

Revision ID: 0027_final_review_gate
Revises: 0026_synthetic_evaluations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027_final_review_gate"
down_revision: str | None = "0026_synthetic_evaluations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "final_reviews"
_GATE_TABLE = "human_gates"
_EVENT_TABLE = "human_gate_events"
_GATE_CONSTRAINT = "ck_human_gates_gate_type_valid"
_EVENT_CONSTRAINT = "ck_human_gate_events_gate_type_valid"
_TRIGGER = "trg_final_reviews_immutable"
_FUNCTION = "reject_final_review_mutation"
_PREVIOUS_GATE_TYPES = (
    "PROJECT_BRIEF",
    "AGENT_TEAM",
    "USER_MODELING",
    "REQUIREMENTS",
    "DESIGN",
    "ARCHITECTURE",
    "HIGH_IMPACT_OPERATION",
)
_FINAL_GATE_TYPES = (*_PREVIOUS_GATE_TYPES, "FINAL_OUTPUT")


def upgrade() -> None:
    """Create append-only final reviews and enable Gate 8."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("parent_review_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workflow_state_version", sa.Integer(), nullable=False),
        sa.Column("ready_for_gate8", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_snapshot_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_final_reviews"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_final_reviews_workflow_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_review_id"],
            ["final_reviews.id"],
            name="fk_final_reviews_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workflow_run_id",
            "version_number",
            name="uq_final_reviews_run_version",
        ),
        sa.UniqueConstraint(
            "workflow_run_id",
            "content_hash",
            name="uq_final_reviews_run_hash",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_final_reviews_version",
        ),
        sa.CheckConstraint(
            "workflow_state_version >= 1",
            name="ck_final_reviews_workflow_state",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_final_reviews_content_hash",
        ),
        sa.CheckConstraint(
            "char_length(review_snapshot_json) > 0",
            name="ck_final_reviews_snapshot",
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND parent_review_id IS NULL) OR "
            "(version_number > 1 AND parent_review_id IS NOT NULL)",
            name="ck_final_reviews_parent",
        ),
    )
    op.create_index(
        "ix_final_reviews_project_created",
        _TABLE,
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_final_reviews_run_version",
        _TABLE,
        ["workflow_run_id", "version_number"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'final reviews are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )
    _replace_gate_type_constraints(_FINAL_GATE_TYPES)


def downgrade() -> None:
    """Remove Gate 8 persistence while retaining Gates 1 through 7."""
    _replace_gate_type_constraints(_PREVIOUS_GATE_TYPES)
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_final_reviews_run_version", table_name=_TABLE)
    op.drop_index("ix_final_reviews_project_created", table_name=_TABLE)
    op.drop_table(_TABLE)


def _replace_gate_type_constraints(gate_types: tuple[str, ...]) -> None:
    op.drop_constraint(_EVENT_CONSTRAINT, _EVENT_TABLE, type_="check")
    op.drop_constraint(_GATE_CONSTRAINT, _GATE_TABLE, type_="check")
    values = ", ".join(f"'{gate_type}'" for gate_type in gate_types)
    expression = f"gate_type IN ({values})"
    op.create_check_constraint(_GATE_CONSTRAINT, _GATE_TABLE, expression)
    op.create_check_constraint(_EVENT_CONSTRAINT, _EVENT_TABLE, expression)
