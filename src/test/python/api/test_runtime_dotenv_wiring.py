"""Exercise the standard runtime factory with dotenv-only credentials and no external I/O."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestwin.api import services
from orchestwin.api.runtime_configuration import RuntimeConfigurationError
from orchestwin.config import ApplicationSettings, RuntimeEnvironment

DATABASE_URL = "postgresql+psycopg://owner:runtime-test-password@127.0.0.1:5432/runtime_test"
JWT_SECRET = "dotenv-factory-test-secret-with-at-least-32-characters"


class DatabaseDouble:
    """No engine, sockets, queries, or migrations are created by this test double."""

    def __init__(self) -> None:
        self.session_factory = object()
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def factory_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SimpleNamespace:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    database = DatabaseDouble()
    database_settings = []
    token_settings = []
    token_service = services.JwtAccessTokenService
    stage = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object()
    )
    sandbox = SimpleNamespace(brownfield=object(), execution_queries=object(), high_impact=object())

    def build_database(settings):
        database_settings.append(settings)
        return database

    def build_tokens(settings):
        token_settings.append(settings)
        return token_service(settings)

    monkeypatch.setattr(services, "create_database_runtime", build_database)
    monkeypatch.setattr(services, "JwtAccessTokenService", build_tokens)
    monkeypatch.setattr(services, "build_requirements_services", lambda _factory: stage)
    monkeypatch.setattr(services, "build_design_services", lambda _factory: stage)
    monkeypatch.setattr(services, "build_architecture_services", lambda _factory: stage)
    monkeypatch.setattr(services, "build_sprint07_services", lambda _settings, _factory: sandbox)
    monkeypatch.setattr(services, "ContentAddressedAdapterRegistry", lambda _root: object())
    monkeypatch.setattr(services, "SqlAlchemyTrainingApiService", lambda **_kwargs: object())
    return SimpleNamespace(
        database=database,
        database_settings=database_settings,
        token_settings=token_settings,
        stage=stage,
        root=tmp_path,
    )


def app_settings() -> ApplicationSettings:
    return ApplicationSettings(environment=RuntimeEnvironment.TEST, _env_file=None)


def test_standard_factory_composes_services_with_dotenv_only(factory_context) -> None:
    (factory_context.root / ".env").write_text(
        f"ORCHESTWIN_DATABASE_URL={DATABASE_URL}\nORCHESTWIN_AUTH_JWT_SECRET={JWT_SECRET}\n",
        encoding="utf-8",
    )
    before = dict(os.environ)

    runtime = services.create_default_runtime(app_settings())

    assert runtime.database_runtime is factory_context.database
    assert runtime.identity_service is not None
    assert runtime.project_service is not None
    assert runtime.requirements_generation_service is factory_context.stage.generation
    assert len(factory_context.database_settings) == 1
    assert factory_context.database_settings[0].url.get_secret_value() == DATABASE_URL
    assert factory_context.token_settings[0].signing_secret == JWT_SECRET
    assert dict(os.environ) == before
    asyncio.run(runtime.close())
    assert factory_context.database.disposed is True


def test_standard_factory_remains_unconfigured_without_credentials(factory_context) -> None:
    runtime = services.create_default_runtime(app_settings())
    assert runtime.database_runtime is None
    assert runtime.identity_service is None
    assert factory_context.database_settings == []
    assert factory_context.token_settings == []


def test_partial_configuration_stops_before_database_allocation(factory_context) -> None:
    (factory_context.root / ".env").write_text(
        f"ORCHESTWIN_DATABASE_URL={DATABASE_URL}\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_CONFIGURATION_INCOMPLETE"):
        services.create_default_runtime(app_settings())
    assert factory_context.database_settings == []


def test_invalid_jwt_stops_before_database_allocation(factory_context) -> None:
    (factory_context.root / ".env").write_text(
        f"ORCHESTWIN_DATABASE_URL={DATABASE_URL}\nORCHESTWIN_AUTH_JWT_SECRET=too-short\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeConfigurationError, match="RUNTIME_AUTH_CONFIGURATION_INVALID"):
        services.create_default_runtime(app_settings())
    assert factory_context.database_settings == []
