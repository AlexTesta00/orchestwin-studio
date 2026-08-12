"""SQLAlchemy records for immutable versioned team proposals."""

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
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import (
    JSONB,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)

from orchestwin.persistence.orm import (
    OrmBase,
)


class TeamProposalVersionRecord(OrmBase):
    """Persisted immutable agent-team proposal snapshot."""

    __tablename__ = "team_proposals"
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
            "revision_kind IN ('PROPOSER_GENERATED', 'OWNER_EDITED')",
            name="revision_kind_valid",
        ),
        CheckConstraint(
            "("
            "revision_kind = 'PROPOSER_GENERATED' "
            "AND based_on_version_number IS NULL"
            ") OR ("
            "revision_kind = 'OWNER_EDITED' "
            "AND based_on_version_number IS NOT NULL "
            "AND based_on_version_number "
            "< version_number"
            ")",
            name="revision_lineage_consistent",
        ),
        CheckConstraint(
            "brief_version_number >= 1",
            name="brief_version_positive",
        ),
        CheckConstraint(
            "char_length(brief_content_hash) = 64",
            name="brief_content_hash_length",
        ),
        CheckConstraint(
            "catalog_version >= 1",
            name="catalog_version_positive",
        ),
        CheckConstraint(
            "char_length(catalog_content_hash) = 64",
            name="catalog_content_hash_length",
        ),
        CheckConstraint(
            "char_length(constraints_content_hash) = 64",
            name="constraints_content_hash_length",
        ),
        CheckConstraint(
            "provider_kind IN ('FAKE_DETERMINISTIC', 'MODEL_ADAPTER')",
            name="provider_kind_valid",
        ),
        CheckConstraint(
            "char_length(btrim(provider_id)) BETWEEN 1 AND 128",
            name="provider_id_length",
        ),
        CheckConstraint(
            "provider_version >= 1",
            name="provider_version_positive",
        ),
        CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name="content_object",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="content_hash_length",
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
            name=("fk_team_proposals_project_brief_version"),
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "project_id",
                "based_on_version_number",
            ],
            [
                "team_proposals.project_id",
                "team_proposals.version_number",
            ],
            name=("fk_team_proposals_based_on_version"),
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "project_id",
            "version_number",
            name=("uq_team_proposals_project_id_version_number"),
        ),
        Index(
            "ix_team_proposals_project_id",
            "project_id",
        ),
        Index(
            "ix_team_proposals_brief_version",
            "project_id",
            "brief_version_number",
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
    revision_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    based_on_version_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    brief_version_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey(
            "project_brief_versions.id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    brief_version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    brief_content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    catalog_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    catalog_content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    constraints_content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    provider_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    provider_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )
    provider_version: Mapped[int] = mapped_column(
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
    )
