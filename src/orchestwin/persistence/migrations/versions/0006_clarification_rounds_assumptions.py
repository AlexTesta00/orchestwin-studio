"""Create clarification rounds and Project Brief assumptions.

Revision ID: 0006_clarification_rounds_assumptions
Revises: 0005_project_brief_versions
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_clarification_rounds_assumptions"
down_revision: str | Sequence[str] | None = "0005_project_brief_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create persisted clarification and assumption state."""
    op.create_table(
        "clarification_rounds",
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
            "source_brief_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "round_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "catalog_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "questions",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'OPEN'"),
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
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "answered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "resulting_brief_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "source_brief_version_number >= 1",
            name=("ck_clarification_rounds_source_brief_version_positive"),
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 3",
            name=("ck_clarification_rounds_round_number_valid"),
        ),
        sa.CheckConstraint(
            "catalog_version >= 1",
            name=("ck_clarification_rounds_catalog_version_positive"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(questions) = 'array' AND jsonb_array_length(questions) > 0",
            name=("ck_clarification_rounds_questions_non_empty_array"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'ANSWERED')",
            name=("ck_clarification_rounds_status_valid"),
        ),
        sa.CheckConstraint(
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
            name=("ck_clarification_rounds_state_consistent"),
        ),
        sa.ForeignKeyConstraint(
            [
                "created_by_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_clarification_rounds_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
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
        sa.ForeignKeyConstraint(
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
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_clarification_rounds",
        ),
        sa.UniqueConstraint(
            "project_id",
            "round_number",
            name=("uq_clarification_rounds_project_id_round_number"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "source_brief_version_number",
            name=("uq_clarification_rounds_project_id_source_brief_version"),
        ),
    )
    op.create_index(
        "ix_clarification_rounds_project_id",
        "clarification_rounds",
        [
            "project_id",
        ],
        unique=False,
    )
    op.create_index(
        "uq_clarification_rounds_open_project",
        "clarification_rounds",
        [
            "project_id",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )

    op.create_table(
        "brief_assumptions",
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
            "brief_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "field",
            sa.String(length=48),
            nullable=False,
        ),
        sa.Column(
            "statement",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'PROPOSED'"),
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
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "decision_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.CheckConstraint(
            "brief_version_number >= 1",
            name=("ck_brief_assumptions_brief_version_positive"),
        ),
        sa.CheckConstraint(
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
            name=("ck_brief_assumptions_field_valid"),
        ),
        sa.CheckConstraint(
            "source IN ('OWNER_PROVIDED', 'MODEL_PROPOSED', 'DETERMINISTIC_RULE')",
            name=("ck_brief_assumptions_source_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'ACCEPTED', 'REJECTED')",
            name=("ck_brief_assumptions_status_valid"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(statement)) BETWEEN 1 AND 2000",
            name=("ck_brief_assumptions_statement_length"),
        ),
        sa.CheckConstraint(
            "decision_reason IS NULL OR char_length(btrim(decision_reason)) BETWEEN 1 AND 2000",
            name=("ck_brief_assumptions_decision_reason_length"),
        ),
        sa.CheckConstraint(
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
            name=("ck_brief_assumptions_decision_state_consistent"),
        ),
        sa.ForeignKeyConstraint(
            [
                "created_by_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_brief_assumptions_created_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "decided_by_user_id",
            ],
            [
                "users.id",
            ],
            name=("fk_brief_assumptions_decided_by_user_id_users"),
            ondelete="RESTRICT",
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
            name=("fk_brief_assumptions_project_brief_version"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_brief_assumptions",
        ),
    )
    op.create_index(
        "ix_brief_assumptions_project_id",
        "brief_assumptions",
        [
            "project_id",
        ],
        unique=False,
    )
    op.create_index(
        "ix_brief_assumptions_status",
        "brief_assumptions",
        [
            "status",
        ],
        unique=False,
    )


def downgrade() -> None:
    """Remove clarification and assumption persistence."""
    op.drop_index(
        "ix_brief_assumptions_status",
        table_name="brief_assumptions",
    )
    op.drop_index(
        "ix_brief_assumptions_project_id",
        table_name="brief_assumptions",
    )
    op.drop_table("brief_assumptions")

    op.drop_index(
        "uq_clarification_rounds_open_project",
        table_name="clarification_rounds",
    )
    op.drop_index(
        "ix_clarification_rounds_project_id",
        table_name="clarification_rounds",
    )
    op.drop_table("clarification_rounds")
