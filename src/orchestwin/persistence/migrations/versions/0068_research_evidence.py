import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0068_research_evidence"
down_revision = "0067_claude_code_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_evidence_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_reason", sa.String(300), nullable=True),
        sa.PrimaryKeyConstraint("id", "version", name="pk_research_evidence_versions"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "code", "version", name="uq_research_evidence_code"),
        sa.CheckConstraint(
            "version >= 1 AND byte_count BETWEEN 1 AND 32768", name="ck_research_evidence_counts"
        ),
    )
    op.create_index("ix_research_evidence_project", "research_evidence_versions", ["project_id"])
    op.create_table(
        "research_evidence_texts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", "version", name="pk_research_evidence_texts"),
        sa.ForeignKeyConstraint(
            ["id", "version"],
            ["research_evidence_versions.id", "research_evidence_versions.version"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 24000 AND octet_length(text) <= 32768",
            name="ck_research_evidence_text_size",
        ),
    )
    op.create_table(
        "research_evidence_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_version", sa.Integer(), nullable=False),
        sa.Column("update_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("field", sa.String(64), nullable=False),
        sa.Column("change", postgresql.JSONB(), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=True),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_research_evidence_changes"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["update_id"], ["twin_updates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["source_id", "source_version"],
            ["research_evidence_versions.id", "research_evidence_versions.version"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_research_evidence_changes_project",
        "research_evidence_changes",
        ["project_id", "twin_id"],
    )
    op.add_column("twin_updates", sa.Column("evidence", postgresql.JSONB(), nullable=True))
    op.drop_constraint(op.f("ck_twin_updates_material"), "twin_updates", type_="check")
    op.create_check_constraint(
        op.f("ck_twin_updates_material"),
        "twin_updates",
        "material_changes BETWEEN 0 AND 8 AND material_tests BETWEEN 0 AND 4 AND (material_changes + material_tests >= 1 OR evidence IS NOT NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM research_evidence_versions) OR EXISTS (SELECT 1 FROM twin_updates WHERE evidence IS NOT NULL)"
        )
    ):
        raise RuntimeError("research evidence must be preserved before downgrade")
    op.drop_constraint(op.f("ck_twin_updates_material"), "twin_updates", type_="check")
    op.create_check_constraint(
        op.f("ck_twin_updates_material"),
        "twin_updates",
        "material_changes BETWEEN 0 AND 8 AND material_tests BETWEEN 0 AND 4 AND material_changes + material_tests >= 1",
    )
    op.drop_column("twin_updates", "evidence")
    op.drop_index("ix_research_evidence_changes_project", table_name="research_evidence_changes")
    op.drop_table("research_evidence_changes")
    op.drop_table("research_evidence_texts")
    op.drop_index("ix_research_evidence_project", table_name="research_evidence_versions")
    op.drop_table("research_evidence_versions")
