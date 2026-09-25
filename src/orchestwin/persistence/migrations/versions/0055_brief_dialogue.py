import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0055_brief_dialogue"
down_revision = "0054_eight_user_twins"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
KNOWN_TASKS = (
    "'proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1',"
    "'proposal-design-v1','proposal-architecture-v1','proposal-web-source-v1','proposal-web-repair-v1',"
    "'proposal-jvm-source-v1','proposal-jvm-repair-v1','proposal-twin-chat-v1',"
    "'proposal-user-twin-evaluation-v1'"
)
DIALOGUE_TASK = "'proposal-brief-dialogue-v1'"
DIALOGUES = "brief_dialogues"
TURNS = "brief_dialogue_turns"
TEXT_FIELDS = "'name','description','problem','domain','temporal_constraints','budget'"
LIST_FIELDS = (
    "'goals','target_users','technical_constraints','functional_requirements',"
    "'non_functional_requirements','risks','stakeholders','available_artifacts','definition_of_done'"
)
QUESTION_LIMIT = 20


def _replace(table, name, expression):
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(name, table, f"COALESCE(({expression}), false)")


def upgrade():
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS},{DIALOGUE_TASK})")
    op.create_table(
        DIALOGUES,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_brief_version_number", sa.Integer(), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resulting_brief_version_number", sa.Integer(), nullable=True),
        sa.Column("synthesis_generation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{DIALOGUES}"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{DIALOGUES}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{DIALOGUES}_owner", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "source_brief_version_number"],
            ["project_brief_versions.project_id", "project_brief_versions.version_number"],
            name=f"fk_{DIALOGUES}_source_brief_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "resulting_brief_version_number"],
            ["project_brief_versions.project_id", "project_brief_versions.version_number"],
            name=f"fk_{DIALOGUES}_resulting_brief_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["synthesis_generation_id"],
            [f"{GENERATIONS}.id"],
            name=f"fk_{DIALOGUES}_synthesis_generation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("synthesis_generation_id", name=f"uq_{DIALOGUES}_synthesis_generation"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'READY', 'SYNTHESIZED', 'CLOSED')",
            name=op.f(f"ck_{DIALOGUES}_status"),
        ),
        sa.CheckConstraint(
            "source_brief_version_number >= 1", name=op.f(f"ck_{DIALOGUES}_source_version")
        ),
        sa.CheckConstraint(
            "length(statement) BETWEEN 1 AND 2000", name=op.f(f"ck_{DIALOGUES}_statement")
        ),
        sa.CheckConstraint(
            "(status IN ('OPEN', 'READY') AND resulting_brief_version_number IS NULL"
            " AND synthesis_generation_id IS NULL AND completed_at IS NULL)"
            " OR (status = 'SYNTHESIZED' AND resulting_brief_version_number IS NOT NULL"
            " AND resulting_brief_version_number > source_brief_version_number"
            " AND synthesis_generation_id IS NOT NULL AND completed_at IS NOT NULL)"
            " OR (status = 'CLOSED' AND resulting_brief_version_number IS NULL"
            " AND synthesis_generation_id IS NULL AND completed_at IS NOT NULL)",
            name=op.f(f"ck_{DIALOGUES}_state"),
        ),
    )
    op.create_index(f"ix_{DIALOGUES}_project", DIALOGUES, ["project_id", "created_at"])
    op.create_index(
        f"uq_{DIALOGUES}_active_project",
        DIALOGUES,
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'READY')"),
    )
    op.create_table(
        TURNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dialogue_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(length=48), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("model_generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_kind", sa.String(length=16), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answer_items", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{TURNS}"),
        sa.ForeignKeyConstraint(
            ["dialogue_id"], [f"{DIALOGUES}.id"], name=f"fk_{TURNS}_dialogue", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["model_generation_id"],
            [f"{GENERATIONS}.id"],
            name=f"fk_{TURNS}_generation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("dialogue_id", "ordinal", name=f"uq_{TURNS}_ordinal"),
        sa.UniqueConstraint("model_generation_id", name=f"uq_{TURNS}_generation"),
        sa.CheckConstraint(
            f"ordinal BETWEEN 1 AND {QUESTION_LIMIT}", name=op.f(f"ck_{TURNS}_ordinal")
        ),
        sa.CheckConstraint(
            f"field IS NULL OR field IN ({TEXT_FIELDS},{LIST_FIELDS})",
            name=op.f(f"ck_{TURNS}_field"),
        ),
        sa.CheckConstraint("length(question) BETWEEN 1 AND 500", name=op.f(f"ck_{TURNS}_question")),
        sa.CheckConstraint(
            "(answer_kind IS NULL AND answer_text IS NULL AND answer_items IS NULL"
            " AND answered_at IS NULL)"
            " OR (answer_kind = 'TEXT' AND length(answer_text) BETWEEN 1 AND 2000"
            " AND answer_items IS NULL AND answered_at IS NOT NULL)"
            " OR (answer_kind = 'ITEM_LIST' AND answer_text IS NULL"
            " AND jsonb_typeof(answer_items) = 'array'"
            " AND jsonb_array_length(answer_items) BETWEEN 1 AND 20 AND answered_at IS NOT NULL)"
            " OR (answer_kind = 'UNKNOWN' AND answer_text IS NULL AND answer_items IS NULL"
            " AND answered_at IS NOT NULL)",
            name=op.f(f"ck_{TURNS}_answer_state"),
        ),
        sa.CheckConstraint(
            f"answer_kind IS DISTINCT FROM 'ITEM_LIST' OR field IN ({LIST_FIELDS})",
            name=op.f(f"ck_{TURNS}_list_answer_field"),
        ),
        sa.CheckConstraint(
            f"answer_kind IS DISTINCT FROM 'TEXT' OR field IS NULL OR field IN ({TEXT_FIELDS})",
            name=op.f(f"ck_{TURNS}_text_answer_field"),
        ),
        sa.CheckConstraint(
            "answered_at IS NULL OR answered_at >= asked_at", name=op.f(f"ck_{TURNS}_answer_time")
        ),
    )


def downgrade():
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM {DIALOGUES}) THEN
                RAISE EXCEPTION 'Cannot remove retained brief dialogues';
            END IF;
        END $$;
    """)
    op.drop_table(TURNS)
    op.drop_index(f"uq_{DIALOGUES}_active_project", table_name=DIALOGUES)
    op.drop_index(f"ix_{DIALOGUES}_project", table_name=DIALOGUES)
    op.drop_table(DIALOGUES)
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS})")
