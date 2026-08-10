"""SQLAlchemy records for the Project Definition context."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.domain import ProjectMode


class ProjectRecord(OrmBase):
    """Persisted owner-scoped project aggregate."""

    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 120",
            name="display_name_length",
        ),
        CheckConstraint(
            "mode IN ('GREENFIELD_GENERATION', 'BROWNFIELD_ASSESSMENT')",
            name="mode_valid",
        ),
        CheckConstraint(
            "current_brief_version >= 0",
            name="current_brief_version_non_negative",
        ),
        Index(
            "ix_projects_owner_user_id",
            "owner_user_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    display_name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )
    mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    current_brief_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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

    @property
    def project_mode(self) -> ProjectMode:
        """Return the validated project mode."""
        return ProjectMode(self.mode)
