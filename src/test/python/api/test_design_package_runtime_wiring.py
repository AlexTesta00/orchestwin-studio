from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.services import create_default_runtime
from orchestwin.artifacts.design_package_export import DesignPackageExportService


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def test_default_runtime_composes_the_design_package_exporter_from_the_stage_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requirements_marker = SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object()
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
    exporter = runtime.design_package_export_service

    assert isinstance(exporter, DesignPackageExportService)
    assert exporter.project_service is runtime.project_service
    assert exporter.brief_gate_service is runtime.brief_gate_service
    assert exporter.team_proposal_service is runtime.team_proposal_service
    assert exporter.agent_team_service is runtime.agent_team_service
    assert exporter.user_modeling_services is runtime.user_modeling_services
    assert exporter.requirements_query_service is requirements_marker.queries
    assert exporter.requirements_gate_service is requirements_marker.gate
    assert exporter.design_query_service is design_marker.queries
    assert exporter.design_gate_service is design_marker.gate
