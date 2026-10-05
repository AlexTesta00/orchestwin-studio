import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0069_human_validation"
down_revision = "0068_research_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "project_validation_hypotheses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", "version_number", name="pk_project_validation_hypotheses"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id", "code", "version_number", name="uq_project_validation_hypothesis_code"
        ),
        sa.UniqueConstraint(
            "id", "version_number", "content_hash", name="uq_project_validation_hypothesis_hash"
        ),
        sa.CheckConstraint(
            "version_number >= 1 AND content_hash ~ '^[a-f0-9]{64}$' AND code ~ '^HYP-[0-9]{3,6}$'",
            name="ck_project_validation_hypothesis_identity",
        ),
    )
    op.create_index(
        "ix_project_validation_hypotheses_project", "project_validation_hypotheses", ["project_id"]
    )
    op.create_table(
        "project_validation_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("hypothesis_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hypothesis_version_number", sa.Integer(), nullable=False),
        sa.Column("hypothesis_content_hash", sa.String(64), nullable=False),
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_project_validation_outcomes"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["hypothesis_id", "hypothesis_version_number", "hypothesis_content_hash"],
            [
                "project_validation_hypotheses.id",
                "project_validation_hypotheses.version_number",
                "project_validation_hypotheses.content_hash",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id", "evidence_version"],
            ["research_evidence_versions.id", "research_evidence_versions.version"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("project_id", "code", name="uq_project_validation_outcome_code"),
        sa.CheckConstraint(
            "hypothesis_version_number >= 1 AND evidence_version >= 1 AND content_hash ~ '^[a-f0-9]{64}$' AND code ~ '^HVO-[0-9]{3,6}$'",
            name="ck_project_validation_outcome_identity",
        ),
    )
    op.create_index(
        "ix_project_validation_outcomes_project", "project_validation_outcomes", ["project_id"]
    )
    op.execute(
        "CREATE FUNCTION human_validation_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'human validation records are append-only'; END $$"
    )
    for table in ("project_validation_hypotheses", "project_validation_outcomes"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION human_validation_append_only()"
            )
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM project_validation_hypotheses) OR EXISTS (SELECT 1 FROM project_validation_outcomes)"
        )
    ):
        raise RuntimeError("human validation records must be preserved before downgrade")
    op.drop_index(
        "ix_project_validation_outcomes_project", table_name="project_validation_outcomes"
    )
    op.drop_table("project_validation_outcomes")
    op.drop_index(
        "ix_project_validation_hypotheses_project", table_name="project_validation_hypotheses"
    )
    op.drop_table("project_validation_hypotheses")
    op.execute("DROP FUNCTION human_validation_append_only()")
