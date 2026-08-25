"""Persist immutable sandbox runs, command results, logs, and artifact references.

Revision ID: 0018_sandbox_runs
Revises: 0017_brownfield_intake
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_sandbox_runs"
down_revision: str | None = "0017_brownfield_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS_TABLE = "sandbox_runs"
_COMMANDS_TABLE = "sandbox_command_results"
_RUNS_TRIGGER = "trg_sandbox_runs_immutable"
_COMMANDS_TRIGGER = "trg_sandbox_command_results_immutable"
_FUNCTION = "reject_sandbox_evidence_mutation"


def upgrade() -> None:
    """Create append-only owner-scoped sandbox evidence storage."""
    op.create_table(
        _RUNS_TABLE,
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intake_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("intake_version_number", sa.Integer(), nullable=True),
        sa.Column("intake_content_hash", sa.String(length=64), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("evidence_content_hash", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=128), nullable=False),
        sa.Column("plan_content_hash", sa.String(length=64), nullable=False),
        sa.Column("profile_id", sa.String(length=128), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("image_reference", sa.Text(), nullable=False),
        sa.Column("runtime_reference", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column(
            "evidence_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("run_id", name="pk_sandbox_runs"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_sandbox_runs_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["intake_id"],
            ["brownfield_intake_versions.id"],
            name="fk_sandbox_runs_intake",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_sandbox_runs_creator",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_sandbox_runs_positive_schema",
        ),
        sa.CheckConstraint(
            "evidence_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sandbox_runs_evidence_content_hash",
        ),
        sa.CheckConstraint(
            "plan_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sandbox_runs_plan_content_hash",
        ),
        sa.CheckConstraint(
            "intake_content_hash IS NULL OR intake_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sandbox_runs_intake_content_hash",
        ),
        sa.CheckConstraint(
            "(intake_id IS NULL AND intake_version_number IS NULL "
            "AND intake_content_hash IS NULL) OR "
            "(intake_id IS NOT NULL AND intake_version_number > 0 "
            "AND intake_content_hash IS NOT NULL)",
            name="ck_sandbox_runs_intake_reference_shape",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="ck_sandbox_runs_time_range",
        ),
        sa.CheckConstraint(
            "recorded_at >= finished_at",
            name="ck_sandbox_runs_recording_time",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'SUCCEEDED', 'FAILED', 'TIMED_OUT', "
            "'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR'"
            ")",
            name="ck_sandbox_runs_status",
        ),
    )
    op.create_table(
        _COMMANDS_TABLE,
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("command_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output_parser_id", sa.String(length=128), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("stdout_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("stderr_log", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint(
            "run_id",
            "ordinal",
            name="pk_sandbox_command_results",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["sandbox_runs.run_id"],
            name="fk_sandbox_command_results_run",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id",
            "command_id",
            name="uq_sandbox_command_results_run_command",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_sandbox_command_results_ordinal",
        ),
        sa.CheckConstraint(
            "finished_at >= started_at",
            name="ck_sandbox_command_results_time_range",
        ),
        sa.CheckConstraint(
            "exit_code IS NULL OR exit_code BETWEEN 0 AND 255",
            name="ck_sandbox_command_results_exit_code",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'SUCCEEDED', 'FAILED', 'TIMED_OUT', "
            "'RESOURCE_LIMIT_EXCEEDED', 'CANCELLED', 'RUNTIME_ERROR'"
            ")",
            name="ck_sandbox_command_results_status",
        ),
    )
    op.create_index(
        "ix_sandbox_runs_project_recorded",
        _RUNS_TABLE,
        ["project_id", "recorded_at"],
        unique=False,
    )
    op.create_index(
        "ix_sandbox_command_results_run_ordinal",
        _COMMANDS_TABLE,
        ["run_id", "ordinal"],
        unique=False,
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'sandbox run evidence is immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_RUNS_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_RUNS_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_COMMANDS_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_COMMANDS_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )


def downgrade() -> None:
    """Remove immutable sandbox evidence after both mutation guards."""
    op.execute(f"DROP TRIGGER IF EXISTS {_COMMANDS_TRIGGER} ON {_COMMANDS_TABLE};")
    op.execute(f"DROP TRIGGER IF EXISTS {_RUNS_TRIGGER} ON {_RUNS_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index(
        "ix_sandbox_command_results_run_ordinal",
        table_name=_COMMANDS_TABLE,
    )
    op.drop_index(
        "ix_sandbox_runs_project_recorded",
        table_name=_RUNS_TABLE,
    )
    op.drop_table(_COMMANDS_TABLE)
    op.drop_table(_RUNS_TABLE)
