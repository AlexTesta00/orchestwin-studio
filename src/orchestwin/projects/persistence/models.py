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
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
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


class ProjectBriefVersionRecord(OrmBase):
    """Immutable Project Brief snapshot."""

    __tablename__ = "project_brief_versions"
    __table_args__ = (
        CheckConstraint(
            "version_number >= 1",
            name="version_number_positive",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="schema_version_positive",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="content_hash_length",
        ),
        UniqueConstraint(
            "project_id",
            "version_number",
            name=("uq_project_brief_versions_project_id_version_number"),
        ),
        Index(
            "ix_project_brief_versions_project_id",
            "project_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "projects.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    content: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
