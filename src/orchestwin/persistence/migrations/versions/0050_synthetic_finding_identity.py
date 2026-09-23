from alembic import op

revision = "0050_synthetic_finding_identity"
down_revision = "0049_twin_evaluation_task"
branch_labels = None
depends_on = None

FINDINGS = "synthetic_findings"
PRIMARY_KEY = "pk_synthetic_findings"
IDENTITY = "uq_synthetic_findings_identity"


def upgrade():
    op.execute(f"ALTER TABLE {FINDINGS} DROP CONSTRAINT IF EXISTS {IDENTITY}")
    op.drop_constraint(PRIMARY_KEY, FINDINGS, type_="primary")
    op.create_primary_key(
        PRIMARY_KEY,
        FINDINGS,
        ["evaluation_run_id", "twin_id", "twin_version", "finding_id"],
    )


def downgrade():
    op.drop_constraint(PRIMARY_KEY, FINDINGS, type_="primary")
    op.create_primary_key(PRIMARY_KEY, FINDINGS, ["evaluation_run_id", "finding_id"])
