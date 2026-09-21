"""Disposable test namespaces with real migrations and unchanged audit guards."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import sqlalchemy as sa
from pydantic import SecretStr

from orchestwin.persistence.config import DatabaseSettings
from orchestwin.persistence.migrate import upgrade_database


@contextmanager
def isolated_postgres_settings(settings: DatabaseSettings) -> Iterator[DatabaseSettings]:
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
        upgrade_database(scoped)
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
