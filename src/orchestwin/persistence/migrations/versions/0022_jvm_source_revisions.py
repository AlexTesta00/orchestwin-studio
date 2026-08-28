"""Persist immutable JVM source revisions and provenance snapshots.

Revision ID: 0022_jvm_source_revisions
Revises: 0021_web_execution_attempts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022_jvm_source_revisions"
down_revision: str | None = "0021_web_execution_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "jvm_source_revisions"
_TRIGGER = "trg_jvm_source_revisions_immutable"
_FUNCTION = "reject_jvm_source_revision_mutation"


def upgrade() -> None:
    """Create append-only source revision storage with linear project lineage."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("based_on_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_tree_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("target", sa.String(length=32), nullable=False),
        sa.Column("layout", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("related_failure_signature", sa.String(length=64), nullable=True),
        sa.Column(
            "revision_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jvm_source_revisions"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_jvm_source_revisions_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_jvm_source_revisions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "based_on_revision_id"],
            [f"{_TABLE}.project_id", f"{_TABLE}.id"],
            name="fk_jvm_source_revisions_predecessor_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "based_on_version_number"],
            [f"{_TABLE}.project_id", f"{_TABLE}.version_number"],
            name="fk_jvm_source_revisions_predecessor_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "id",
            name="uq_jvm_source_revisions_project_id",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name="uq_jvm_source_revisions_project_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_jvm_source_revisions_project_hash",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_jvm_source_revisions_positive_version",
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND based_on_revision_id IS NULL "
            "AND based_on_version_number IS NULL) OR "
            "(version_number > 1 AND based_on_revision_id IS NOT NULL "
            "AND based_on_version_number = version_number - 1)",
            name="ck_jvm_source_revisions_linear_lineage",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_jvm_source_revisions_content_hash",
        ),
        sa.CheckConstraint(
            "source_tree_hash ~ '^[0-9a-f]{64}$'",
            name="ck_jvm_source_revisions_source_tree_hash",
        ),
        sa.CheckConstraint(
            "validation_scope_hash ~ '^[0-9a-f]{64}$'",
            name="ck_jvm_source_revisions_validation_scope_hash",
        ),
        sa.CheckConstraint(
            "related_failure_signature IS NULL OR related_failure_signature ~ '^[0-9a-f]{64}$'",
            name="ck_jvm_source_revisions_failure_signature",
        ),
        sa.CheckConstraint(
            "target IN ('JVM_JAVA', 'JVM_KOTLIN', 'JVM_SCALA')",
            name="ck_jvm_source_revisions_target",
        ),
        sa.CheckConstraint(
            "layout IN ('SINGLE_MODULE')",
            name="ck_jvm_source_revisions_layout",
        ),
        sa.CheckConstraint(
            "origin IN ('GENERATED_PLAN', 'IMPORTED_BROWNFIELD', "
            "'REPAIR_CHANGE_SET', 'DETERMINISTIC_FIXTURE')",
            name="ck_jvm_source_revisions_origin",
        ),
    )
    op.create_index(
        "ix_jvm_source_revisions_project_version",
        _TABLE,
        ["project_id", "version_number"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'JVM source revisions are immutable';
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
    """Remove JVM source revision persistence."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_jvm_source_revisions_project_version", table_name=_TABLE)
    op.drop_table(_TABLE)
