"""Persist owner-reviewed User Twin profile diffs.

Revision ID: 0010_user_twin_profile_diffs
Revises: 0009_user_modeling_snapshots
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_user_twin_profile_diffs"
down_revision: str | None = "0009_user_modeling_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "user_twin_profile_diffs"


def upgrade() -> None:
    """Create reviewable User Twin profile-diff persistence."""
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_snapshot_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_snapshot_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "base_snapshot_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "twin_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_twin_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_twin_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "base_twin_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "proposal_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "diff_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "decided_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "decided_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "decision_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "applied_snapshot_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_user_twin_profile_diffs",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_user_twin_profile_diffs_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_snapshot_version_id"],
            ["user_modeling_snapshot_versions.id"],
            name=("fk_user_twin_profile_diffs_base_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_twin_version_id"],
            ["user_twin_profile_versions.id"],
            name=("fk_user_twin_profile_diffs_base_twin"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["applied_snapshot_version_id"],
            ["user_modeling_snapshot_versions.id"],
            name=("fk_user_twin_profile_diffs_applied_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "base_snapshot_version_number > 0",
            name=("ck_user_twin_profile_diffs_positive_snapshot_version"),
        ),
        sa.CheckConstraint(
            "base_twin_version_number > 0",
            name=("ck_user_twin_profile_diffs_positive_twin_version"),
        ),
        sa.CheckConstraint(
            ("base_snapshot_content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_twin_profile_diffs_snapshot_hash"),
        ),
        sa.CheckConstraint(
            ("base_twin_content_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_twin_profile_diffs_twin_hash"),
        ),
        sa.CheckConstraint(
            ("proposal_hash ~ '^[0-9a-f]{64}$'"),
            name=("ck_user_twin_profile_diffs_proposal_hash"),
        ),
        sa.CheckConstraint(
            ("status IN ('PROPOSED', 'APPROVED', 'REJECTED')"),
            name=("ck_user_twin_profile_diffs_status"),
        ),
        sa.CheckConstraint(
            """
            (
                status = 'PROPOSED'
                AND decided_by_user_id IS NULL
                AND decided_at IS NULL
                AND decision_reason IS NULL
                AND applied_snapshot_version_id IS NULL
            )
            OR
            (
                status = 'REJECTED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NOT NULL
                AND applied_snapshot_version_id IS NULL
            )
            OR
            (
                status = 'APPROVED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND applied_snapshot_version_id IS NOT NULL
            )
            """,
            name=("ck_user_twin_profile_diffs_decision_metadata"),
        ),
    )

    op.create_index(
        ("ix_user_twin_profile_diffs_project_twin_created"),
        _TABLE,
        [
            "project_id",
            "twin_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        ("uq_user_twin_profile_diffs_pending_base_twin"),
        _TABLE,
        [
            "project_id",
            "base_snapshot_version_id",
            "twin_id",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'PROPOSED'"),
    )


def downgrade() -> None:
    """Remove User Twin profile-diff persistence."""
    op.drop_index(
        ("uq_user_twin_profile_diffs_pending_base_twin"),
        table_name=_TABLE,
    )

    op.drop_index(
        ("ix_user_twin_profile_diffs_project_twin_created"),
        table_name=_TABLE,
    )

    op.drop_table(_TABLE)
