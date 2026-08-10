"""Alembic migration environment."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    async_engine_from_config,
)

from orchestwin.identity.persistence.models import (
    AuthSessionRecord,
    UserRecord,
)
from orchestwin.persistence.config import (
    load_database_settings,
)
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.persistence.models import (
    ProjectRecord,
)

configuration = context.config

if configuration.config_file_name is not None:
    fileConfig(
        configuration.config_file_name,
        disable_existing_loggers=False,
    )

_IMPORTED_MODELS = (
    UserRecord,
    AuthSessionRecord,
    ProjectRecord,
)

target_metadata = OrmBase.metadata


def database_url() -> str:
    """Resolve the database URL from Alembic or application settings."""
    configured_url = configuration.get_main_option("sqlalchemy.url")

    if configured_url:
        return configured_url

    return load_database_settings().url.get_secret_value()


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def configure_connection(
    connection: object,
) -> None:
    """Configure and run migrations on a synchronous connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create the async migration engine and run migrations."""
    section = configuration.get_section(configuration.config_ini_section) or {}
    section["sqlalchemy.url"] = database_url()

    connectable = async_engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(configure_connection)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations using the async SQLAlchemy engine."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
