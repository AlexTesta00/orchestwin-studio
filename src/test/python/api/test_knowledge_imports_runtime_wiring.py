from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.knowledge.project_import_service import ProjectImportService
from orchestwin.knowledge.twin_import_service import TwinImportService
from orchestwin.knowledge.twin_import_sources import SqlAlchemyTwinImportCandidateQuery
from orchestwin.projects.requirements_realignment_service import (
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_runtime import ManagedRequirementsUnitOfWorkFactory
from orchestwin.twins.runtime import (
    ManagedUserModelingUnitOfWorkFactory,
    SqlAlchemyUserModelingGovernanceAdapter,
)


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def stage_services() -> SimpleNamespace:
    return SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object(), changes=object()
    )


def user_modeling_services() -> SimpleNamespace:
    return SimpleNamespace(
        runtime_mode=object(),
        commands=object(),
        revisions=object(),
        queries=object(),
        gates=object(),
    )


@pytest.fixture
def composed(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    database = FakeDatabaseRuntime()
    user_modeling = user_modeling_services()
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    monkeypatch.setattr(
        services_module, "build_user_modeling_services", lambda _factory: user_modeling
    )
    monkeypatch.setattr(
        services_module, "build_requirements_services", lambda _factory: stage_services()
    )
    monkeypatch.setattr(services_module, "build_design_services", lambda _factory: stage_services())
    monkeypatch.setattr(
        services_module, "SqlAlchemyArtifactGraphQueryService", lambda _factory: object()
    )
    return SimpleNamespace(
        runtime=create_default_runtime(), database=database, user_modeling=user_modeling
    )


def test_default_runtime_composes_the_twin_import_from_the_user_modeling_services(
    composed: SimpleNamespace,
) -> None:
    service = composed.runtime.twin_import_service

    assert isinstance(service, TwinImportService)
    assert isinstance(service._governance, SqlAlchemyUserModelingGovernanceAdapter)
    assert isinstance(service._uow_factory, ManagedUserModelingUnitOfWorkFactory)
    assert service._project_service is composed.runtime.project_service
    assert service._user_modeling_queries is composed.user_modeling.queries
    assert service._user_modeling_gates is composed.user_modeling.gates
    assert isinstance(service._candidate_query, SqlAlchemyTwinImportCandidateQuery)
    assert service._candidate_query._session_factory is composed.database.session_factory


def test_default_runtime_composes_the_requirements_realignment_from_the_current_twins(
    composed: SimpleNamespace,
) -> None:
    service = composed.runtime.requirements_realignment_service

    assert isinstance(service, RequirementsRealignmentService)
    assert isinstance(service._uow_factory, ManagedRequirementsUnitOfWorkFactory)
    assert service._user_modeling_queries is composed.user_modeling.queries
    assert service._user_modeling_gates is composed.user_modeling.gates


def test_default_runtime_composes_the_project_import_on_the_database_sessions(
    composed: SimpleNamespace,
) -> None:
    service = composed.runtime.project_import_service

    assert isinstance(service, ProjectImportService)
    assert service._session_factory is composed.database.session_factory


def test_the_application_publishes_the_import_services_and_their_routes(
    composed: SimpleNamespace,
) -> None:
    application = create_app(
        runtime=ApplicationRuntime(
            twin_import_service=composed.runtime.twin_import_service,
            requirements_realignment_service=(composed.runtime.requirements_realignment_service),
            project_import_service=composed.runtime.project_import_service,
        )
    )
    paths = set(application.openapi()["paths"])

    assert application.state.twin_import_service is composed.runtime.twin_import_service
    assert (
        application.state.requirements_realignment_service
        is composed.runtime.requirements_realignment_service
    )
    assert application.state.project_import_service is composed.runtime.project_import_service
    assert {
        "/api/v1/projects/{project_id}/user-modeling/twin-imports",
        "/api/v1/projects/{project_id}/user-modeling/twin-imports/sources",
        "/api/v1/projects/{project_id}/user-modeling/twin-imports/sources/{source_project_id}",
        "/api/v1/projects/{project_id}/requirements/twin-alignment",
        "/api/v1/project-imports",
        "/api/v1/projects/{project_id}/import",
    } <= paths
