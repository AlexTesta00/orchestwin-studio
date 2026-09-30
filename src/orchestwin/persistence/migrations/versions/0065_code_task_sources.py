import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0065_code_task_sources"
down_revision = "0064_acceptance_tests"
branch_labels = None
depends_on = None

TASKS = "code_tasks"
RUNS = "acceptance_test_runs"
TEST_RUN_FOREIGN_KEY = f"fk_{TASKS}_test_run"
TEST_RUN_INDEX = f"ix_{TASKS}_test_run"
STATUS_CHECK = f"ck_{TASKS}_status"
DONE_CHECK = f"ck_{TASKS}_done_at"
CLOSED_CHECK = f"ck_{TASKS}_closed_at"
ORIGIN_CHECK = f"ck_{TASKS}_origin"
SOURCE_CHECK = f"ck_{TASKS}_origin_source"
FINDING_CHECK = f"ck_{TASKS}_finding"
NOTE_CHECK = f"ck_{TASKS}_note"
ORIGINS = "'CODE_CHANGE','TEST_RUN','OWNER'"
TWIN_NAME_LIMIT = 200
FINDING_LIMIT = 400
NOTE_LIMIT = 300
ADDED_COLUMNS = ("origin", "test_run_id", "twin_id", "twin_name", "finding_text", "note")


def _check(name, condition):
    op.create_check_constraint(op.f(name), TASKS, condition)


def _drop_check(name):
    op.drop_constraint(op.f(name), TASKS, type_="check")


def upgrade() -> None:
    op.add_column(
        TASKS,
        sa.Column("origin", sa.String(length=16), nullable=False, server_default="CODE_CHANGE"),
    )
    op.alter_column(TASKS, "origin", server_default=None)
    op.add_column(TASKS, sa.Column("test_run_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TASKS, sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(TASKS, sa.Column("twin_name", sa.String(length=TWIN_NAME_LIMIT), nullable=True))
    op.add_column(TASKS, sa.Column("finding_text", sa.String(length=FINDING_LIMIT), nullable=True))
    op.add_column(TASKS, sa.Column("note", sa.String(length=NOTE_LIMIT), nullable=True))
    op.create_foreign_key(
        TEST_RUN_FOREIGN_KEY, TASKS, RUNS, ["test_run_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(TEST_RUN_INDEX, TASKS, ["test_run_id"])
    op.alter_column(TASKS, "from_change_id", nullable=True)
    _drop_check(DONE_CHECK)
    _drop_check(STATUS_CHECK)
    op.alter_column(TASKS, "done_at", new_column_name="closed_at")
    _check(STATUS_CHECK, "status IN ('OPEN','DONE','DROPPED')")
    _check(CLOSED_CHECK, "(status IN ('DONE','DROPPED')) = (closed_at IS NOT NULL)")
    _check(ORIGIN_CHECK, f"origin IN ({ORIGINS})")
    _check(
        SOURCE_CHECK,
        "(origin = 'CODE_CHANGE' AND from_change_id IS NOT NULL AND test_run_id IS NULL)"
        " OR (origin = 'TEST_RUN' AND from_change_id IS NULL AND test_run_id IS NOT NULL"
        " AND twin_id IS NOT NULL)"
        " OR (origin = 'OWNER' AND from_change_id IS NULL AND test_run_id IS NULL"
        " AND twin_id IS NULL)",
    )
    _check(
        FINDING_CHECK,
        "(twin_id IS NULL AND twin_name IS NULL AND finding_text IS NULL)"
        " OR (twin_id IS NOT NULL AND twin_name IS NOT NULL AND finding_text IS NOT NULL"
        f" AND char_length(twin_name) BETWEEN 1 AND {TWIN_NAME_LIMIT}"
        f" AND char_length(finding_text) BETWEEN 1 AND {FINDING_LIMIT})",
    )
    _check(NOTE_CHECK, f"note IS NULL OR char_length(note) BETWEEN 1 AND {NOTE_LIMIT}")


def downgrade() -> None:
    op.execute(f"DELETE FROM {TASKS} WHERE from_change_id IS NULL")
    op.execute(f"UPDATE {TASKS} SET status = 'DONE' WHERE status = 'DROPPED'")
    for name in (NOTE_CHECK, FINDING_CHECK, SOURCE_CHECK, ORIGIN_CHECK, CLOSED_CHECK):
        _drop_check(name)
    _drop_check(STATUS_CHECK)
    op.alter_column(TASKS, "closed_at", new_column_name="done_at")
    _check(STATUS_CHECK, "status IN ('OPEN','DONE')")
    _check(DONE_CHECK, "(status = 'DONE') = (done_at IS NOT NULL)")
    op.alter_column(TASKS, "from_change_id", nullable=False)
    op.drop_index(TEST_RUN_INDEX, table_name=TASKS)
    op.drop_constraint(TEST_RUN_FOREIGN_KEY, TASKS, type_="foreignkey")
    for column in reversed(ADDED_COLUMNS):
        op.drop_column(TASKS, column)
