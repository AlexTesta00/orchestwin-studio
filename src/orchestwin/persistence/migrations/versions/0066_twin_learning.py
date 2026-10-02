import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066_twin_learning"
down_revision = "0065_code_task_sources"
branch_labels = None
depends_on = None

UPDATES = "twin_updates"
OBSERVATIONS = "twin_learned_observations"
UPDATE_INDEX = f"ix_{UPDATES}_project_twin_created"
PENDING_INDEX = f"uq_{UPDATES}_pending"
OBSERVATION_INDEX = f"ix_{OBSERVATIONS}_project_twin"
OBSERVATION_UPDATE_INDEX = f"ix_{OBSERVATIONS}_update"
STATUSES = "'PROPOSED','APPROVED','REJECTED','EMPTY'"
SOURCES = "'TWIN_CRITIQUE','OWNER'"
TWIN_NAME_LIMIT = 200
COMMENT_LIMIT = 600
STATEMENT_LIMIT = 400
BASIS_LIMIT = 300
REASON_LIMIT = 300
MAX_PROPOSED = 6
MAX_CHANGES = 8
MAX_TESTS = 4


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


def _check(table, name, condition):
    return sa.CheckConstraint(condition, name=op.f(f"ck_{table}_{name}"))


def _length(table, column, maximum, *, optional=False):
    condition = f"char_length({column}) BETWEEN 1 AND {maximum}"
    if optional:
        condition = f"{column} IS NULL OR {condition}"
    return _check(table, column, condition)


def upgrade() -> None:
    op.create_table(
        UPDATES,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_name", sa.String(length=TWIN_NAME_LIMIT), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locale", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("base_profile_version", sa.Integer(), nullable=False),
        sa.Column("base_development_version", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=COMMENT_LIMIT), nullable=False),
        sa.Column("observations", _jsonb(), nullable=False),
        sa.Column("material_changes", sa.Integer(), nullable=False),
        sa.Column("material_tests", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kept", _jsonb(), nullable=True),
        sa.Column("decision_reason", sa.String(length=REASON_LIMIT), nullable=True),
        sa.Column("generation_ids", _jsonb(), nullable=False),
        sa.Column("cost_microusd", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{UPDATES}"),
        *_owned(UPDATES),
        _length(UPDATES, "twin_name", TWIN_NAME_LIMIT),
        _check(UPDATES, "locale", "char_length(locale) BETWEEN 2 AND 20"),
        _check(UPDATES, "status", f"status IN ({STATUSES})"),
        _check(UPDATES, "base_profile_version", "base_profile_version >= 1"),
        _check(UPDATES, "base_development_version", "base_development_version >= 0"),
        _length(UPDATES, "comment", COMMENT_LIMIT),
        _check(
            UPDATES,
            "observations",
            "CASE WHEN jsonb_typeof(observations) = 'array' THEN "
            f"jsonb_array_length(observations) <= {MAX_PROPOSED} AND "
            "(status = 'EMPTY') = (jsonb_array_length(observations) = 0) ELSE false END",
        ),
        _check(
            UPDATES,
            "material",
            f"material_changes BETWEEN 0 AND {MAX_CHANGES} AND "
            f"material_tests BETWEEN 0 AND {MAX_TESTS} AND "
            "material_changes + material_tests >= 1",
        ),
        _check(
            UPDATES,
            "decision",
            "(status IN ('APPROVED','REJECTED')) = (decided_at IS NOT NULL) AND "
            "(decided_at IS NULL) = (kept IS NULL)",
        ),
        _check(
            UPDATES,
            "kept",
            "kept IS NULL OR CASE WHEN jsonb_typeof(kept) = 'array' THEN "
            "(status = 'APPROVED') = (jsonb_array_length(kept) >= 1) ELSE false END",
        ),
        _check(
            UPDATES,
            "decision_reason",
            "decision_reason IS NULL OR (decided_at IS NOT NULL AND "
            f"char_length(decision_reason) BETWEEN 1 AND {REASON_LIMIT})",
        ),
        _check(UPDATES, "generation_ids", "jsonb_typeof(generation_ids) = 'array'"),
        _check(UPDATES, "cost", "cost_microusd >= 0"),
    )
    op.create_index(UPDATE_INDEX, UPDATES, ["project_id", "twin_id", "created_at"])
    op.create_index(
        PENDING_INDEX,
        UPDATES,
        ["project_id", "twin_id"],
        unique=True,
        postgresql_where=sa.text("status = 'PROPOSED'"),
    )
    op.create_table(
        OBSERVATIONS,
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=12), nullable=False),
        sa.Column("statement", sa.String(length=STATEMENT_LIMIT), nullable=False),
        sa.Column("basis", sa.String(length=BASIS_LIMIT), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("requirement", sa.String(length=12), nullable=True),
        sa.Column("screen", sa.String(length=12), nullable=True),
        sa.Column("contradicts_profile", sa.String(length=BASIS_LIMIT), nullable=True),
        sa.Column("added_in_version", sa.Integer(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("update_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("retired_in_version", sa.Integer(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retire_reason", sa.String(length=REASON_LIMIT), nullable=True),
        sa.PrimaryKeyConstraint("project_id", "number", name=f"pk_{OBSERVATIONS}"),
        sa.ForeignKeyConstraint(
            ["update_id"], [f"{UPDATES}.id"], name=f"fk_{OBSERVATIONS}_update", ondelete="RESTRICT"
        ),
        *_owned(OBSERVATIONS),
        _check(OBSERVATIONS, "number", "number BETWEEN 1 AND 999999"),
        _check(OBSERVATIONS, "code", "code ~ '^OBS-[0-9]{3,6}$'"),
        _length(OBSERVATIONS, "statement", STATEMENT_LIMIT),
        _length(OBSERVATIONS, "basis", BASIS_LIMIT, optional=True),
        _check(OBSERVATIONS, "source", f"source IN ({SOURCES})"),
        _check(
            OBSERVATIONS,
            "origin",
            "(source = 'OWNER' AND update_id IS NULL AND basis IS NULL) OR "
            "(source = 'TWIN_CRITIQUE' AND update_id IS NOT NULL AND basis IS NOT NULL)",
        ),
        _check(
            OBSERVATIONS,
            "requirement",
            "requirement IS NULL OR requirement ~ '^REQ-[0-9]{3,6}$'",
        ),
        _check(OBSERVATIONS, "screen", "screen IS NULL OR screen ~ '^SCR-[0-9]{3,6}$'"),
        _length(OBSERVATIONS, "contradicts_profile", BASIS_LIMIT, optional=True),
        _check(OBSERVATIONS, "added_in_version", "added_in_version >= 1"),
        _check(
            OBSERVATIONS,
            "retirement",
            "(retired_in_version IS NULL) = (retired_at IS NULL) AND "
            "(retired_in_version IS NULL OR retired_in_version > added_in_version)",
        ),
        _check(
            OBSERVATIONS,
            "retire_reason",
            "retire_reason IS NULL OR (retired_at IS NOT NULL AND "
            f"char_length(retire_reason) BETWEEN 1 AND {REASON_LIMIT})",
        ),
    )
    op.create_index(OBSERVATION_INDEX, OBSERVATIONS, ["project_id", "twin_id", "number"])
    op.create_index(OBSERVATION_UPDATE_INDEX, OBSERVATIONS, ["update_id"])


def downgrade() -> None:
    op.drop_index(OBSERVATION_UPDATE_INDEX, table_name=OBSERVATIONS)
    op.drop_index(OBSERVATION_INDEX, table_name=OBSERVATIONS)
    op.drop_table(OBSERVATIONS)
    op.drop_index(PENDING_INDEX, table_name=UPDATES)
    op.drop_index(UPDATE_INDEX, table_name=UPDATES)
    op.drop_table(UPDATES)
