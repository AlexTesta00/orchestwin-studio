"""SQLAlchemy records for the Project Definition context."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
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


class ClarificationRoundRecord(OrmBase):
    """Persisted clarification-round snapshot."""

    __tablename__ = "clarification_rounds"
    __table_args__ = (
        CheckConstraint(
            "source_brief_version_number >= 1",
            name="source_brief_version_positive",
        ),
        CheckConstraint(
            "round_number BETWEEN 1 AND 3",
            name="round_number_valid",
        ),
        CheckConstraint(
            "catalog_version >= 1",
            name="catalog_version_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(questions) = 'array' AND jsonb_array_length(questions) > 0",
            name="questions_non_empty_array",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'ANSWERED')",
            name="status_valid",
        ),
        CheckConstraint(
            "("
            "status = 'OPEN' "
            "AND answered_at IS NULL "
            "AND resulting_brief_version_number IS NULL"
            ") OR ("
            "status = 'ANSWERED' "
            "AND answered_at IS NOT NULL "
            "AND resulting_brief_version_number IS NOT NULL "
            "AND resulting_brief_version_number "
            "> source_brief_version_number"
            ")",
            name="state_consistent",
        ),
        ForeignKeyConstraint(
            [
                "project_id",
                "source_brief_version_number",
            ],
            [
                "project_brief_versions.project_id",
                "project_brief_versions.version_number",
            ],
            name=("fk_clarification_rounds_source_brief_version"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "project_id",
                "resulting_brief_version_number",
            ],
            [
                "project_brief_versions.project_id",
                "project_brief_versions.version_number",
            ],
            name=("fk_clarification_rounds_resulting_brief_version"),
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "project_id",
            "round_number",
            name=("uq_clarification_rounds_project_id_round_number"),
        ),
        UniqueConstraint(
            "project_id",
            "source_brief_version_number",
            name=("uq_clarification_rounds_project_id_source_brief_version"),
        ),
        Index(
            "ix_clarification_rounds_project_id",
            "project_id",
        ),
        Index(
            "uq_clarification_rounds_open_project",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'OPEN'"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    source_brief_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    round_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    catalog_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    questions: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="OPEN",
        server_default="OPEN",
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
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    resulting_brief_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )


class BriefAssumptionRecord(OrmBase):
    """Persisted assumption kept separate from Project Brief content."""

    __tablename__ = "brief_assumptions"
    __table_args__ = (
        CheckConstraint(
            "brief_version_number >= 1",
            name="brief_version_positive",
        ),
        CheckConstraint(
            "field IN ("
            "'name', "
            "'description', "
            "'problem', "
            "'goals', "
            "'target_users', "
            "'domain', "
            "'technical_constraints', "
            "'temporal_constraints', "
            "'budget', "
            "'functional_requirements', "
            "'non_functional_requirements', "
            "'risks', "
            "'stakeholders', "
            "'available_artifacts', "
            "'definition_of_done'"
            ")",
            name="field_valid",
        ),
        CheckConstraint(
            "source IN ('OWNER_PROVIDED', 'MODEL_PROPOSED', 'DETERMINISTIC_RULE')",
            name="source_valid",
        ),
        CheckConstraint(
            "status IN ('PROPOSED', 'ACCEPTED', 'REJECTED')",
            name="status_valid",
        ),
        CheckConstraint(
            "char_length(btrim(statement)) BETWEEN 1 AND 2000",
            name="statement_length",
        ),
        CheckConstraint(
            "decision_reason IS NULL OR char_length(btrim(decision_reason)) BETWEEN 1 AND 2000",
            name="decision_reason_length",
        ),
        CheckConstraint(
            "("
            "status = 'PROPOSED' "
            "AND decided_by_user_id IS NULL "
            "AND decided_at IS NULL "
            "AND decision_reason IS NULL"
            ") OR ("
            "status = 'ACCEPTED' "
            "AND decided_by_user_id IS NOT NULL "
            "AND decided_at IS NOT NULL"
            ") OR ("
            "status = 'REJECTED' "
            "AND decided_by_user_id IS NOT NULL "
            "AND decided_at IS NOT NULL "
            "AND decision_reason IS NOT NULL"
            ")",
            name="decision_state_consistent",
        ),
        ForeignKeyConstraint(
            [
                "project_id",
                "brief_version_number",
            ],
            [
                "project_brief_versions.project_id",
                "project_brief_versions.version_number",
            ],
            name=("fk_brief_assumptions_project_brief_version"),
            ondelete="RESTRICT",
        ),
        Index(
            "ix_brief_assumptions_project_id",
            "project_id",
        ),
        Index(
            "ix_brief_assumptions_status",
            "status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
    )
    project_id: Mapped[UUID] = mapped_column(
        Uuid,
        nullable=False,
    )
    brief_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    field_name: Mapped[str] = mapped_column(
        "field",
        String(48),
        nullable=False,
    )
    statement: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="PROPOSED",
        server_default="PROPOSED",
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
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey(
            "users.id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    decision_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
