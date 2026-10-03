import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0070_workflow_inputs"
down_revision = "0069_human_validation"
branch_labels = None
depends_on = None


def _team_constraints(owner_provided: bool) -> None:
    table = "team_proposals"
    op.drop_constraint("ck_team_proposals_revision_kind_valid", table, type_="check")
    op.drop_constraint("ck_team_proposals_revision_lineage_consistent", table, type_="check")
    kinds = "'PROPOSER_GENERATED', 'OWNER_EDITED'"
    initial = "revision_kind = 'PROPOSER_GENERATED'"
    if owner_provided:
        kinds += ", 'OWNER_PROVIDED'"
        initial = "revision_kind IN ('PROPOSER_GENERATED', 'OWNER_PROVIDED')"
    op.create_check_constraint(
        "ck_team_proposals_revision_kind_valid", table, f"revision_kind IN ({kinds})"
    )
    op.create_check_constraint(
        "ck_team_proposals_revision_lineage_consistent",
        table,
        f"({initial} AND based_on_version_number IS NULL) OR "
        "(revision_kind = 'OWNER_EDITED' AND based_on_version_number IS NOT NULL "
        "AND based_on_version_number < version_number)",
    )


def upgrade() -> None:
    _team_constraints(True)
    op.create_table(
        "project_workflow_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_project_workflow_decisions"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("project_id", "sequence", name="uq_project_workflow_decision_sequence"),
        sa.CheckConstraint(
            "sequence >= 1 AND content_hash ~ '^[a-f0-9]{64}$' AND jsonb_typeof(snapshot) = 'object'",
            name="ck_project_workflow_decision_identity",
        ),
    )
    op.create_table(
        "project_provided_prototypes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", "version_number", name="pk_project_provided_prototypes"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "project_id", "code", "version_number", name="uq_project_provided_prototype_code"
        ),
        sa.CheckConstraint(
            "version_number >= 1 AND content_hash ~ '^[a-f0-9]{64}$' AND code ~ '^PRT-[0-9]{3,6}$' AND jsonb_typeof(snapshot) = 'object'",
            name="ck_project_provided_prototype_identity",
        ),
    )
    for table in ("project_workflow_decisions", "project_provided_prototypes"):
        op.create_index(f"ix_{table}_project", table, ["project_id"])
    op.execute(
        "CREATE FUNCTION workflow_inputs_append_only() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'workflow inputs are append-only'; END $$"
    )
    for table in ("project_workflow_decisions", "project_provided_prototypes"):
        op.execute(
            sa.text(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION workflow_inputs_append_only()"
            )
        )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM project_workflow_decisions) OR EXISTS (SELECT 1 FROM project_provided_prototypes) OR EXISTS (SELECT 1 FROM team_proposals WHERE revision_kind = 'OWNER_PROVIDED')"
        )
    ):
        raise RuntimeError("owner workflow inputs must be preserved before downgrade")
    for table in ("project_provided_prototypes", "project_workflow_decisions"):
        op.drop_index(f"ix_{table}_project", table_name=table)
        op.drop_table(table)
    op.execute("DROP FUNCTION workflow_inputs_append_only()")
    _team_constraints(False)
