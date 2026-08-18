"""Tests for the packaged Alembic migration workflow."""

from io import StringIO

from alembic import command
from alembic.script import ScriptDirectory

from orchestwin.persistence.migrate import (
    build_argument_parser,
    create_alembic_config,
)

DATABASE_PASSWORD_SENTINEL = "database-secret-must-not-leak-8472"
TEST_DATABASE_URL = (
    f"postgresql+psycopg://user:{DATABASE_PASSWORD_SENTINEL}@localhost:5432/orchestwin"
)


def test_packaged_migration_graph_contains_single_baseline() -> None:
    """Expose one valid migration branch beginning at the baseline."""
    configuration = create_alembic_config(TEST_DATABASE_URL)
    scripts = ScriptDirectory.from_config(configuration)
    baseline = scripts.get_revision("0001_persistence_baseline")

    assert baseline is not None
    assert baseline.down_revision is None
    assert len(scripts.get_heads()) == 1


def test_packaged_migrations_support_offline_sql_without_leaking_credentials() -> None:
    """Render migrations without exposing database connection credentials."""
    output = StringIO()
    configuration = create_alembic_config(
        TEST_DATABASE_URL,
        output_buffer=output,
    )

    command.upgrade(
        configuration,
        "head",
        sql=True,
    )

    generated_sql = output.getvalue()

    assert "alembic_version" in generated_sql
    assert "0001_persistence_baseline" in generated_sql
    assert "0002_identity_users" in generated_sql
    assert "CREATE TABLE users" in generated_sql
    assert "password_hash" in generated_sql

    assert DATABASE_PASSWORD_SENTINEL not in generated_sql
    assert TEST_DATABASE_URL not in generated_sql


def test_migration_cli_defaults_upgrade_to_head() -> None:
    """Default the upgrade command to the latest revision."""
    parsed = build_argument_parser().parse_args(["upgrade"])

    assert parsed.command == "upgrade"
    assert parsed.revision == "head"
