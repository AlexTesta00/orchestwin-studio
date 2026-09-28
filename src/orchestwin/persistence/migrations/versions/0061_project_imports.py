import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0061_project_imports"
down_revision = "0060_knowledge_package_versions"
branch_labels = None
depends_on = None

IMPORTS = "project_imports"
SOURCE_NAME_LIMIT = 200
OWNER_INDEX = f"ix_{IMPORTS}_owner_imported"
IMMUTABILITY_FUNCTION = "reject_project_import_mutation"
IMMUTABILITY_TRIGGER = f"trg_{IMPORTS}_immutable"
CREATE_FUNCTION = f"""
    CREATE FUNCTION {IMMUTABILITY_FUNCTION}()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION
            'Project imports are immutable';
    END;
    $$;
"""
CREATE_TRIGGER = f"""
    CREATE TRIGGER {IMMUTABILITY_TRIGGER}
    BEFORE UPDATE OR DELETE
    ON {IMPORTS}
    FOR EACH ROW
    EXECUTE FUNCTION {IMMUTABILITY_FUNCTION}();
"""
DROP_TRIGGER = f"DROP TRIGGER IF EXISTS {IMMUTABILITY_TRIGGER} ON {IMPORTS};"
DROP_FUNCTION = f"DROP FUNCTION IF EXISTS {IMMUTABILITY_FUNCTION}();"


def upgrade() -> None:
    op.create_table(
        IMPORTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_project_name", sa.String(length=SOURCE_NAME_LIMIT), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("package_content_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("archive_hash", sa.String(length=64), nullable=False),
        sa.Column("archive_size", sa.Integer(), nullable=False),
        sa.Column("stage_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{IMPORTS}"),
        sa.UniqueConstraint("project_id", name=f"uq_{IMPORTS}_project"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{IMPORTS}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{IMPORTS}_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("package_version >= 1", name=op.f(f"ck_{IMPORTS}_package_version")),
        sa.CheckConstraint("schema_version >= 1", name=op.f(f"ck_{IMPORTS}_schema_version")),
        sa.CheckConstraint("archive_size >= 1", name=op.f(f"ck_{IMPORTS}_archive_size")),
        sa.CheckConstraint(
            "package_content_hash ~ '^[0-9a-f]{64}$'",
            name=op.f(f"ck_{IMPORTS}_package_content_hash"),
        ),
        sa.CheckConstraint(
            "archive_hash ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{IMPORTS}_archive_hash")
        ),
        sa.CheckConstraint(
            f"char_length(source_project_name) BETWEEN 1 AND {SOURCE_NAME_LIMIT}",
            name=op.f(f"ck_{IMPORTS}_source_project_name"),
        ),
    )
    op.create_index(OWNER_INDEX, IMPORTS, ["owner_user_id", "imported_at"])
    op.execute(CREATE_FUNCTION)
    op.execute(CREATE_TRIGGER)


def downgrade() -> None:
    op.execute(DROP_TRIGGER)
    op.execute(DROP_FUNCTION)
    op.drop_index(OWNER_INDEX, table_name=IMPORTS)
    op.drop_table(IMPORTS)
