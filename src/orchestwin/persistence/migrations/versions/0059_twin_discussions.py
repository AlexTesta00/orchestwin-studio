import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0059_twin_discussions"
down_revision = "0058_design_finding_validations"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
APPLICATIONS = "insight_applications"
DISCUSSIONS = "design_discussions"
ROUNDS = "design_discussion_rounds"
KNOWN_TASKS = (
    "'proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1',"
    "'proposal-design-v1','proposal-architecture-v1','proposal-web-source-v1','proposal-web-repair-v1',"
    "'proposal-jvm-source-v1','proposal-jvm-repair-v1','proposal-twin-chat-v1',"
    "'proposal-user-twin-evaluation-v1','proposal-brief-dialogue-v1'"
)
DISCUSSION_TASK = "'proposal-twin-discussion-v1'"
SOURCE_KINDS = "'TWIN_CHAT_INSIGHT','DESIGN_CRITIQUE','SYNTHETIC_FINDING'"
DISCUSSION_SOURCE = "'TWIN_DISCUSSION'"
SOURCE_KIND_CONSTRAINT = "ck_insight_applications_ck_insight_applications_source_kind"
STATUSES = "'OPEN','APPROVED','CLOSED'"
ROUND_LIMIT = 4
NOTE_LIMIT = 1000
LOCALE_LIMIT = 20
OPEN_INDEX = "uq_design_discussions_open_version"
PROJECT_INDEX = "ix_design_discussions_project_created"
RETAINED_GUARD = """
    DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM design_discussions) THEN
            RAISE EXCEPTION 'Cannot remove retained design discussions';
        END IF;
        IF EXISTS (SELECT 1 FROM insight_applications WHERE source_kind = 'TWIN_DISCUSSION') THEN
            RAISE EXCEPTION 'Cannot remove retained twin discussion insight applications';
        END IF;
        IF EXISTS (SELECT 1 FROM model_proposal_generations
            WHERE task_id = 'proposal-twin-discussion-v1') THEN
            RAISE EXCEPTION 'Cannot remove protection of retained twin discussion generations';
        END IF;
    END $$;
"""


def _replace_task_check(expression):
    op.drop_constraint(op.f(f"ck_{GENERATIONS}_task_valid"), GENERATIONS, type_="check")
    op.create_check_constraint("task_valid", GENERATIONS, f"COALESCE(({expression}), false)")


def _replace_source_kind_check(kinds):
    op.drop_constraint(op.f(SOURCE_KIND_CONSTRAINT), APPLICATIONS, type_="check")
    op.create_check_constraint(
        op.f(SOURCE_KIND_CONSTRAINT), APPLICATIONS, f"source_kind IN ({kinds})"
    )


def upgrade():
    _replace_task_check(f"task_id IN ({KNOWN_TASKS},{DISCUSSION_TASK})")
    _replace_source_kind_check(f"{SOURCE_KINDS},{DISCUSSION_SOURCE}")
    op.create_table(
        DISCUSSIONS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("design_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("design_version_number", sa.Integer(), nullable=False),
        sa.Column("design_content_hash", sa.String(length=64), nullable=False),
        sa.Column("alternative_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alternative_code", sa.String(length=16), nullable=False),
        sa.Column("locale", sa.String(length=LOCALE_LIMIT), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{DISCUSSIONS}"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{DISCUSSIONS}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{DISCUSSIONS}_owner", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["design_version_id"],
            ["design_package_versions.id"],
            name=f"fk_{DISCUSSIONS}_design_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(f"status IN ({STATUSES})", name=op.f(f"ck_{DISCUSSIONS}_status")),
        sa.CheckConstraint(
            "design_version_number >= 1", name=op.f(f"ck_{DISCUSSIONS}_design_version")
        ),
        sa.CheckConstraint(
            "design_content_hash ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{DISCUSSIONS}_design_hash")
        ),
        sa.CheckConstraint(
            "alternative_code ~ '^DES-[0-9]{3,}$'", name=op.f(f"ck_{DISCUSSIONS}_alternative_code")
        ),
        sa.CheckConstraint(
            f"char_length(locale) BETWEEN 2 AND {LOCALE_LIMIT}",
            name=op.f(f"ck_{DISCUSSIONS}_locale"),
        ),
        sa.CheckConstraint(
            "(status = 'OPEN' AND decided_at IS NULL)"
            " OR (status <> 'OPEN' AND decided_at IS NOT NULL AND decided_at >= created_at)",
            name=op.f(f"ck_{DISCUSSIONS}_decision"),
        ),
    )
    op.create_index(PROJECT_INDEX, DISCUSSIONS, ["project_id", "created_at"])
    op.create_index(
        OPEN_INDEX,
        DISCUSSIONS,
        ["design_version_id"],
        unique=True,
        postgresql_where=sa.text("status = 'OPEN'"),
    )
    op.create_table(
        ROUNDS,
        sa.Column("discussion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("owner_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("round_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("discussion_id", "ordinal", name=f"pk_{ROUNDS}"),
        sa.ForeignKeyConstraint(
            ["discussion_id"],
            [f"{DISCUSSIONS}.id"],
            name=f"fk_{ROUNDS}_discussion",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            f"ordinal BETWEEN 1 AND {ROUND_LIMIT}", name=op.f(f"ck_{ROUNDS}_ordinal")
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{ROUNDS}_content_hash")
        ),
        sa.CheckConstraint(
            f"owner_note IS NULL OR char_length(owner_note) BETWEEN 1 AND {NOTE_LIMIT}",
            name=op.f(f"ck_{ROUNDS}_owner_note"),
        ),
    )


def downgrade():
    op.execute(RETAINED_GUARD)
    op.drop_table(ROUNDS)
    op.drop_index(OPEN_INDEX, table_name=DISCUSSIONS)
    op.drop_index(PROJECT_INDEX, table_name=DISCUSSIONS)
    op.drop_table(DISCUSSIONS)
    _replace_source_kind_check(SOURCE_KINDS)
    _replace_task_check(f"task_id IN ({KNOWN_TASKS})")
