import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0058_design_finding_validations"
down_revision = "0057_design_evaluation_loop"
branch_labels = None
depends_on = None

VALIDATIONS = "design_finding_validations"
FINDINGS = "design_synthetic_findings"
DECISIONS = "'OWNER_CONFIRMED','OWNER_DISMISSED'"


def upgrade():
    op.create_table(
        VALIDATIONS,
        sa.Column("evaluation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("validation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "evaluation_run_id",
            "twin_id",
            "finding_id",
            "sequence_number",
            name=f"pk_{VALIDATIONS}",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id", "twin_id", "finding_id"],
            [f"{FINDINGS}.evaluation_run_id", f"{FINDINGS}.twin_id", f"{FINDINGS}.finding_id"],
            name=f"fk_{VALIDATIONS}_finding",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{VALIDATIONS}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{VALIDATIONS}_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(f"decision IN ({DECISIONS})", name=f"ck_{VALIDATIONS}_decision"),
        sa.CheckConstraint("sequence_number >= 1", name=f"ck_{VALIDATIONS}_sequence"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=f"ck_{VALIDATIONS}_content_hash"
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) BETWEEN 1 AND 1000", name=f"ck_{VALIDATIONS}_note"
        ),
    )
    op.create_index(f"ix_{VALIDATIONS}_project_decided", VALIDATIONS, ["project_id", "decided_at"])


def downgrade():
    op.drop_index(f"ix_{VALIDATIONS}_project_decided", table_name=VALIDATIONS)
    op.drop_table(VALIDATIONS)
