import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0072_guidance_choice"
down_revision = "0071_usage_journal"
branch_labels = None
depends_on = None

MODES = "'GUIDED', 'EXPERT'"


def upgrade() -> None:
    op.create_table(
        "user_guidance_choices",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("chosen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_guidance_choices"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(f"mode IN ({MODES})", name=op.f("ck_user_guidance_choice_mode")),
    )
    op.execute(
        "CREATE FUNCTION user_guidance_choice_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'guidance choices are append-only'; END $$"
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER user_guidance_choices_immutable BEFORE UPDATE OR DELETE ON user_guidance_choices FOR EACH ROW EXECUTE FUNCTION user_guidance_choice_append_only()"
        )
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM user_guidance_choices)")):
        raise RuntimeError("guidance choices must be preserved before downgrade")
    op.drop_table("user_guidance_choices")
    op.execute("DROP FUNCTION user_guidance_choice_append_only()")
