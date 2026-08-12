"""Create immutable versioned agent-team proposals.

Revision ID: 0008_versioned_team_proposals
Revises: 0007_project_brief_human_gates
Create Date: 2026-08-12
"""

from collections.abc import (
    Sequence,
)

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import (
    postgresql,
)

revision: str = "0008_versioned_team_proposals"
down_revision: str | Sequence[str] | None = "0007_project_brief_human_gates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable versioned team-proposal snapshots."""
    op.create_table(
        "team_proposals",
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
            "revision_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "based_on_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "brief_version_id",
            sa.Uuid(),
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
            "constraints_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "provider_kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "provider_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "provider_version",
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
            nullable=False,
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=("ck_team_proposals_version_number_positive"),
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name=("ck_team_proposals_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "revision_kind IN ('PROPOSER_GENERATED', 'OWNER_EDITED')",
            name=("ck_team_proposals_revision_kind_valid"),
        ),
        sa.CheckConstraint(
            "("
            "revision_kind = 'PROPOSER_GENERATED' "
            "AND based_on_version_number IS NULL"
            ") OR ("
            "revision_kind = 'OWNER_EDITED' "
            "AND based_on_version_number IS NOT NULL "
            "AND based_on_version_number "
            "< version_number"
            ")",
            name=("ck_team_proposals_revision_lineage_consistent"),
        ),
        sa.CheckConstraint(
            "brief_version_number >= 1",
            name=("ck_team_proposals_brief_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(brief_content_hash) = 64",
            name=("ck_team_proposals_brief_content_hash_length"),
        ),
        sa.CheckConstraint(
            "catalog_version >= 1",
            name=("ck_team_proposals_catalog_version_positive"),
        ),
        sa.CheckConstraint(
            "char_length(catalog_content_hash) = 64",
            name=("ck_team_proposals_catalog_content_hash_length"),
        ),
        sa.CheckConstraint(
            "char_length(constraints_content_hash) = 64",
            name=("ck_team_proposals_constraints_content_hash_length"),
        ),
        sa.CheckConstraint(
            "provider_kind IN ('FAKE_DETERMINISTIC', 'MODEL_ADAPTER')",
            name=("ck_team_proposals_provider_kind_valid"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(provider_id)) BETWEEN 1 AND 128",
            name=("ck_team_proposals_provider_id_length"),
        ),
        sa.CheckConstraint(
            "provider_version >= 1",
            name=("ck_team_proposals_provider_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(content) = 'object'",
            name=("ck_team_proposals_content_object"),
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name=("ck_team_proposals_content_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            [
                "brief_version_id",
            ],
            [
                "project_brief_versions.id",
            ],
            name=("fk_team_proposals_brief_version_id"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "created_by_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_team_proposals_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
            ],
            [
                "projects.id",
            ],
            name=("fk_team_proposals_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_team_proposals",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name=("uq_team_proposals_project_id_version_number"),
        ),
    )
    op.create_index(
        "ix_team_proposals_project_id",
        "team_proposals",
        [
            "project_id",
        ],
        unique=False,
    )
    op.create_index(
        "ix_team_proposals_brief_version",
        "team_proposals",
        [
            "project_id",
            "brief_version_number",
        ],
        unique=False,
    )

    op.execute(
        """
        CREATE FUNCTION reject_team_proposal_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Team proposal versions are immutable';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER
            trg_team_proposals_immutable
        BEFORE UPDATE OR DELETE
        ON team_proposals
        FOR EACH ROW
        EXECUTE FUNCTION
            reject_team_proposal_mutation();
        """
    )


def downgrade() -> None:
    """Remove immutable versioned team proposals."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS
            trg_team_proposals_immutable
        ON team_proposals;
        """
    )
    op.execute(
        """
        DROP FUNCTION IF EXISTS
            reject_team_proposal_mutation();
        """
    )

    op.drop_index(
        "ix_team_proposals_brief_version",
        table_name="team_proposals",
    )
    op.drop_index(
        "ix_team_proposals_project_id",
        table_name="team_proposals",
    )
    op.drop_table("team_proposals")
