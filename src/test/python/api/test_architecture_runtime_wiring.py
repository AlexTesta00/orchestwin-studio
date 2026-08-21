"""Tests for deterministic Architecture runtime wiring."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment

CURRENT_ARCHITECTURE_PATH = "/api/v1/projects/{project_id}/architecture/current"
ARCHITECTURE_GATE_DECISION_PATH = "/api/v1/projects/{project_id}/architecture/gate/decision"


class FakeDatabaseRuntime:
    """Minimal process-level database runtime for composition tests."""

    def __init__(self) -> None:
        self.session_factory = object()
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def test_application_registers_architecture_routes_and_runtime_state() -> None:
    """Expose Architecture endpoints through the standard API factory."""
    marker = object()
    runtime = ApplicationRuntime(
        architecture_generation_service=marker,
        architecture_revision_service=marker,
        architecture_query_service=marker,
        architecture_gate_service=marker,
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

    assert CURRENT_ARCHITECTURE_PATH in openapi_paths
    assert "get" in openapi_paths[CURRENT_ARCHITECTURE_PATH]
    assert ARCHITECTURE_GATE_DECISION_PATH in openapi_paths
    assert "post" in openapi_paths[ARCHITECTURE_GATE_DECISION_PATH]
    assert app.state.architecture_generation_service is marker
    assert app.state.architecture_revision_service is marker
    assert app.state.architecture_query_service is marker
    assert app.state.architecture_gate_service is marker


def test_default_runtime_composes_architecture_services_with_database_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wire the deterministic Architecture stack when the platform runtime is enabled."""
    database = FakeDatabaseRuntime()
    architecture_marker = SimpleNamespace(
        generation=object(),
        revisions=object(),
        queries=object(),
        gate=object(),
    )
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

    def build_architecture(session_factory):
        captured_session_factories.append(session_factory)
        return architecture_marker

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
        lambda _session_factory: design_marker,
    )
    monkeypatch.setattr(
        services_module,
        "build_architecture_services",
        build_architecture,
    )

    runtime = create_default_runtime()

    assert captured_session_factories == [database.session_factory]
    assert runtime.architecture_generation_service is architecture_marker.generation
    assert runtime.architecture_revision_service is architecture_marker.revisions
    assert runtime.architecture_query_service is architecture_marker.queries
    assert runtime.architecture_gate_service is architecture_marker.gate

    asyncio.run(runtime.close())

    assert database.disposed is True
