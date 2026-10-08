import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073_knowledge_alignment"
down_revision = "0072_guidance_choice"
branch_labels = None
depends_on = None

RUNS = "knowledge_alignment_runs"
PROPOSALS = "knowledge_alignment_proposals"
RUN_INDEX = f"ix_{RUNS}_project_created"
PROPOSAL_INDEX = f"ix_{PROPOSALS}_project_status"
COMMIT = "'^[0-9a-f]{7,64}$'"
ALTERNATIVE = "'^DES-[0-9]{3,6}$'"
SECTIONS = "'REQUIREMENTS','DESIGN','TESTS'"
STATUSES = "'PROPOSED','APPLIED','SKIPPED'"
MAX_COMMITS = 50
MAX_NUMBER = 999999
SUMMARY_LIMIT = 600
TITLE_LIMIT = 200
REQUEST_LIMIT = 2000
RATIONALE_LIMIT = 400
NOTE_LIMIT = 300


def _jsonb():
    return postgresql.JSONB(astext_type=sa.Text())


def _owned(table):
    return (
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{table}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{table}_owner", ondelete="RESTRICT"
        ),
    )


def upgrade() -> None:
    op.create_table(
        RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_commit", sa.String(length=64), nullable=True),
        sa.Column("to_commit", sa.String(length=64), nullable=False),
        sa.Column("commits", _jsonb(), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("requirements_version_number", sa.Integer(), nullable=False),
        sa.Column("design_version_number", sa.Integer(), nullable=False),
        sa.Column("alternative_code", sa.String(length=16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost_microusd", sa.Integer(), nullable=False),
        sa.Column("generation_ids", _jsonb(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{RUNS}"),
        *_owned(RUNS),
        sa.CheckConstraint(f"to_commit ~ {COMMIT}", name=op.f(f"ck_{RUNS}_to_commit")),
        sa.CheckConstraint(
            f"from_commit IS NULL OR from_commit ~ {COMMIT}", name=op.f(f"ck_{RUNS}_from_commit")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(commits) = 'array' AND "
            f"jsonb_array_length(commits) BETWEEN 1 AND {MAX_COMMITS}",
            name=op.f(f"ck_{RUNS}_commits"),
        ),
        sa.CheckConstraint("char_length(locale) BETWEEN 2 AND 20", name=op.f(f"ck_{RUNS}_locale")),
        sa.CheckConstraint(
            "requirements_version_number >= 1 AND design_version_number >= 1",
            name=op.f(f"ck_{RUNS}_versions"),
        ),
        sa.CheckConstraint(
            f"alternative_code ~ {ALTERNATIVE}", name=op.f(f"ck_{RUNS}_alternative_code")
        ),
        sa.CheckConstraint(
            f"char_length(summary) BETWEEN 1 AND {SUMMARY_LIMIT}", name=op.f(f"ck_{RUNS}_summary")
        ),
        sa.CheckConstraint("cost_microusd >= 0", name=op.f(f"ck_{RUNS}_cost")),
        sa.CheckConstraint(
            "jsonb_typeof(generation_ids) = 'array'", name=op.f(f"ck_{RUNS}_generation_ids")
        ),
    )
    op.create_index(RUN_INDEX, RUNS, ["project_id", "created_at"])
    op.create_table(
        PROPOSALS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=TITLE_LIMIT), nullable=False),
        sa.Column("request", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("subjects", _jsonb(), nullable=False),
        sa.Column("origin", _jsonb(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("applied_text", sa.Text(), nullable=True),
        sa.Column("applied_diff_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PROPOSALS}"),
        sa.UniqueConstraint("project_id", "number", name=f"uq_{PROPOSALS}_number"),
        sa.ForeignKeyConstraint(
            ["run_id"], [f"{RUNS}.id"], name=f"fk_{PROPOSALS}_run", ondelete="RESTRICT"
        ),
        *_owned(PROPOSALS),
        sa.CheckConstraint(
            f"number BETWEEN 1 AND {MAX_NUMBER}", name=op.f(f"ck_{PROPOSALS}_number")
        ),
        sa.CheckConstraint(f"section IN ({SECTIONS})", name=op.f(f"ck_{PROPOSALS}_section")),
        sa.CheckConstraint(
            f"char_length(title) BETWEEN 1 AND {TITLE_LIMIT}", name=op.f(f"ck_{PROPOSALS}_title")
        ),
        sa.CheckConstraint(
            f"char_length(request) BETWEEN 1 AND {REQUEST_LIMIT}",
            name=op.f(f"ck_{PROPOSALS}_request"),
        ),
        sa.CheckConstraint(
            f"char_length(rationale) BETWEEN 1 AND {RATIONALE_LIMIT}",
            name=op.f(f"ck_{PROPOSALS}_rationale"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(subjects) = 'object'", name=op.f(f"ck_{PROPOSALS}_subjects")
        ),
        sa.CheckConstraint("jsonb_typeof(origin) = 'object'", name=op.f(f"ck_{PROPOSALS}_origin")),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f(f"ck_{PROPOSALS}_status")),
        sa.CheckConstraint(
            "(status = 'PROPOSED') = (decided_at IS NULL)",
            name=op.f(f"ck_{PROPOSALS}_decision_time"),
        ),
        sa.CheckConstraint(
            "decision_note IS NULL OR (status <> 'PROPOSED' AND "
            f"char_length(decision_note) BETWEEN 1 AND {NOTE_LIMIT})",
            name=op.f(f"ck_{PROPOSALS}_decision_note"),
        ),
        sa.CheckConstraint(
            "applied_text IS NULL OR (status = 'APPLIED' AND "
            f"char_length(applied_text) BETWEEN 1 AND {REQUEST_LIMIT})",
            name=op.f(f"ck_{PROPOSALS}_applied_text"),
        ),
        sa.CheckConstraint(
            "applied_diff_id IS NULL OR status = 'APPLIED'",
            name=op.f(f"ck_{PROPOSALS}_applied_diff"),
        ),
    )
    op.create_index(PROPOSAL_INDEX, PROPOSALS, ["project_id", "status"])


def downgrade() -> None:
    op.drop_index(PROPOSAL_INDEX, table_name=PROPOSALS)
    op.drop_table(PROPOSALS)
    op.drop_index(RUN_INDEX, table_name=RUNS)
    op.drop_table(RUNS)
