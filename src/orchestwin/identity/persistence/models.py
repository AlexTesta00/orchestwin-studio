"""SQLAlchemy records for the Identity and Access context."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase


class UserRecord(OrmBase):
    """Persisted local user account."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    email_normalized: Mapped[str] = mapped_column(
        String(320),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AuthSessionRecord(OrmBase):
    """Persisted opaque refresh-token session."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "char_length(refresh_token_digest) = 64",
            name="refresh_token_digest_length",
        ),
        CheckConstraint(
            "("
            "rotated_at IS NULL "
            "AND replaced_by_session_id IS NULL"
            ") OR ("
            "rotated_at IS NOT NULL "
            "AND replaced_by_session_id IS NOT NULL"
            ")",
            name="rotation_state_consistent",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="expires_after_creation",
        ),
        Index(
            "ix_auth_sessions_user_id",
            "user_id",
        ),
        Index(
            "ix_auth_sessions_token_family_id",
            "token_family_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    token_family_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    refresh_token_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    replaced_by_session_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "auth_sessions.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
