"""Create owner-scoped projects.

Revision ID: 0004_projects
Revises: 0003_auth_sessions
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_projects"
down_revision: str | Sequence[str] | None = "0003_auth_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the owner-scoped project table."""
    op.create_table(
        "projects",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "display_name",
            sa.String(length=120),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "current_brief_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "archived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 120",
            name=("ck_projects_display_name_length"),
        ),
        sa.CheckConstraint(
            "mode IN ('GREENFIELD_GENERATION', 'BROWNFIELD_ASSESSMENT')",
            name="ck_projects_mode_valid",
        ),
        sa.CheckConstraint(
            "current_brief_version >= 0",
            name=("ck_projects_current_brief_version_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=("fk_projects_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_projects",
        ),
    )
    op.create_index(
        "ix_projects_owner_user_id",
        "projects",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the project table."""
    op.drop_index(
        "ix_projects_owner_user_id",
        table_name="projects",
    )
    op.drop_table("projects")
