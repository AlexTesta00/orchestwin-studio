"""Persist immutable QLoRA training runs and checkpoint evidence.

Revision ID: 0031_training_runs
Revises: 0030_training_datasets
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_training_runs"
down_revision: str | None = "0030_training_datasets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS = "training_runs"
_CHECKPOINTS = "training_run_checkpoints"
_RUN_FUNCTION = "reject_training_run_mutation"
_CHECKPOINT_FUNCTION = "reject_training_run_checkpoint_mutation"
_RUN_TRIGGER = "trg_training_runs_immutable"
_CHECKPOINT_TRIGGER = "trg_training_run_checkpoints_immutable"


def upgrade() -> None:
    """Create owner-scoped append-only training evidence storage."""
    op.create_table(
        _RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_version_number", sa.Integer(), nullable=False),
        sa.Column("dataset_content_hash", sa.String(length=64), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("configuration_sha256", sa.String(length=64), nullable=False),
        sa.Column("package_lock_sha256", sa.String(length=64), nullable=False),
        sa.Column("environment_sha256", sa.String(length=64), nullable=False),
        sa.Column("process_log_relative_path", sa.String(length=512), nullable=False),
        sa.Column("process_log_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_milliseconds", sa.Integer(), nullable=False),
        sa.Column("peak_gpu_memory_mb", sa.Integer(), nullable=True),
        sa.Column("metric_count", sa.Integer(), nullable=False),
        sa.Column("checkpoint_count", sa.Integer(), nullable=False),
        sa.Column("adapter_relative_path", sa.String(length=512), nullable=True),
        sa.Column("adapter_sha256", sa.String(length=64), nullable=True),
        sa.Column("failure_kind", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome_snapshot_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_training_runs"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_training_runs_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id", "dataset_version_number", "owner_user_id"],
            [
                "training_dataset_versions.dataset_id",
                "training_dataset_versions.version_number",
                "training_dataset_versions.owner_user_id",
            ],
            name="fk_training_runs_dataset_scope",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "owner_user_id", name="uq_training_runs_owner_scope"),
        sa.UniqueConstraint("content_hash", name="uq_training_runs_content_hash"),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_request_hash",
        ),
        sa.CheckConstraint(
            "configuration_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_configuration_hash",
        ),
        sa.CheckConstraint(
            "dataset_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_dataset_hash",
        ),
        sa.CheckConstraint(
            "package_lock_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_package_lock_hash",
        ),
        sa.CheckConstraint(
            "environment_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_environment_hash",
        ),
        sa.CheckConstraint(
            "process_log_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_process_log_hash",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_runs_content_hash",
        ),
        sa.CheckConstraint(
            "duration_milliseconds >= 0",
            name="ck_training_runs_duration_non_negative",
        ),
        sa.CheckConstraint(
            "peak_gpu_memory_mb IS NULL OR peak_gpu_memory_mb >= 0",
            name="ck_training_runs_peak_memory_non_negative",
        ),
        sa.CheckConstraint(
            "metric_count >= 0",
            name="ck_training_runs_metric_count_non_negative",
        ),
        sa.CheckConstraint(
            "checkpoint_count >= 0",
            name="ck_training_runs_checkpoint_count_non_negative",
        ),
        sa.CheckConstraint(
            "char_length(outcome_snapshot_json) > 0",
            name="ck_training_runs_snapshot_required",
        ),
    )
    op.create_index(
        "ix_training_runs_owner_started",
        _RUNS,
        ["owner_user_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "ix_training_runs_owner_dataset",
        _RUNS,
        ["owner_user_id", "dataset_id", "dataset_version_number"],
        unique=False,
    )

    op.create_table(
        _CHECKPOINTS,
        sa.Column("training_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("relative_path", sa.String(length=512), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint(
            "training_run_id",
            "step",
            name="pk_training_run_checkpoints",
        ),
        sa.ForeignKeyConstraint(
            ["training_run_id", "owner_user_id"],
            ["training_runs.id", "training_runs.owner_user_id"],
            name="fk_training_run_checkpoints_run_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "training_run_id",
            "relative_path",
            name="uq_training_run_checkpoints_path",
        ),
        sa.CheckConstraint(
            "step >= 1",
            name="ck_training_run_checkpoints_step_positive",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_training_run_checkpoints_content_hash",
        ),
    )
    op.create_index(
        "ix_training_run_checkpoints_owner_run",
        _CHECKPOINTS,
        ["owner_user_id", "training_run_id"],
        unique=False,
    )

    _create_immutable_trigger(
        table_name=_RUNS,
        function_name=_RUN_FUNCTION,
        trigger_name=_RUN_TRIGGER,
        message="training runs are immutable",
    )
    _create_immutable_trigger(
        table_name=_CHECKPOINTS,
        function_name=_CHECKPOINT_FUNCTION,
        trigger_name=_CHECKPOINT_TRIGGER,
        message="training run checkpoints are immutable",
    )


def downgrade() -> None:
    """Remove training run evidence after its immutability guards."""
    _drop_immutable_trigger(
        table_name=_CHECKPOINTS,
        function_name=_CHECKPOINT_FUNCTION,
        trigger_name=_CHECKPOINT_TRIGGER,
    )
    _drop_immutable_trigger(
        table_name=_RUNS,
        function_name=_RUN_FUNCTION,
        trigger_name=_RUN_TRIGGER,
    )
    op.drop_index("ix_training_run_checkpoints_owner_run", table_name=_CHECKPOINTS)
    op.drop_table(_CHECKPOINTS)
    op.drop_index("ix_training_runs_owner_dataset", table_name=_RUNS)
    op.drop_index("ix_training_runs_owner_started", table_name=_RUNS)
    op.drop_table(_RUNS)


def _create_immutable_trigger(
    *,
    table_name: str,
    function_name: str,
    trigger_name: str,
    message: str,
) -> None:
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {function_name}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '{message}';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
        BEFORE UPDATE OR DELETE ON {table_name}
        FOR EACH ROW EXECUTE FUNCTION {function_name}();
        """
    )


def _drop_immutable_trigger(
    *,
    table_name: str,
    function_name: str,
    trigger_name: str,
) -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name};")
    op.execute(f"DROP FUNCTION IF EXISTS {function_name}();")
