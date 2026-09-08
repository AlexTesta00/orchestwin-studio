"""Exercise User Modeling through the normal application factory, not a separate test app."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings
from orchestwin.models.user_modeling_runtime import UserModelingRuntimeMode
from orchestwin.twins.runtime import UserModelingServices

PROJECT = UUID("00000000-0000-4000-8000-000000053201")
OWNER = UUID("00000000-0000-4000-8000-000000053202")
PREFIX = f"/api/v1/projects/{PROJECT}/user-modeling"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_standard_factory_registers_modeling_routes_with_the_custom_api_prefix():
    bundle = SimpleNamespace(
        commands=object(), revisions=object(), queries=object(), gates=object()
    )
    runtime = ApplicationRuntime(user_modeling_services=bundle)
    app = create_app(
        ApplicationSettings(api_prefix="/internal/v2", _env_file=None),
        runtime=runtime,
        auth_settings=AuthApiSettings(_env_file=None),
    )
    paths = app.openapi()["paths"]
    prefix = "/internal/v2/projects/{project_id}/user-modeling"
    for suffix, method in (
        ("/personas/proposals", "post"),
        ("/snapshots/generate", "post"),
        ("/snapshots/current", "get"),
        ("/snapshots", "get"),
        ("/gate/submit", "post"),
        ("/gate/decision", "post"),
        ("/gate/events", "get"),
        ("/readiness", "get"),
    ):
        assert method in paths[prefix + suffix]
    assert app.state.user_modeling_services is bundle
    assert not any(path.startswith("/api/v1/") for path in paths)


def test_standard_factory_preserves_authenticated_owner_scope():
    queries = SimpleNamespace(snapshot_history=AsyncMock(return_value=()))
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    bundle = SimpleNamespace(commands=object(), revisions=object(), queries=queries, gates=object())
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(identity_service=identity, user_modeling_services=bundle),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    with TestClient(app) as client:
        assert client.get(PREFIX + "/snapshots").status_code == 401
        response = client.get(PREFIX + "/snapshots", headers={"Authorization": "Bearer owned"})
    assert response.status_code == 200
    assert response.json() == []
    queries.snapshot_history.assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)


def test_unconfigured_factory_keeps_routes_but_never_fabricates_results():
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(identity_service=identity),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    with TestClient(app) as client:
        response = client.get(PREFIX + "/readiness", headers={"Authorization": "Bearer owned"})
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "USER_MODELING_SERVICE_UNAVAILABLE"}}


def test_default_runtime_builds_the_persisted_modeling_bundle(monkeypatch):
    # These credentials are test-only. No real database is created or contacted.
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "test-only-jwt-secret-at-least-32-characters")
    database = SimpleNamespace(session_factory=object(), dispose=AsyncMock())
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    runtime = create_default_runtime()
    try:
        bundle = runtime.user_modeling_services
        assert isinstance(bundle, UserModelingServices)
        assert bundle.runtime_mode is UserModelingRuntimeMode.FAKE_DETERMINISTIC
        assert bundle.commands is not None
        assert bundle.queries is not None
        assert bundle.revisions is not None
        assert bundle.gates is not None
    finally:
        asyncio.run(runtime.close())
    database.dispose.assert_awaited_once()


def test_missing_credentials_does_not_build_a_modeling_runtime(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("no database means no persisted modeling service")

    monkeypatch.setattr(services_module, "build_user_modeling_services", forbidden)
    runtime = create_default_runtime(ApplicationSettings(_env_file=None))
    assert runtime.user_modeling_services is None
    asyncio.run(runtime.close())
