"""Dedicated JVM ports keep unavailable source/repair commands explicit."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from test_jvm_execution_api import (
    EXECUTION_ID,
    OWNER_ID,
    PROJECT_ID,
    _execution_body,
    _source_body,
    _user,
)

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.jvm_execution import JvmApiCommandResult, JvmApiCommandStatus
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings


def test_dedicated_prepare_and_read_routes_are_owner_scoped():
    start = SimpleNamespace(
        prepare_execution=AsyncMock(
            return_value=JvmApiCommandResult(
                JvmApiCommandStatus.EXECUTION_PREPARED, {"id": str(EXECUTION_ID)}, "Prepared."
            )
        )
    )
    reads = SimpleNamespace(execution_report=AsyncMock(return_value={"status": "FAILED"}))
    app = create_app(
        ApplicationSettings(_env_file=None),
        auth_settings=AuthApiSettings(_env_file=None),
        runtime=ApplicationRuntime(
            jvm_execution_start_api_service=start, jvm_execution_read_api_service=reads
        ),
    )
    app.dependency_overrides[current_user_dependency] = _user
    body = {**_execution_body(), "authorization_id": None}
    with TestClient(app) as client:
        response = client.post(f"/api/v1/projects/{PROJECT_ID}/jvm-executions/prepare", json=body)
        assert response.status_code == 201
        assert response.json()["status"] == "EXECUTION_PREPARED"
        assert (
            client.get(f"/api/v1/jvm-executions/{EXECUTION_ID}/report").json()["snapshot"]["status"]
            == "FAILED"
        )
        assert (
            client.post(
                f"/api/v1/projects/{PROJECT_ID}/jvm-source-revisions", json=_source_body()
            ).status_code
            == 503
        )
        assert (
            client.get(f"/api/v1/jvm-executions/{EXECUTION_ID}/repair-proposals").status_code == 503
        )
        body["launcher_integrity_verified"] = True
        assert (
            client.post(
                f"/api/v1/projects/{PROJECT_ID}/jvm-executions/prepare", json=body
            ).status_code
            == 422
        )
    call = start.prepare_execution.await_args.kwargs
    assert call["owner_user_id"] == OWNER_ID and call["project_id"] == PROJECT_ID
    assert call["command"].authorization_id is None


def test_default_composition_connects_jvm_ports_without_execution_or_connections(
    tmp_path, monkeypatch
):
    import os

    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORCHESTWIN_DATABASE_URL", "postgresql+psycopg://test:test@127.0.0.1/test")
    monkeypatch.setenv("ORCHESTWIN_AUTH_JWT_SECRET", "test-only-jwt-secret-at-least-32-characters")
    database = SimpleNamespace(session_factory=object(), dispose=AsyncMock())
    monkeypatch.setattr(services_module, "create_database_runtime", lambda settings: database)
    runtime = services_module.create_default_runtime(ApplicationSettings(_env_file=None))
    assert runtime.jvm_execution_start_api_service.operations is runtime.jvm_operation_store
    assert runtime.jvm_execution_read_api_service is not None
    assert runtime.jvm_execution_api_service is None
    assert not runtime.jvm_execution_start_api_service.backend.config.enabled
    assert not (tmp_path / "var").exists()
