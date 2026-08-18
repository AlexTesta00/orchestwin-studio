"""Create rotating refresh-token sessions.

Revision ID: 0003_auth_sessions
Revises: 0002_identity_users
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_auth_sessions"
down_revision: str | Sequence[str] | None = "0002_identity_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the refresh-session table."""
    op.create_table(
        "auth_sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "token_family_id",
            sa.Uuid(),
            nullable=False,
        ),
        sa.Column(
            "refresh_token_digest",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "rotated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "replaced_by_session_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "revocation_reason",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(refresh_token_digest) = 64",
            name=("ck_auth_sessions_refresh_token_digest_length"),
        ),
        sa.CheckConstraint(
            "("
            "rotated_at IS NULL "
            "AND replaced_by_session_id IS NULL"
            ") OR ("
            "rotated_at IS NOT NULL "
            "AND replaced_by_session_id IS NOT NULL"
            ")",
            name=("ck_auth_sessions_rotation_state_consistent"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=("ck_auth_sessions_expires_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_session_id"],
            ["auth_sessions.id"],
            name=("fk_auth_sessions_replaced_by_session_id_auth_sessions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_auth_sessions",
        ),
        sa.UniqueConstraint(
            "refresh_token_digest",
            name=("uq_auth_sessions_refresh_token_digest"),
        ),
    )
    op.create_index(
        "ix_auth_sessions_token_family_id",
        "auth_sessions",
        ["token_family_id"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_user_id",
        "auth_sessions",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove the refresh-session table."""
    op.drop_index(
        "ix_auth_sessions_user_id",
        table_name="auth_sessions",
    )
    op.drop_index(
        "ix_auth_sessions_token_family_id",
        table_name="auth_sessions",
    )
    op.drop_table("auth_sessions")
