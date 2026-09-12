"""Persist immutable evidence for exact Web profile validation scopes.

Revision ID: 0034_web_validation_evidence
Revises: 0033_authorized_evaluation_artifacts
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0034_web_validation_evidence"
down_revision: str | None = "0033_authorized_evaluation_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "web_profile_validation_evidence"
_FUNCTION = "reject_web_profile_validation_evidence_mutation"
_ROW_TRIGGER = "trg_web_profile_validation_evidence_immutable"
_TRUNCATE_TRIGGER = "trg_web_profile_validation_evidence_no_truncate"
_INDEX = "ix_web_profile_validation_evidence_profile_version"
_IDENTIFIER = "^[A-Za-z][A-Za-z0-9]*([._:/-][A-Za-z0-9]+)*$"
_HASH = "^[0-9a-f]{64}$"
_PROFILE_KINDS = (
    "'CONTRACT_TESTS', 'RUNNER_BUILD', 'CI_VERIFICATION', "
    "'ENVIRONMENT_MANIFEST', 'KNOWN_LIMITATIONS', 'REPRODUCIBILITY'"
)
_CONFIGURATION_KINDS = "'VALID_FIXTURE_RUN', 'FAILURE_REPAIR_RERUN', 'BROWSER_EVIDENCE'"
_SNAPSHOT_KEYS = (
    "evidence_id",
    "kind",
    "profile_id",
    "profile_version",
    "baseline_scope_hash",
    "language_configuration",
    "execution_runner_image_digest",
    "browser_runner_image_digest",
    "artifact_content_hash",
    "reference",
    "recorded_at",
    "passed",
)


def upgrade() -> None:
    """Create append-only storage without granting any execution capability."""
    snapshot_keys = "ARRAY[" + ", ".join(f"'{key}'" for key in _SNAPSHOT_KEYS) + "]"
    snapshot_values = " AND ".join(
        f"evidence_snapshot -> '{key}' = COALESCE(to_jsonb({key}), 'null'::jsonb)"
        for key in _SNAPSHOT_KEYS
        if key != "recorded_at"
    )
    op.create_table(
        _TABLE,
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("profile_id", sa.Text(), nullable=False),
        sa.Column("profile_version", sa.String(length=64), nullable=False),
        sa.Column("baseline_scope_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "language_configuration",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        sa.Column("execution_runner_image_digest", sa.String(length=64), nullable=False),
        sa.Column("browser_runner_image_digest", sa.String(length=64), nullable=True),
        sa.Column("artifact_content_hash", sa.String(length=64), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_snapshot", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("evidence_id", name=f"pk_{_TABLE}"),
        sa.CheckConstraint(
            f"evidence_id ~ '{_IDENTIFIER}' AND profile_id ~ '{_IDENTIFIER}' "
            f"AND reference ~ '{_IDENTIFIER}'",
            name=f"ck_{_TABLE}_identifiers",
        ),
        sa.CheckConstraint(
            "profile_version ~ '^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$'",
            name=f"ck_{_TABLE}_profile_version",
        ),
        sa.CheckConstraint(
            f"baseline_scope_hash ~ '{_HASH}' "
            f"AND execution_runner_image_digest ~ '{_HASH}' "
            f"AND artifact_content_hash ~ '{_HASH}' "
            f"AND content_hash ~ '{_HASH}' "
            f"AND (browser_runner_image_digest IS NULL "
            f"OR browser_runner_image_digest ~ '{_HASH}')",
            name=f"ck_{_TABLE}_digests",
        ),
        sa.CheckConstraint(
            f"(kind IN ({_PROFILE_KINDS}) AND language_configuration IS NULL) OR "
            f"(kind IN ({_CONFIGURATION_KINDS}) AND language_configuration IS NOT NULL)",
            name=f"ck_{_TABLE}_kind_configuration",
        ),
        sa.CheckConstraint(
            "language_configuration IS NULL OR ("
            "jsonb_typeof(language_configuration) = 'object' "
            "AND language_configuration ?& ARRAY['frontend', 'backend'] "
            "AND language_configuration - ARRAY['frontend', 'backend'] = '{}'::jsonb "
            "AND language_configuration -> 'frontend' "
            "IN ('null'::jsonb, '\"STATIC_ASSETS\"', '\"JAVASCRIPT\"', '\"TYPESCRIPT\"') "
            "AND language_configuration -> 'backend' "
            "IN ('null'::jsonb, '\"JAVASCRIPT\"', '\"TYPESCRIPT\"', '\"PHP\"') "
            "AND (language_configuration ->> 'frontend' IS NOT NULL "
            "OR language_configuration ->> 'backend' IS NOT NULL)) IS TRUE",
            name=f"ck_{_TABLE}_language_configuration",
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(evidence_snapshot) = 'object' "
            f"AND evidence_snapshot ?& {snapshot_keys} "
            f"AND evidence_snapshot - {snapshot_keys} = '{{}}'::jsonb) IS TRUE",
            name=f"ck_{_TABLE}_snapshot_shape",
        ),
        sa.CheckConstraint(
            f"({snapshot_values}) IS TRUE",
            name=f"ck_{_TABLE}_snapshot_values",
        ),
        sa.CheckConstraint(
            # Python accepts timezone offsets PostgreSQL cannot parse. Store the
            # relational instant in UTC; the codec verifies instant equality and
            # the original timestamp representation against the content hash.
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
            RAISE EXCEPTION 'Web profile validation evidence is immutable';
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
    """Remove validation-evidence storage after dropping mutation guards."""
    op.execute(f"DROP TRIGGER IF EXISTS {_ROW_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP TRIGGER IF EXISTS {_TRUNCATE_TRIGGER} ON {_TABLE};")
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_table(_TABLE)
