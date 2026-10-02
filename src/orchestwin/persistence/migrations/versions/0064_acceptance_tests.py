import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0064_acceptance_tests"
down_revision = "0063_code_changes"
branch_labels = None
depends_on = None

PLANS = "acceptance_test_plans"
RUNS = "acceptance_test_runs"
REVIEWS = "acceptance_test_reviews"
PLAN_INDEX = f"ix_{PLANS}_project_created"
RUN_INDEX = f"ix_{RUNS}_project_recorded"
REVIEW_INDEX = f"ix_{REVIEWS}_run_reviewed"


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


def _typed(table, column, kind):
    return sa.CheckConstraint(
        f"jsonb_typeof({column}) = '{kind}'", name=op.f(f"ck_{table}_{column}")
    )


def _locale(table):
    return sa.CheckConstraint(
        "char_length(locale) BETWEEN 2 AND 20", name=op.f(f"ck_{table}_locale")
    )


def _cost(table):
    return sa.CheckConstraint("cost_microusd >= 0", name=op.f(f"ck_{table}_cost"))


def upgrade() -> None:
    op.create_table(
        PLANS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("reference", _jsonb(), nullable=False),
        sa.Column("application", _jsonb(), nullable=False),
        sa.Column("criteria", _jsonb(), nullable=False),
        sa.Column("replan_of", _jsonb(), nullable=False),
        sa.Column("snapshot_summary", _jsonb(), nullable=False),
        sa.Column("paths", _jsonb(), nullable=False),
        sa.Column("not_covered", _jsonb(), nullable=False),
        sa.Column("generation_ids", _jsonb(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PLANS}"),
        *_owned(PLANS),
        _locale(PLANS),
        _typed(PLANS, "reference", "object"),
        _typed(PLANS, "application", "object"),
        _typed(PLANS, "criteria", "array"),
        _typed(PLANS, "replan_of", "array"),
        _typed(PLANS, "snapshot_summary", "object"),
        _typed(PLANS, "paths", "array"),
        _typed(PLANS, "not_covered", "array"),
        _typed(PLANS, "generation_ids", "array"),
        _cost(PLANS),
    )
    op.create_index(PLAN_INDEX, PLANS, ["project_id", "created_at"])
    op.create_table(
        RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replan_ids", _jsonb(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application", _jsonb(), nullable=False),
        sa.Column("browsers", _jsonb(), nullable=False),
        sa.Column("reference", _jsonb(), nullable=False),
        sa.Column("results", _jsonb(), nullable=False),
        sa.Column("not_covered", _jsonb(), nullable=False),
        sa.Column("criteria", _jsonb(), nullable=False),
        sa.Column("summary", _jsonb(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{RUNS}"),
        sa.ForeignKeyConstraint(
            ["plan_id"], [f"{PLANS}.id"], name=f"fk_{RUNS}_plan", ondelete="RESTRICT"
        ),
        *_owned(RUNS),
        _typed(RUNS, "replan_ids", "array"),
        _typed(RUNS, "application", "object"),
        _typed(RUNS, "browsers", "array"),
        _typed(RUNS, "reference", "object"),
        _typed(RUNS, "results", "array"),
        _typed(RUNS, "not_covered", "array"),
        _typed(RUNS, "criteria", "array"),
        _typed(RUNS, "summary", "object"),
        sa.CheckConstraint("finished_at >= started_at", name=op.f(f"ck_{RUNS}_finished_at")),
        _cost(RUNS),
    )
    op.create_index(RUN_INDEX, RUNS, ["project_id", "recorded_at"])
    op.create_table(
        REVIEWS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("critiques", _jsonb(), nullable=False),
        sa.Column("generation_ids", _jsonb(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{REVIEWS}"),
        sa.ForeignKeyConstraint(
            ["run_id"], [f"{RUNS}.id"], name=f"fk_{REVIEWS}_run", ondelete="CASCADE"
        ),
        *_owned(REVIEWS),
        _locale(REVIEWS),
        _typed(REVIEWS, "critiques", "array"),
        _typed(REVIEWS, "generation_ids", "array"),
        _cost(REVIEWS),
    )
    op.create_index(REVIEW_INDEX, REVIEWS, ["run_id", "reviewed_at"])


def downgrade() -> None:
    op.drop_index(REVIEW_INDEX, table_name=REVIEWS)
    op.drop_table(REVIEWS)
    op.drop_index(RUN_INDEX, table_name=RUNS)
    op.drop_table(RUNS)
    op.drop_index(PLAN_INDEX, table_name=PLANS)
    op.drop_table(PLANS)
