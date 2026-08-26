"""Persist Gate 7 high-impact operation requests and human-gate type.

Revision ID: 0019_high_impact_gate_type
Revises: 0018_sandbox_runs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_high_impact_gate_type"
down_revision: str | None = "0018_sandbox_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "high_impact_operation_versions"
_GATE_TABLE = "human_gates"
_EVENT_TABLE = "human_gate_events"
_GATE_CONSTRAINT = "ck_human_gates_gate_type_valid"
_EVENT_CONSTRAINT = "ck_human_gate_events_gate_type_valid"
_TRIGGER = "trg_high_impact_operation_versions_immutable"
_FUNCTION = "reject_high_impact_operation_version_mutation"
_PREVIOUS_GATE_TYPES = (
    "PROJECT_BRIEF",
    "AGENT_TEAM",
    "USER_MODELING",
    "REQUIREMENTS",
    "DESIGN",
    "ARCHITECTURE",
)
_GATE_SEVEN_TYPES = (*_PREVIOUS_GATE_TYPES, "HIGH_IMPACT_OPERATION")


def upgrade() -> None:
    """Create append-only Gate 7 requests and enable their human-gate type."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_content_hash", sa.String(length=64), nullable=False),
        sa.Column("classification", sa.String(length=40), nullable=False),
        sa.Column(
            "request_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "classification_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_high_impact_operation_versions"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_high_impact_operation_versions_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_high_impact_operation_versions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "based_on_version_number"],
            [f"{_TABLE}.project_id", f"{_TABLE}.version_number"],
            name="fk_high_impact_operation_versions_previous",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name="uq_high_impact_operation_versions_project_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_high_impact_operation_versions_project_hash",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_high_impact_operation_versions_positive_version",
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND based_on_version_number IS NULL) OR "
            "(version_number > 1 AND based_on_version_number = version_number - 1)",
            name="ck_high_impact_operation_versions_linear_lineage",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_high_impact_operation_versions_content_hash",
        ),
        sa.CheckConstraint(
            "policy_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_high_impact_operation_versions_policy_hash",
        ),
        sa.CheckConstraint(
            "classification IN ("
            "'ALLOWED_WITHOUT_APPROVAL', "
            "'REQUIRES_OWNER_APPROVAL', "
            "'FORBIDDEN_BY_POLICY'"
            ")",
            name="ck_high_impact_operation_versions_classification",
        ),
    )
    op.create_index(
        "ix_high_impact_operation_versions_project_version",
        _TABLE,
        ["project_id", "version_number"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'high-impact operation versions are immutable';
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
    _replace_gate_type_constraints(_GATE_SEVEN_TYPES)


def downgrade() -> None:
    """Remove Gate 7 persistence while retaining Gates 1 through 6."""
    _replace_gate_type_constraints(_PREVIOUS_GATE_TYPES)
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index(
        "ix_high_impact_operation_versions_project_version",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)


def _replace_gate_type_constraints(gate_types: tuple[str, ...]) -> None:
    op.drop_constraint(_EVENT_CONSTRAINT, _EVENT_TABLE, type_="check")
    op.drop_constraint(_GATE_CONSTRAINT, _GATE_TABLE, type_="check")
    values = ", ".join(f"'{gate_type}'" for gate_type in gate_types)
    expression = f"gate_type IN ({values})"
    op.create_check_constraint(_GATE_CONSTRAINT, _GATE_TABLE, expression)
    op.create_check_constraint(_EVENT_CONSTRAINT, _EVENT_TABLE, expression)
