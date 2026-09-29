import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0063_code_changes"
down_revision = "0062_hosted_model_providers"
branch_labels = None
depends_on = None

CHANGES = "project_code_changes"
REVIEWS = "code_change_reviews"
TASKS = "code_tasks"
CHANGE_INDEX = f"ix_{CHANGES}_project_recorded"
REVIEW_INDEX = f"ix_{REVIEWS}_change_reviewed"
TASK_CHANGE_INDEX = f"ix_{TASKS}_from_change"
COMMIT = "'^[0-9a-f]{7,64}$'"
DECISIONS = "'ALIGNED','DESIGN_CHANGE','REQUIREMENTS_CHANGE','CODE_TASKS','DISMISSED'"
VERDICTS = "'ALIGNED','CODE_DRIFT','DESIGN_OUTDATED','REQUIREMENTS_OUTDATED'"
MESSAGE_LIMIT = 2000
AUTHOR_LIMIT = 200
DIFF_LIMIT = 65536
NOTE_LIMIT = 2000
TASK_LIMIT = 300


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
        CHANGES,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("commit", sa.String(length=64), nullable=False),
        sa.Column("parent", sa.String(length=64), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("author", sa.String(length=AUTHOR_LIMIT), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("files", _jsonb(), nullable=False),
        sa.Column("diff", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_kind", sa.String(length=32), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aligned_requirements_version", sa.Integer(), nullable=True),
        sa.Column("aligned_design_version", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{CHANGES}"),
        sa.UniqueConstraint("project_id", "commit", name=f"uq_{CHANGES}_commit"),
        *_owned(CHANGES),
        sa.CheckConstraint(f"commit ~ {COMMIT}", name=op.f(f"ck_{CHANGES}_commit")),
        sa.CheckConstraint(
            f"parent IS NULL OR (parent ~ {COMMIT} AND parent <> commit)",
            name=op.f(f"ck_{CHANGES}_parent"),
        ),
        sa.CheckConstraint(
            f"char_length(message) BETWEEN 1 AND {MESSAGE_LIMIT}",
            name=op.f(f"ck_{CHANGES}_message"),
        ),
        sa.CheckConstraint(
            f"author IS NULL OR char_length(author) BETWEEN 1 AND {AUTHOR_LIMIT}",
            name=op.f(f"ck_{CHANGES}_author"),
        ),
        sa.CheckConstraint("jsonb_typeof(files) = 'array'", name=op.f(f"ck_{CHANGES}_files")),
        sa.CheckConstraint(f"char_length(diff) <= {DIFF_LIMIT}", name=op.f(f"ck_{CHANGES}_diff")),
        sa.CheckConstraint(
            f"decision_kind IS NULL OR decision_kind IN ({DECISIONS})",
            name=op.f(f"ck_{CHANGES}_decision_kind"),
        ),
        sa.CheckConstraint(
            "(decision_kind IS NULL) = (decided_at IS NULL)",
            name=op.f(f"ck_{CHANGES}_decision_time"),
        ),
        sa.CheckConstraint(
            f"decision_note IS NULL OR (decision_kind IS NOT NULL AND "
            f"char_length(decision_note) BETWEEN 1 AND {NOTE_LIMIT})",
            name=op.f(f"ck_{CHANGES}_decision_note"),
        ),
        sa.CheckConstraint(
            "(decision_kind IS NOT NULL AND decision_kind = 'ALIGNED') OR "
            "(aligned_requirements_version IS NULL AND aligned_design_version IS NULL)",
            name=op.f(f"ck_{CHANGES}_aligned_versions"),
        ),
        sa.CheckConstraint(
            "(aligned_requirements_version IS NULL OR aligned_requirements_version >= 1) AND "
            "(aligned_design_version IS NULL OR aligned_design_version >= 1)",
            name=op.f(f"ck_{CHANGES}_aligned_version_numbers"),
        ),
    )
    op.create_index(CHANGE_INDEX, CHANGES, ["project_id", "recorded_at"])
    op.create_table(
        REVIEWS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("reference", _jsonb(), nullable=False),
        sa.Column("critiques", _jsonb(), nullable=False),
        sa.Column("alignment", _jsonb(), nullable=False),
        sa.Column("generation_ids", _jsonb(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{REVIEWS}"),
        sa.ForeignKeyConstraint(
            ["change_id"], [f"{CHANGES}.id"], name=f"fk_{REVIEWS}_change", ondelete="CASCADE"
        ),
        *_owned(REVIEWS),
        sa.CheckConstraint(
            "char_length(locale) BETWEEN 2 AND 20", name=op.f(f"ck_{REVIEWS}_locale")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(reference) = 'object'", name=op.f(f"ck_{REVIEWS}_reference")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(critiques) = 'array'", name=op.f(f"ck_{REVIEWS}_critiques")
        ),
        sa.CheckConstraint(
            "jsonb_typeof(alignment) = 'object' AND "
            f"COALESCE(alignment->>'status' IN ({VERDICTS}), false)",
            name=op.f(f"ck_{REVIEWS}_alignment"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(generation_ids) = 'array'", name=op.f(f"ck_{REVIEWS}_generation_ids")
        ),
        sa.CheckConstraint("cost_microusd >= 0", name=op.f(f"ck_{REVIEWS}_cost")),
    )
    op.create_index(REVIEW_INDEX, REVIEWS, ["change_id", "reviewed_at"])
    op.create_table(
        TASKS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("text", sa.String(length=TASK_LIMIT), nullable=False),
        sa.Column("about", _jsonb(), nullable=False),
        sa.Column("from_change_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TASKS}"),
        sa.UniqueConstraint("project_id", "number", name=f"uq_{TASKS}_number"),
        sa.ForeignKeyConstraint(
            ["from_change_id"],
            [f"{CHANGES}.id"],
            name=f"fk_{TASKS}_from_change",
            ondelete="CASCADE",
        ),
        *_owned(TASKS),
        sa.CheckConstraint("number BETWEEN 1 AND 999999", name=op.f(f"ck_{TASKS}_number")),
        sa.CheckConstraint("code ~ '^TSK-[0-9]{3,6}$'", name=op.f(f"ck_{TASKS}_code")),
        sa.CheckConstraint(
            f"char_length(text) BETWEEN 1 AND {TASK_LIMIT}", name=op.f(f"ck_{TASKS}_text")
        ),
        sa.CheckConstraint("jsonb_typeof(about) = 'object'", name=op.f(f"ck_{TASKS}_about")),
        sa.CheckConstraint("status IN ('OPEN','DONE')", name=op.f(f"ck_{TASKS}_status")),
        sa.CheckConstraint(
            "(status = 'DONE') = (done_at IS NOT NULL)", name=op.f(f"ck_{TASKS}_done_at")
        ),
    )
    op.create_index(TASK_CHANGE_INDEX, TASKS, ["from_change_id"])


def downgrade() -> None:
    op.drop_index(TASK_CHANGE_INDEX, table_name=TASKS)
    op.drop_table(TASKS)
    op.drop_index(REVIEW_INDEX, table_name=REVIEWS)
    op.drop_table(REVIEWS)
    op.drop_index(CHANGE_INDEX, table_name=CHANGES)
    op.drop_table(CHANGES)
