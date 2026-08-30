"""Persist durable workflow runs and append-only checkpoints.

Revision ID: 0024_workflow_runs_checkpoints
Revises: 0023_jvm_execution_attempts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024_workflow_runs_checkpoints"
down_revision: str | None = "0023_jvm_execution_attempts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS = "workflow_runs"
_CHECKPOINTS = "workflow_checkpoints"
_GRAPH_CHECKPOINTS = "workflow_graph_checkpoints"
_GRAPH_WRITES = "workflow_graph_writes"
_TRIGGER = "trg_workflow_checkpoints_immutable"
_FUNCTION = "reject_workflow_checkpoint_mutation"


def upgrade() -> None:
    """Create owner-scoped current run state and immutable checkpoint history."""
    op.create_table(
        _RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_mode", sa.String(length=32), nullable=False),
        sa.Column("current_stage", sa.String(length=48), nullable=False),
        sa.Column("status", sa.String(length=48), nullable=False),
        sa.Column("resume_status", sa.String(length=48), nullable=True),
        sa.Column("pending_gate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("state_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_runs"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_workflow_runs_project",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_workflow_runs_owner",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "owner_user_id",
            name="uq_workflow_runs_scope",
        ),
        sa.CheckConstraint(
            "project_mode IN ('GREENFIELD_GENERATION', 'BROWNFIELD_ASSESSMENT')",
            name="ck_workflow_runs_project_mode",
        ),
        sa.CheckConstraint("state_version >= 1", name="ck_workflow_runs_state_version"),
        sa.CheckConstraint(
            "checkpoint_sequence >= 0",
            name="ck_workflow_runs_checkpoint_sequence",
        ),
        sa.CheckConstraint(
            "state_hash ~ '^[0-9a-f]{64}$'",
            name="ck_workflow_runs_state_hash",
        ),
        sa.CheckConstraint(
            "char_length(state_snapshot_json) > 0",
            name="ck_workflow_runs_snapshot",
        ),
    )
    op.create_index(
        "ix_workflow_runs_project_updated",
        _RUNS,
        ["project_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_workflow_runs_owner_status",
        _RUNS,
        ["owner_user_id", "status"],
        unique=False,
    )

    op.create_table(
        _CHECKPOINTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("parent_checkpoint_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_workflow_checkpoints"),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            [f"{_RUNS}.id", f"{_RUNS}.project_id", f"{_RUNS}.owner_user_id"],
            name="fk_workflow_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "parent_checkpoint_id"],
            [f"{_CHECKPOINTS}.run_id", f"{_CHECKPOINTS}.id"],
            name="fk_workflow_checkpoints_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id",
            "sequence_number",
            name="uq_workflow_checkpoints_sequence",
        ),
        sa.UniqueConstraint("run_id", "id", name="uq_workflow_checkpoints_run_id"),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_workflow_checkpoints_sequence",
        ),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_workflow_checkpoints_schema_version",
        ),
        sa.CheckConstraint(
            "state_version >= 1",
            name="ck_workflow_checkpoints_state_version",
        ),
        sa.CheckConstraint(
            "state_hash ~ '^[0-9a-f]{64}$'",
            name="ck_workflow_checkpoints_state_hash",
        ),
        sa.CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="ck_workflow_checkpoints_payload_hash",
        ),
        sa.CheckConstraint(
            "(sequence_number = 1 AND parent_checkpoint_id IS NULL) OR "
            "(sequence_number > 1 AND parent_checkpoint_id IS NOT NULL)",
            name="ck_workflow_checkpoints_lineage",
        ),
    )
    op.create_index(
        "ix_workflow_checkpoints_run_sequence",
        _CHECKPOINTS,
        ["run_id", "sequence_number"],
        unique=False,
    )
    op.create_table(
        _GRAPH_CHECKPOINTS,
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_namespace", sa.String(length=256), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_checkpoint_id", sa.String(length=64), nullable=True),
        sa.Column("checkpoint_type", sa.String(length=64), nullable=False),
        sa.Column("checkpoint_blob", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_type", sa.String(length=64), nullable=False),
        sa.Column("metadata_blob", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
            name="pk_workflow_graph_checkpoints",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "project_id", "owner_user_id"],
            [f"{_RUNS}.id", f"{_RUNS}.project_id", f"{_RUNS}.owner_user_id"],
            name="fk_workflow_graph_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
            name="uq_workflow_graph_checkpoints_identity",
        ),
    )
    op.create_index(
        "ix_workflow_graph_checkpoints_latest",
        _GRAPH_CHECKPOINTS,
        ["run_id", "checkpoint_namespace", "checkpoint_id"],
        unique=False,
    )
    op.create_table(
        _GRAPH_WRITES,
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checkpoint_namespace", sa.String(length=256), nullable=False),
        sa.Column("checkpoint_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("write_index", sa.Integer(), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_path", sa.String(length=512), nullable=False),
        sa.Column("channel", sa.String(length=256), nullable=False),
        sa.Column("value_type", sa.String(length=64), nullable=False),
        sa.Column("value_blob", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint(
            "run_id",
            "checkpoint_namespace",
            "checkpoint_id",
            "task_id",
            "write_index",
            name="pk_workflow_graph_writes",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "checkpoint_namespace", "checkpoint_id"],
            [
                f"{_GRAPH_CHECKPOINTS}.run_id",
                f"{_GRAPH_CHECKPOINTS}.checkpoint_namespace",
                f"{_GRAPH_CHECKPOINTS}.checkpoint_id",
            ],
            name="fk_workflow_graph_writes_checkpoint",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_workflow_graph_writes_checkpoint",
        _GRAPH_WRITES,
        ["run_id", "checkpoint_namespace", "checkpoint_id"],
        unique=False,
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'workflow checkpoints are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_CHECKPOINTS}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )


def downgrade() -> None:
    """Remove checkpoint and workflow-run persistence."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_CHECKPOINTS};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index("ix_workflow_graph_writes_checkpoint", table_name=_GRAPH_WRITES)
    op.drop_table(_GRAPH_WRITES)
    op.drop_index("ix_workflow_graph_checkpoints_latest", table_name=_GRAPH_CHECKPOINTS)
    op.drop_table(_GRAPH_CHECKPOINTS)
    op.drop_index("ix_workflow_checkpoints_run_sequence", table_name=_CHECKPOINTS)
    op.drop_table(_CHECKPOINTS)
    op.drop_index("ix_workflow_runs_owner_status", table_name=_RUNS)
    op.drop_index("ix_workflow_runs_project_updated", table_name=_RUNS)
    op.drop_table(_RUNS)
