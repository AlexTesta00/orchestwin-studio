"""Disposable test namespaces with real migrations and unchanged audit guards."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import sqlalchemy as sa
from pydantic import SecretStr

from orchestwin.persistence.config import DatabaseSettings
from orchestwin.persistence.migrate import downgrade_database, upgrade_database

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


def catalog_snapshot(settings: DatabaseSettings) -> dict[str, list[tuple[str, ...]]]:
    """Describe every relation, constraint, index, trigger and function of the scoped schema."""
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


def assert_reversible_migration(settings: DatabaseSettings, migration) -> None:
    """Prove that downgrading the migration restores its previous revision exactly."""
    with (
        isolated_postgres_settings(settings, revision=migration.down_revision) as reference,
        isolated_postgres_settings(settings, revision=migration.revision) as migrated,
    ):
        expected = catalog_snapshot(reference)
        assert expected["revision"] == [(migration.down_revision,)]
        assert catalog_snapshot(migrated)["revision"] == [(migration.revision,)]

        downgrade_database(migrated, revision=migration.down_revision)

        assert catalog_snapshot(migrated) == expected

        upgrade_database(migrated, revision=migration.revision)

        assert catalog_snapshot(migrated)["revision"] == [(migration.revision,)]


@contextmanager
def isolated_postgres_settings(
    settings: DatabaseSettings, *, revision: str = "head"
) -> Iterator[DatabaseSettings]:
    """Create, migrate and remove only the namespace owned by this invocation.

    Each test keeps real commits, multiple sessions and runtime restarts. No
    existing application table is emptied and no mutation trigger is disabled.
    Public tables are excluded from the scoped connection's search path.
    """
    schema = f"test_orchestwin_{uuid4().hex}"
    administration = sa.create_engine(settings.sqlalchemy_url, poolclass=sa.pool.NullPool)
    owned_oid = None
    try:
        with administration.begin() as connection:
            connection.execute(sa.schema.CreateSchema(schema))
            owned_oid = connection.scalar(
                sa.text("SELECT oid FROM pg_namespace WHERE nspname = :schema"),
                {"schema": schema},
            )
        scoped_url = settings.sqlalchemy_url.update_query_dict(
            {"options": f"-csearch_path={schema}"}
        )
        scoped = settings.model_copy(
            update={"url": SecretStr(scoped_url.render_as_string(hide_password=False))}
        )
        upgrade_database(scoped, revision=revision)
        yield scoped
    finally:
        try:
            if owned_oid is not None:
                if re.fullmatch(r"test_orchestwin_[0-9a-f]{32}", schema) is None:
                    raise RuntimeError("test schema name is invalid")
                with administration.begin() as connection:
                    current_oid = connection.scalar(
                        sa.text("SELECT oid FROM pg_namespace WHERE nspname = :schema"),
                        {"schema": schema},
                    )
                    if current_oid is not None:
                        if current_oid != owned_oid:
                            raise RuntimeError("test schema identity changed; cleanup refused")
                        connection.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
                        connection.execute(sa.schema.DropSchema(schema, cascade=True))
        finally:
            administration.dispose()
