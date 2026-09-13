"""Persist immutable validation evidence for exact JVM profile versions.

Revision ID: 0036_jvm_validation_evidence
Revises: 0035_web_governed_operations
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0036_jvm_validation_evidence"
down_revision: str | None = "0035_web_governed_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "jvm_profile_validation_evidence"
_FUNCTION = "reject_jvm_profile_validation_evidence_mutation"
_ROW_TRIGGER = "trg_jvm_profile_validation_evidence_immutable"
_TRUNCATE_TRIGGER = "trg_jvm_profile_validation_evidence_no_truncate"
_INDEX = "ix_jvm_profile_validation_evidence_profile_version"
_IDENTIFIER = "^[A-Za-z][A-Za-z0-9]*([._/-][A-Za-z0-9]+)*$"
_REFERENCE = "^[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$"
_HASH = "^[0-9a-f]{64}$"
_HASH_FIELDS = (
    "baseline_scope_hash",
    "runner_image_digest",
    "runner_build_recipe_hash",
    "toolchain_manifest_hash",
    "fixture_bundle_hash",
    "environment_fingerprint",
    "artifact_content_hash",
    "content_hash",
)
_KINDS = (
    "CONTRACT_TESTS",
    "RUNNER_IMAGE",
    "RUNNER_BUILD_RECIPE",
    "TOOLCHAIN_MANIFEST",
    "SOURCE_FIXTURE",
    "VALIDATE_REPORT",
    "SETUP_REPORT",
    "STATIC_CHECK_REPORT",
    "BUILD_REPORT",
    "TEST_REPORT",
    "RUN_REPORT",
    "ARTIFACT_INVENTORY",
    "FAILURE_MATRIX",
    "REPAIR_RERUN",
    "REPRODUCIBILITY",
    "KNOWN_LIMITATIONS",
)
_SNAPSHOT_KEYS = (
    "evidence_id",
    "kind",
    "profile_id",
    "profile_version",
    *_HASH_FIELDS[:-1],
    "reference",
    "recorded_at",
    "passed",
)


def upgrade() -> None:
    """Preserve platform evidence without granting execution capability."""
    snapshot_keys = "ARRAY[" + ", ".join(f"'{key}'" for key in _SNAPSHOT_KEYS) + "]"
    snapshot_values = " AND ".join(
        f"evidence_snapshot -> '{key}' = to_jsonb({key})"
        for key in _SNAPSHOT_KEYS
        if key != "recorded_at"
    )
    kinds = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.create_table(
        _TABLE,
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        *(sa.Column(field, sa.String(length=64), nullable=False) for field in _HASH_FIELDS[:-1]),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("evidence_id", name=f"pk_{_TABLE}"),
        sa.CheckConstraint(
            f"evidence_id ~ '{_IDENTIFIER}' AND profile_id ~ '{_IDENTIFIER}'",
            name=f"ck_{_TABLE}_identifiers",
        ),
        sa.CheckConstraint(f"reference ~ '{_REFERENCE}'", name=f"ck_{_TABLE}_reference"),
        sa.CheckConstraint(
            "profile_version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$'",
            name=f"ck_{_TABLE}_profile_version",
        ),
        sa.CheckConstraint(
            " AND ".join(f"{field} ~ '{_HASH}'" for field in _HASH_FIELDS),
            name=f"ck_{_TABLE}_digests",
        ),
        sa.CheckConstraint(f"kind IN ({kinds})", name=f"ck_{_TABLE}_kind"),
        sa.CheckConstraint(
            "(jsonb_typeof(evidence_snapshot) = 'object' "
            f"AND evidence_snapshot ?& {snapshot_keys} "
            f"AND evidence_snapshot - {snapshot_keys} = '{{}}'::jsonb) IS TRUE",
            name=f"ck_{_TABLE}_snapshot_shape",
        ),
        sa.CheckConstraint(f"({snapshot_values}) IS TRUE", name=f"ck_{_TABLE}_snapshot_values"),
        sa.CheckConstraint(
            # PostgreSQL cannot parse every offset accepted by Python. Keep the
            # original offset in the hashed snapshot and the SQL instant in UTC;
            # hydration verifies canonical timestamp text and instant equality.
            "(jsonb_typeof(evidence_snapshot -> 'recorded_at') = 'string' "
            "AND evidence_snapshot ->> 'recorded_at' "
            r"~ 'T.*[+-][0-9]{2}:[0-9]{2}(:[0-9]{2}(\.[0-9]{6})?)?$') IS TRUE",
            name=f"ck_{_TABLE}_snapshot_timestamp",
        ),
    )
    op.create_index(_INDEX, _TABLE, ["profile_id", "profile_version"], unique=False)
    op.execute(
        f"""
        CREATE FUNCTION {_FUNCTION}()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'JVM profile validation evidence is immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_ROW_TRIGGER}
        BEFORE UPDATE OR DELETE ON {_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON {_TABLE}
        FOR EACH STATEMENT EXECUTE FUNCTION {_FUNCTION}();
        """
    )


def downgrade() -> None:
    """Drop guards before removing the validation evidence table."""
    op.execute(f"DROP TRIGGER IF EXISTS {_ROW_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRUNCATE_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
