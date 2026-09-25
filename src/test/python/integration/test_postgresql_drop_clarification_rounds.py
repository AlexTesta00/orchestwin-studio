from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa

from orchestwin.persistence import load_database_settings
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    isolated_postgres_settings,
)

pytestmark = pytest.mark.integration

MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0056_drop_clarification_rounds"
)


def test_upgrade_removes_the_rounds_table_and_keeps_the_assumptions():
    settings = load_database_settings(env_file=None)
    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        engine = sa.create_engine(scoped.sqlalchemy_url, poolclass=sa.pool.NullPool)
        try:
            with engine.connect() as connection:
                tables = set(
                    connection.scalars(
                        sa.text(
                            "SELECT table_name FROM information_schema.tables"
                            " WHERE table_schema = current_schema()"
                        )
                    ).all()
                )
            assert "clarification_rounds" not in tables
            assert {"brief_assumptions", "brief_dialogues", "brief_dialogue_turns"} <= tables
        finally:
            engine.dispose()


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
