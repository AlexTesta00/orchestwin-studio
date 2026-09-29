from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC
from orchestwin.api.requirements import create_requirements_router
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.requirements_change_application import (
    RequirementsChangeIssueCode,
    RequirementsChangeResult,
    RequirementsChangeStatus,
)
from src.test.python.projects.test_requirements_application import OWNER_ID, PROJECT_ID
from src.test.python.projects.test_requirements_change_application import (
    OWNER_REQUEST,
    Harness,
)

PREFIX = "/api/v1"
CHANGES = f"{PREFIX}/projects/{PROJECT_ID}/requirements/change-requests"
JOBS = f"{PREFIX}/projects/{PROJECT_ID}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
NOW = datetime(2026, 9, 29, 9, 30, tzinfo=UTC)
CALL = {"owner_user_id": OWNER_ID, "project_id": PROJECT_ID, "owner_request": OWNER_REQUEST}
PAYLOAD_KEYS = {
    "status",
    "diff",
    "version",
    "issue",
    "proposal_issue",
    "diff_persistence_status",
    "version_persistence_status",
}


def account() -> UserAccount:
    return UserAccount(
        id=OWNER_ID,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def application(service):
    app = create_app(
        ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None),
        runtime=ApplicationRuntime(identity_service=object()),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = account
    if service is not None:
        app.state.requirements_change_service = service
    return app


class ScriptedChanges:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    async def request_change(self, **arguments):
        self.calls.append(arguments)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def refused(issue):
    return lambda: RequirementsChangeResult(status=RequirementsChangeStatus.REJECTED, issue=issue)


def answered(response):
    return {"status_code": response.status_code, "body": response.json()}


def test_a_change_request_answers_with_the_proposed_revision():
    harness = Harness()

    with TestClient(application(harness.service)) as client:
        response = client.post(CHANGES, json={"request": f"  {OWNER_REQUEST}\n"})
    body = response.json()
    operations = body["diff"]["operations"]

    assert response.status_code == 201
    assert set(body) == PAYLOAD_KEYS
    assert body["status"] == "CREATED"
    assert (body["version"], body["issue"], body["proposal_issue"]) == (None, None, None)
    assert body["diff"]["status"] == "PROPOSED"
    assert [(item["operation"], item["display_code"]) for item in operations] == [
        ("REPLACE", "REQ-001")
    ]
    assert body["diff"]["proposed_specification"]["requirements"][0]["statement"].endswith(
        f"({OWNER_REQUEST})"
    )
    assert [request.owner_request for request in harness.port.requests] == [OWNER_REQUEST]


def test_a_change_request_runs_as_a_job_when_the_client_prefers_it():
    harness = Harness()
    app = application(harness.service)

    with TestClient(app) as client:
        started = client.post(CHANGES, json={"request": OWNER_REQUEST}, headers=ASYNC)
        job_id = started.json()["job_id"]
        client.portal.call(app.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()
        running = client.get(JOBS, params={"status": "RUNNING"}).json()

    assert started.status_code == 202
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert (started.json()["kind"], started.json()["operation"]) == (
        "REQUEST",
        "REQUIREMENTS_CHANGE",
    )
    assert (job["operation"], job["status"]) == ("REQUIREMENTS_CHANGE", "SUCCEEDED")
    assert job["response"]["status_code"] == 201
    assert set(job["response"]["body"]) == PAYLOAD_KEYS
    assert job["response"]["body"]["diff"]["status"] == "PROPOSED"
    assert running == {"items": []}
    assert len(harness.port.requests) == 1


CASES = [
    ("created", lambda: Harness().run(), 201, None),
    ("project", refused(RequirementsChangeIssueCode.PROJECT_NOT_FOUND), 404, "PROJECT_NOT_FOUND"),
    (
        "specification",
        refused(RequirementsChangeIssueCode.SPECIFICATION_NOT_FOUND),
        404,
        "REQUIREMENTS_SPECIFICATION_NOT_FOUND",
    ),
    (
        "pending",
        refused(RequirementsChangeIssueCode.REVISION_PENDING),
        409,
        "REQUIREMENTS_REVISION_PENDING",
    ),
    (
        "unchanged",
        refused(RequirementsChangeIssueCode.UNCHANGED),
        409,
        "REQUIREMENTS_UNCHANGED",
    ),
    (
        "context",
        refused(RequirementsChangeIssueCode.CONTEXT_CHANGED),
        409,
        "REQUIREMENTS_CONTEXT_CHANGED",
    ),
    (
        "approval",
        refused(RequirementsChangeIssueCode.USER_MODELING_APPROVAL_REQUIRED),
        409,
        "USER_MODELING_APPROVAL_REQUIRED",
    ),
    (
        "proposal",
        refused(RequirementsChangeIssueCode.PROPOSAL_REJECTED),
        409,
        "PROPOSAL_REJECTED",
    ),
    ("invalid", refused(RequirementsChangeIssueCode.INVALID_PROPOSAL), 409, "INVALID_PROPOSAL"),
    ("timeout", lambda: ProposalGenerationError("TIMEOUT"), 503, "TIMEOUT"),
    (
        "budget",
        lambda: ProposalGenerationError("GENERATION_BUDGET_EXCEEDED"),
        402,
        "GENERATION_BUDGET_EXCEEDED",
    ),
    ("provider", lambda: ProposalGenerationError("INVALID_PROVIDER_OUTPUT"), 502, None),
]


@pytest.mark.parametrize(
    ("outcome", "status_code", "code"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_the_job_answers_exactly_as_the_synchronous_request(outcome, status_code, code):
    service = ScriptedChanges(outcome())
    app = application(service)

    with TestClient(app, raise_server_exceptions=False) as client:
        synchronous = client.post(CHANGES, json={"request": OWNER_REQUEST})
        started = client.post(CHANGES, json={"request": OWNER_REQUEST}, headers=ASYNC)
        job_id = started.json()["job_id"]
        client.portal.call(app.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()

    detail = synchronous.json().get("detail")

    assert synchronous.status_code == status_code
    assert started.status_code == 202
    assert job["response"] == answered(synchronous)
    assert job["status"] == ("SUCCEEDED" if status_code < 400 else "FAILED")
    assert service.calls == [CALL, CALL]
    if isinstance(service.outcome, ProposalGenerationError):
        assert detail == {"code": service.outcome.code, "stage": "MODEL_PROPOSAL"}
    elif code is not None:
        assert detail == {"code": code}
    else:
        assert set(synchronous.json()) == PAYLOAD_KEYS


@pytest.mark.parametrize(
    "body",
    [
        {"request": ""},
        {"request": "   \n "},
        {"request": "x" * 2001},
        {"request": f" {'x' * 2001} "},
        {},
        {"request": None},
        {"request": 42},
        {"request": OWNER_REQUEST, "note": "extra"},
    ],
    ids=["empty", "blank", "too-long", "too-long-trimmed", "missing", "null", "number", "extra"],
)
def test_an_invalid_request_is_refused_at_once_with_or_without_the_preference(body):
    service = ScriptedChanges(refused(RequirementsChangeIssueCode.UNCHANGED)())

    with TestClient(application(service)) as client:
        synchronous = client.post(CHANGES, json=body)
        preferred = client.post(CHANGES, json=body, headers=ASYNC)
        jobs = client.get(JOBS).json()

    assert synchronous.status_code == 422
    assert synchronous.json()["detail"] == "invalid_request"
    assert answered(preferred) == answered(synchronous)
    assert jobs == {"items": []}
    assert service.calls == []


def test_a_request_of_two_thousand_characters_is_trimmed_and_accepted():
    service = ScriptedChanges(Harness().run())
    text = "x" * 2000

    with TestClient(application(service)) as client:
        response = client.post(CHANGES, json={"request": f"\t{text}  "})

    assert response.status_code == 201
    assert [call["owner_request"] for call in service.calls] == [text]


def test_a_studio_without_the_change_service_answers_unavailable():
    with TestClient(application(None)) as client:
        response = client.post(CHANGES, json={"request": OWNER_REQUEST})

    assert response.status_code == 503
    assert response.json() == {"detail": "requirements_change_service_unavailable"}


def test_the_change_request_route_is_part_of_the_requirements_router():
    [route] = [
        route
        for route in create_requirements_router().routes
        if isinstance(route, APIRoute)
        and route.path == "/projects/{project_id}/requirements/change-requests"
    ]

    assert route.methods == {"POST"}
    assert route.status_code == 201
    assert route.operation_id == "requestRequirementsChange"
