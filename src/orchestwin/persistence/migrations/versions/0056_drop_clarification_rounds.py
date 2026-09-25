import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0056_drop_clarification_rounds"
down_revision = "0055_brief_dialogue"
branch_labels = None
depends_on = None

TABLE = "clarification_rounds"
INDEXES = ("uq_clarification_rounds_open_project", "ix_clarification_rounds_project_id")


def upgrade():
    for name in INDEXES:
        op.drop_index(name, table_name=TABLE)
    op.drop_table(TABLE)


def downgrade():
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("source_brief_version_number", sa.Integer(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("catalog_version", sa.Integer(), nullable=False),
        sa.Column("questions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resulting_brief_version_number", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "source_brief_version_number >= 1",
            name="ck_clarification_rounds_source_brief_version_positive",
        ),
        sa.CheckConstraint(
            "round_number BETWEEN 1 AND 3", name="ck_clarification_rounds_round_number_valid"
        ),
        sa.CheckConstraint(
            "catalog_version >= 1", name="ck_clarification_rounds_catalog_version_positive"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(questions) = 'array' AND jsonb_array_length(questions) > 0",
            name="ck_clarification_rounds_questions_non_empty_array",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'ANSWERED')", name="ck_clarification_rounds_status_valid"
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
            name="ck_clarification_rounds_state_consistent",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_clarification_rounds_created_by_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_brief_version_number"],
            ["project_brief_versions.project_id", "project_brief_versions.version_number"],
            name="fk_clarification_rounds_source_brief_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "resulting_brief_version_number"],
            ["project_brief_versions.project_id", "project_brief_versions.version_number"],
            name="fk_clarification_rounds_resulting_brief_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_clarification_rounds"),
        sa.UniqueConstraint(
            "project_id", "round_number", name="uq_clarification_rounds_project_id_round_number"
        ),
        sa.UniqueConstraint(
            "project_id",
            "source_brief_version_number",
            name="uq_clarification_rounds_project_id_source_brief_version",
        ),
    )
    op.create_index("ix_clarification_rounds_project_id", TABLE, ["project_id"], unique=False)
    op.create_index(
        "uq_clarification_rounds_open_project",
        TABLE,
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
