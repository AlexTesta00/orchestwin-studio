"""Dedicated Web execution ports preserve legacy dependencies and typed HTTP inputs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from test_web_execution_api import EXECUTION_ID, OWNER_ID, PROJECT_ID, _execution_body, _user

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.web_execution import WebApiCommandResult, WebApiCommandStatus
from orchestwin.config import ApplicationSettings


def test_dedicated_prepare_browser_and_repair_services_are_owner_scoped():
    start = SimpleNamespace(
        prepare_execution=AsyncMock(
            return_value=WebApiCommandResult(
                WebApiCommandStatus.EXECUTION_PREPARED, {"id": str(EXECUTION_ID)}, "Plan prepared."
            )
        )
    )
    browser = SimpleNamespace(browser_evidence=AsyncMock(return_value={"status": "FAILED"}))
    repairs = SimpleNamespace(repair_proposals=AsyncMock(return_value=()))
    runtime = ApplicationRuntime(
        web_execution_start_api_service=start,
        web_browser_evidence_api_service=browser,
        web_repair_api_service=repairs,
    )
    app = create_app(
        ApplicationSettings(_env_file=None),
        runtime=runtime,
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = _user
    body = _execution_body()
    body["authorization_id"] = None
    body["declared_routes"] = []
    body["browser_interactions"] = [
        {
            "route_id": "root",
            "actions": [
                {"kind": "click", "selector": "#add"},
                {"kind": "expect_text", "selector": "#result", "value": "5"},
                {"kind": "press", "selector": "#add", "value": "Enter"},
                {"kind": "expect_text", "selector": "#result", "value": "5"},
            ],
        }
    ]
    with TestClient(app) as client:
        response = client.post(f"/api/v1/projects/{PROJECT_ID}/web-execution-plans", json=body)
        assert response.status_code == 201
        assert (
            client.get(f"/api/v1/web-executions/{EXECUTION_ID}/browser-evidence").json()[
                "snapshot"
            ]["status"]
            == "FAILED"
        )
        assert client.get(f"/api/v1/web-executions/{EXECUTION_ID}/repair-proposals").json() == {
            "items": []
        }
        body["browser_interactions"][0]["actions"] = body["browser_interactions"][0]["actions"][:2]
        assert (
            client.post(f"/api/v1/projects/{PROJECT_ID}/web-execution-plans", json=body).status_code
            == 422
        )
    call = start.prepare_execution.await_args.kwargs
    assert call["owner_user_id"] == OWNER_ID and call["project_id"] == PROJECT_ID
    assert len(call["command"].browser_interactions[0].actions) == 4


def test_default_runtime_composes_dedicated_web_ports_without_connecting_or_executing(
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
    assert runtime.web_execution_start_api_service is not None
    assert runtime.web_browser_evidence_api_service is runtime.web_execution_read_api_service
    assert runtime.web_repair_api_service is not None and runtime.web_operation_store is not None
    assert not runtime.web_execution_start_api_service.backend.config.enabled
    assert not (tmp_path / "var").exists()
