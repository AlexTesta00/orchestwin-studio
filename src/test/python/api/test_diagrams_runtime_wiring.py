from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.services import create_default_runtime
from orchestwin.knowledge.diagram_service import ProjectDiagramService


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def test_default_runtime_composes_the_diagram_service_from_the_stage_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirements_marker = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object(), changes=object()
    )
    design_marker = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object()
    )
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(
        services_module, "create_database_runtime", lambda _settings: FakeDatabaseRuntime()
    )
    monkeypatch.setattr(
        services_module, "build_requirements_services", lambda _factory: requirements_marker
    )
    monkeypatch.setattr(services_module, "build_design_services", lambda _factory: design_marker)
    monkeypatch.setattr(
        services_module, "SqlAlchemyArtifactGraphQueryService", lambda _factory: object()
    )

    runtime = create_default_runtime()
    diagrams = runtime.project_diagram_service

    assert isinstance(diagrams, ProjectDiagramService)
    assert diagrams.project_service is runtime.project_service
    assert diagrams.requirements_query_service is requirements_marker.queries
    assert diagrams.design_query_service is design_marker.queries
