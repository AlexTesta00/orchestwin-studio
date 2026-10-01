from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.design_mockups import (
    DESIGN_CONTEXT_CHANGED,
    MockupCommandError,
    ModelMockupApplication,
)
from orchestwin.api.design_realignment import create_design_realignment_router
from orchestwin.api.services import ApplicationRuntime, create_default_runtime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.design_realignment_service import (
    DesignAlignment,
    DesignRealignment,
    DesignRealignmentFailure,
    DesignRealignmentService,
)
from orchestwin.projects.design_runtime import ManagedDesignUnitOfWorkFactory
from src.test.python.artifacts.test_design_realignment import (
    OWNER_ID,
    PROJECT_ID,
    REALIGNED_VERSION_ID,
    design_version,
    realigned_version,
    requirements_without_a_cited_requirement,
    reworded_requirements,
)
from src.test.python.projects.test_design_realignment_service import (
    REALIGNED_ID,
    after_change,
)

NOW = datetime(2026, 10, 1, 11, 0, tzinfo=UTC)
PATH = f"/api/v1/projects/{PROJECT_ID}/design/requirements-alignment"
ROUTE = "/api/v1/projects/{project_id}/design/requirements-alignment"
CONFLICTS = (
    "REQUIREMENTS_APPROVAL_REQUIRED",
    "ALREADY_ALIGNED",
    "DESIGN_REVISION_PENDING",
    "TWIN_SET_CHANGED",
    "PERSISTENCE_REJECTED",
)
MISSING_CODES = ("REQ-002", "USR-002", "AC-002")


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeRealignmentService:
    def __init__(
        self,
        *,
        alignment: DesignAlignment | None = None,
        error: DesignRealignmentFailure | None = None,
    ) -> None:
        self.alignment = alignment or DesignAlignment(
            aligned=False,
            issue=None,
            design_version_number=1,
            grounded_requirements_version_number=1,
            requirements_version_number=2,
            missing_codes=(),
            uncovered_codes=("REQ-003",),
        )
        self.error = error
        self.calls: list[tuple[str, UUID, UUID]] = []
        self.realignment = DesignRealignment(
            version=realigned_version(reworded_requirements()),
            requirements_version_number=2,
            uncovered_codes=("REQ-003",),
        )

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> DesignAlignment:
        self.calls.append(("status", owner_user_id, project_id))
        return self.alignment

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> DesignRealignment:
        self.calls.append(("realign", owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.realignment


def client(service: FakeRealignmentService | None) -> TestClient:
    application = FastAPI()
    application.include_router(create_design_realignment_router(), prefix="/api/v1")
    application.state.design_realignment_service = service
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


class RequirementsQuery:
    def __init__(self, version) -> None:
        self.version = version

    async def current(self, *, owner_user_id: UUID, project_id: UUID):
        return self.version


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def stage_services() -> SimpleNamespace:
    return SimpleNamespace(
        generation=object(), revisions=object(), queries=object(), gate=object(), changes=object()
    )


@pytest.fixture
def composed(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    database = FakeDatabaseRuntime()
    requirements = stage_services()
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
        services_module,
        "build_user_modeling_services",
        lambda _factory: SimpleNamespace(
            runtime_mode=object(),
            commands=object(),
            revisions=object(),
            queries=object(),
            gates=object(),
        ),
    )
    monkeypatch.setattr(
        services_module, "build_requirements_services", lambda _factory: requirements
    )
    monkeypatch.setattr(services_module, "build_design_services", lambda _factory: stage_services())
    monkeypatch.setattr(
        services_module, "SqlAlchemyArtifactGraphQueryService", lambda _factory: object()
    )
    settings = ApplicationSettings(environment=RuntimeEnvironment.TEST, _env_file=None)
    return SimpleNamespace(
        runtime=create_default_runtime(settings), database=database, requirements=requirements
    )


def test_the_alignment_tells_whether_the_design_follows_the_current_requirements():
    service = FakeRealignmentService()

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": None,
        "design_version_number": 1,
        "grounded_requirements_version_number": 1,
        "requirements_version_number": 2,
        "missing_codes": [],
        "uncovered_codes": ["REQ-003"],
    }
    assert service.calls == [("status", OWNER_ID, PROJECT_ID)]


def test_the_alignment_names_the_codes_that_the_requirements_no_longer_contain():
    service = FakeRealignmentService(
        alignment=DesignAlignment(
            aligned=False,
            issue="REQUIREMENT_NO_LONGER_AVAILABLE",
            design_version_number=1,
            grounded_requirements_version_number=1,
            requirements_version_number=2,
            missing_codes=MISSING_CODES,
            uncovered_codes=(),
        )
    )

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json()["issue"] == "REQUIREMENT_NO_LONGER_AVAILABLE"
    assert response.json()["missing_codes"] == list(MISSING_CODES)


def test_the_alignment_of_a_project_without_a_design_names_the_blocker():
    service = FakeRealignmentService(
        alignment=DesignAlignment(
            aligned=False,
            issue="DESIGN_NOT_FOUND",
            design_version_number=None,
            grounded_requirements_version_number=None,
            requirements_version_number=None,
            missing_codes=(),
            uncovered_codes=(),
        )
    )

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": "DESIGN_NOT_FOUND",
        "design_version_number": None,
        "grounded_requirements_version_number": None,
        "requirements_version_number": None,
        "missing_codes": [],
        "uncovered_codes": [],
    }


def test_realignment_answers_created_with_the_new_design_version():
    service = FakeRealignmentService()

    response = client(service).post(PATH)

    assert response.status_code == 201
    assert response.json() == {
        "version_id": str(REALIGNED_VERSION_ID),
        "version_number": 2,
        "based_on_version_number": 1,
        "content_hash": service.realignment.version.content_hash,
        "requirements_version_number": 2,
        "gate_approval_required": True,
        "uncovered_codes": ["REQ-003"],
    }
    assert service.calls == [("realign", OWNER_ID, PROJECT_ID)]


@pytest.mark.parametrize(
    ("code", "status"),
    [("DESIGN_NOT_FOUND", 404), *((code, 409) for code in CONFLICTS)],
)
def test_every_realignment_failure_keeps_its_code_with_a_distinct_status(code, status):
    service = FakeRealignmentService(error=DesignRealignmentFailure(code))

    response = client(service).post(PATH)

    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}


def test_a_requirement_no_longer_available_lists_the_missing_codes():
    service = FakeRealignmentService(
        error=DesignRealignmentFailure(
            "REQUIREMENT_NO_LONGER_AVAILABLE", missing_codes=MISSING_CODES
        )
    )

    response = client(service).post(PATH)

    assert response.status_code == 409
    assert response.json() == {
        "detail": {"code": "REQUIREMENT_NO_LONGER_AVAILABLE", "missing_codes": list(MISSING_CODES)}
    }


def test_the_routes_realign_once_and_then_report_the_design_as_aligned():
    harness = after_change()
    api = client(harness.service)

    before = api.get(PATH)
    created = api.post(PATH)
    after = api.get(PATH)
    again = api.post(PATH)

    assert (before.status_code, before.json()) == (
        200,
        {
            "aligned": False,
            "issue": None,
            "design_version_number": 1,
            "grounded_requirements_version_number": 1,
            "requirements_version_number": 2,
            "missing_codes": [],
            "uncovered_codes": ["REQ-003"],
        },
    )
    assert (created.status_code, created.json()) == (
        201,
        {
            "version_id": str(REALIGNED_ID),
            "version_number": 2,
            "based_on_version_number": 1,
            "content_hash": harness.store.current.content_hash,
            "requirements_version_number": 2,
            "gate_approval_required": True,
            "uncovered_codes": ["REQ-003"],
        },
    )
    assert (after.status_code, after.json()) == (
        200,
        {
            "aligned": True,
            "issue": "ALREADY_ALIGNED",
            "design_version_number": 2,
            "grounded_requirements_version_number": 2,
            "requirements_version_number": 2,
            "missing_codes": [],
            "uncovered_codes": ["REQ-003"],
        },
    )
    assert (again.status_code, again.json()) == (409, {"detail": {"code": "ALREADY_ALIGNED"}})
    assert harness.store.commits == 1


def test_the_routes_refuse_a_design_that_cites_a_removed_requirement():
    harness = after_change(requirements_without_a_cited_requirement)
    api = client(harness.service)

    status = api.get(PATH)
    refused = api.post(PATH)

    assert status.json()["issue"] == "REQUIREMENT_NO_LONGER_AVAILABLE"
    assert status.json()["missing_codes"] == list(MISSING_CODES)
    assert (refused.status_code, refused.json()) == (
        409,
        {
            "detail": {
                "code": "REQUIREMENT_NO_LONGER_AVAILABLE",
                "missing_codes": list(MISSING_CODES),
            }
        },
    )
    assert harness.nothing_written()


def test_realignment_is_unavailable_without_the_service():
    api = client(None)

    for response in (api.get(PATH), api.post(PATH)):
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "DESIGN_REALIGNMENT_SERVICE_UNAVAILABLE"}}


def test_the_project_identifier_in_the_path_must_be_a_uuid():
    service = FakeRealignmentService()
    api = client(service)
    path = "/api/v1/projects/project-a/design/requirements-alignment"

    for response in (api.get(path), api.post(path)):
        assert response.status_code == 422
    assert service.calls == []


def test_the_realignment_routes_are_documented_in_openapi():
    paths = client(FakeRealignmentService()).app.openapi()["paths"]
    route = paths[ROUTE]

    assert route["get"]["operationId"] == "getDesignRequirementsAlignment"
    assert route["post"]["operationId"] == "realignDesignToRequirements"
    assert route["get"]["tags"] == route["post"]["tags"] == ["design"]
    assert "201" in route["post"]["responses"]


def test_mockups_find_the_requirements_of_a_realigned_design():
    current = reworded_requirements()
    written = design_version()
    realigned = realigned_version(current, written)
    application = ModelMockupApplication(
        SimpleNamespace(
            proposal_evidence_store=None, requirements_query_service=RequirementsQuery(current)
        )
    )

    with pytest.raises(MockupCommandError) as raised:
        asyncio.run(application.grounded_requirements(OWNER_ID, PROJECT_ID, written))
    found = asyncio.run(application.grounded_requirements(OWNER_ID, PROJECT_ID, realigned))

    assert (raised.value.status_code, raised.value.code) == (409, DESIGN_CONTEXT_CHANGED)
    assert found is current


def test_default_runtime_composes_the_design_realignment_from_the_requirements_services(
    composed: SimpleNamespace,
) -> None:
    service = composed.runtime.design_realignment_service

    assert isinstance(service, DesignRealignmentService)
    assert isinstance(service._uow_factory, ManagedDesignUnitOfWorkFactory)
    assert service._uow_factory._session_factory is composed.database.session_factory
    assert service._requirements_queries is composed.requirements.queries
    assert service._requirements_gates is composed.requirements.gate


def test_the_application_publishes_the_design_realignment_and_its_routes(
    composed: SimpleNamespace,
) -> None:
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST, api_prefix="/api/v1", _env_file=None
        ),
        runtime=ApplicationRuntime(
            design_realignment_service=composed.runtime.design_realignment_service
        ),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    route = application.openapi()["paths"][ROUTE]

    assert (
        application.state.design_realignment_service is composed.runtime.design_realignment_service
    )
    assert set(route) == {"get", "post"}
