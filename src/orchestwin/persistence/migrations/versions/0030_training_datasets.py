"""Persist immutable evaluator dataset versions and quality evidence.

Revision ID: 0030_training_datasets
Revises: 0029_langgraph_pending_writes
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_training_datasets"
down_revision: str | None = "0029_langgraph_pending_writes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DATASETS = "training_dataset_versions"
_REPORTS = "training_dataset_quality_reports"
_DATASET_FUNCTION = "reject_training_dataset_version_mutation"
_REPORT_FUNCTION = "reject_training_dataset_quality_report_mutation"
_DATASET_TRIGGER = "trg_training_dataset_versions_immutable"
_REPORT_TRIGGER = "trg_training_dataset_quality_reports_immutable"


def upgrade() -> None:
    """Create owner-scoped append-only dataset metadata storage."""
    op.create_table(
        _DATASETS,
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("based_on_version_number", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_content_hash", sa.String(length=64), nullable=False),
        sa.Column("examples_digest", sa.String(length=64), nullable=False),
        sa.Column("example_count", sa.Integer(), nullable=False),
        sa.Column("publishable", sa.Boolean(), nullable=False),
        sa.Column("manifest_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint(
            "dataset_id",
            "version_number",
            name="pk_training_dataset_versions",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name="fk_training_dataset_versions_owner_user_id_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "version_number",
            "owner_user_id",
            name="uq_training_dataset_versions_scope",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name="ck_training_dataset_versions_version_positive",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_dataset_versions_content_hash",
        ),
        sa.CheckConstraint(
            "policy_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_dataset_versions_policy_hash",
        ),
        sa.CheckConstraint(
            "examples_digest ~ '^[0-9a-f]{64}$'",
            name="ck_training_dataset_versions_examples_digest",
        ),
        sa.CheckConstraint(
            "example_count >= 1",
            name="ck_training_dataset_versions_example_count",
        ),
        sa.CheckConstraint(
            "char_length(manifest_snapshot_json) > 0",
            name="ck_training_dataset_versions_snapshot",
        ),
    )
    op.create_index(
        "ix_training_dataset_versions_owner_created",
        _DATASETS,
        ["owner_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_training_dataset_versions_owner_hash",
        _DATASETS,
        ["owner_user_id", "content_hash"],
        unique=False,
    )

    op.create_table(
        _REPORTS,
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dataset_version_number", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("excluded_count", sa.Integer(), nullable=False),
        sa.Column("leakage_issue_count", sa.Integer(), nullable=False),
        sa.Column("publishable", sa.Boolean(), nullable=False),
        sa.Column("report_snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_training_dataset_quality_reports"),
        sa.ForeignKeyConstraint(
            ["dataset_id", "dataset_version_number", "owner_user_id"],
            [
                "training_dataset_versions.dataset_id",
                "training_dataset_versions.version_number",
                "training_dataset_versions.owner_user_id",
            ],
            name="fk_training_dataset_quality_reports_dataset_scope",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "dataset_version_number",
            name="uq_training_dataset_quality_reports_dataset_version",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_training_dataset_quality_reports_content_hash",
        ),
        sa.CheckConstraint(
            "candidate_count >= 1",
            name="ck_training_dataset_quality_reports_candidate_count",
        ),
        sa.CheckConstraint(
            "accepted_count >= 1",
            name="ck_training_dataset_quality_reports_accepted_count",
        ),
        sa.CheckConstraint(
            "duplicate_count >= 0",
            name="ck_training_dataset_quality_reports_duplicate_count",
        ),
        sa.CheckConstraint(
            "excluded_count >= 0",
            name="ck_training_dataset_quality_reports_excluded_count",
        ),
        sa.CheckConstraint(
            "leakage_issue_count >= 0",
            name="ck_training_dataset_quality_reports_leakage_count",
        ),
        sa.CheckConstraint(
            "char_length(report_snapshot_json) > 0",
            name="ck_training_dataset_quality_reports_snapshot",
        ),
    )
    op.create_index(
        "ix_training_dataset_quality_reports_owner_created",
        _REPORTS,
        ["owner_user_id", "created_at"],
        unique=False,
    )

    _create_immutable_trigger(
        table_name=_DATASETS,
        function_name=_DATASET_FUNCTION,
        trigger_name=_DATASET_TRIGGER,
        message="training dataset versions are immutable",
    )
    _create_immutable_trigger(
        table_name=_REPORTS,
        function_name=_REPORT_FUNCTION,
        trigger_name=_REPORT_TRIGGER,
        message="training dataset quality reports are immutable",
    )


def downgrade() -> None:
    """Remove dataset metadata after its immutability guards."""
    _drop_immutable_trigger(
        table_name=_REPORTS,
        function_name=_REPORT_FUNCTION,
        trigger_name=_REPORT_TRIGGER,
    )
    _drop_immutable_trigger(
        table_name=_DATASETS,
        function_name=_DATASET_FUNCTION,
        trigger_name=_DATASET_TRIGGER,
    )
    op.drop_index("ix_training_dataset_quality_reports_owner_created", table_name=_REPORTS)
    op.drop_table(_REPORTS)
    op.drop_index("ix_training_dataset_versions_owner_hash", table_name=_DATASETS)
    op.drop_index("ix_training_dataset_versions_owner_created", table_name=_DATASETS)
    op.drop_table(_DATASETS)


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
