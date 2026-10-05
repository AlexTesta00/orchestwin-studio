from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta

import pytest

from orchestwin.activity import MAX_JOURNAL_EVENTS, project_activity
from orchestwin.cli.commands import activity as activity_command

from .support.fake_studio import (
    PREFIX,
    FakeProject,
    FakeStudio,
    _Answer,
    _Call,
    _Invalid,
    _Refusal,
    route_table,
)
from .support.terminal import START

OWNER = "owner@example.com"
STRANGER = "stranger@example.com"
PASSWORD = "Test-password-not-real!"
BASE = "/projects/{project_id}/activity"
SECTION_KEYS = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
NOT_ACTIVE = (409, {"code": "ACTIVITY_SESSION_NOT_ACTIVE"})
INVALID = (422, {"code": "ACTIVITY_INPUT_INVALID"})


def studio_with(through: str = "design") -> tuple[FakeStudio, FakeProject]:
    studio = FakeStudio(language="en")
    studio.add_account(OWNER, PASSWORD)
    return studio, studio.seed_project(owner=OWNER, name="Synthetic study", through=through)


def call(
    project: FakeProject,
    method: str,
    suffix: str = "",
    body: object = None,
    *,
    raw: bytes | None = None,
    **params: str,
) -> _Call:
    content = raw if raw is not None else b"" if body is None else json.dumps(body).encode()
    return _Call(
        method,
        f"/projects/{project.id}/activity{suffix}",
        project.account,
        {"project_id": project.id, **params},
        {},
        {},
        content,
        False,
    )


def refused(route: Callable[[_Call], _Answer], value: _Call) -> tuple[int, object]:
    with pytest.raises(_Refusal) as caught:
        route(value)
    return caught.value.status, caught.value.detail


def start(studio: FakeStudio, project: FakeProject, code: str = "SES-P01") -> _Answer:
    return studio._route_activity_start(call(project, "POST", "/sessions", {"session_code": code}))


def batch(code: str = "SES-P01", name: str = "design", waits: int = 0) -> dict[str, object]:
    moments = [(START + timedelta(seconds=index), 1.5, 201) for index in range(waits)]
    return activity_command.journal(
        code, name, START, START + timedelta(seconds=30), 30.0, 0, moments
    )


def test_the_fake_serves_exactly_the_five_routes_of_the_contract() -> None:
    base = PREFIX + BASE
    found = {route for route in route_table() if route[1].startswith(base)}

    assert found == {
        ("GET", base),
        ("GET", base + "/session"),
        ("POST", base + "/sessions"),
        ("POST", base + "/sessions/{session_code}/end"),
        ("POST", base + "/events"),
    }


def test_a_session_starts_ends_and_its_code_is_never_used_again() -> None:
    studio, project = studio_with()

    started = start(studio, project)
    active = studio._route_activity_session(call(project, "GET", "/session"))
    while_active = [
        refused(
            studio._route_activity_start,
            call(project, "POST", "/sessions", {"session_code": "SES-P02"}),
        ),
        refused(
            studio._route_activity_end,
            call(project, "POST", "/sessions/SES-P02/end", session_code="SES-P02"),
        ),
    ]
    ended = studio._route_activity_end(
        call(project, "POST", "/sessions/SES-P01/end", session_code="SES-P01")
    )
    idle = studio._route_activity_session(call(project, "GET", "/session"))
    afterwards = [
        refused(
            studio._route_activity_start,
            call(project, "POST", "/sessions", {"session_code": "SES-P01"}),
        ),
        refused(
            studio._route_activity_end,
            call(project, "POST", "/sessions/SES-P01/end", session_code="SES-P01"),
        ),
    ]

    journal = project.activity_journal
    session = {"code": "SES-P01", "started_at": journal[0]["received_at"]}
    assert (started.status, started.body) == (
        201,
        {"status": "ACTIVITY_SESSION_STARTED", "session": session},
    )
    assert (active.status, active.body) == (200, {"active": True, "session": session})
    assert while_active == [(409, {"code": "ACTIVITY_SESSION_ACTIVE"}), NOT_ACTIVE]
    assert (ended.status, ended.body) == (
        200,
        {
            "status": "ACTIVITY_SESSION_ENDED",
            "session": {**session, "ended_at": journal[1]["received_at"]},
        },
    )
    assert idle.body == {"active": False, "session": None}
    assert afterwards == [(409, {"code": "ACTIVITY_SESSION_CODE_USED"}), NOT_ACTIVE]
    assert [(row["sequence"], row["source"], row["kind"]) for row in journal] == [
        (1, "STUDIO", "SESSION_STARTED"),
        (2, "STUDIO", "SESSION_ENDED"),
    ]
    assert project.usage == []


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"session_code": "ses-p01"}).encode(),
        json.dumps({"session_code": "SES-"}).encode(),
        json.dumps({"session_code": "SES-" + "A" * 21}).encode(),
        json.dumps({"session_code": 5}).encode(),
        json.dumps({"session_code": "SES-P01", "name": "Mario Rossi"}).encode(),
        json.dumps({}).encode(),
        json.dumps(["SES-P01"]).encode(),
        b"",
    ],
)
def test_a_start_that_is_not_valid_is_refused_without_the_input_in_the_answer(
    content: bytes,
) -> None:
    studio, project = studio_with("brief")

    assert (
        refused(studio._route_activity_start, call(project, "POST", "/sessions", raw=content))
        == INVALID
    )
    assert project.activity_journal == []


def test_a_body_that_is_not_json_is_refused_like_the_real_application() -> None:
    studio, project = studio_with("brief")

    with pytest.raises(_Invalid) as caught:
        studio._route_activity_start(call(project, "POST", "/sessions", raw=b"{"))

    assert caught.value.errors == [{"loc": ["body", 0], "type": "json_invalid"}]
    assert project.activity_journal == []


def test_the_input_is_checked_before_the_project_like_the_real_router() -> None:
    studio, project = studio_with("brief")
    studio.add_account(STRANGER, PASSWORD)
    values = [
        call(project, "POST", "/sessions", {"session_code": "ses-p01"}),
        call(project, "POST", "/sessions/x/end", session_code="SES-p01"),
        call(project, "POST", "/events", {**batch(), "source": "WEB"}),
    ]
    for value in values:
        value.user = studio._accounts[STRANGER]

    assert [
        refused(route, value)
        for route, value in zip(
            (
                studio._route_activity_start,
                studio._route_activity_end,
                studio._route_activity_events,
            ),
            values,
            strict=True,
        )
    ] == [INVALID, INVALID, INVALID]


def test_a_full_journal_refuses_a_new_session() -> None:
    studio, project = studio_with("brief")
    start(studio, project)
    studio._route_activity_end(
        call(project, "POST", "/sessions/SES-P01/end", session_code="SES-P01")
    )
    project.activity_journal.extend(
        {**project.activity_journal[-1], "sequence": sequence}
        for sequence in range(3, MAX_JOURNAL_EVENTS + 1)
    )

    full = refused(
        studio._route_activity_start,
        call(project, "POST", "/sessions", {"session_code": "SES-P02"}),
    )

    assert full == (409, {"code": "ACTIVITY_JOURNAL_FULL"})
    assert len(project.activity_journal) == MAX_JOURNAL_EVENTS


def test_a_batch_of_the_command_line_is_recorded_after_the_session_rows() -> None:
    studio, project = studio_with("brief")
    start(studio, project)

    answer = studio._route_activity_events(call(project, "POST", "/events", batch(waits=2)))

    rows = project.activity_journal[1:]
    assert (answer.status, answer.body) == (
        202,
        {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 4},
    )
    assert [row["sequence"] for row in rows] == [2, 3, 4, 5]
    assert [row["kind"] for row in rows] == [
        "COMMAND_STARTED",
        "GENERATION_WAITED",
        "GENERATION_WAITED",
        "COMMAND_FINISHED",
    ]
    assert {row["received_at"] for row in rows} == {project.activity_journal[1]["received_at"]}
    assert rows[0]["client_at"] == START.isoformat()
    assert rows[1]["duration_ms"] == 1500
    assert rows[-1]["status"] == "0"
    assert all(row["session_code"] == "SES-P01" and row["source"] == "UT" for row in rows)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (batch("SES-P02"), NOT_ACTIVE),
        ({**batch(), "note": "free text"}, INVALID),
        ({**batch(), "source": "WEB"}, INVALID),
        ({**batch(), "source": "STUDIO"}, INVALID),
        ({**batch(), "events": batch()["events"][:1] * 51}, INVALID),
        ({**batch(), "events": []}, INVALID),
        ({"session_code": "SES-P01", "source": "UT"}, INVALID),
        (["not", "an", "object"], INVALID),
    ],
)
def test_a_batch_that_breaks_a_rule_is_refused_and_nothing_is_recorded(
    body: object, expected: tuple[int, object]
) -> None:
    studio, project = studio_with("brief")
    start(studio, project)

    assert (
        refused(studio._route_activity_events, call(project, "POST", "/events", body)) == expected
    )
    assert len(project.activity_journal) == 1


def test_without_an_active_session_a_batch_is_refused() -> None:
    studio, project = studio_with("brief")

    assert (
        refused(studio._route_activity_events, call(project, "POST", "/events", batch()))
        == NOT_ACTIVE
    )


def test_a_full_journal_refuses_the_batch_that_would_go_over_the_limit() -> None:
    studio, project = studio_with("brief")
    start(studio, project)
    moment = START.isoformat()
    project.activity_journal.extend(
        {
            "sequence": sequence,
            "session_code": "SES-P01",
            "source": "UT",
            "kind": "COMMAND_STARTED",
            "section": None,
            "target": "status",
            "client_at": moment,
            "received_at": moment,
            "duration_ms": None,
            "status": None,
        }
        for sequence in range(2, MAX_JOURNAL_EVENTS)
    )
    single = {**batch(), "events": batch()["events"][:1]}

    full = refused(studio._route_activity_events, call(project, "POST", "/events", batch()))
    last = studio._route_activity_events(call(project, "POST", "/events", single))

    assert full == (409, {"code": "ACTIVITY_JOURNAL_FULL"})
    assert last.body == {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": 1}
    assert len(project.activity_journal) == MAX_JOURNAL_EVENTS


@pytest.mark.parametrize(
    ("route", "method", "suffix", "body", "params"),
    [
        ("_route_activity", "GET", "", None, {}),
        ("_route_activity_session", "GET", "/session", None, {}),
        ("_route_activity_start", "POST", "/sessions", {"session_code": "SES-P01"}, {}),
        (
            "_route_activity_end",
            "POST",
            "/sessions/SES-P01/end",
            None,
            {"session_code": "SES-P01"},
        ),
        ("_route_activity_events", "POST", "/events", batch(), {}),
    ],
)
def test_every_route_hides_the_project_of_another_owner(
    route: str, method: str, suffix: str, body: object, params: dict[str, str]
) -> None:
    studio, project = studio_with("brief")
    studio.add_account(STRANGER, PASSWORD)
    start(studio, project)
    stranger = studio._accounts[STRANGER]
    value = call(project, method, suffix, body, **params)
    value.user = stranger

    assert refused(getattr(studio, route), value) == (404, {"code": "PROJECT_NOT_FOUND"})
    assert len(project.activity_journal) == 1


def test_the_document_is_built_by_the_shared_module_from_the_state_of_the_project() -> None:
    studio, project = studio_with()
    for operation in ("PERSONA_PROPOSAL", "DESIGN_PROPOSAL", "TEST_PLAN"):
        studio._record(project, operation)
    start(studio, project)
    studio._route_activity_events(call(project, "POST", "/events", batch(waits=1)))

    answer = studio._route_activity(call(project, "GET"))

    document = answer.body
    sections = {item["key"]: item for item in document["sections"]}
    events = document["events"]
    assert answer.status == 200
    assert document == project_activity(
        project_id=project.id,
        facts=studio._activity_facts(project),
        journal=project.activity_journal,
    )
    assert [bool(sections[key]["first_approved_at"]) for key in SECTION_KEYS] == [
        True,
        True,
        True,
        True,
        True,
        False,
    ]
    assert {key: sections[key]["generations"]["count"] for key in SECTION_KEYS} == {
        "BRIEF": 0,
        "TEAM": 0,
        "USER_TWINS": 1,
        "REQUIREMENTS": 0,
        "DESIGN": 1,
        "PACKAGE": 1,
    }
    assert sections["BRIEF"]["owner_actions"] >= 4
    assert {
        "PROJECT_CREATED",
        "BRIEF_VERSION_SAVED",
        "TEAM_VERSION_SAVED",
        "TWINS_VERSION_SAVED",
        "DEFINITION_VERSION_SAVED",
        "DESIGN_VERSION_SAVED",
        "GATE_SUBMITTED",
        "GATE_APPROVED",
        "GENERATION",
        "SESSION_STARTED",
        "COMMAND_STARTED",
        "GENERATION_WAITED",
        "COMMAND_FINISHED",
    } <= {event["kind"] for event in events}
    assert {
        (event["actor"], event["outcome"])
        for event in events
        if event["kind"] == "TEAM_VERSION_SAVED"
    } == {("MODEL", "PROPOSER_GENERATED")}
    assert {event["actor"] for event in events if event["kind"].startswith("GATE_")} == {"OWNER"}
    assert "CLIENT_CLOCK_NOT_VERIFIED" in document["limits"]
    assert document["sessions"][0]["code"] == "SES-P01"


def test_the_brief_dialogue_of_the_fake_becomes_questions_and_answers() -> None:
    studio = FakeStudio(language="en")
    studio.add_account(OWNER, PASSWORD)
    account = studio._accounts[OWNER]
    project = studio._new_project(account, "Synthetic dialogue", "GREENFIELD_GENERATION")
    dialogue = f"/projects/{project.id}/brief-dialogue"
    opened = _Call(
        "POST",
        dialogue,
        account,
        {"project_id": project.id},
        {},
        {},
        json.dumps({"statement": "A tip calculator for a small bar."}).encode(),
        False,
    )
    studio._route_dialogue_start(opened)
    answered = _Call(
        "POST",
        f"{dialogue}/answers",
        account,
        {"project_id": project.id},
        {},
        {},
        json.dumps({"expected_turn_count": 1, "kind": "UNKNOWN"}).encode(),
        False,
    )
    studio._route_dialogue_answer(answered)

    document = studio._route_activity(call(project, "GET")).body

    assert document["brief_dialogue"]["questions"] == 2
    assert document["brief_dialogue"]["answered"] == 1
    assert document["brief_dialogue"]["unknown_answers"] == 1
    assert len(document["brief_dialogue"]["answer_seconds"]) == 1
    assert document["sections"][0]["generations"]["count"] == 2
    assert document["sessions"] == []
    assert "CLIENT_CLOCK_NOT_VERIFIED" not in document["limits"]
