"""Persist immutable versioned User Modeling snapshots.

Revision ID: 0009_user_modeling_snapshots
Revises: 0008_versioned_team_proposals
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_user_modeling_snapshots"
down_revision: str | None = "0008_versioned_team_proposals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IMMUTABILITY_FUNCTION = "reject_user_modeling_version_mutation"

_PERSONA_TABLE = "persona_profile_versions"
_TWIN_TABLE = "user_twin_profile_versions"
_SNAPSHOT_TABLE = "user_modeling_snapshot_versions"

_VERSION_TABLES = (
    _PERSONA_TABLE,
    _TWIN_TABLE,
    _SNAPSHOT_TABLE,
)


def upgrade() -> None:
    """Create immutable User Modeling version tables."""
    _create_persona_profile_versions()
    _create_user_twin_profile_versions()
    _create_user_modeling_snapshot_versions()
    _create_immutability_guards()


def downgrade() -> None:
    """Remove User Modeling version storage."""
    _drop_immutability_guards()

    op.drop_table(_SNAPSHOT_TABLE)
    op.drop_table(_TWIN_TABLE)
    op.drop_table(_PERSONA_TABLE)


def _create_persona_profile_versions() -> None:
    """Create immutable persona and proto-persona history."""
    op.create_table(
        _PERSONA_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "persona_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "based_on_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "profile_schema_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "profile_source",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "profile_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "confirmation_status",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "rejection_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=("pk_persona_profile_versions"),
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_persona_profile_versions_project"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
                "persona_id",
                "based_on_version_number",
            ],
            [
                "persona_profile_versions.project_id",
                "persona_profile_versions.persona_id",
                "persona_profile_versions.version_number",
            ],
            name=("fk_persona_profile_versions_previous"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "persona_id",
            "version_number",
            name=("uq_persona_profile_versions_project_persona_version"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=("ck_persona_profile_versions_positive_version"),
        ),
        sa.CheckConstraint(
            (
                "("
                "version_number = 1 "
                "AND based_on_version_number IS NULL"
                ") OR ("
                "version_number > 1 "
                "AND based_on_version_number "
                "= version_number - 1"
                ")"
            ),
            name=("ck_persona_profile_versions_linear_lineage"),
        ),
        sa.CheckConstraint(
            "profile_schema_version > 0",
            name=("ck_persona_profile_versions_positive_schema"),
        ),
        sa.CheckConstraint(
            ("profile_source IN ('OWNER_PROVIDED', 'SYSTEM_PROPOSED')"),
            name=("ck_persona_profile_versions_source"),
        ),
        sa.CheckConstraint(
            ("profile_kind IN ('PERSONA', 'PROTO_PERSONA')"),
            name=("ck_persona_profile_versions_kind"),
        ),
        sa.CheckConstraint(
            ("confirmation_status IN ('PENDING_CONFIRMATION', 'CONFIRMED', 'REJECTED')"),
            name=("ck_persona_profile_versions_confirmation"),
        ),
        sa.CheckConstraint(
            (
                "("
                "profile_source = 'OWNER_PROVIDED' "
                "AND profile_kind = 'PERSONA' "
                "AND confirmation_status = 'CONFIRMED' "
                "AND rejection_reason IS NULL"
                ") OR ("
                "profile_source = 'SYSTEM_PROPOSED' "
                "AND profile_kind = 'PROTO_PERSONA'"
                ")"
            ),
            name=("ck_persona_profile_versions_source_kind"),
        ),
        sa.CheckConstraint(
            (
                "("
                "confirmation_status = 'REJECTED' "
                "AND rejection_reason IS NOT NULL"
                ") OR ("
                "confirmation_status <> 'REJECTED' "
                "AND rejection_reason IS NULL"
                ")"
            ),
            name=("ck_persona_profile_versions_rejection_reason"),
        ),
        sa.CheckConstraint(
            ("content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_persona_profile_versions_hash"),
        ),
    )


def _create_user_twin_profile_versions() -> None:
    """Create immutable User Twin history."""
    op.create_table(
        _TWIN_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "twin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "based_on_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "profile_schema_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "persona_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "persona_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "validation_status",
            sa.String(length=40),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "profile_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=("pk_user_twin_profile_versions"),
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_user_twin_profile_versions_project"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
                "persona_id",
                "persona_version_number",
            ],
            [
                "persona_profile_versions.project_id",
                "persona_profile_versions.persona_id",
                "persona_profile_versions.version_number",
            ],
            name=("fk_user_twin_profile_versions_persona"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
                "twin_id",
                "based_on_version_number",
            ],
            [
                "user_twin_profile_versions.project_id",
                "user_twin_profile_versions.twin_id",
                "user_twin_profile_versions.version_number",
            ],
            name=("fk_user_twin_profile_versions_previous"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "twin_id",
            "version_number",
            name=("uq_user_twin_profile_versions_project_twin_version"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=("ck_user_twin_profile_versions_positive_version"),
        ),
        sa.CheckConstraint(
            (
                "("
                "version_number = 1 "
                "AND based_on_version_number IS NULL"
                ") OR ("
                "version_number > 1 "
                "AND based_on_version_number "
                "= version_number - 1"
                ")"
            ),
            name=("ck_user_twin_profile_versions_linear_lineage"),
        ),
        sa.CheckConstraint(
            "profile_schema_version > 0",
            name=("ck_user_twin_profile_versions_positive_schema"),
        ),
        sa.CheckConstraint(
            "persona_version_number > 0",
            name=("ck_user_twin_profile_versions_positive_persona_version"),
        ),
        sa.CheckConstraint(
            (
                "validation_status IN ("
                "'PROTO_UT', "
                "'PROJECT_GROUNDED_UT', "
                "'OWNER_APPROVED_UT', "
                "'EMPIRICALLY_GROUNDED_UT', "
                "'EMPIRICALLY_VALIDATED_UT'"
                ")"
            ),
            name=("ck_user_twin_profile_versions_validation_status"),
        ),
        sa.CheckConstraint(
            ("content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_twin_profile_versions_hash"),
        ),
    )


def _create_user_modeling_snapshot_versions() -> None:
    """Create immutable complete User Modeling snapshots."""
    op.create_table(
        _SNAPSHOT_TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "based_on_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "snapshot_schema_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "brief_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "brief_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "brief_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "team_proposal_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "team_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "team_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "catalog_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "catalog_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "persona_count",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "twin_count",
            sa.SmallInteger(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=("pk_user_modeling_snapshot_versions"),
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_user_modeling_snapshot_versions_project"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "brief_version_id",
            ],
            [
                "project_brief_versions.id",
            ],
            name=("fk_user_modeling_snapshot_versions_brief"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "team_proposal_id",
            ],
            [
                "team_proposals.id",
            ],
            name=("fk_user_modeling_snapshot_versions_team"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
                "based_on_version_number",
            ],
            [
                "user_modeling_snapshot_versions.project_id",
                "user_modeling_snapshot_versions.version_number",
            ],
            name=("fk_user_modeling_snapshot_versions_previous"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name=("uq_user_modeling_snapshot_versions_project_version"),
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name=("ck_user_modeling_snapshot_versions_positive_version"),
        ),
        sa.CheckConstraint(
            (
                "("
                "version_number = 1 "
                "AND based_on_version_number IS NULL"
                ") OR ("
                "version_number > 1 "
                "AND based_on_version_number "
                "= version_number - 1"
                ")"
            ),
            name=("ck_user_modeling_snapshot_versions_linear_lineage"),
        ),
        sa.CheckConstraint(
            "snapshot_schema_version > 0",
            name=("ck_user_modeling_snapshot_versions_positive_schema"),
        ),
        sa.CheckConstraint(
            "brief_version_number > 0",
            name=("ck_user_modeling_snapshot_versions_positive_brief_version"),
        ),
        sa.CheckConstraint(
            "team_version_number > 0",
            name=("ck_user_modeling_snapshot_versions_positive_team_version"),
        ),
        sa.CheckConstraint(
            "catalog_version > 0",
            name=("ck_user_modeling_snapshot_versions_positive_catalog_version"),
        ),
        sa.CheckConstraint(
            ("persona_count BETWEEN 1 AND 4"),
            name=("ck_user_modeling_snapshot_versions_persona_count"),
        ),
        sa.CheckConstraint(
            ("twin_count BETWEEN 1 AND 4"),
            name=("ck_user_modeling_snapshot_versions_twin_count"),
        ),
        sa.CheckConstraint(
            "persona_count = twin_count",
            name=("ck_user_modeling_snapshot_versions_aligned_counts"),
        ),
        sa.CheckConstraint(
            ("brief_content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_modeling_snapshot_versions_brief_hash"),
        ),
        sa.CheckConstraint(
            ("team_content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_modeling_snapshot_versions_team_hash"),
        ),
        sa.CheckConstraint(
            ("catalog_content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_modeling_snapshot_versions_catalog_hash"),
        ),
        sa.CheckConstraint(
            ("content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_modeling_snapshot_versions_hash"),
        ),
    )


def _create_immutability_guards() -> None:
    """Reject row mutation for every versioned User Modeling artifact."""
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'User Modeling version rows are immutable';
            END;
            $$;
            """
        )
    )

    for table_name in _VERSION_TABLES:
        trigger_name = f"trg_{table_name}_immutable"

        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {trigger_name}
                BEFORE UPDATE OR DELETE
                ON {table_name}
                FOR EACH ROW
                EXECUTE FUNCTION
                    {_IMMUTABILITY_FUNCTION}();
                """
            )
        )


def _drop_immutability_guards() -> None:
    """Remove mutation guards before dropping their tables."""
    for table_name in reversed(_VERSION_TABLES):
        trigger_name = f"trg_{table_name}_immutable"

        op.execute(
            sa.text(
                f"""
                DROP TRIGGER IF EXISTS
                    {trigger_name}
                ON {table_name};
                """
            )
        )

    op.execute(
        sa.text(
            f"""
            DROP FUNCTION IF EXISTS
                {_IMMUTABILITY_FUNCTION}();
            """
        )
    )
