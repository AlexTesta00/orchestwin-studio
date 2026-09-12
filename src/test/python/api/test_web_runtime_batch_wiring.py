"""Verify real API factory dependencies and source service integration for C56-C59."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.api.web_source_runtime import SqlAlchemyWebSourceApiService
from orchestwin.config import ApplicationSettings

OWNER = UUID(int=58501)
PROJECT = UUID(int=58502)
REVISION = UUID(int=58503)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key in tuple(os.environ):
        if key.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(key, raising=False)


def app(*, reads=None, legacy=None):
    identity = SimpleNamespace(current_user=AsyncMock(return_value=SimpleNamespace(id=OWNER)))
    return create_app(
        ApplicationSettings(api_prefix="/api/v1", _env_file=None),
        runtime=ApplicationRuntime(
            identity_service=identity,
            web_execution_read_api_service=reads,
            web_execution_api_service=legacy,
        ),
        auth_settings=AuthApiSettings(_env_file=None),
    )


def test_read_routes_require_authenticated_owner_and_prefer_read_service() -> None:
    reads = SimpleNamespace(execution_history=AsyncMock(return_value=()))
    legacy = SimpleNamespace(execution_history=AsyncMock(return_value=()))
    with TestClient(app(reads=reads, legacy=legacy)) as client:
        path = f"/api/v1/projects/{PROJECT}/web-executions"
        assert client.get(path).status_code == 401
        reads.execution_history.assert_not_awaited()
        assert client.get(path, headers={"Authorization": "Bearer test"}).json() == {"items": []}
    reads.execution_history.assert_awaited_once_with(owner_user_id=OWNER, project_id=PROJECT)
    legacy.execution_history.assert_not_awaited()


def test_combined_service_remains_backwards_compatible() -> None:
    legacy = SimpleNamespace(execution_history=AsyncMock(return_value=()))
    with TestClient(app(legacy=legacy)) as client:
        assert (
            client.get(
                f"/api/v1/projects/{PROJECT}/web-executions",
                headers={"Authorization": "Bearer test"},
            ).status_code
            == 200
        )
    legacy.execution_history.assert_awaited_once()


def test_unconfigured_read_service_does_not_fabricate_results() -> None:
    with TestClient(app()) as client:
        response = client.get(
            f"/api/v1/projects/{PROJECT}/web-executions", headers={"Authorization": "Bearer test"}
        )
    assert response.status_code == 503


def test_factory_wires_reads_only_when_credentials_exist(monkeypatch) -> None:
    from orchestwin.api import governed_web_execution_runtime, services

    database = SimpleNamespace(session_factory=object(), dispose=AsyncMock())
    marker = object()
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1/test")
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET", "runtime-test-secret-with-at-least-32-characters"
    )
    monkeypatch.setattr(services, "create_database_runtime", lambda _settings: database)
    constructor = Mock(return_value=marker)
    monkeypatch.setattr(
        governed_web_execution_runtime, "SqlAlchemyWebExecutionReadApiService", constructor
    )
    settings = ApplicationSettings(_env_file=None)
    runtime = create_default_runtime(settings)
    assert runtime.web_execution_read_api_service is marker
    assert runtime.web_execution_api_service is None
    constructor.assert_called_once_with(
        database.session_factory, evidence_root=settings.sandbox_evidence_storage_root.absolute()
    )
    asyncio.run(runtime.close())
    database.dispose.assert_awaited_once()


def test_workspace_preparation_preserves_owner_scope(monkeypatch, tmp_path: Path) -> None:
    from orchestwin.api import web_source_runtime

    snapshot = {"id": str(REVISION)}
    result = object()
    service = SqlAlchemyWebSourceApiService(lambda: None, content_root=tmp_path / "objects")
    service.source_revision = AsyncMock(return_value=snapshot)
    materialize = Mock(return_value=result)
    monkeypatch.setattr(web_source_runtime, "materialize_web_source_snapshot", materialize)
    assert (
        asyncio.run(
            service.prepare_workspace(
                owner_user_id=OWNER,
                project_id=PROJECT,
                revision_id=REVISION,
            )
        )
        is result
    )
    service.source_revision.assert_awaited_once_with(
        owner_user_id=OWNER,
        project_id=PROJECT,
        revision_id=REVISION,
    )
    assert materialize.call_args.args == (snapshot,)


def test_unknown_source_creates_no_workspace(monkeypatch, tmp_path: Path) -> None:
    from orchestwin.api import web_source_runtime

    service = SqlAlchemyWebSourceApiService(lambda: None, content_root=tmp_path / "objects")
    service.source_revision = AsyncMock(return_value=None)
    materialize = Mock()
    monkeypatch.setattr(web_source_runtime, "materialize_web_source_snapshot", materialize)
    assert (
        asyncio.run(
            service.prepare_workspace(
                owner_user_id=OWNER,
                project_id=PROJECT,
                revision_id=REVISION,
            )
        )
        is None
    )
    materialize.assert_not_called()
