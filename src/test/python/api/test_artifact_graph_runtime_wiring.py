"""Composition tests for cross-stage artifact graph queries."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.services import create_default_runtime


class FakeDatabaseRuntime:
    """Minimal process-level database runtime for composition tests."""

    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        """Match the process-owned database runtime contract."""


def test_default_runtime_composes_the_artifact_graph_query_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Build the derived graph query adapter from the shared session factory."""
    database = FakeDatabaseRuntime()
    graph_marker = object()
    requirements_marker = SimpleNamespace(
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
    architecture_marker = SimpleNamespace(
        generation=object(),
        revisions=object(),
        queries=object(),
        gate=object(),
    )
    captured: list[object] = []

    def build_graph_query(session_factory: object) -> object:
        captured.append(session_factory)
        return graph_marker

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
        lambda _session_factory: architecture_marker,
    )
    monkeypatch.setattr(
        services_module,
        "SqlAlchemyArtifactGraphQueryService",
        build_graph_query,
    )

    runtime = create_default_runtime()

    assert captured == [database.session_factory]
    assert runtime.artifact_graph_query_service is graph_marker
