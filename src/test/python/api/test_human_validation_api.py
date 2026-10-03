from __future__ import annotations

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.validation import ValidationError, scenario_walkthrough, validation_overview
from src.test.python.api.test_artifact_why import OWNER_ID, PROJECT_ID, owner
from src.test.python.artifacts.test_validation_projection import document


class Service:
    def __init__(self, *, code=None, owned=True):
        self.code, self.owned, self.calls = code, owned, []

    def scope(self, scope):
        assert scope["owner_user_id"] == OWNER_ID and scope["project_id"] == PROJECT_ID
        self.calls.append(scope)
        if self.code:
            raise ValidationError(self.code)
        if not self.owned:
            raise ValidationError("PROJECT_NOT_FOUND")

    async def current(self, **scope):
        if not self.owned:
            return None
        self.scope(scope)
        return validation_overview(document=document())

    async def walkthrough(self, **scope):
        self.scope(scope)
        return scenario_walkthrough(
            document(),
            scope["scenario_key"],
            alternative_id=scope["alternative_id"],
            document_hash=scope["document_hash"],
        )

    async def save_hypothesis(self, **scope):
        self.scope(scope)
        return {
            "status": "HYPOTHESIS_REVISED" if scope.get("hypothesis_id") else "HYPOTHESIS_SAVED",
            "hypothesis": scope["request"],
        }

    async def record_outcome(self, **scope):
        self.scope(scope)
        return {"status": "VALIDATION_OUTCOME_RECORDED", "outcome": scope["request"]}


def client(service=None, *, authenticated=True):
    app = create_app(
        ApplicationSettings(environment=RuntimeEnvironment.TEST, api_prefix="/api/v1"),
        runtime=ApplicationRuntime(human_validation_service=service, identity_service=object()),
    )
    if authenticated:
        app.dependency_overrides[current_user_dependency] = owner
    return TestClient(app)


PATH = f"/api/v1/projects/{PROJECT_ID}/validation"


def test_read_endpoints_are_owner_scoped_without_provider():
    service = Service()
    browser = client(service)
    assert browser.get(PATH).json()["candidate_count"] == 2
    response = browser.get(
        PATH + "/walkthrough",
        params={
            "scenario_key": "scenario",
            "alternative_id": "alternative",
            "document_hash": "b" * 64,
        },
    )
    assert (
        response.status_code == 200 and response.json()["anchor_candidates"][0]["key"] == "element"
    )
    assert len(service.calls) == 2


def test_web_api_writes_keep_payload_and_version_base_exact():
    service = Service()
    browser = client(service)
    payload = {
        "question": "Synthetic fixture only",
        "based_on_version_number": 1,
        "based_on_content_hash": "c" * 64,
    }
    for path, expected in (
        ("/hypotheses", "HYPOTHESIS_SAVED"),
        (f"/hypotheses/{UUID(int=3508)}/versions", "HYPOTHESIS_REVISED"),
        ("/outcomes", "VALIDATION_OUTCOME_RECORDED"),
    ):
        response = browser.post(PATH + path, json=payload)
        assert response.status_code == 201 and response.json()["status"] == expected
        assert service.calls[-1]["request"] == payload


@pytest.mark.parametrize(
    "code,status",
    [
        ("PROJECT_NOT_FOUND", 404),
        ("HYPOTHESIS_NOT_FOUND", 404),
        ("VALIDATION_SOURCE_NOT_FOUND", 404),
        ("VALIDATION_CONTEXT_CHANGED", 409),
        ("HYPOTHESIS_VERSION_CONFLICT", 409),
        ("VALIDATION_SOURCE_RETIRED", 409),
        ("VALIDATION_SOURCE_TEXT_UNAVAILABLE", 409),
        ("VALIDATION_INPUT_INVALID", 422),
        ("VALIDATION_CITATION_INVALID", 422),
        ("VALIDATION_SESSION_SOURCE_INVALID", 422),
    ],
)
def test_errors_do_not_echo_source_quote_or_request_fields(code, status):
    response = client(Service(code=code)).post(
        PATH + "/outcomes",
        json={"quote": "Private synthetic source fixture", "session_ref": "SES-001"},
    )
    assert response.status_code == status
    assert response.json() == {"detail": {"code": code}}


def test_auth_scope_and_missing_service_are_explicit():
    assert client(Service(), authenticated=False).get(PATH).status_code == 401
    assert client(Service(owned=False)).get(PATH).json() == {
        "detail": {"code": "PROJECT_NOT_FOUND"}
    }
    assert client().get(PATH).json() == {"detail": {"code": "VALIDATION_SERVICE_UNAVAILABLE"}}
