from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa

from orchestwin.persistence import load_database_settings
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from src.test.python.integration.postgres_isolation import isolated_postgres_settings

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0052_design_first_scope"
)
PREVIOUS_REVISION = MIGRATION.down_revision
SURVIVING_SAMPLE = (
    "users",
    "projects",
    "human_gates",
    "human_gate_events",
    "design_package_versions",
    "model_proposal_generations",
    "twin_conversation_turns",
    "training_run_checkpoints",
)

CATALOG_QUERIES = {
    "columns": (
        "SELECT table_name, column_name, data_type, character_maximum_length, is_nullable,"
        " column_default FROM information_schema.columns WHERE table_schema = current_schema()"
        " ORDER BY table_name, ordinal_position"
    ),
    "constraints": (
        "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint"
        " WHERE connamespace = current_schema()::regnamespace ORDER BY 1, 2"
    ),
    "indexes": (
        "SELECT tablename, indexname, indexdef FROM pg_indexes"
        " WHERE schemaname = current_schema() ORDER BY 1, 2"
    ),
    "triggers": (
        "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger"
        " WHERE NOT tgisinternal AND tgrelid IN"
        " (SELECT oid FROM pg_class WHERE relnamespace = current_schema()::regnamespace)"
        " ORDER BY 1, 2"
    ),
    "functions": (
        "SELECT proname, pg_get_functiondef(oid) FROM pg_proc"
        " WHERE pronamespace = current_schema()::regnamespace ORDER BY 1"
    ),
    "revision": "SELECT version_num FROM alembic_version",
}


def snapshot(settings):
    engine = sa.create_engine(settings.sqlalchemy_url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            schema = connection.scalar(sa.text("SELECT current_schema()"))
            return {
                name: [
                    tuple(str(value).replace(f"{schema}.", "") for value in row)
                    for row in connection.execute(sa.text(query))
                ]
                for name, query in CATALOG_QUERIES.items()
            }
    finally:
        engine.dispose()


def test_upgrade_removes_the_persistence_of_the_removed_stages():
    settings = load_database_settings(env_file=None)
    engine = sa.create_engine(settings.sqlalchemy_url, poolclass=sa.pool.NullPool)
    try:
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                MIGRATION.revision
            )
            for table in MIGRATION.TABLES:
                assert connection.scalar(sa.text(f"SELECT to_regclass('{table}')")) is None
            for function in (MIGRATION.GATE_TRIGGER, *MIGRATION.FUNCTIONS):
                assert connection.scalar(sa.text(f"SELECT to_regproc('{function}')")) is None
            for table in SURVIVING_SAMPLE:
                assert connection.scalar(sa.text(f"SELECT to_regclass('{table}')")) == table
            gate_triggers = set(
                connection.scalars(
                    sa.text(
                        "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN"
                        " ('human_gates'::regclass, 'human_gate_events'::regclass)"
                    )
                )
            )
            assert gate_triggers == {"trg_human_gate_events_append_only"}
    finally:
        engine.dispose()


def test_downgrade_restores_the_previous_revision_schema_exactly():
    settings = load_database_settings(env_file=None)
    with (
        isolated_postgres_settings(settings, revision=PREVIOUS_REVISION) as reference,
        isolated_postgres_settings(settings) as migrated,
    ):
        expected = snapshot(reference)
        assert expected["revision"] == [(PREVIOUS_REVISION,)]
        assert snapshot(migrated)["revision"] == [(MIGRATION.revision,)]

        downgrade_database(migrated, revision=PREVIOUS_REVISION)

        assert snapshot(migrated) == expected

        upgrade_database(migrated)

        assert snapshot(migrated)["revision"] == [(MIGRATION.revision,)]
