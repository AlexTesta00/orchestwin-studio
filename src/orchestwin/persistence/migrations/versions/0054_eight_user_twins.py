from alembic import op

revision = "0054_eight_user_twins"
down_revision = "0053_source_task_hooks"
branch_labels = None
depends_on = None

TABLE = "user_modeling_snapshot_versions"
COUNT_COLUMNS = ("persona_count", "twin_count")
PREVIOUS_LIMIT = 4
LIMIT = 8


def _replace_count_limits(limit):
    for column in COUNT_COLUMNS:
        name = f"ck_{TABLE}_{column}"
        op.drop_constraint(name, TABLE, type_="check")
        op.create_check_constraint(name, TABLE, f"{column} BETWEEN 1 AND {limit}")


def upgrade():
    _replace_count_limits(LIMIT)


def downgrade():
    _replace_count_limits(PREVIOUS_LIMIT)
