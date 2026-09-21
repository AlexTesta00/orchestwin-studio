"""The standard API composes source storage without inventing an execution backend."""

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
from orchestwin.api.web_source_runtime import SqlAlchemyWebSourceApiService
from orchestwin.config import ApplicationSettings

OWNER = UUID(int=55501)
PROJECT = UUID(int=55502)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_default_factory_wires_source_service_without_connecting_or_writing(monkeypatch, tmp_path):
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "test-only-jwt-secret-at-least-32-characters")
    database = SimpleNamespace(session_factory=object(), dispose=AsyncMock())
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    root = tmp_path / "workspaces"
    runtime = create_default_runtime(
        ApplicationSettings(brownfield_workspace_root=root, _env_file=None)
    )
    try:
        sources = runtime.web_source_api_service
        assert isinstance(sources, SqlAlchemyWebSourceApiService)
        assert sources._session_factory is database.session_factory
        assert sources._content_root == (root / "web-source-objects").absolute()
        assert not (root / "web-source-objects").exists()
        assert runtime.user_modeling_services is not None
        assert runtime.workflow_run_api_service is not None
        assert runtime.web_execution_api_service is None
        assert runtime.jvm_execution_api_service is None
        assert runtime.finalization_api_service is None
    finally:
        asyncio.run(runtime.close())
    database.dispose.assert_awaited_once()


def test_no_credentials_leaves_source_service_unconfigured():
    runtime = create_default_runtime(ApplicationSettings(_env_file=None))
    assert runtime.web_source_api_service is None
    asyncio.run(runtime.close())


def make_app(*, sources=None, legacy=None):
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    return create_app(
        ApplicationSettings(api_prefix="/internal/v2", _env_file=None),
        runtime=ApplicationRuntime(
            identity_service=identity,
            web_source_api_service=sources,
            web_execution_api_service=legacy,
        ),
        auth_settings=AuthApiSettings(_env_file=None),
    )


def test_source_routes_use_authenticated_owner_and_leave_execution_unavailable():
    sources = SimpleNamespace(source_revision_history=AsyncMock(return_value=()))
    app = make_app(sources=sources)
    assert app.state.web_source_api_service is sources
    with TestClient(app) as client:
        path = f"/internal/v2/projects/{PROJECT}/web-source-revisions"
        assert client.get(path).status_code == 401
        sources.source_revision_history.assert_not_awaited()
        response = client.get(path, headers={"Authorization": "Bearer test-owned"})
        execution = client.get(
            f"/internal/v2/projects/{PROJECT}/web-executions",
            headers={"Authorization": "Bearer test-owned"},
        )
    assert response.status_code == 200 and response.json() == {"items": []}
    assert execution.status_code == 503
    sources.source_revision_history.assert_awaited_once_with(
        owner_user_id=OWNER, project_id=PROJECT
    )


def test_legacy_combined_service_injection_remains_compatible():
    legacy = SimpleNamespace(source_revision_history=AsyncMock(return_value=()))
    with TestClient(make_app(legacy=legacy)) as client:
        response = client.get(
            f"/internal/v2/projects/{PROJECT}/web-source-revisions",
            headers={"Authorization": "Bearer test-owned"},
        )
    assert response.status_code == 200
    legacy.source_revision_history.assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)


def test_separate_source_service_has_precedence_over_legacy_injection():
    sources = SimpleNamespace(source_revision_history=AsyncMock(return_value=()))
    legacy = SimpleNamespace(source_revision_history=AsyncMock(return_value=()))
    with TestClient(make_app(sources=sources, legacy=legacy)) as client:
        response = client.get(
            f"/internal/v2/projects/{PROJECT}/web-source-revisions",
            headers={"Authorization": "Bearer test-owned"},
        )
    assert response.status_code == 200
    sources.source_revision_history.assert_awaited_once()
    legacy.source_revision_history.assert_not_awaited()


def test_unconfigured_source_route_returns_unavailable_not_fake_history():
    with TestClient(make_app()) as client:
        response = client.get(
            f"/internal/v2/projects/{PROJECT}/web-source-revisions",
            headers={"Authorization": "Bearer test-owned"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "WEB_SOURCE_API_SERVICE_UNAVAILABLE"}}


def test_source_and_execution_contract_routes_are_both_present():
    paths = make_app().openapi()["paths"]
    assert "post" in paths["/internal/v2/projects/{project_id}/web-source-revisions"]
    assert "get" in paths["/internal/v2/projects/{project_id}/web-source-revisions/{revision_id}"]
    assert "post" in paths["/internal/v2/projects/{project_id}/web-executions"]
