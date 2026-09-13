"""Offline PostgreSQL DDL contract for immutable JVM validation evidence."""

from io import StringIO

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from orchestwin.jvm_execution.validation_evidence import JvmProfileValidationEvidenceKind
from orchestwin.persistence.migrate import create_alembic_config

REVISION = "0036_jvm_validation_evidence"
DATABASE_URL = "postgresql+psycopg://user:test-only@localhost:5432/unused"


def migration_script():
    return ScriptDirectory.from_config(create_alembic_config(DATABASE_URL)).get_revision(REVISION)


def migration_sql(*, downgrade=False):
    output = StringIO()
    context = MigrationContext.configure(
        url=DATABASE_URL, opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        script = migration_script()
        assert script is not None
        (script.module.downgrade if downgrade else script.module.upgrade)()
    return output.getvalue()


def test_migration_extends_governed_web_history_without_modifying_web_tables() -> None:
    script = migration_script()
    assert script.down_revision == "0035_web_governed_operations"
    sql = migration_sql()
    assert "CREATE TABLE jvm_profile_validation_evidence" in sql
    assert "ALTER TABLE web_" not in sql


def test_ddl_preserves_all_jvm_identity_hashes_and_exact_snapshot() -> None:
    sql = migration_sql()
    for field in (
        "baseline_scope_hash",
        "runner_image_digest",
        "runner_build_recipe_hash",
        "toolchain_manifest_hash",
        "fixture_bundle_hash",
        "environment_fingerprint",
        "artifact_content_hash",
        "content_hash",
    ):
        assert f"{field} VARCHAR(64) NOT NULL" in sql
        assert f"{field} ~ '^[0-9a-f]{{64}}$'" in sql
    assert "CONSTRAINT pk_jvm_profile_validation_evidence PRIMARY KEY (evidence_id)" in sql
    assert "recorded_at TIMESTAMP WITH TIME ZONE NOT NULL" in sql
    assert "passed BOOLEAN NOT NULL" in sql
    assert "evidence_snapshot JSONB NOT NULL" in sql
    assert "(profile_id, profile_version)" in sql
    for kind in JvmProfileValidationEvidenceKind:
        assert f"'{kind.value}'" in sql
    for field in (
        "passed",
        "runner_build_recipe_hash",
        "toolchain_manifest_hash",
        "fixture_bundle_hash",
        "environment_fingerprint",
    ):
        assert f"to_jsonb({field})" in sql
    assert "evidence_snapshot - ARRAY[" in sql
    assert "IS TRUE" in sql


def test_ddl_uses_distinct_domain_identifier_and_uri_rules_and_offset_snapshot() -> None:
    sql = migration_sql()
    assert "profile_id ~ '^[A-Za-z][A-Za-z0-9]*([._/-][A-Za-z0-9]+)*$'" in sql
    assert "reference ~ '^[A-Za-z][A-Za-z0-9+.-]*:[A-Za-z0-9][A-Za-z0-9._:/-]*$'" in sql
    assert "jsonb_typeof(evidence_snapshot -> 'recorded_at') = 'string'" in sql
    assert "::timestamptz" not in sql.lower()


def test_mutation_guards_cover_update_delete_and_truncate_and_drop_safely() -> None:
    sql = migration_sql()
    assert "BEFORE UPDATE OR DELETE ON jvm_profile_validation_evidence" in sql
    assert "BEFORE TRUNCATE ON jvm_profile_validation_evidence" in sql
    assert "FOR EACH ROW" in sql and "FOR EACH STATEMENT" in sql
    assert "RAISE EXCEPTION" in sql
    downgrade = migration_sql(downgrade=True)
    assert downgrade.count("DROP TRIGGER") == 2
    assert downgrade.rindex("DROP TRIGGER") < downgrade.index("DROP FUNCTION")
    assert downgrade.index("DROP FUNCTION") < downgrade.index("DROP TABLE")
