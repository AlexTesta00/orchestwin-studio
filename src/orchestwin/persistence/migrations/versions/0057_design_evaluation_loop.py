import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0057_design_evaluation_loop"
down_revision = "0056_drop_clarification_rounds"
branch_labels = None
depends_on = None

RUNS = "design_evaluation_runs"
FINDINGS = "design_synthetic_findings"
APPLICATIONS = "insight_applications"
CRITERIA = (
    "'usefulness','comprehensibility','actionability','cognitive_load','trust',"
    "'accessibility','task_alignment'"
)
SEVERITIES = "'critical','major','moderate','minor','observation'"
EPISTEMIC = (
    "'USER_PROVIDED','EMPIRICALLY_SUPPORTED','HUMAN_VALIDATED','MODEL_INFERRED',"
    "'UNSUPPORTED_ASSUMPTION'"
)
SOURCE_KINDS = "'TWIN_CHAT_INSIGHT','DESIGN_CRITIQUE','SYNTHETIC_FINDING'"
TARGETS = "'BRIEF','REQUIREMENTS','DESIGN'"


def upgrade():
    op.create_table(
        RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("design_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("design_version_number", sa.Integer(), nullable=False),
        sa.Column("design_content_hash", sa.String(length=64), nullable=False),
        sa.Column("alternative_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alternative_code", sa.String(length=16), nullable=False),
        sa.Column("evaluator_id", sa.String(length=256), nullable=False),
        sa.Column("evaluator_version", sa.String(length=256), nullable=False),
        sa.Column("model_config_ref", sa.String(length=256), nullable=False),
        sa.Column("prompt_version_ref", sa.String(length=256), nullable=False),
        sa.Column("response_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("run_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{RUNS}"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{RUNS}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{RUNS}_owner", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["design_version_id"],
            ["design_package_versions.id"],
            name=f"fk_{RUNS}_design_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("design_version_number >= 1", name=f"ck_{RUNS}_version"),
        sa.CheckConstraint("design_content_hash ~ '^[0-9a-f]{64}$'", name=f"ck_{RUNS}_design_hash"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=f"ck_{RUNS}_content_hash"),
        sa.CheckConstraint("response_count BETWEEN 1 AND 8", name=f"ck_{RUNS}_response_count"),
        sa.CheckConstraint("finding_count >= 0", name=f"ck_{RUNS}_finding_count"),
        sa.CheckConstraint("completed_at >= started_at", name=f"ck_{RUNS}_time_order"),
        sa.CheckConstraint(
            "alternative_code ~ '^DES-[0-9]{3,}$'", name=f"ck_{RUNS}_alternative_code"
        ),
    )
    op.create_index(f"ix_{RUNS}_project_started", RUNS, ["project_id", "started_at"])
    op.create_table(
        FINDINGS,
        sa.Column("evaluation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_version", sa.Integer(), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("criterion", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("epistemic_status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("requires_human_validation", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("finding_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "evaluation_run_id", "twin_id", "finding_id", name=f"pk_{FINDINGS}"
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id"], [f"{RUNS}.id"], name=f"fk_{FINDINGS}_run", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{FINDINGS}_project", ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("evaluation_run_id", "sequence_number", name=f"uq_{FINDINGS}_sequence"),
        sa.CheckConstraint("sequence_number >= 1", name=f"ck_{FINDINGS}_sequence"),
        sa.CheckConstraint("twin_version >= 1", name=f"ck_{FINDINGS}_twin_version"),
        sa.CheckConstraint("artifact_version >= 1", name=f"ck_{FINDINGS}_artifact_version"),
        sa.CheckConstraint(f"criterion IN ({CRITERIA})", name=f"ck_{FINDINGS}_criterion"),
        sa.CheckConstraint(f"severity IN ({SEVERITIES})", name=f"ck_{FINDINGS}_severity"),
        sa.CheckConstraint(f"epistemic_status IN ({EPISTEMIC})", name=f"ck_{FINDINGS}_epistemic"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=f"ck_{FINDINGS}_confidence"),
        sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name=f"ck_{FINDINGS}_content_hash"),
    )
    op.create_index(f"ix_{FINDINGS}_project_twin", FINDINGS, ["project_id", "twin_id"])
    op.create_table(
        APPLICATIONS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=200), nullable=False),
        sa.Column("source_twin_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("target_field", sa.String(length=48), nullable=True),
        sa.Column("target_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_version_number", sa.Integer(), nullable=False),
        sa.Column("target_code", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{APPLICATIONS}"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{APPLICATIONS}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{APPLICATIONS}_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            f"source_kind IN ({SOURCE_KINDS})", name=f"ck_{APPLICATIONS}_source_kind"
        ),
        sa.CheckConstraint(f"target IN ({TARGETS})", name=f"ck_{APPLICATIONS}_target"),
        sa.CheckConstraint("char_length(text) BETWEEN 1 AND 2000", name=f"ck_{APPLICATIONS}_text"),
        sa.CheckConstraint("target_version_number >= 1", name=f"ck_{APPLICATIONS}_target_version"),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=f"ck_{APPLICATIONS}_content_hash"
        ),
    )
    op.create_index(
        f"ix_{APPLICATIONS}_project_created", APPLICATIONS, ["project_id", "created_at"]
    )


def downgrade():
    op.drop_index(f"ix_{APPLICATIONS}_project_created", table_name=APPLICATIONS)
    op.drop_table(APPLICATIONS)
    op.drop_index(f"ix_{FINDINGS}_project_twin", table_name=FINDINGS)
    op.drop_table(FINDINGS)
    op.drop_index(f"ix_{RUNS}_project_started", table_name=RUNS)
    op.drop_table(RUNS)
