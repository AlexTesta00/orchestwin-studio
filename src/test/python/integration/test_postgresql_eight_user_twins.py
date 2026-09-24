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
    "orchestwin.persistence.migrations.versions.0054_eight_user_twins"
)


def test_upgrade_allows_eight_personas_and_twins_per_snapshot():
    settings = load_database_settings(env_file=None)
    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        engine = sa.create_engine(scoped.sqlalchemy_url, poolclass=sa.pool.NullPool)
        try:
            with engine.connect() as connection:
                definitions = dict(
                    connection.execute(
                        sa.text(
                            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                            " WHERE conrelid = 'user_modeling_snapshot_versions'::regclass"
                            " AND contype = 'c' AND pg_get_constraintdef(oid) LIKE '%count%'"
                        )
                    ).all()
                )
            assert sorted(definitions.values()) == [
                "CHECK (((persona_count >= 1) AND (persona_count <= 8)))",
                "CHECK (((twin_count >= 1) AND (twin_count <= 8)))",
                "CHECK ((persona_count = twin_count))",
            ]
        finally:
            engine.dispose()


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
