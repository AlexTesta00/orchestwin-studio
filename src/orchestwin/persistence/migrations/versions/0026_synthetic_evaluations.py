"""Persist append-only synthetic evaluation runs and findings.

Revision ID: 0026_synthetic_evaluations
Revises: 0025_workflow_events
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_synthetic_evaluations"
down_revision: str | None = "0025_workflow_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUNS = "evaluation_runs"
_FINDINGS = "synthetic_findings"
_RUN_FUNCTION = "reject_evaluation_run_mutation"
_FINDING_FUNCTION = "reject_synthetic_finding_mutation"
_RUN_TRIGGER = "trg_evaluation_runs_immutable"
_FINDING_TRIGGER = "trg_synthetic_findings_immutable"
_CRITERIA = (
    "'usefulness', 'comprehensibility', 'actionability', 'cognitive_load', "
    "'trust', 'accessibility', 'task_alignment'"
)
_SEVERITIES = "'critical', 'major', 'moderate', 'minor', 'observation'"
_EPISTEMIC_STATUSES = (
    "'USER_PROVIDED', 'EMPIRICALLY_SUPPORTED', 'HUMAN_VALIDATED', "
    "'MODEL_INFERRED', 'UNSUPPORTED_ASSUMPTION'"
)


def upgrade() -> None:
    """Create owner-scoped append-only evaluation storage."""
    op.create_table(
        _RUNS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_bundle_hash", sa.String(length=64), nullable=False),
        sa.Column("evaluator_id", sa.String(length=256), nullable=False),
        sa.Column("evaluator_version", sa.String(length=256), nullable=False),
        sa.Column("model_config_ref", sa.String(length=256), nullable=False),
        sa.Column("prompt_version_ref", sa.String(length=256), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_count", sa.Integer(), nullable=False),
        sa.Column("finding_count", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("run_snapshot_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_evaluation_runs"),
        sa.ForeignKeyConstraint(
            ["workflow_run_id", "project_id", "owner_user_id"],
            ["workflow_runs.id", "workflow_runs.project_id", "workflow_runs.owner_user_id"],
            name="fk_evaluation_runs_workflow_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "id",
            "project_id",
            "owner_user_id",
            name="uq_evaluation_runs_scope",
        ),
        sa.CheckConstraint("status = 'COMPLETED'", name="ck_evaluation_runs_status"),
        sa.CheckConstraint(
            "artifact_bundle_hash ~ '^[0-9a-f]{64}$'",
            name="ck_evaluation_runs_artifact_bundle_hash",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_evaluation_runs_content_hash",
        ),
        sa.CheckConstraint(
            "response_count BETWEEN 1 AND 4",
            name="ck_evaluation_runs_response_count",
        ),
        sa.CheckConstraint(
            "finding_count >= 0",
            name="ck_evaluation_runs_finding_count",
        ),
        sa.CheckConstraint(
            "char_length(run_snapshot_json) > 0",
            name="ck_evaluation_runs_snapshot",
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name="ck_evaluation_runs_time_order",
        ),
    )
    op.create_index(
        "ix_evaluation_runs_project_completed",
        _RUNS,
        ["project_id", "completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_evaluation_runs_workflow_completed",
        _RUNS,
        ["workflow_run_id", "completed_at"],
        unique=False,
    )

    op.create_table(
        _FINDINGS,
        sa.Column("evaluation_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("finding_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("twin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("twin_version", sa.Integer(), nullable=False),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("artifact_version", sa.Integer(), nullable=False),
        sa.Column("criterion", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("epistemic_status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("requires_human_validation", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("finding_snapshot_json", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint(
            "evaluation_run_id",
            "finding_id",
            name="pk_synthetic_findings",
        ),
        sa.ForeignKeyConstraint(
            ["evaluation_run_id", "project_id", "owner_user_id"],
            ["evaluation_runs.id", "evaluation_runs.project_id", "evaluation_runs.owner_user_id"],
            name="fk_synthetic_findings_evaluation_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "finding_id",
            name="uq_synthetic_findings_identity",
        ),
        sa.UniqueConstraint(
            "evaluation_run_id",
            "sequence_number",
            name="uq_synthetic_findings_sequence",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_synthetic_findings_sequence",
        ),
        sa.CheckConstraint(
            "twin_version >= 1",
            name="ck_synthetic_findings_twin_version",
        ),
        sa.CheckConstraint(
            "artifact_version >= 1",
            name="ck_synthetic_findings_artifact_version",
        ),
        sa.CheckConstraint(
            f"criterion IN ({_CRITERIA})",
            name="ck_synthetic_findings_criterion",
        ),
        sa.CheckConstraint(
            f"severity IN ({_SEVERITIES})",
            name="ck_synthetic_findings_severity",
        ),
        sa.CheckConstraint(
            f"epistemic_status IN ({_EPISTEMIC_STATUSES})",
            name="ck_synthetic_findings_epistemic_status",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_synthetic_findings_confidence",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_synthetic_findings_content_hash",
        ),
        sa.CheckConstraint(
            "char_length(finding_snapshot_json) > 0",
            name="ck_synthetic_findings_snapshot",
        ),
    )
    op.create_index(
        "ix_synthetic_findings_run_sequence",
        _FINDINGS,
        ["evaluation_run_id", "sequence_number"],
        unique=False,
    )
    op.create_index(
        "ix_synthetic_findings_project_severity",
        _FINDINGS,
        ["project_id", "severity"],
        unique=False,
    )
    op.create_index(
        "ix_synthetic_findings_twin",
        _FINDINGS,
        ["twin_id", "twin_version"],
        unique=False,
    )

    _create_immutable_trigger(
        table_name=_RUNS,
        function_name=_RUN_FUNCTION,
        trigger_name=_RUN_TRIGGER,
        message="evaluation runs are immutable",
    )
    _create_immutable_trigger(
        table_name=_FINDINGS,
        function_name=_FINDING_FUNCTION,
        trigger_name=_FINDING_TRIGGER,
        message="synthetic findings are immutable",
    )


def downgrade() -> None:
    """Remove synthetic evaluation storage after its mutation guards."""
    _drop_immutable_trigger(
        table_name=_FINDINGS,
        function_name=_FINDING_FUNCTION,
        trigger_name=_FINDING_TRIGGER,
    )
    _drop_immutable_trigger(
        table_name=_RUNS,
        function_name=_RUN_FUNCTION,
        trigger_name=_RUN_TRIGGER,
    )
    op.drop_index("ix_synthetic_findings_twin", table_name=_FINDINGS)
    op.drop_index("ix_synthetic_findings_project_severity", table_name=_FINDINGS)
    op.drop_index("ix_synthetic_findings_run_sequence", table_name=_FINDINGS)
    op.drop_table(_FINDINGS)
    op.drop_index("ix_evaluation_runs_workflow_completed", table_name=_RUNS)
    op.drop_index("ix_evaluation_runs_project_completed", table_name=_RUNS)
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
