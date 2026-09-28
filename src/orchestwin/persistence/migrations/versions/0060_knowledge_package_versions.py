import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0060_knowledge_package_versions"
down_revision = "0059_twin_discussions"
branch_labels = None
depends_on = None

PACKAGES = "knowledge_package_versions"
FILE_NAME_LIMIT = 200
ARCHIVE_LIMIT = 64 * 1024 * 1024
PROJECT_INDEX = f"ix_{PACKAGES}_project_created"
IMMUTABILITY_FUNCTION = "reject_knowledge_package_version_mutation"
IMMUTABILITY_TRIGGER = f"trg_{PACKAGES}_immutable"
CREATE_FUNCTION = f"""
    CREATE FUNCTION {IMMUTABILITY_FUNCTION}()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION
            'Knowledge package versions are immutable';
    END;
    $$;
"""
CREATE_TRIGGER = f"""
    CREATE TRIGGER {IMMUTABILITY_TRIGGER}
    BEFORE UPDATE OR DELETE
    ON {PACKAGES}
    FOR EACH ROW
    EXECUTE FUNCTION {IMMUTABILITY_FUNCTION}();
"""
DROP_TRIGGER = f"DROP TRIGGER IF EXISTS {IMMUTABILITY_TRIGGER} ON {PACKAGES};"
DROP_FUNCTION = f"DROP FUNCTION IF EXISTS {IMMUTABILITY_FUNCTION}();"


def upgrade() -> None:
    op.create_table(
        PACKAGES,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("archive_hash", sa.String(length=64), nullable=False),
        sa.Column("file_name", sa.String(length=FILE_NAME_LIMIT), nullable=False),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("archive_size", sa.Integer(), nullable=False),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("archive", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{PACKAGES}"),
        sa.UniqueConstraint("project_id", "version_number", name=f"uq_{PACKAGES}_project_version"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=f"fk_{PACKAGES}_project", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name=f"fk_{PACKAGES}_owner", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("version_number >= 1", name=op.f(f"ck_{PACKAGES}_version_number")),
        sa.CheckConstraint("schema_version >= 1", name=op.f(f"ck_{PACKAGES}_schema_version")),
        sa.CheckConstraint("file_count >= 1", name=op.f(f"ck_{PACKAGES}_file_count")),
        sa.CheckConstraint(
            f"archive_size BETWEEN 1 AND {ARCHIVE_LIMIT}", name=op.f(f"ck_{PACKAGES}_archive_size")
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{PACKAGES}_content_hash")
        ),
        sa.CheckConstraint(
            "archive_hash ~ '^[0-9a-f]{64}$'", name=op.f(f"ck_{PACKAGES}_archive_hash")
        ),
        sa.CheckConstraint(
            "octet_length(archive) = archive_size", name=op.f(f"ck_{PACKAGES}_archive_length")
        ),
        sa.CheckConstraint(
            f"char_length(file_name) BETWEEN 1 AND {FILE_NAME_LIMIT}",
            name=op.f(f"ck_{PACKAGES}_file_name"),
        ),
    )
    op.create_index(PROJECT_INDEX, PACKAGES, ["project_id", "created_at"])
    op.execute(CREATE_FUNCTION)
    op.execute(CREATE_TRIGGER)


def downgrade() -> None:
    op.execute(DROP_TRIGGER)
    op.execute(DROP_FUNCTION)
    op.drop_index(PROJECT_INDEX, table_name=PACKAGES)
    op.drop_table(PACKAGES)
