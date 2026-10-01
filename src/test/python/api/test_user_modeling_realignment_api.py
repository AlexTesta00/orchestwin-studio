from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.api.user_modeling_realignment import create_user_modeling_realignment_router
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.twins.realignment_service import (
    ALREADY_ALIGNED,
    BRIEF_APPROVAL_REQUIRED,
    PERSISTENCE_REJECTED,
    TEAM_APPROVAL_REQUIRED,
    USER_TWIN_REVISION_PENDING,
    USER_TWINS_NOT_FOUND,
    UserModelingAlignment,
    UserModelingRealignmentFailure,
)
from src.test.python.knowledge.test_twin_import import OWNER_ID
from src.test.python.twins.test_user_modeling_realignment import (
    PROJECT_ID,
    REALIGNED_SNAPSHOT_ID,
    SECOND_TEAM,
    first_snapshot,
    realign,
)
from src.test.python.twins.test_user_modeling_realignment_service import SCENARIOS, behind

NOW = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
PREFIX = "/api/v1"
PATH = f"{PREFIX}/projects/{PROJECT_ID}/user-modeling/context-alignment"
ROUTE = "/api/v1/projects/{project_id}/user-modeling/context-alignment"
CONFLICTS = (
    BRIEF_APPROVAL_REQUIRED,
    TEAM_APPROVAL_REQUIRED,
    ALREADY_ALIGNED,
    USER_TWIN_REVISION_PENDING,
    PERSISTENCE_REJECTED,
)


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
        alignment: UserModelingAlignment | None = None,
        error: UserModelingRealignmentFailure | None = None,
    ) -> None:
        self.alignment = alignment or UserModelingAlignment(
            aligned=False,
            issue=None,
            snapshot_version_number=1,
            brief_version_number=1,
            team_version_number=2,
        )
        self.error = error
        self.calls: list[tuple[str, UUID, UUID]] = []
        self.realignment = realign(first_snapshot(), team=SECOND_TEAM)

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> UserModelingAlignment:
        self.calls.append(("status", owner_user_id, project_id))
        return self.alignment

    async def realign(self, *, owner_user_id: UUID, project_id: UUID):
        self.calls.append(("realign", owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.realignment


def client(service: object | None) -> TestClient:
    application = FastAPI()
    application.include_router(create_user_modeling_realignment_router(), prefix=PREFIX)
    application.state.user_modeling_realignment_service = service
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_the_alignment_tells_whether_the_twins_follow_the_current_brief_and_team():
    service = FakeRealignmentService()

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": None,
        "snapshot_version_number": 1,
        "brief_version_number": 1,
        "team_version_number": 2,
    }
    assert service.calls == [("status", OWNER_ID, PROJECT_ID)]


def test_the_alignment_of_a_project_without_twins_names_the_blocker():
    service = FakeRealignmentService(
        alignment=UserModelingAlignment(
            aligned=False,
            issue=USER_TWINS_NOT_FOUND,
            snapshot_version_number=None,
            brief_version_number=None,
            team_version_number=None,
        )
    )

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": "USER_TWINS_NOT_FOUND",
        "snapshot_version_number": None,
        "brief_version_number": None,
        "team_version_number": None,
    }


def test_the_re_anchoring_answers_created_with_the_new_snapshot_version():
    service = FakeRealignmentService()

    response = client(service).post(PATH)

    assert response.status_code == 201
    assert response.json() == {
        "snapshot_version_id": str(REALIGNED_SNAPSHOT_ID),
        "snapshot_version_number": 2,
        "based_on_version_number": 1,
        "content_hash": service.realignment.snapshot_version.content_hash,
        "twin_count": 2,
        "gate_approval_required": True,
    }
    assert service.calls == [("realign", OWNER_ID, PROJECT_ID)]


@pytest.mark.parametrize(
    ("code", "status"),
    [(USER_TWINS_NOT_FOUND, 404), *((code, 409) for code in CONFLICTS)],
)
def test_every_refusal_keeps_its_code_with_a_distinct_status(code, status):
    service = FakeRealignmentService(error=UserModelingRealignmentFailure(code))

    response = client(service).post(PATH)

    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}


def test_the_re_anchoring_is_unavailable_without_the_service():
    api = client(None)

    for response in (api.get(PATH), api.post(PATH)):
        assert response.status_code == 503
        assert response.json() == {
            "detail": {"code": "USER_MODELING_REALIGNMENT_SERVICE_UNAVAILABLE"}
        }


def test_the_project_identifier_in_the_path_must_be_a_uuid():
    service = FakeRealignmentService()
    api = client(service)
    path = f"{PREFIX}/projects/project-a/user-modeling/context-alignment"

    for response in (api.get(path), api.post(path)):
        assert response.status_code == 422
    assert service.calls == []


def test_the_re_anchoring_routes_are_documented_in_openapi():
    route = client(FakeRealignmentService()).app.openapi()["paths"][ROUTE]

    assert route["get"]["operationId"] == "getUserModelingContextAlignment"
    assert route["post"]["operationId"] == "realignUserModelingToContext"
    assert route["get"]["tags"] == route["post"]["tags"] == ["user-modeling"]
    assert "201" in route["post"]["responses"]


def test_the_service_answers_before_and_after_the_re_anchoring_and_refuses_a_second_one():
    harness = behind()
    api = client(harness.service)

    before = api.get(PATH)
    created = api.post(PATH)
    after = api.get(PATH)
    repeated = api.post(PATH)

    assert before.status_code == 200
    assert before.json() == {
        "aligned": False,
        "issue": None,
        "snapshot_version_number": 1,
        "brief_version_number": 1,
        "team_version_number": 2,
    }
    assert created.status_code == 201
    current = harness.store.current
    assert created.json() == {
        "snapshot_version_id": str(REALIGNED_SNAPSHOT_ID),
        "snapshot_version_number": 2,
        "based_on_version_number": 1,
        "content_hash": current.content_hash,
        "twin_count": 2,
        "gate_approval_required": True,
    }
    assert after.status_code == 200
    assert after.json() == {
        "aligned": True,
        "issue": "ALREADY_ALIGNED",
        "snapshot_version_number": 2,
        "brief_version_number": 1,
        "team_version_number": 2,
    }
    assert repeated.status_code == 409
    assert repeated.json() == {"detail": {"code": "ALREADY_ALIGNED"}}
    assert harness.store.commits == 1


@pytest.mark.parametrize("name", SCENARIOS)
def test_every_refusal_of_the_service_reaches_the_client_with_its_status(name):
    build, code = SCENARIOS[name]
    harness = build()
    api = client(harness.service)

    alignment = api.get(PATH)
    refusal = api.post(PATH)

    assert alignment.status_code == 200
    assert alignment.json()["issue"] == code
    assert refusal.status_code == (404 if code == USER_TWINS_NOT_FOUND else 409)
    assert refusal.json() == {"detail": {"code": code}}
    assert harness.nothing_written()


def test_the_application_publishes_the_service_and_its_routes():
    service = FakeRealignmentService()

    application = create_app(
        ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None),
        runtime=ApplicationRuntime(user_modeling_realignment_service=service),
        auth_settings=AuthApiSettings(_env_file=None),
    )

    assert application.state.user_modeling_realignment_service is service
    assert ROUTE in application.openapi()["paths"]
