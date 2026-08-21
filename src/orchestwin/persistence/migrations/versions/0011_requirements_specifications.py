from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_requirements_specifications"
down_revision: str | None = "0010_user_twin_profile_diffs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SPECIFICATION_TABLE = "requirements_specification_versions"
_DIFF_TABLE = "requirements_specification_diffs"
_IMMUTABILITY_FUNCTION = "reject_requirements_version_mutation"
_IMMUTABILITY_TRIGGER = "trg_requirements_specification_versions_immutable"


def upgrade() -> None:
    """Create requirements versions, traceability snapshots, and diffs."""
    _create_specification_versions()
    _create_specification_diffs()
    _create_immutability_guard()


def downgrade() -> None:
    """Remove requirements persistence in dependency-safe order."""
    op.drop_index(
        "uq_requirements_specification_diffs_pending_base",
        table_name=_DIFF_TABLE,
    )
    op.drop_index(
        "ix_requirements_specification_diffs_project_created",
        table_name=_DIFF_TABLE,
    )
    op.drop_table(_DIFF_TABLE)

    _drop_immutability_guard()

    op.drop_index(
        "ix_requirements_specification_versions_project_version",
        table_name=_SPECIFICATION_TABLE,
    )
    op.drop_table(_SPECIFICATION_TABLE)


def _create_specification_versions() -> None:
    """Create append-only requirements specification history."""
    op.create_table(
        _SPECIFICATION_TABLE,
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
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "based_on_version_number",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "schema_version",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "specification_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "traceability_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "traceability_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "coverage_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_requirements_specification_versions",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_requirements_specification_versions_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_requirements_specification_versions_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "project_id",
                "based_on_version_number",
            ],
            [
                "requirements_specification_versions.project_id",
                "requirements_specification_versions.version_number",
            ],
            name="fk_requirements_specification_versions_previous",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "project_id",
            "version_number",
            name="uq_requirements_specification_versions_project_version",
        ),
        sa.UniqueConstraint(
            "project_id",
            "content_hash",
            name="uq_requirements_specification_versions_project_hash",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_requirements_specification_versions_positive_version",
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name="ck_requirements_specification_versions_positive_schema",
        ),
        sa.CheckConstraint(
            """
            (
                version_number = 1
                AND based_on_version_number IS NULL
            )
            OR
            (
                version_number > 1
                AND based_on_version_number = version_number - 1
            )
            """,
            name="ck_requirements_specification_versions_linear_lineage",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_requirements_specification_versions_content_hash",
        ),
        sa.CheckConstraint(
            "traceability_hash ~ '^[0-9a-f]{64}$'",
            name="ck_requirements_specification_versions_traceability_hash",
        ),
    )

    op.create_index(
        "ix_requirements_specification_versions_project_version",
        _SPECIFICATION_TABLE,
        [
            "project_id",
            "version_number",
        ],
        unique=False,
    )


def _create_specification_diffs() -> None:
    """Create mutable decision metadata around immutable diff proposals."""
    op.create_table(
        _DIFF_TABLE,
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
            "base_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "base_version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "base_content_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "proposed_content_hash",
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
            "applied_specification_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name="pk_requirements_specification_diffs",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_requirements_specification_diffs_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["base_version_id"],
            ["requirements_specification_versions.id"],
            name="fk_requirements_specification_diffs_base_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name="fk_requirements_specification_diffs_creator",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name="fk_requirements_specification_diffs_decider",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["applied_specification_version_id"],
            ["requirements_specification_versions.id"],
            name="fk_requirements_specification_diffs_applied_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "base_version_number > 0",
            name="ck_requirements_specification_diffs_positive_base_version",
        ),
        sa.CheckConstraint(
            "base_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_requirements_specification_diffs_base_hash",
        ),
        sa.CheckConstraint(
            "proposed_content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_requirements_specification_diffs_proposed_hash",
        ),
        sa.CheckConstraint(
            "proposal_hash ~ '^[0-9a-f]{64}$'",
            name="ck_requirements_specification_diffs_proposal_hash",
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'APPROVED', 'REJECTED')",
            name="ck_requirements_specification_diffs_status",
        ),
        sa.CheckConstraint(
            """
            (
                status = 'PROPOSED'
                AND decided_by_user_id IS NULL
                AND decided_at IS NULL
                AND decision_reason IS NULL
                AND applied_specification_version_id IS NULL
            )
            OR
            (
                status = 'REJECTED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND decision_reason IS NOT NULL
                AND applied_specification_version_id IS NULL
            )
            OR
            (
                status = 'APPROVED'
                AND decided_by_user_id IS NOT NULL
                AND decided_at IS NOT NULL
                AND applied_specification_version_id IS NOT NULL
            )
            """,
            name="ck_requirements_specification_diffs_decision_metadata",
        ),
    )

    op.create_index(
        "ix_requirements_specification_diffs_project_created",
        _DIFF_TABLE,
        [
            "project_id",
            "created_at",
        ],
        unique=False,
    )
    op.create_index(
        "uq_requirements_specification_diffs_pending_base",
        _DIFF_TABLE,
        [
            "project_id",
            "base_version_id",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'PROPOSED'"),
    )


def _create_immutability_guard() -> None:
    """Reject update and delete operations on version rows."""
    op.execute(
        sa.text(
            f"""
            CREATE FUNCTION {_IMMUTABILITY_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION
                    'Requirements specification versions are immutable';
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER {_IMMUTABILITY_TRIGGER}
            BEFORE UPDATE OR DELETE
            ON {_SPECIFICATION_TABLE}
            FOR EACH ROW
            EXECUTE FUNCTION {_IMMUTABILITY_FUNCTION}();
            """
        )
    )


def _drop_immutability_guard() -> None:
    """Remove the version mutation guard."""
    op.execute(
        sa.text(
            f"""
            DROP TRIGGER IF EXISTS
                {_IMMUTABILITY_TRIGGER}
            ON {_SPECIFICATION_TABLE};
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            DROP FUNCTION IF EXISTS
                {_IMMUTABILITY_FUNCTION}();
            """
        )
    )
