import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0075_design_critiques"
down_revision = "0074_design_version_restore"
branch_labels = None
depends_on = None

SOURCES = "design_critique_sources"
SHOTS = "design_critique_shots"
RUNS = "design_critique_runs"
SOURCE_INDEX = f"ix_{SOURCES}_project_created"
RUN_INDEX = f"ix_{RUNS}_project_started"
KINDS = "'IMAGE','WEB_PAGE'"
MEDIA_TYPES = "'image/png','image/jpeg'"
MAX_SHOT_BYTES = 5 * 1024 * 1024
TITLE_LIMIT = 200


def _uuid():
    return postgresql.UUID(as_uuid=True)


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


def _from_source(table):
    return sa.ForeignKeyConstraint(
        ["source_id"], [f"{SOURCES}.id"], name=f"fk_{table}_source", ondelete="RESTRICT"
    )


def upgrade() -> None:
    op.create_table(
        SOURCES,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("owner_user_id", _uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=TITLE_LIMIT), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("page_snapshot", _jsonb(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SOURCES}"),
        *_owned(SOURCES),
        sa.CheckConstraint(f"kind IN ({KINDS})", name=op.f(f"ck_{SOURCES}_kind")),
    )
    op.create_index(SOURCE_INDEX, SOURCES, ["project_id", "created_at"])
    op.create_table(
        SHOTS,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("source_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("owner_user_id", _uuid(), nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("viewport_width", sa.Integer(), nullable=True),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{SHOTS}"),
        sa.UniqueConstraint("source_id", "code", name=f"uq_{SHOTS}_source_code"),
        _from_source(SHOTS),
        *_owned(SHOTS),
        sa.CheckConstraint(f"media_type IN ({MEDIA_TYPES})", name=op.f(f"ck_{SHOTS}_media_type")),
        sa.CheckConstraint(
            f"byte_size BETWEEN 1 AND {MAX_SHOT_BYTES}", name=op.f(f"ck_{SHOTS}_byte_size")
        ),
    )
    op.create_table(
        RUNS,
        sa.Column("id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("owner_user_id", _uuid(), nullable=False),
        sa.Column("source_id", _uuid(), nullable=False),
        sa.Column("evaluator_id", sa.String(length=256), nullable=False),
        sa.Column("evaluator_version", sa.String(length=256), nullable=False),
        sa.Column("model_config_ref", sa.String(length=256), nullable=False),
        sa.Column("prompt_version_ref", sa.String(length=256), nullable=False),
        sa.Column("response_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("run_snapshot", _jsonb(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{RUNS}"),
        *_owned(RUNS),
        _from_source(RUNS),
    )
    op.create_index(RUN_INDEX, RUNS, ["project_id", "started_at"])


def downgrade() -> None:
    op.drop_index(RUN_INDEX, table_name=RUNS)
    op.drop_table(RUNS)
    op.drop_table(SHOTS)
    op.drop_index(SOURCE_INDEX, table_name=SOURCES)
    op.drop_table(SOURCES)
