"""Expand Alembic revision identifier capacity.

Revision ID: 0005a_expand_alembic_version
Revises: 0005_project_brief_versions
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005a_expand_alembic_version"
down_revision: str | Sequence[str] | None = "0005_project_brief_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow descriptive Alembic revision identifiers."""
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore Alembic's default revision identifier capacity."""
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
