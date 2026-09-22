import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0048_twin_conversations"
down_revision = "0047_source_reset_and_repair_retry"
branch_labels = None
depends_on = None

GENERATIONS = "model_proposal_generations"
KNOWN_TASKS = (
    "'proposal-team-v1','proposal-personas-v1','proposal-user-twins-v1','proposal-requirements-v1',"
    "'proposal-design-v1','proposal-architecture-v1','proposal-web-source-v1','proposal-web-repair-v1',"
    "'proposal-jvm-source-v1','proposal-jvm-repair-v1'"
)
CHAT_TASK = "'proposal-twin-chat-v1'"
TABLES = ("twin_conversations", "twin_conversation_turns")


def _replace(table, name, expression):
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(name, table, f"COALESCE(({expression}), false)")


def upgrade():
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS},{CHAT_TASK})")
    op.create_table(
        "twin_conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_version_number", sa.Integer(), nullable=False),
        sa.Column("twin_content_hash", sa.String(length=64), nullable=False),
        sa.Column("twin_name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_twin_conversations"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_twin_conversations_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_twin_conversations_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["twin_version_id"],
            ["user_twin_profile_versions.id"],
            name="fk_twin_conversations_twin_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "twin_version_number > 0", name="ck_twin_conversations_positive_version"
        ),
        sa.CheckConstraint(
            "twin_content_hash ~ '^[0-9a-f]{64}$'", name="ck_twin_conversations_content_hash"
        ),
        sa.CheckConstraint(
            "length(twin_name) BETWEEN 1 AND 200", name="ck_twin_conversations_twin_name"
        ),
    )
    op.create_index(
        "ix_twin_conversations_twin",
        "twin_conversations",
        ["project_id", "twin_id", "created_at"],
    )
    op.create_table(
        "twin_conversation_turns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("insights_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_generation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_twin_conversation_turns"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["twin_conversations.id"],
            name="fk_twin_conversation_turns_conversation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["model_generation_id"],
            ["model_proposal_generations.id"],
            name="fk_twin_conversation_turns_generation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "conversation_id", "ordinal", name="uq_twin_conversation_turns_ordinal"
        ),
        sa.UniqueConstraint("model_generation_id", name="uq_twin_conversation_turns_generation"),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 40", name="ck_twin_conversation_turns_ordinal"),
        sa.CheckConstraint(
            "length(question) BETWEEN 1 AND 1000", name="ck_twin_conversation_turns_question"
        ),
        sa.CheckConstraint(
            "length(reply) BETWEEN 1 AND 2000", name="ck_twin_conversation_turns_reply"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(insights_json) = 'array' AND jsonb_array_length(insights_json) <= 6",
            name="ck_twin_conversation_turns_insights",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name="ck_twin_conversation_turns_content_hash"
        ),
    )
    op.execute("""
        CREATE FUNCTION protect_twin_conversations() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Twin conversations are append-only';
        END;
        $$ LANGUAGE plpgsql;
    """)
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_twin_conversations()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION protect_twin_conversations()"
        )


def downgrade():
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM twin_conversations) THEN
                RAISE EXCEPTION 'Cannot remove protection of retained twin conversations';
            END IF;
        END $$;
    """)
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_immutable ON {table}")
    op.execute("DROP FUNCTION protect_twin_conversations()")
    op.drop_table("twin_conversation_turns")
    op.drop_index("ix_twin_conversations_twin", table_name="twin_conversations")
    op.drop_table("twin_conversations")
    _replace(GENERATIONS, "task_valid", f"task_id IN ({KNOWN_TASKS})")
