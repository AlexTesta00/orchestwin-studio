"""Real PostgreSQL regression tests for disposable, fully migrated test schemas."""

from __future__ import annotations

from contextlib import contextmanager

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from orchestwin.persistence import load_database_settings
from src.test.python.integration import postgres_isolation

pytestmark = pytest.mark.integration


@contextmanager
def engine_for(settings):
    engine = sa.create_engine(settings.sqlalchemy_url, poolclass=sa.pool.NullPool)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.mark.parametrize("repetition", [1, 2])
def test_fixed_fixture_names_are_isolated_and_audit_guards_remain_active(repetition):
    settings = load_database_settings(env_file=None)
    with engine_for(settings) as engine:
        with engine.begin() as connection:
            schema = connection.scalar(sa.text("SELECT current_schema()"))
            assert schema.startswith("test_orchestwin_")
            assert connection.scalar(sa.text("SELECT to_regclass('same_test_fixture')")) is None
            connection.execute(sa.text("CREATE TABLE same_test_fixture (id integer PRIMARY KEY)"))
            connection.execute(sa.text("INSERT INTO same_test_fixture VALUES (1)"))
            assert connection.scalar(sa.text("SELECT count(*) FROM users")) == 0
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version"))
        # The exact operation that broke CI must remain prohibited, even here.
        with (
            pytest.raises(DBAPIError, match="cannot be deleted or truncated"),
            engine.begin() as connection,
        ):
            connection.execute(sa.text("TRUNCATE TABLE users CASCADE"))


@pytest.mark.parametrize("failure_stage", ["migration", "body"])
def test_failed_schema_setup_or_test_body_cleans_only_its_own_namespace(monkeypatch, failure_stage):
    settings = load_database_settings(env_file=None)
    with engine_for(settings) as engine:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE retained_outer_fixture (id integer)"))
            connection.execute(sa.text("INSERT INTO retained_outer_fixture VALUES (42)"))
            before = set(connection.scalars(sa.text("SELECT oid FROM pg_namespace")))

        def fail_migration(_settings):
            raise RuntimeError("deliberate migration failure")

        if failure_stage == "migration":
            monkeypatch.setattr(postgres_isolation, "upgrade_database", fail_migration)
        with (
            pytest.raises(RuntimeError, match="deliberate"),
            postgres_isolation.isolated_postgres_settings(settings) as inner,
        ):
            with engine_for(inner) as isolated, isolated.connect() as connection:
                assert (
                    connection.scalar(sa.text("SELECT to_regclass('retained_outer_fixture')"))
                    is None
                )
            raise RuntimeError("deliberate test failure")
        with engine.connect() as connection:
            assert set(connection.scalars(sa.text("SELECT oid FROM pg_namespace"))) == before
            assert connection.scalar(sa.text("SELECT id FROM retained_outer_fixture")) == 42
