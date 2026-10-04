from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from orchestwin.activity import ActivityError, project_activity
from orchestwin.api import services as services_module
from orchestwin.api.app import create_app
from orchestwin.api.auth import AuthApiSettings, current_user_dependency
from orchestwin.api.services import ApplicationRuntime
from orchestwin.config import ApplicationSettings, RuntimeEnvironment
from orchestwin.identity.domain import NormalizedEmail, UserAccount
from orchestwin.projects.activity_runtime import SqlAlchemyProjectActivityService
from orchestwin.projects.persistence.usage_journal import SqlAlchemyUsageJournalRepository
from src.test.python.projects.test_activity_runtime import (
    CLIENT,
    OWNER,
    PROJECT,
    START,
    Clock,
    Store,
    at,
    service,
    web,
)

PATH = f"/api/v1/projects/{PROJECT}/activity"
TEMPLATE = "/api/v1/projects/{project_id}/activity"
STARTED = {"code": "SES-P01", "started_at": START.isoformat()}
PRIVATE = "Mario Rossi"
EVENTS = {
    "session_code": "SES-P01",
    "source": "WEB",
    "events": [{"kind": "DETAIL_OPENED", "client_at": CLIENT, "target": PRIVATE}],
}
ROUTES = [
    ("GET", "", None),
    ("GET", "/session", None),
    ("POST", "/sessions", {"session_code": "SES-P01"}),
    ("POST", "/sessions/SES-P01/end", None),
    ("POST", "/events", EVENTS),
]


def owner():
    return UserAccount(
        id=OWNER,
        email=NormalizedEmail("synthetic-owner@example.invalid"),
        password_hash="$argon2id$fixture",
        is_active=True,
        created_at=START,
        updated_at=START,
    )


class Service:
    def __init__(self, *, code=None, found=True):
        self.code, self.found, self.calls = code, found, []

    def record(self, name, values):
        assert (values.pop("owner_user_id"), values.pop("project_id")) == (OWNER, PROJECT)
        self.calls.append((name, values))
        if self.code:
            raise ActivityError(self.code)

    async def current(self, **values):
        self.record("current", values)
        return project_activity(project_id=str(PROJECT), facts=[]) if self.found else None

    async def session(self, **values):
        self.record("session", values)
        return {"active": True, "session": STARTED} if self.found else None

    async def start_session(self, **values):
        self.record("start_session", values)
        return {"status": "ACTIVITY_SESSION_STARTED", "session": STARTED}

    async def end_session(self, **values):
        self.record("end_session", values)
        return {
            "status": "ACTIVITY_SESSION_ENDED",
            "session": {**STARTED, "ended_at": at(60).isoformat()},
        }

    async def append_events(self, **values):
        self.record("append_events", values)
        return {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": len(values["request"]["events"])}


def client(activity=None, *, authenticated=True):
    application = create_app(
        ApplicationSettings(
            environment=RuntimeEnvironment.TEST, api_prefix="/api/v1", _env_file=None
        ),
        runtime=ApplicationRuntime(activity_service=activity, identity_service=object()),
        auth_settings=AuthApiSettings(_env_file=None),
    )
    if authenticated:
        application.dependency_overrides[current_user_dependency] = owner
    return TestClient(application)


def answer(browser, method, suffix, body=None):
    response = browser.request(method, PATH + suffix, json=body)
    return response.status_code, response.json()


def test_the_five_routes_answer_with_their_statuses():
    activity = Service()
    browser = client(activity)

    status, document = answer(browser, "GET", "")
    assert (status, document["kind"], document["project_id"]) == (
        200,
        "orchestwin.project-activity",
        str(PROJECT),
    )
    assert answer(browser, "GET", "/session") == (200, {"active": True, "session": STARTED})
    assert answer(browser, "POST", "/sessions", {"session_code": "SES-P01"}) == (
        201,
        {"status": "ACTIVITY_SESSION_STARTED", "session": STARTED},
    )
    status, ended = answer(browser, "POST", "/sessions/SES-P01/end")
    assert (status, ended["status"]) == (200, "ACTIVITY_SESSION_ENDED")
    assert answer(browser, "POST", "/events", EVENTS) == (
        202,
        {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 1},
    )
    assert activity.calls == [
        ("current", {}),
        ("session", {}),
        ("start_session", {"session_code": "SES-P01"}),
        ("end_session", {"session_code": "SES-P01"}),
        ("append_events", {"request": EVENTS}),
    ]


def test_an_unknown_project_is_not_found_on_both_reads():
    browser = client(Service(found=False))

    for suffix in ("", "/session"):
        assert answer(browser, "GET", suffix) == (404, {"detail": {"code": "PROJECT_NOT_FOUND"}})


@pytest.mark.parametrize(
    "code,status",
    [
        ("PROJECT_NOT_FOUND", 404),
        ("ACTIVITY_SESSION_ACTIVE", 409),
        ("ACTIVITY_SESSION_CODE_USED", 409),
        ("ACTIVITY_SESSION_NOT_ACTIVE", 409),
        ("ACTIVITY_JOURNAL_FULL", 409),
        ("ACTIVITY_INPUT_INVALID", 422),
        ("ACTIVITY_RECORDS_INVALID", 422),
    ],
)
def test_every_error_answers_only_its_code(code, status):
    activity = Service(code=code)
    browser = client(activity)

    for method, suffix, body in ROUTES:
        response = browser.request(method, PATH + suffix, json=body)
        assert (response.status_code, response.json()) == (status, {"detail": {"code": code}})
        assert PRIVATE not in response.text
    assert len(activity.calls) == len(ROUTES)


@pytest.mark.parametrize(
    "body",
    [
        {"session_code": "SES-P01", "name": PRIVATE},
        {"code": "SES-P01"},
        {},
        ["SES-P01"],
        "SES-P01",
        7,
        None,
    ],
    ids=["other-key", "wrong-key", "empty", "list", "text", "number", "missing"],
)
def test_a_start_body_other_than_the_code_alone_is_refused_before_the_service(body):
    activity = Service()

    status, refused = answer(client(activity), "POST", "/sessions", body)

    assert (status, refused) == (422, {"detail": {"code": "ACTIVITY_INPUT_INVALID"}})
    assert activity.calls == []


def test_a_missing_service_and_a_missing_user_are_explicit():
    unavailable, anonymous = client(), client(Service(), authenticated=False)

    for method, suffix, body in ROUTES:
        assert answer(unavailable, method, suffix, body) == (
            503,
            {"detail": {"code": "ACTIVITY_SERVICE_UNAVAILABLE"}},
        )
        assert anonymous.request(method, PATH + suffix, json=body).status_code == 401


def test_the_routes_are_documented_with_their_operation_ids():
    paths = client(Service()).app.openapi()["paths"]
    expected = {
        TEMPLATE: ("get", "getProjectActivity", "200"),
        TEMPLATE + "/session": ("get", "getActivitySession", "200"),
        TEMPLATE + "/sessions": ("post", "startActivitySession", "201"),
        TEMPLATE + "/sessions/{session_code}/end": ("post", "endActivitySession", "200"),
        TEMPLATE + "/events": ("post", "recordActivityEvents", "202"),
    }

    assert {path for path in paths if path.startswith(TEMPLATE)} == set(expected)
    for path, (method, operation, status) in expected.items():
        assert list(paths[path]) == [method]
        assert paths[path][method]["operationId"] == operation
        assert paths[path][method]["tags"] == ["activity"]
        assert status in paths[path][method]["responses"]


def test_the_real_service_keeps_its_rules_behind_the_routes():
    store, clock = Store(), Clock(at(0))
    browser = client(service(store, clock))
    events = {
        "session_code": "SES-P01",
        "source": "WEB",
        "events": [
            web("SECTION_OPENED", 1, section="DESIGN"),
            web("MOCKUP_OPENED", 5, section="DESIGN", target="DES-001"),
            web("PAGE_HIDDEN", 31, section="DESIGN"),
        ],
    }

    assert answer(browser, "GET", "/session") == (200, {"active": False, "session": None})
    assert answer(browser, "POST", "/sessions", {"session_code": "SES-P01"})[0] == 201
    assert answer(browser, "POST", "/sessions", {"session_code": "SES-P02"}) == (
        409,
        {"detail": {"code": "ACTIVITY_SESSION_ACTIVE"}},
    )
    assert answer(browser, "POST", "/events", {**events, "note": PRIVATE}) == (
        422,
        {"detail": {"code": "ACTIVITY_INPUT_INVALID"}},
    )
    clock.now = at(40)
    assert answer(browser, "POST", "/events", events) == (
        202,
        {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 3},
    )
    clock.now = at(60)
    assert answer(browser, "POST", "/sessions/SES-P01/end") == (
        200,
        {
            "status": "ACTIVITY_SESSION_ENDED",
            "session": {
                "code": "SES-P01",
                "started_at": at(0).isoformat(),
                "ended_at": at(60).isoformat(),
            },
        },
    )
    assert answer(browser, "POST", "/events", events) == (
        409,
        {"detail": {"code": "ACTIVITY_SESSION_NOT_ACTIVE"}},
    )
    assert answer(browser, "POST", "/sessions", {"session_code": "SES-P01"}) == (
        409,
        {"detail": {"code": "ACTIVITY_SESSION_CODE_USED"}},
    )
    assert answer(browser, "POST", "/sessions/SES-P0%201/end") == (
        422,
        {"detail": {"code": "ACTIVITY_INPUT_INVALID"}},
    )

    status, document = answer(browser, "GET", "")

    assert status == 200
    assert document["sessions"] == [
        {
            "code": "SES-P01",
            "started_at": at(0).isoformat(),
            "ended_at": at(60).isoformat(),
            "events": 5,
            "sources": ["STUDIO", "WEB"],
            "discarded_intervals": 0,
        }
    ]
    design = next(item for item in document["sections"] if item["key"] == "DESIGN")
    assert design["journal"] == {
        "opened": 1,
        "dwell_seconds": 30.0,
        "details_opened": 0,
        "why_opened": 0,
        "mockups_opened": 1,
    }
    assert PRIVATE not in json.dumps(document)


class FakeDatabaseRuntime:
    def __init__(self) -> None:
        self.session_factory = object()

    async def dispose(self) -> None:
        return None


def test_the_default_studio_registers_the_activity_service_and_its_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    for name in tuple(os.environ):
        if name.upper().startswith("ORCHESTWIN_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(
        "ORCHESTWIN_DATABASE_URL",
        "postgresql+psycopg://orchestwin:test@127.0.0.1:5432/orchestwin",
    )
    monkeypatch.setenv(
        "ORCHESTWIN_AUTH_JWT_SECRET",
        "a-runtime-test-secret-that-is-long-enough-for-validation",
    )
    database = FakeDatabaseRuntime()
    monkeypatch.setattr(services_module, "create_database_runtime", lambda _settings: database)
    settings = ApplicationSettings(
        environment=RuntimeEnvironment.TEST, api_prefix="/api/v1", debug=False, _env_file=None
    )

    runtime = services_module.create_default_runtime(settings)
    application = create_app(
        settings, runtime=runtime, auth_settings=AuthApiSettings(_env_file=None)
    )
    activity = runtime.activity_service

    assert isinstance(activity, SqlAlchemyProjectActivityService)
    assert application.state.activity_service is activity
    assert activity._session_factory is database.session_factory
    assert activity._journal is SqlAlchemyUsageJournalRepository
    assert TEMPLATE + "/events" in application.openapi()["paths"]
