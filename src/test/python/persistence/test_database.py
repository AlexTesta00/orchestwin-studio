"""Tests for the async SQLAlchemy infrastructure boundary."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from pydantic import SecretStr, ValidationError

from orchestwin.persistence import (
    DatabaseSettings,
    OrmBase,
    create_database_runtime,
    load_database_settings,
)

DATABASE_ENVIRONMENT_VARIABLES = (
    "ORCHESTWIN_DATABASE_URL",
    "ORCHESTWIN_DATABASE_ECHO",
    "ORCHESTWIN_DATABASE_POOL_SIZE",
    "ORCHESTWIN_DATABASE_MAX_OVERFLOW",
    "ORCHESTWIN_DATABASE_POOL_TIMEOUT_SECONDS",
    "ORCHESTWIN_DATABASE_POOL_RECYCLE_SECONDS",
)


@pytest.fixture(autouse=True)
def clear_database_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep persistence tests independent from developer configuration."""
    for variable_name in DATABASE_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable_name, raising=False)

    yield


def build_settings() -> DatabaseSettings:
    """Create deterministic PostgreSQL settings for infrastructure tests."""
    return DatabaseSettings(
        url=SecretStr("postgresql+psycopg://orchestwin:local-secret@localhost:5432/orchestwin"),
        echo=True,
        pool_size=7,
        max_overflow=4,
        pool_timeout_seconds=12,
        pool_recycle_seconds=900,
        _env_file=None,
    )


def test_database_settings_load_prefixed_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Parse database and pool configuration from the OrchesTwin namespace."""
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://user:password@database:5432/orchestwin",
    )
    monkeypatch.setenv("ORCHESTWIN_DATABASE_ECHO", "true")
    monkeypatch.setenv("ORCHESTWIN_DATABASE_POOL_SIZE", "8")

    settings = load_database_settings(env_file=None)

    assert settings.sqlalchemy_url.drivername == "postgresql+psycopg"
    assert settings.sqlalchemy_url.host == "database"
    assert settings.sqlalchemy_url.database == "orchestwin"
    assert settings.echo is True
    assert settings.pool_size == 8


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+aiosqlite:///orchestwin.db",
        "postgresql+asyncpg://user:password@localhost/orchestwin",
        "mysql+aiomysql://user:password@localhost/orchestwin",
    ],
)
def test_database_settings_reject_unsupported_urls(database_url: str) -> None:
    """Reject databases and drivers outside the approved persistence profile."""
    with pytest.raises(ValidationError):
        DatabaseSettings(
            url=SecretStr(database_url),
            _env_file=None,
        )


def test_database_url_secret_is_not_exposed_in_settings_repr() -> None:
    """Keep connection credentials out of ordinary settings diagnostics."""
    settings = build_settings()

    assert "local-secret" not in repr(settings)


def test_database_runtime_builds_without_opening_a_connection() -> None:
    """Compose the engine and session factory without requiring PostgreSQL."""
    runtime = create_database_runtime(build_settings())

    assert runtime.engine.url.drivername == "postgresql+psycopg"
    assert runtime.engine.pool._pre_ping is True

    async def inspect_and_close_runtime() -> None:
        session = runtime.session_factory()

        try:
            assert session.sync_session.expire_on_commit is False
            assert session.sync_session.autoflush is False
        finally:
            await session.close()
            await runtime.dispose()

    asyncio.run(inspect_and_close_runtime())


def test_orm_base_uses_deterministic_constraint_names() -> None:
    """Provide stable constraint names for Alembic migrations."""
    convention = OrmBase.metadata.naming_convention

    assert convention["pk"] == "pk_%(table_name)s"
    assert convention["fk"] == ("fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s")
    assert convention["uq"] == "uq_%(table_name)s_%(column_0_name)s"
