"""Persist immutable Web execution attempts and normalized reports.

Revision ID: 0021_web_execution_attempts
Revises: 0020_web_source_revisions
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021_web_execution_attempts"
down_revision: str | None = "0020_web_source_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "web_execution_attempts"
_TRIGGER = "trg_web_execution_attempts_immutable"
_FUNCTION = "reject_web_execution_attempt_mutation"


def upgrade() -> None:
    """Create append-only execution-attempt storage with exact lineage."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("previous_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision_version", sa.Integer(), nullable=False),
        sa.Column("source_revision_content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("profile_validation_content_hash", sa.String(length=64), nullable=False),
        sa.Column("execution_plan_content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_content_hash", sa.String(length=64), nullable=False),
        sa.Column("runner_image_digest", sa.String(length=64), nullable=False),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column("report_status", sa.String(length=16), nullable=False),
        sa.Column(
            "attempt_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_web_execution_attempts"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_web_execution_attempts_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_web_execution_attempts_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_revision_id"],
            ["web_source_revisions.project_id", "web_source_revisions.id"],
            name="fk_web_execution_attempts_source_revision",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "previous_attempt_id"],
            [f"{_TABLE}.project_id", f"{_TABLE}.id"],
            name="fk_web_execution_attempts_previous",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "id",
            name="uq_web_execution_attempts_project_id",
        ),
        sa.UniqueConstraint(
            "project_id",
            "attempt_number",
            name="uq_web_execution_attempts_project_number",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_web_execution_attempts_project_hash",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_web_execution_attempts_positive_attempt",
        ),
        sa.CheckConstraint(
            "(attempt_number = 1 AND previous_attempt_id IS NULL) OR "
            "(attempt_number > 1 AND previous_attempt_id IS NOT NULL)",
            name="ck_web_execution_attempts_linear_lineage",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_content_hash",
        ),
        sa.CheckConstraint(
            "source_revision_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_source_revision_hash",
        ),
        sa.CheckConstraint(
            "source_tree_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_source_tree_hash",
        ),
        sa.CheckConstraint(
            "profile_validation_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_profile_validation_hash",
        ),
        sa.CheckConstraint(
            "execution_plan_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_execution_plan_hash",
        ),
        sa.CheckConstraint(
            "policy_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_policy_hash",
        ),
        sa.CheckConstraint(
            "runner_image_digest ~ '^[0-9a-f]{64}$'",
            name="ck_web_execution_attempts_runner_hash",
        ),
        sa.CheckConstraint(
            "trigger IN ('INITIAL', 'PROFILE_VALIDATION', 'REPAIR_RERUN', 'MANUAL_RERUN')",
            name="ck_web_execution_attempts_trigger",
        ),
        sa.CheckConstraint(
            "report_status IN ('PASSED', 'FAILED', 'INCOMPLETE')",
            name="ck_web_execution_attempts_report_status",
        ),
    )
    op.create_index(
        "ix_web_execution_attempts_project_number",
        _TABLE,
        ["project_id", "attempt_number"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Web execution attempts are immutable';
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


def downgrade() -> None:
    """Remove Web execution-attempt persistence."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_web_execution_attempts_project_number", table_name=_TABLE)
    op.drop_table(_TABLE)
