"""Persist immutable owner-scoped evaluator artifact metadata.

Revision ID: 0033_authorized_evaluation_artifacts
Revises: 0032_static_browser_inspections
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0033_authorized_evaluation_artifacts"
down_revision: str | None = "0032_static_browser_inspections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "authorized_evaluation_artifacts"
_FUNCTION = "reject_authorized_evaluation_artifact_mutation"
_TRIGGER = "trg_authorized_evaluation_artifacts_immutable"

_KINDS = (
    "'SCREENSHOT', "
    "'DOM_SNAPSHOT', "
    "'ACCESSIBILITY_TREE', "
    "'AXE_REPORT', "
    "'FUNCTIONAL_TEST_REPORT', "
    "'EXECUTION_REPORT', "
    "'DESIGN_SPECIFICATION', "
    "'PROTOTYPE_MANIFEST', "
    "'SOURCE_SNAPSHOT'"
)


def upgrade() -> None:
    """Create immutable artifact registrations bound to workflow ownership."""
    op.create_table(
        _TABLE,
        sa.Column(
            "owner_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "workflow_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "artifact_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "version_number",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            sa.String(length=127),
            nullable=False,
        ),
        sa.Column(
            "sha256_digest",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "size_bytes",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "storage_key",
            sa.String(length=74),
            nullable=False,
        ),
        sa.Column(
            "location",
            sa.String(length=500),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint(
            "owner_user_id",
            "project_id",
            "workflow_run_id",
            "artifact_id",
            "version_number",
            name="pk_authorized_evaluation_artifacts",
        ),
        sa.ForeignKeyConstraint(
            [
                "workflow_run_id",
                "project_id",
                "owner_user_id",
            ],
            [
                "workflow_runs.id",
                "workflow_runs.project_id",
                "workflow_runs.owner_user_id",
            ],
            name=("fk_authorized_evaluation_artifacts_workflow_scope"),
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "version_number >= 1",
            name=("ck_authorized_evaluation_artifacts_version_positive"),
        ),
        sa.CheckConstraint(
            f"kind IN ({_KINDS})",
            name=("ck_authorized_evaluation_artifacts_kind"),
        ),
        sa.CheckConstraint(
            "sha256_digest ~ '^[0-9a-f]{64}$'",
            name=("ck_authorized_evaluation_artifacts_digest"),
        ),
        sa.CheckConstraint(
            "size_bytes >= 1",
            name=("ck_authorized_evaluation_artifacts_size_positive"),
        ),
        sa.CheckConstraint(
            (
                "storage_key = "
                "'sha256/' || "
                "substring(sha256_digest from 1 for 2) || "
                "'/' || sha256_digest"
            ),
            name=("ck_authorized_evaluation_artifacts_storage_key"),
        ),
        sa.CheckConstraint(
            ("char_length(media_type) BETWEEN 3 AND 127 AND position('/' in media_type) > 1"),
            name=("ck_authorized_evaluation_artifacts_media_type"),
        ),
        sa.CheckConstraint(
            "char_length(location) BETWEEN 1 AND 500",
            name=("ck_authorized_evaluation_artifacts_location"),
        ),
    )

    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'authorized evaluation artifact registrations are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW
        EXECUTE FUNCTION {_FUNCTION}();
        """
    )


def downgrade() -> None:
    """Remove the registry after removing its mutation guard."""
    op.execute(f"DROP TRIGGER IF EXISTS {_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_table(_TABLE)
