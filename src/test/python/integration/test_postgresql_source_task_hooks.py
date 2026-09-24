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
    "orchestwin.persistence.migrations.versions.0053_source_task_hooks"
)
EVIDENCE_TABLES = (
    "model_proposal_generations",
    "model_proposal_generation_events",
    "model_proposal_artifact_links",
)
RETAINED_TRIGGERS = {
    "model_proposal_generations_immutable",
    "model_proposal_generations_no_truncate",
    "model_proposal_request_owner",
    "model_proposal_event_sequence",
    "model_proposal_generation_events_immutable",
    "model_proposal_generation_events_no_truncate",
    "model_proposal_artifact_exact",
    "model_proposal_artifact_links_immutable",
    "model_proposal_artifact_links_no_truncate",
}


def test_upgrade_removes_only_the_source_task_hooks():
    settings = load_database_settings(env_file=None)
    with isolated_postgres_settings(settings, revision=MIGRATION.revision) as scoped:
        engine = sa.create_engine(scoped.sqlalchemy_url, poolclass=sa.pool.NullPool)
        try:
            with engine.connect() as connection:
                triggers = set(
                    connection.scalars(
                        sa.text(
                            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN"
                            " ('model_proposal_generations'::regclass,"
                            " 'model_proposal_generation_events'::regclass,"
                            " 'model_proposal_artifact_links'::regclass)"
                        )
                    )
                )
                assert triggers == RETAINED_TRIGGERS
                for function in MIGRATION.FUNCTIONS:
                    assert connection.scalar(sa.text(f"SELECT to_regproc('{function}')")) is None
                assert connection.scalar(sa.text("SELECT to_regproc('model_source_context')"))
                assert (
                    connection.scalar(sa.text(f"SELECT to_regclass('{MIGRATION.INDEX}')")) is None
                )
                for table in EVIDENCE_TABLES:
                    assert connection.scalar(sa.text(f"SELECT to_regclass('{table}')")) == table
        finally:
            engine.dispose()


def test_downgrade_restores_the_previous_revision_schema_exactly():
    assert_reversible_migration(load_database_settings(env_file=None), MIGRATION)
