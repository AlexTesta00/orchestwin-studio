from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.knowledge.diagram_service import ProjectDiagrams, build_project_diagrams
from src.test.python.artifacts.design_fixtures import (
    OWNER_ID,
    PROJECT_ID,
    design_version,
    requirements_version,
)

NOW = datetime(2026, 9, 27, 18, 0, tzinfo=UTC)
PATH = f"/api/v1/projects/{PROJECT_ID}/diagrams"


def user() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def diagrams(locale: str, *, with_design: bool = True) -> ProjectDiagrams:
    snapshot = {"fields": {"name": "Lista ospiti workshop"}}
    return build_project_diagrams(
        brief=SimpleNamespace(brief=SimpleNamespace(to_snapshot=lambda: snapshot)),
        requirements=requirements_version(),
        design=design_version() if with_design else None,
        locale=locale,
    )


class FakeProjectDiagramService:
    def __init__(self, *, found: bool = True, with_design: bool = True) -> None:
        self.found = found
        self.with_design = with_design
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def current(
        self, *, owner_user_id: UUID, project_id: UUID, locale: str
    ) -> ProjectDiagrams | None:
        self.calls.append((owner_user_id, project_id, locale))
        return diagrams(locale, with_design=self.with_design) if self.found else None


def client(runtime: ApplicationRuntime) -> TestClient:
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=runtime,
        auth_settings=AuthApiSettings(),
    )
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_diagrams_are_served_in_the_requested_language_with_their_sources() -> None:
    service = FakeProjectDiagramService()

    response = client(ApplicationRuntime(project_diagram_service=service)).get(
        PATH, params={"locale": "it"}
    )

    assert response.status_code == 200
    body = response.json()
    expected = diagrams("it")
    assert service.calls == [(OWNER_ID, PROJECT_ID, "it")]
    assert body["project_id"] == str(PROJECT_ID)
    assert body["locale"] == "it"
    assert body["mermaid_version"] == "12.0.0"
    assert body["system_name"] == "Lista ospiti workshop"
    assert body["requirements"] == {
        "version_id": str(expected.requirements.version_id),
        "version_number": expected.requirements.version_number,
        "content_hash": expected.requirements.content_hash,
    }
    assert body["design"]["version_id"] == str(expected.design.version_id)
    assert body["diagrams"] == [item.to_snapshot() for item in expected.diagrams]
    assert body["diagrams"][0]["title"] == "Casi d'uso"


def test_locale_defaults_to_english_and_rejects_unknown_languages() -> None:
    service = FakeProjectDiagramService(with_design=False)
    api = client(ApplicationRuntime(project_diagram_service=service))

    default = api.get(PATH)
    unknown = api.get(PATH, params={"locale": "de"})

    assert default.status_code == 200
    assert default.json()["design"] is None
    assert default.json()["diagrams"][0]["title"] == "Use cases"
    assert unknown.status_code == 422
    assert service.calls == [(OWNER_ID, PROJECT_ID, "en")]


def test_project_without_requirements_has_no_diagrams() -> None:
    response = client(
        ApplicationRuntime(project_diagram_service=FakeProjectDiagramService(found=False))
    ).get(PATH)

    assert response.status_code == 404
    assert response.json() == {"detail": {"code": "DIAGRAMS_NOT_FOUND"}}


def test_diagrams_are_unavailable_without_the_service() -> None:
    response = client(ApplicationRuntime()).get(PATH)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": "DIAGRAM_SERVICE_UNAVAILABLE"}}


def test_diagrams_are_registered_in_openapi_and_application_state() -> None:
    service = FakeProjectDiagramService()
    application = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(project_diagram_service=service),
        auth_settings=AuthApiSettings(),
    )

    operation = application.openapi()["paths"]["/api/v1/projects/{project_id}/diagrams"]

    assert operation["get"]["operationId"] == "getProjectDiagrams"
    assert application.state.project_diagram_service is service
