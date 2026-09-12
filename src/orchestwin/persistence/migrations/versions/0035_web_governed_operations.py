"""Persist exact Web Gate 7 operations and single-use execution claims.

Revision ID: 0035_web_governed_operations
Revises: 0034_web_validation_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0035_web_governed_operations"
down_revision: str | None = "0034_web_validation_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "web_governed_operations"
_FUNCTION = "protect_web_governed_operation"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_revision_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_content_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "gate_id",
            sa.Uuid(),
            sa.ForeignKey("human_gates.id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("result_json", sa.Text()),
        sa.Column("result_content_hash", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["project_id", "source_revision_id"],
            ["web_source_revisions.project_id", "web_source_revisions.id"],
            ondelete="RESTRICT",
            name="fk_web_governed_operations_source",
        ),
        sa.CheckConstraint("kind IN ('EXECUTION', 'REPAIR')", name="kind_valid"),
        sa.CheckConstraint(
            "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="state_valid"
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$' AND payload_content_hash ~ '^[0-9a-f]{64}$'",
            name="hashes_valid",
        ),
        sa.CheckConstraint(
            "octet_length(payload_json) BETWEEN 1 AND 4194304", name="payload_bounded"
        ),
        sa.CheckConstraint("jsonb_typeof(payload_json::jsonb) = 'object'", name="payload_object"),
        sa.CheckConstraint(
            "result_json IS NULL OR (octet_length(result_json) BETWEEN 1 AND 4194304 AND jsonb_typeof(result_json::jsonb) = 'object')",
            name="result_bounded",
        ),
        sa.CheckConstraint(
            "result_content_hash IS NULL OR result_content_hash ~ '^[0-9a-f]{64}$'",
            name="result_hash_valid",
        ),
        sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="started_order"),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)",
            name="finished_order",
        ),
        sa.CheckConstraint(
            "(state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR "
            "(state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR "
            "(state = 'COMPLETED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL) OR "
            "(state = 'FAILED' AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL AND "
            "(started_at IS NOT NULL OR result_json::jsonb = jsonb_build_object('failure_code', 'WEB_OPERATION_CANCELLED', 'execution_started', false)))",
            name="lifecycle_valid",
        ),
    )
    op.create_index(
        "ix_web_governed_operations_project_created", _TABLE, ["project_id", "created_at"]
    )
    op.create_index(
        "uq_web_governed_operations_project_running",
        _TABLE,
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("state = 'RUNNING'"),
    )
    op.execute("""
        CREATE FUNCTION protect_web_governed_operation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION 'Web operation audit records cannot be deleted or truncated';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id OR NEW.project_id IS DISTINCT FROM OLD.project_id OR
               NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id OR NEW.source_revision_id IS DISTINCT FROM OLD.source_revision_id OR
               NEW.kind IS DISTINCT FROM OLD.kind OR NEW.payload_json IS DISTINCT FROM OLD.payload_json OR
               NEW.payload_content_hash IS DISTINCT FROM OLD.payload_content_hash OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR
               NEW.gate_id IS DISTINCT FROM OLD.gate_id OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                RAISE EXCEPTION 'Web operation approval inputs are immutable';
            END IF;
            IF NOT ((OLD.state = 'PENDING' AND NEW.state = 'RUNNING') OR
                    (OLD.state = 'PENDING' AND NEW.state = 'FAILED' AND NEW.started_at IS NULL) OR
                    (OLD.state = 'RUNNING' AND NEW.state IN ('COMPLETED', 'FAILED') AND NEW.started_at = OLD.started_at)) THEN
                RAISE EXCEPTION 'Web operation lifecycle transition is forbidden';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        f"CREATE TRIGGER web_governed_operation_guard BEFORE UPDATE OR DELETE ON {_TABLE} FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}()"
    )
    op.execute(
        f"CREATE TRIGGER web_governed_operation_no_truncate BEFORE TRUNCATE ON {_TABLE} FOR EACH STATEMENT EXECUTE FUNCTION {_FUNCTION}()"
    )


def downgrade() -> None:
    op.execute(f"DROP TRIGGER web_governed_operation_guard ON {_TABLE}")
    op.execute(f"DROP TRIGGER web_governed_operation_no_truncate ON {_TABLE}")
    op.execute(f"DROP FUNCTION {_FUNCTION}()")
    op.drop_table(_TABLE)
