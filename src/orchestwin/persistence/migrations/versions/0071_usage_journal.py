import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0071_usage_journal"
down_revision = "0070_workflow_inputs"
branch_labels = None
depends_on = None

SOURCES = "'WEB', 'UT', 'STUDIO'"
KINDS = (
    "'SECTION_OPENED', 'DETAIL_OPENED', 'WHY_OPENED', 'MOCKUP_OPENED', 'MODE_CHANGED', "
    "'LOCALE_SET', 'PAGE_HIDDEN', 'PAGE_VISIBLE', 'REQUEST_FAILED', 'COMMAND_STARTED', "
    "'COMMAND_FINISHED', 'GENERATION_WAITED', 'SESSION_STARTED', 'SESSION_ENDED'"
)
SECTIONS = "'BRIEF', 'TEAM', 'USER_TWINS', 'REQUIREMENTS', 'DESIGN', 'PACKAGE'"
SESSION_CODE = "^SES-[A-Z0-9][A-Z0-9-]{0,19}$"
TARGET = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$"
STATUS = "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$"
MAX_DURATION_MS = 86400000


def _check(column, condition):
    return sa.CheckConstraint(condition, name=op.f(f"ck_project_usage_event_{column}"))


def upgrade() -> None:
    op.create_table(
        "project_usage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_code", sa.String(24), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("section", sa.String(16), nullable=True),
        sa.Column("target", sa.String(80), nullable=True),
        sa.Column("client_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_project_usage_events"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "sequence", name="uq_project_usage_event_sequence"),
        _check("session_code", f"session_code ~ '{SESSION_CODE}'"),
        _check("sequence", "sequence >= 1"),
        _check("source", f"source IN ({SOURCES})"),
        _check("kind", f"kind IN ({KINDS})"),
        _check("section", f"section IS NULL OR section IN ({SECTIONS})"),
        _check("target", f"target IS NULL OR target ~ '{TARGET}'"),
        _check(
            "duration_ms", f"duration_ms IS NULL OR duration_ms BETWEEN 0 AND {MAX_DURATION_MS}"
        ),
        _check("status", f"status IS NULL OR status ~ '{STATUS}'"),
    )
    op.execute(
        "CREATE FUNCTION usage_journal_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'usage journal events are append-only'; END $$"
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER project_usage_events_immutable BEFORE UPDATE OR DELETE ON project_usage_events FOR EACH ROW EXECUTE FUNCTION usage_journal_append_only()"
        )
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM project_usage_events)")):
        raise RuntimeError("usage journal events must be preserved before downgrade")
    op.drop_table("project_usage_events")
    op.execute("DROP FUNCTION usage_journal_append_only()")
