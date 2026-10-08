from alembic import op

revision = "0074_design_version_restore"
down_revision = "0073_knowledge_alignment"
branch_labels = None
depends_on = None

TABLE = "design_package_versions"
CONSTRAINT = "uq_design_package_versions_project_hash"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, TABLE, type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(CONSTRAINT, TABLE, ["project_id", "content_hash"])
