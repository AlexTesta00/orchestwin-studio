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
    "orchestwin.persistence.migrations.versions.0052_design_first_scope"
)
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


def test_upgrade_removes_the_persistence_of_the_removed_stages():
    settings = load_database_settings(env_file=None)
    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        engine = sa.create_engine(scoped.sqlalchemy_url, poolclass=sa.pool.NullPool)
        try:
            with engine.connect() as connection:
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
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
