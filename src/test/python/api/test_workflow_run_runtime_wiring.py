"""Test workflow lifecycle composition through the standard FastAPI app factory."""

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
from orchestwin.api.workflow_run_runtime import SqlAlchemyWorkflowRunApiService
from orchestwin.config import ApplicationSettings

OWNER = UUID(int=54201)
PROJECT = UUID(int=54202)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


def test_default_factory_constructs_workflow_service_without_opening_a_connection(monkeypatch):
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "test-only-jwt-secret-at-least-32-characters")
    database = SimpleNamespace(session_factory=object(), dispose=AsyncMock())
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    runtime = create_default_runtime(ApplicationSettings(_env_file=None))
    try:
        assert isinstance(runtime.workflow_run_api_service, SqlAlchemyWorkflowRunApiService)
        assert runtime.workflow_run_api_service._session_factory is database.session_factory
        assert runtime.user_modeling_services is not None  # C53 is preserved.
        assert runtime.web_execution_api_service is None  # Not claimed by this commit.
        assert runtime.jvm_execution_api_service is None
        assert runtime.finalization_api_service is None
    finally:
        asyncio.run(runtime.close())
    database.dispose.assert_awaited_once()


def test_missing_credentials_preserves_unconfigured_runtime(monkeypatch):
    def forbidden(*_a, **_kw):
        raise AssertionError("No workflow adapter may be constructed without credentials")

    monkeypatch.setattr(services_module, "SqlAlchemyWorkflowRunApiService", forbidden)
    runtime = create_default_runtime(ApplicationSettings(_env_file=None))
    assert runtime.workflow_run_api_service is None
    asyncio.run(runtime.close())


def test_standard_routes_use_custom_prefix_and_authenticated_owner():
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    workflows = SimpleNamespace(list_runs=AsyncMock(return_value=()))
    app = create_app(
        ApplicationSettings(api_prefix="/internal/v2", _env_file=None),
        runtime=ApplicationRuntime(identity_service=identity, workflow_run_api_service=workflows),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    paths = app.openapi()["paths"]
    assert "post" in paths["/internal/v2/projects/{project_id}/runs"]
    assert "get" in paths["/internal/v2/runs/{run_id}/checkpoints"]
    assert "get" in paths["/internal/v2/runs/{run_id}/events"]
    with TestClient(app) as client:
        path = f"/internal/v2/projects/{PROJECT}/runs"
        assert client.get(path).status_code == 401
        workflows.list_runs.assert_not_awaited()
        response = client.get(path, headers={"Authorization": "Bearer test-owned"})
    assert response.status_code == 200
    assert response.json() == {"items": []}
    workflows.list_runs.assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)


def test_unconfigured_workflow_routes_do_not_return_fabricated_state():
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=ApplicationRuntime(identity_service=identity),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/projects/{PROJECT}/runs", headers={"Authorization": "Bearer test-owned"}
        )
    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "WORKFLOW_RUN_API_SERVICE_UNAVAILABLE"}}
