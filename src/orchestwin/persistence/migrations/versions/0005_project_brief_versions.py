"""Create immutable Project Brief versions.

Revision ID: 0005_project_brief_versions
Revises: 0004_projects
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_project_brief_versions"
down_revision: str | Sequence[str] | None = "0004_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable Project Brief snapshots."""
    op.create_table(
        "project_brief_versions",
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
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=("ck_project_brief_versions_version_number_positive"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name=("ck_project_brief_versions_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name=("ck_project_brief_versions_content_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=("fk_project_brief_versions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=("fk_project_brief_versions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_project_brief_versions",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name=("uq_project_brief_versions_project_id_version_number"),
        ),
    )
    op.create_index(
        "ix_project_brief_versions_project_id",
        "project_brief_versions",
        ["project_id"],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_project_brief_version_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Project Brief versions are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER
            trg_project_brief_versions_immutable
        BEFORE UPDATE OR DELETE
        ON project_brief_versions
        FOR EACH ROW
        EXECUTE FUNCTION
            reject_project_brief_version_mutation();
        """
    )


def downgrade() -> None:
    """Remove immutable Project Brief snapshots."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_project_brief_versions_immutable
        ON project_brief_versions;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            reject_project_brief_version_mutation();
        """
    )
    op.drop_index(
        "ix_project_brief_versions_project_id",
        table_name="project_brief_versions",
    )
    op.drop_table("project_brief_versions")
