"""Persist immutable deterministic final export bundles.

Revision ID: 0028_export_bundles
Revises: 0027_final_review_gate
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028_export_bundles"
down_revision: str | None = "0027_final_review_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "export_bundles"
_TRIGGER = "trg_export_bundles_immutable"
_FUNCTION = "reject_export_bundle_mutation"


def upgrade() -> None:
    """Create append-only export bundle metadata."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("manifest_hash", sa.String(length=64), nullable=False),
        sa.Column("final_review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("final_review_hash", sa.String(length=64), nullable=False),
        sa.Column("final_approval_gate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("final_approval_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("archive_hash", sa.String(length=64), nullable=False),
        sa.Column("archive_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_ref", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bundle_snapshot_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_export_bundles"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_export_bundles_workflow_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("manifest_id", name="uq_export_bundles_manifest"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "archive_hash",
            name="uq_export_bundles_run_hash",
        ),
        sa.CheckConstraint(
            "manifest_hash ~ '^[0-9a-f]{64}$'",
            name="ck_export_bundles_manifest_hash",
        ),
        sa.CheckConstraint(
            "final_review_hash ~ '^[0-9a-f]{64}$'",
            name="ck_export_bundles_final_review_hash",
        ),
        sa.CheckConstraint(
            "archive_hash ~ '^[0-9a-f]{64}$'",
            name="ck_export_bundles_archive_hash",
        ),
        sa.CheckConstraint(
            "archive_size_bytes > 0",
            name="ck_export_bundles_archive_size",
        ),
        sa.CheckConstraint(
            "char_length(storage_ref) > 0",
            name="ck_export_bundles_storage_ref",
        ),
        sa.CheckConstraint(
            "char_length(bundle_snapshot_json) > 0",
            name="ck_export_bundles_snapshot",
        ),
    )
    op.create_index(
        "ix_export_bundles_project_created",
        _TABLE,
        ["project_id", "created_at"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'export bundles are immutable';
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
    """Remove immutable export bundle metadata."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_export_bundles_project_created", table_name=_TABLE)
    op.drop_table(_TABLE)
