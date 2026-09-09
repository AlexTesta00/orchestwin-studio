"""Persist exact static inspection plans and single-use execution claims."""

import sqlalchemy as sa
from alembic import op

revision = "0032_static_browser_inspections"
down_revision = "0031_training_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "static_browser_inspections",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column(
            "project_id", sa.Uuid, sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "owner_user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "source_revision_id",
            sa.Uuid,
            sa.ForeignKey("web_source_revisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "gate_id",
            sa.Uuid,
            sa.ForeignKey("human_gates.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("job_hash", sa.String(64), nullable=False),
        sa.Column("plan_json", sa.Text, nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result_json", sa.Text),
        sa.Column("result_hash", sa.String(64)),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="state_valid"
        ),
        sa.CheckConstraint(
            "plan_hash ~ '^[0-9a-f]{64}$' AND job_hash ~ '^[0-9a-f]{64}$'", name="hashes_valid"
        ),
        sa.CheckConstraint("octet_length(plan_json) BETWEEN 1 AND 5242880", name="plan_size_valid"),
        sa.CheckConstraint(
            "(state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR "
            "(state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR "
            "(state IN ('COMPLETED', 'FAILED') AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_hash IS NOT NULL)",
            name="lifecycle_consistent",
        ),
        sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="start_order"),
        sa.CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="finish_order"),
    )
    op.create_index(
        "ix_static_browser_inspections_project_created",
        "static_browser_inspections",
        ["project_id", "created_at"],
    )
    op.execute("""
        CREATE FUNCTION protect_static_browser_inspection() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'static inspection audit records are not deletable';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['state','started_at','finished_at','result_json','result_hash'])
                IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['state','started_at','finished_at','result_json','result_hash']) THEN
                RAISE EXCEPTION 'static inspection plans are immutable';
            END IF;
            IF NOT ((OLD.state = 'PENDING' AND NEW.state = 'RUNNING') OR
                    (OLD.state = 'RUNNING' AND NEW.state IN ('COMPLETED','FAILED')
                     AND NEW.started_at = OLD.started_at)) THEN
                RAISE EXCEPTION 'static inspection transition is forbidden';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER static_browser_inspection_guard
        BEFORE UPDATE OR DELETE ON static_browser_inspections
        FOR EACH ROW EXECUTE FUNCTION protect_static_browser_inspection()
    """)


def downgrade() -> None:
    op.drop_table("static_browser_inspections")
    op.execute("DROP FUNCTION protect_static_browser_inspection()")
