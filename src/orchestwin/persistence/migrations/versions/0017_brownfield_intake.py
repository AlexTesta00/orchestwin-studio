"""Persist immutable brownfield source-intake versions.

Revision ID: 0017_brownfield_intake
Revises: 0016_architecture_gate_type
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_brownfield_intake"
down_revision: str | None = "0016_architecture_gate_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "brownfield_intake_versions"
_TRIGGER = "trg_brownfield_intake_versions_immutable"
_FUNCTION = "reject_brownfield_intake_version_mutation"


def upgrade() -> None:
    """Create append-only owner-scoped brownfield intake storage."""
    op.create_table(
        _TABLE,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("archive_sha256", sa.String(length=64), nullable=False),
        sa.Column("archive_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("archive_storage_key", sa.Text(), nullable=False),
        sa.Column("inventory_content_hash", sa.String(length=64), nullable=False),
        sa.Column("capability_status", sa.String(length=40), nullable=False),
        sa.Column("effective_capability_status", sa.String(length=32), nullable=False),
        sa.Column("selected_profile_id", sa.String(length=128), nullable=True),
        sa.Column("selected_profile_version", sa.String(length=64), nullable=True),
        sa.Column("selected_profile_content_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "intake_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_brownfield_intake_versions"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_brownfield_intake_versions_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_brownfield_intake_versions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "based_on_version_number"],
            [f"{_TABLE}.project_id", f"{_TABLE}.version_number"],
            name="fk_brownfield_intake_versions_previous",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name="uq_brownfield_intake_versions_project_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_brownfield_intake_versions_project_hash",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_brownfield_intake_versions_positive_version",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_brownfield_intake_versions_positive_schema",
        ),
        sa.CheckConstraint(
            "archive_size_bytes >= 0",
            name="ck_brownfield_intake_versions_archive_size",
        ),
        sa.CheckConstraint(
            "(version_number = 1 AND based_on_version_number IS NULL) OR "
            "(version_number > 1 AND based_on_version_number = version_number - 1)",
            name="ck_brownfield_intake_versions_linear_lineage",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_brownfield_intake_versions_content_hash",
        ),
        sa.CheckConstraint(
            "archive_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_brownfield_intake_versions_archive_hash",
        ),
        sa.CheckConstraint(
            "inventory_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_brownfield_intake_versions_inventory_hash",
        ),
        sa.CheckConstraint(
            "selected_profile_content_hash IS NULL OR "
            "selected_profile_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_brownfield_intake_versions_selected_profile_hash",
        ),
        sa.CheckConstraint(
            "capability_status IN ("
            "'VALIDATED_LEVEL_D_SELECTED', "
            "'EXPERIMENTAL_LEVEL_D_SELECTED', "
            "'DESIGN_ONLY_LEVEL_C_SELECTED', "
            "'HUMAN_DECISION_REQUIRED', "
            "'UNSUPPORTED'"
            ")",
            name="ck_brownfield_intake_versions_capability_status",
        ),
        sa.CheckConstraint(
            "effective_capability_status IN ("
            "'VALIDATED_LEVEL_D', "
            "'EXPERIMENTAL_LEVEL_D', "
            "'DESIGN_ONLY_LEVEL_C'"
            ")",
            name="ck_brownfield_intake_versions_effective_capability",
        ),
        sa.CheckConstraint(
            "(selected_profile_id IS NULL "
            "AND selected_profile_version IS NULL "
            "AND selected_profile_content_hash IS NULL) OR "
            "(selected_profile_id IS NOT NULL "
            "AND selected_profile_version IS NOT NULL "
            "AND selected_profile_content_hash IS NOT NULL)",
            name="ck_brownfield_intake_versions_selected_profile_shape",
        ),
    )
    op.create_index(
        "ix_brownfield_intake_versions_project_version",
        _TABLE,
        ["project_id", "version_number"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'brownfield intake versions are immutable';
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
    """Remove the immutable intake store after its mutation guard."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index(
        "ix_brownfield_intake_versions_project_version",
        table_name=_TABLE,
    )
    op.drop_table(_TABLE)
