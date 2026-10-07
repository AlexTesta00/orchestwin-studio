from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.design import create_design_router
from orchestwin.api.generation_requests import PREFERENCE_APPLIED, RESPOND_ASYNC
from orchestwin.api.services import ApplicationRuntime
from orchestwin.artifacts.design_revision_application import (
    DesignRevisionResult,
    DesignRevisionStatus,
)
from orchestwin.config import ApplicationSettings
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.projects.design_change_application import (
    DesignChangeIssueCode,
    DesignChangeResult,
    DesignChangeStatus,
)
from src.test.python.api.test_design_api import design_version, proposed_diff
from src.test.python.artifacts import design_fixtures

PREFIX = "/api/v1"
OWNER = design_fixtures.OWNER_ID
PROJECT = design_fixtures.PROJECT_ID
CHANGES = f"{PREFIX}/projects/{PROJECT}/design/change-requests"
JOBS = f"{PREFIX}/projects/{PROJECT}/generation-jobs"
ASYNC = {"Prefer": RESPOND_ASYNC}
NOW = datetime(2026, 10, 6, 9, 30, tzinfo=UTC)
OWNER_REQUEST = "Aggiungi un passo di conferma prima del salvataggio della prenotazione."
CHANGES_TEXT = ("Il flusso di prenotazione chiede una conferma prima del salvataggio.",)
CALL = {"owner_user_id": OWNER, "project_id": PROJECT, "owner_request": OWNER_REQUEST}
PAYLOAD_KEYS = {"revision", "changes"}


def account() -> UserAccount:
    return UserAccount(
        id=OWNER,
        email=NormalizedEmail("owner@example.com"),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def application(service, **runtime):
    app = create_app(
        ApplicationSettings(api_prefix=PREFIX, debug=False, _env_file=None),
        runtime=ApplicationRuntime(identity_service=object(), **runtime),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    app.dependency_overrides[current_user_dependency] = account
    if service is not None:
        app.state.design_change_service = service
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


def created():
    version = design_version()
    return DesignChangeResult(
        status=DesignChangeStatus.CREATED,
        revision=DesignRevisionResult(
            status=DesignRevisionStatus.CREATED, diff=proposed_diff(version)
        ),
        changes=CHANGES_TEXT,
    )


def refused(issue):
    return lambda: DesignChangeResult(status=DesignChangeStatus.REJECTED, issue=issue)


def answered(response):
    return {"status_code": response.status_code, "body": response.json()}


def test_a_change_request_answers_with_the_revision_and_the_changes():
    service = ScriptedChanges(created())

    with TestClient(application(service)) as client:
        response = client.post(CHANGES, json={"request": f"  {OWNER_REQUEST}\n"})
    body = response.json()

    assert response.status_code == 201, response.text
    assert set(body) == PAYLOAD_KEYS
    assert body["changes"] == list(CHANGES_TEXT)
    assert body["revision"]["status"] == "CREATED"
    assert body["revision"]["version"] is None
    assert body["revision"]["diff"]["status"] == "PROPOSED"
    assert body["revision"]["diff"]["base_version_number"] == 1
    assert [item["artifact_kind"] for item in body["revision"]["diff"]["changes"]] == [
        "OPEN_QUESTIONS"
    ]
    assert service.calls == [CALL]


def test_a_change_request_runs_as_a_job_when_the_client_prefers_it():
    service = ScriptedChanges(created())
    app = application(service)

    with TestClient(app) as client:
        started = client.post(CHANGES, json={"request": OWNER_REQUEST}, headers=ASYNC)
        job_id = started.json()["job_id"]
        client.portal.call(app.state.generation_jobs.wait, UUID(job_id))
        job = client.get(f"{JOBS}/{job_id}").json()
        running = client.get(JOBS, params={"status": "RUNNING"}).json()

    assert started.status_code == 202
    assert started.headers[PREFERENCE_APPLIED] == RESPOND_ASYNC
    assert (started.json()["kind"], started.json()["operation"]) == ("REQUEST", "DESIGN_CHANGE")
    assert (job["operation"], job["status"]) == ("DESIGN_CHANGE", "SUCCEEDED")
    assert job["response"]["status_code"] == 201
    assert set(job["response"]["body"]) == PAYLOAD_KEYS
    assert job["response"]["body"]["changes"] == list(CHANGES_TEXT)
    assert running == {"items": []}
    assert service.calls == [CALL]


CASES = [
    ("created", created, 201, None),
    ("project", refused(DesignChangeIssueCode.PROJECT_NOT_FOUND), 404, "PROJECT_NOT_FOUND"),
    (
        "specification",
        refused(DesignChangeIssueCode.SPECIFICATION_NOT_FOUND),
        404,
        "REQUIREMENTS_SPECIFICATION_NOT_FOUND",
    ),
    ("design", refused(DesignChangeIssueCode.DESIGN_NOT_FOUND), 404, "DESIGN_PACKAGE_NOT_FOUND"),
    (
        "alternative",
        refused(DesignChangeIssueCode.ALTERNATIVE_NOT_CHOSEN),
        409,
        "DESIGN_ALTERNATIVE_NOT_CHOSEN",
    ),
    ("pending", refused(DesignChangeIssueCode.REVISION_PENDING), 409, "DESIGN_REVISION_PENDING"),
    ("unchanged", refused(DesignChangeIssueCode.UNCHANGED), 409, "DESIGN_UNCHANGED"),
    (
        "prototype",
        refused(DesignChangeIssueCode.PROTOTYPE_REQUIRED),
        409,
        "DESIGN_PROTOTYPE_REQUIRED",
    ),
    ("context", refused(DesignChangeIssueCode.CONTEXT_CHANGED), 409, "DESIGN_CONTEXT_CHANGED"),
    ("invalid", refused(DesignChangeIssueCode.INVALID_PROPOSAL), 409, "INVALID_PROPOSAL"),
    (
        "persistence",
        refused(DesignChangeIssueCode.PERSISTENCE_REJECTED),
        409,
        "PERSISTENCE_REJECTED",
    ),
    (
        "model",
        refused(DesignChangeIssueCode.MODEL_NOT_CONFIGURED),
        503,
        "DESIGN_CHANGE_MODEL_NOT_CONFIGURED",
    ),
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

    assert synchronous.status_code == status_code, synchronous.text
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
        {"request": "x" * 1001},
        {"request": f" {'x' * 1001} "},
        {},
        {"request": None},
        {"request": 42},
        {"request": OWNER_REQUEST, "locale": "it-IT"},
    ],
    ids=["empty", "blank", "too-long", "too-long-trimmed", "missing", "null", "number", "extra"],
)
def test_an_invalid_request_is_refused_at_once_with_or_without_the_preference(body):
    service = ScriptedChanges(created())

    with TestClient(application(service)) as client:
        synchronous = client.post(CHANGES, json=body)
        preferred = client.post(CHANGES, json=body, headers=ASYNC)
        jobs = client.get(JOBS).json()

    assert synchronous.status_code == 422
    assert synchronous.json()["detail"] == "invalid_request"
    assert answered(preferred) == answered(synchronous)
    assert jobs == {"items": []}
    assert service.calls == []


def test_a_request_of_a_thousand_characters_is_trimmed_and_accepted():
    service = ScriptedChanges(created())
    text = "x" * 1000

    with TestClient(application(service)) as client:
        response = client.post(CHANGES, json={"request": f"\t{text}  "})

    assert response.status_code == 201
    assert [call["owner_request"] for call in service.calls] == [text]


def test_a_studio_without_the_change_service_answers_unavailable():
    with TestClient(application(None)) as client:
        response = client.post(CHANGES, json={"request": OWNER_REQUEST})

    assert response.status_code == 503
    assert response.json() == {"detail": "design_change_service_unavailable"}


def test_a_studio_without_the_change_service_still_refuses_an_invalid_request():
    service = ScriptedChanges(created())
    body = {"request": ""}

    with TestClient(application(service)) as client:
        configured = client.post(CHANGES, json=body)
    with TestClient(application(None)) as client:
        synchronous = client.post(CHANGES, json=body)
        preferred = client.post(CHANGES, json=body, headers=ASYNC)
        jobs = client.get(JOBS).json()

    assert synchronous.status_code == 422
    assert synchronous.json()["detail"] == "invalid_request"
    assert answered(synchronous) == answered(configured)
    assert answered(preferred) == answered(synchronous)
    assert jobs == {"items": []}
    assert service.calls == []


def test_a_project_with_a_provided_prototype_cannot_change_the_design_from_words():
    service = ScriptedChanges(created())
    seen = []

    async def state(*, owner_user_id, project_id):
        seen.append((owner_user_id, project_id))
        return {"source": "PROVIDED_PROTOTYPE"}

    app = application(service, workflow_inputs_service=SimpleNamespace(state=state))

    with TestClient(app) as client:
        response = client.post(CHANGES, json={"request": OWNER_REQUEST})

    assert response.status_code == 409
    assert response.json() == {"detail": {"code": "PROVIDED_PROTOTYPE_OPERATION_UNAVAILABLE"}}
    assert seen == [(OWNER, PROJECT)]
    assert service.calls == []


def test_the_change_request_route_is_part_of_the_design_router():
    [route] = [
        route
        for route in create_design_router().routes
        if isinstance(route, APIRoute)
        and route.path == "/projects/{project_id}/design/change-requests"
    ]

    assert route.methods == {"POST"}
    assert route.status_code == 201
    assert route.operation_id == "requestDesignChange"
