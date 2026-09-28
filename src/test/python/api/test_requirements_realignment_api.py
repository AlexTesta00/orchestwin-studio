from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.requirements_realignment import create_requirements_realignment_router
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.requirements_realignment import realigned_requirements_version
from orchestwin.projects.requirements_realignment_service import (
    RequirementsAlignment,
    RequirementsRealignmentFailure,
)
from src.test.python.knowledge.test_twin_import import OWNER_ID
from src.test.python.projects.test_requirements_realignment import (
    PROJECT_ID,
    REALIGNED_AT,
    REALIGNED_VERSION_ID,
    first_snapshot,
    requirements_version,
    second_snapshot,
)

NOW = datetime(2026, 9, 27, 23, 45, tzinfo=UTC)
PATH = f"/api/v1/projects/{PROJECT_ID}/requirements/twin-alignment"
CONFLICTS = (
    "USER_TWINS_REQUIRED",
    "USER_TWINS_APPROVAL_REQUIRED",
    "REQUIREMENTS_ALREADY_ALIGNED",
    "REQUIREMENTS_CONTEXT_CHANGED",
    "TWIN_NO_LONGER_AVAILABLE",
    "REQUIREMENTS_REVISION_PENDING",
    "PERSISTENCE_REJECTED",
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
        alignment: RequirementsAlignment | None = None,
        error: RequirementsRealignmentFailure | None = None,
    ) -> None:
        self.alignment = alignment or RequirementsAlignment(
            aligned=False,
            issue=None,
            requirements_version_number=3,
            snapshot_version_number=2,
            twins_approved=True,
        )
        self.error = error
        self.calls: list[tuple[str, UUID, UUID]] = []
        self.version = realigned_requirements_version(
            requirements_version(first_snapshot()),
            second_snapshot(),
            version_id=REALIGNED_VERSION_ID,
            created_by_user_id=OWNER_ID,
            created_at=REALIGNED_AT,
        )

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> RequirementsAlignment:
        self.calls.append(("status", owner_user_id, project_id))
        return self.alignment

    async def realign(self, *, owner_user_id: UUID, project_id: UUID):
        self.calls.append(("realign", owner_user_id, project_id))
        if self.error is not None:
            raise self.error
        return self.version


def client(service: FakeRealignmentService | None) -> TestClient:
    application = FastAPI()
    application.include_router(create_requirements_realignment_router(), prefix="/api/v1")
    application.state.requirements_realignment_service = service
    application.dependency_overrides[current_user_dependency] = user
    return TestClient(application)


def test_the_alignment_tells_whether_the_requirements_follow_the_current_twins():
    service = FakeRealignmentService()

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": None,
        "requirements_version_number": 3,
        "snapshot_version_number": 2,
        "twins_approved": True,
    }
    assert service.calls == [("status", OWNER_ID, PROJECT_ID)]


def test_the_alignment_of_a_project_without_requirements_names_the_blocker():
    service = FakeRealignmentService(
        alignment=RequirementsAlignment(
            aligned=False,
            issue="REQUIREMENTS_NOT_FOUND",
            requirements_version_number=None,
            snapshot_version_number=None,
            twins_approved=False,
        )
    )

    response = client(service).get(PATH)

    assert response.status_code == 200
    assert response.json() == {
        "aligned": False,
        "issue": "REQUIREMENTS_NOT_FOUND",
        "requirements_version_number": None,
        "snapshot_version_number": None,
        "twins_approved": False,
    }


def test_realignment_answers_created_with_the_new_requirements_version():
    service = FakeRealignmentService()

    response = client(service).post(PATH)

    assert response.status_code == 201
    assert response.json() == {
        "version_id": str(REALIGNED_VERSION_ID),
        "version_number": 4,
        "based_on_version_number": 3,
        "content_hash": service.version.content_hash,
        "user_modeling_version_number": 2,
        "twin_count": 3,
        "gate_approval_required": True,
    }
    assert service.calls == [("realign", OWNER_ID, PROJECT_ID)]


@pytest.mark.parametrize(
    ("code", "status"),
    [("REQUIREMENTS_NOT_FOUND", 404), *((code, 409) for code in CONFLICTS)],
)
def test_every_realignment_failure_keeps_its_code_with_a_distinct_status(code, status):
    service = FakeRealignmentService(error=RequirementsRealignmentFailure(code))

    response = client(service).post(PATH)

    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}


def test_realignment_is_unavailable_without_the_service():
    api = client(None)

    for response in (api.get(PATH), api.post(PATH)):
        assert response.status_code == 503
        assert response.json() == {
            "detail": {"code": "REQUIREMENTS_REALIGNMENT_SERVICE_UNAVAILABLE"}
        }


def test_the_project_identifier_in_the_path_must_be_a_uuid():
    service = FakeRealignmentService()
    api = client(service)
    path = "/api/v1/projects/project-a/requirements/twin-alignment"

    for response in (api.get(path), api.post(path)):
        assert response.status_code == 422
    assert service.calls == []


def test_the_realignment_routes_are_documented_in_openapi():
    paths = client(FakeRealignmentService()).app.openapi()["paths"]
    route = paths["/api/v1/projects/{project_id}/requirements/twin-alignment"]

    assert route["get"]["operationId"] == "getRequirementsTwinAlignment"
    assert route["post"]["operationId"] == "realignRequirementsToTwins"
    assert route["get"]["tags"] == route["post"]["tags"] == ["requirements"]
    assert "201" in route["post"]["responses"]
