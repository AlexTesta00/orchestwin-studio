"""Tests for deterministic Design runtime wiring."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment

CURRENT_DESIGN_PATH = "/api/v1/projects/{project_id}/design/current"
DESIGN_GATE_DECISION_PATH = "/api/v1/projects/{project_id}/design/gate/decision"


class FakeDatabaseRuntime:
    """Minimal process-level database runtime for composition tests."""

    def __init__(self) -> None:
        self.session_factory = object()
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_application_registers_design_routes_and_runtime_state() -> None:
    """Expose Design endpoints through the standard API factory."""
    marker = object()
    runtime = ApplicationRuntime(
        design_generation_service=marker,
        design_revision_service=marker,
        design_query_service=marker,
        design_gate_service=marker,
    )
    app = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST,
            api_prefix="/api/v1",
        ),
        runtime=runtime,
        auth_settings=AuthApiSettings(),
    )
    openapi_paths = app.openapi()["paths"]

    assert CURRENT_DESIGN_PATH in openapi_paths
    assert "get" in openapi_paths[CURRENT_DESIGN_PATH]
    assert DESIGN_GATE_DECISION_PATH in openapi_paths
    assert "post" in openapi_paths[DESIGN_GATE_DECISION_PATH]
    assert app.state.design_generation_service is marker
    assert app.state.design_revision_service is marker
    assert app.state.design_query_service is marker
    assert app.state.design_gate_service is marker


def test_default_runtime_composes_design_services_with_the_database_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire the deterministic Design stack whenever the platform runtime is enabled."""
    database = FakeDatabaseRuntime()
    design_marker = SimpleNamespace(
        generation=object(),
        revisions=object(),
        queries=object(),
        gate=object(),
    )
    requirements_marker = SimpleNamespace(
        generation=object(),
        revisions=object(),
        queries=object(),
        gate=object(),
    )
    captured_session_factories: list[object] = []

    def build_design(session_factory):
        captured_session_factories.append(session_factory)
        return design_marker

    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(
        services_module,
        "create_database_runtime",
        lambda _settings: database,
    )
    monkeypatch.setattr(
        services_module,
        "build_requirements_services",
        lambda _session_factory: requirements_marker,
    )
    monkeypatch.setattr(
        services_module,
        "build_design_services",
        build_design,
    )

    runtime = create_default_runtime()

    assert captured_session_factories == [database.session_factory]
    assert runtime.design_generation_service is design_marker.generation
    assert runtime.design_revision_service is design_marker.revisions
    assert runtime.design_query_service is design_marker.queries
    assert runtime.design_gate_service is design_marker.gate

    asyncio.run(runtime.close())

    assert database.disposed is True
