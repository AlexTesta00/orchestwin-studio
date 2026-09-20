"""Executable PostgreSQL DDL contracts for immutable Web validation evidence."""

from __future__ import annotations

from io import StringIO

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from orchestwin.persistence.migrate import create_alembic_config

REVISION = "0034_web_validation_evidence"
DATABASE_URL = "postgresql+psycopg://user:test-only@localhost:5432/unused"


def migration_script():
    scripts = ScriptDirectory.from_config(create_alembic_config(DATABASE_URL))
    return scripts.get_revision(REVISION)


def migration_sql(*, downgrade: bool = False) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        url=DATABASE_URL,
        opts={"as_sql": True, "output_buffer": output},
    )
    with Operations.context(context):
        script = migration_script()
        assert script is not None
        if downgrade:
            script.module.downgrade()
        else:
            script.module.upgrade()
    return output.getvalue()


def test_validation_evidence_migration_extends_current_history() -> None:
    script = migration_script()

    assert script is not None
    assert script.down_revision == "0033_authorized_evaluation_artifacts"


def test_validation_evidence_migration_preserves_all_evidence_fields() -> None:
    sql = migration_sql()

    assert "CREATE TABLE web_profile_validation_evidence" in sql
    for column in ("evidence_id", "profile_id", "reference"):
        assert f"{column} TEXT NOT NULL" in sql
    for column in (
        "baseline_scope_hash",
        "execution_runner_image_digest",
        "artifact_content_hash",
        "content_hash",
    ):
        assert f"{column} VARCHAR(64) NOT NULL" in sql
    assert "kind VARCHAR(32) NOT NULL" in sql
    assert "profile_version VARCHAR(64) NOT NULL" in sql
    assert "language_configuration JSONB," in sql
    assert "browser_runner_image_digest VARCHAR(64)," in sql
    assert "recorded_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "passed BOOLEAN NOT NULL" in sql
    assert "evidence_snapshot JSONB NOT NULL" in sql
    assert "PRIMARY KEY (evidence_id)" in sql
    assert "(profile_id, profile_version)" in sql


def test_validation_evidence_migration_rejects_invalid_identity_and_snapshots() -> None:
    sql = migration_sql()

    for constraint in (
        "identifiers",
        "profile_version",
        "digests",
        "kind_configuration",
        "language_configuration",
        "snapshot_shape",
        "snapshot_values",
        "snapshot_timestamp",
    ):
        assert f"ck_web_profile_validation_evidence_{constraint}" in sql
    assert "^[0-9a-f]{64}$" in sql
    assert "FAILURE_REPAIR_RERUN" in sql
    assert "KNOWN_LIMITATIONS" in sql
    assert "jsonb_typeof(language_configuration)" in sql
    assert "jsonb_typeof(evidence_snapshot)" in sql
    assert "to_jsonb(passed)" in sql
    assert "IS TRUE" in sql


def test_validation_evidence_migration_rejects_update_delete_and_truncate() -> None:
    sql = migration_sql()

    assert "BEFORE UPDATE OR DELETE ON web_profile_validation_evidence" in sql
    assert "BEFORE TRUNCATE ON web_profile_validation_evidence" in sql
    assert "FOR EACH ROW" in sql
    assert "FOR EACH STATEMENT" in sql
    assert "RAISE EXCEPTION" in sql


def test_validation_evidence_downgrade_removes_guards_before_table() -> None:
    sql = migration_sql(downgrade=True)

    table_drop = sql.index("DROP TABLE web_profile_validation_evidence")
    function_drop = sql.index("DROP FUNCTION")
    assert sql.count("DROP TRIGGER") == 2
    assert sql.rindex("DROP TRIGGER") < function_drop < table_drop
