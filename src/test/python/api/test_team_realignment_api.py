from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orchestwin.agents.realignment_service import TeamAlignment, TeamRealignmentFailure
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.team_realignment import create_team_realignment_router
from src.test.python.agents.test_team_realignment import NEXT_ID, World
from src.test.python.api.test_user_modeling_realignment_api import user

PROJECT_ID = "00000000-0000-4000-8000-000000000010"
PATH = f"/api/v1/projects/{PROJECT_ID}/team/context-alignment"


class Service:
    def __init__(self, issue=None):
        self.issue = issue
        self.calls = []

    async def status(self, **scope):
        self.calls.append(("status", scope))
        return TeamAlignment(False, self.issue, 1, 2)

    async def realign(self, **scope):
        self.calls.append(("realign", scope))
        if self.issue:
            raise TeamRealignmentFailure(self.issue)
        return SimpleNamespace(
            id=NEXT_ID, version_number=2, based_on_version_number=1, content_hash="a" * 64
        )


def client(service):
    app = FastAPI()
    app.include_router(create_team_realignment_router(), prefix="/api/v1")
    app.state.team_realignment_service = service
    app.dependency_overrides[current_user_dependency] = user
    return TestClient(app)


def test_team_context_alignment_and_append_have_typed_owner_scoped_payloads():
    service = Service()
    api = client(service)
    assert api.get(PATH).json() == {
        "aligned": False,
        "issue": None,
        "team_version_number": 1,
        "brief_version_number": 2,
    }
    response = api.post(PATH)
    assert response.status_code == 200
    assert response.json() == {
        "version_id": str(NEXT_ID),
        "version_number": 2,
        "based_on_version_number": 1,
        "content_hash": "a" * 64,
        "gate_approval_required": True,
    }
    assert all(scope["owner_user_id"] == user().id for _, scope in service.calls)
    assert all(str(scope["project_id"]) == PROJECT_ID for _, scope in service.calls)


@pytest.mark.parametrize(
    "code",
    [
        "TEAM_NOT_FOUND",
        "BRIEF_APPROVAL_REQUIRED",
        "TEAM_APPROVAL_REQUIRED",
        "PREPARE_AGAIN",
        "ALREADY_ALIGNED",
        "PERSISTENCE_REJECTED",
    ],
)
def test_team_realignment_failure_is_a_controlled_http_refusal(code):
    answer = client(Service(code)).post(PATH)
    assert answer.status_code == (404 if code == "TEAM_NOT_FOUND" else 409)
    assert answer.json() == {"detail": {"code": code}}


def test_unavailable_service_and_invalid_project_are_documented():
    api = client(None)
    assert api.get(PATH).status_code == api.post(PATH).status_code == 503
    assert client(Service()).post(PATH.replace(PROJECT_ID, "invalid")).status_code == 422
    operation = client(Service()).app.openapi()["paths"][
        "/api/v1/projects/{project_id}/team/context-alignment"
    ]
    assert operation["get"]["operationId"] == "getTeamContextAlignment"
    assert operation["post"]["operationId"] == "realignTeamContext"


def test_the_api_rejects_a_team_still_waiting_for_approval_even_with_valid_choices():
    from orchestwin.workflow.gates import HumanGateStatus

    world = World()
    world.gate.status = HumanGateStatus.PENDING_APPROVAL
    api = client(world.service)
    from src.test.python.agents.test_team_realignment import OWNER_ID

    api.app.dependency_overrides[current_user_dependency] = lambda: SimpleNamespace(id=OWNER_ID)
    answer = api.post(PATH)
    assert answer.status_code == 409
    assert answer.json() == {"detail": {"code": "TEAM_APPROVAL_REQUIRED"}}
    assert len(world.versions) == 1
