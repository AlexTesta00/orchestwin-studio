from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orchestwin.activity import ACTORS, SECTIONS
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    IDEA,
    PROJECT_NAME,
    TEST_EMAIL,
    TEST_PASSWORD,
    Answer,
    Journey,
    Scene,
    StudioApi,
    StudioProcess,
    journey_scene,
    stay_on_the_studio,
)
from src.test.python.integration.test_postgresql_cli_verify import approve_the_design

pytestmark = pytest.mark.integration

CODE = "SES-P01"
STRANGER_EMAIL = "activity-stranger@example.com"
PRIVATE = ("Mario Rossi", "typed by the owner")
CLIENT = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
GATED = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN")
OWNER_REVISIONS = frozenset({"OWNER_EDITED", "OWNER_PROVIDED"})
LIMITS = [
    "ACTOR_DERIVED_FROM_RECORD_KIND",
    "ELAPSED_INCLUDES_IDLE_TIME",
    "FAILED_EVALUATION_RUNS_NOT_RECORDED",
    "GENERATION_JOBS_NOT_PERSISTED",
    "PRE_MODEL_REFUSALS_NOT_RECORDED",
    "VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS",
]
NO_GATE = {"submissions": 0, "approvals": 0, "revision_requests": 0, "rejections": 0}


def web(kind: str, seconds: float, **values: object) -> dict[str, object]:
    return {"kind": kind, "client_at": (CLIENT + timedelta(seconds=seconds)).isoformat(), **values}


BATCH = {
    "session_code": CODE,
    "source": "WEB",
    "events": [
        web("SECTION_OPENED", 0, section="BRIEF"),
        web("DETAIL_OPENED", 5, section="BRIEF", target="brief-assumptions"),
        web("SECTION_OPENED", 30, section="DESIGN"),
        web("MOCKUP_OPENED", 40, section="DESIGN", target="DES-001"),
        web("PAGE_HIDDEN", 90, section="DESIGN"),
    ],
}


def test_the_activity_tells_the_times_and_steps_of_a_real_project(tmp_path: Path) -> None:
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        steps = (
            ("1 a project taken to the approved design", lambda: approve_the_design(scene)),
            ("2 the activity tells the facts of every section", lambda: read_the_facts(scene)),
            ("3 a study session records the opened sections", lambda: record_a_session(scene)),
            ("4 another owner finds no activity", lambda: stay_outside(scene, studio.origin)),
        )
        for name, step in steps:
            if journey.problems:
                break
            with journey.step(name):
                step()
        with journey.step("every request stayed on the Studio of the test"):
            stay_on_the_studio(scene)
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def request(scene: Scene, method: str, suffix: str, body: object | None = None) -> Answer:
    return scene.api.request(method, f"{scene.base}/activity{suffix}", body)


def refused(answer: Answer, status: int, code: str) -> None:
    assert (answer.status, answer.json()) == (status, {"detail": {"code": code}}), answer.content


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value)


def by_key(document: Mapping) -> dict[str, Mapping]:
    return {section["key"]: section for section in document["sections"]}


def facts(document: Mapping, section: str, kind: str) -> list[Mapping]:
    return [
        event
        for event in document["events"]
        if (event["source"], event["section"], event["kind"]) == ("SERVER", section, kind)
    ]


def versions(document: Mapping, section: str, kind: str) -> set[int]:
    return {event["version_number"] for event in facts(document, section, kind)}


def private(scene: Scene) -> tuple[str, ...]:
    return (PROJECT_NAME, IDEA, TEST_EMAIL, str(scene.api.document("/auth/me")["id"]), *PRIVATE)


def read_the_facts(scene: Scene) -> None:
    document = scene.document("/activity")
    events = document["events"]
    sections = by_key(document)

    assert (document["kind"], document["schema_version"], document["project_id"]) == (
        "orchestwin.project-activity",
        1,
        scene.project_id,
    )
    assert list(sections) == list(SECTIONS)
    assert [event["number"] for event in events] == list(range(1, len(events) + 1))
    assert [instant(event["at"]) for event in events] == sorted(
        instant(event["at"]) for event in events
    )
    assert {event["source"] for event in events} == {"SERVER"}
    assert all(
        event["actor"] in ACTORS and event["session_code"] is None and event["target"] is None
        for event in events
    )
    assert (document["sessions"], document["limits"]) == ([], LIMITS)
    assert document["totals"]["events"] == len(events)

    assert len(facts(document, "BRIEF", "PROJECT_CREATED")) == 1
    current = {
        ("BRIEF", "BRIEF_VERSION_SAVED"): "/brief-versions/current",
        ("TEAM", "TEAM_VERSION_SAVED"): "/team-proposals/current",
        ("USER_TWINS", "TWINS_VERSION_SAVED"): "/user-modeling/snapshots/current",
        ("REQUIREMENTS", "DEFINITION_VERSION_SAVED"): "/requirements/current",
        ("DESIGN", "DESIGN_VERSION_SAVED"): "/design/current",
    }
    for (section, kind), path in current.items():
        assert scene.document(path)["version_number"] in versions(document, section, kind), kind
    assert versions(document, "PACKAGE", "PACKAGE_PUBLISHED") == set(scene.folder_numbers())
    assert all(
        event["actor"] == ("OWNER" if event["outcome"] in OWNER_REVISIONS else "MODEL")
        for event in facts(document, "TEAM", "TEAM_VERSION_SAVED")
    )

    for key in GATED:
        section = sections[key]
        assert section["gate"]["submissions"] >= 1, section
        assert section["gate"]["approvals"] >= 1, section
        assert instant(section["first_event_at"]) <= instant(section["first_approved_at"]), section
        assert section["approved_at"] is not None and section["elapsed_seconds"] >= 0, section
    assert sections["PACKAGE"]["gate"] == NO_GATE
    gates = [event for event in events if event["kind"].startswith("GATE_")]
    assert gates
    for event in gates:
        automatic = event["kind"] == "GATE_SUPERSEDED" or event["outcome"] == "ALIGNED"
        assert event["actor"] == ("STUDIO" if automatic else "OWNER"), event
        assert event["outcome"] is None or event["kind"] == "GATE_APPROVED", event
        assert isinstance(event["version_number"], int) and event["version_number"] >= 1, event

    generations = [event for event in events if event["kind"] == "GENERATION"]
    usage = scene.document("/model-usage")["totals"]["generations"]
    assert len(generations) == usage == document["totals"]["generations"]
    for event in generations:
        assert event["actor"] == "MODEL" and isinstance(event["purpose"], str), event
        assert event["duration_ms"] is None or event["duration_ms"] >= 0, event

    text = json.dumps(document)
    assert not [value for value in private(scene) if value in text]


def record_a_session(scene: Scene) -> None:
    assert scene.document("/activity/session") == {"active": False, "session": None}
    started = request(scene, "POST", "/sessions", {"session_code": CODE})
    assert started.status == 201, started.content
    session = started.json()["session"]
    assert (started.json()["status"], session["code"]) == ("ACTIVITY_SESSION_STARTED", CODE)
    assert scene.document("/activity/session") == {"active": True, "session": session}

    refused(
        request(scene, "POST", "/sessions", {"session_code": "SES-P02"}),
        409,
        "ACTIVITY_SESSION_ACTIVE",
    )
    refused(
        request(scene, "POST", "/sessions", {"session_code": CODE, "name": PRIVATE[0]}),
        422,
        "ACTIVITY_INPUT_INVALID",
    )
    refused(
        request(scene, "POST", "/events", {**BATCH, "note": PRIVATE[1]}),
        422,
        "ACTIVITY_INPUT_INVALID",
    )
    refused(
        request(scene, "POST", "/events", {**BATCH, "session_code": "SES-P02"}),
        409,
        "ACTIVITY_SESSION_NOT_ACTIVE",
    )
    recorded = request(scene, "POST", "/events", BATCH)
    assert (recorded.status, recorded.json()) == (
        202,
        {"status": "ACTIVITY_EVENTS_RECORDED", "recorded": len(BATCH["events"])},
    )
    ended = request(scene, "POST", f"/sessions/{CODE}/end")
    assert ended.status == 200, ended.content
    closed = ended.json()["session"]
    assert (ended.json()["status"], closed["code"], closed["started_at"]) == (
        "ACTIVITY_SESSION_ENDED",
        CODE,
        session["started_at"],
    )
    assert instant(closed["ended_at"]) >= instant(session["started_at"])
    refused(request(scene, "POST", "/events", BATCH), 409, "ACTIVITY_SESSION_NOT_ACTIVE")
    refused(request(scene, "POST", f"/sessions/{CODE}/end"), 409, "ACTIVITY_SESSION_NOT_ACTIVE")
    refused(
        request(scene, "POST", "/sessions", {"session_code": CODE}),
        409,
        "ACTIVITY_SESSION_CODE_USED",
    )
    assert scene.document("/activity/session") == {"active": False, "session": None}

    document = scene.document("/activity")
    sections = by_key(document)
    journal = [event for event in document["events"] if event["source"] != "SERVER"]
    assert document["sessions"] == [
        {
            "code": CODE,
            "started_at": session["started_at"],
            "ended_at": closed["ended_at"],
            "events": len(BATCH["events"]) + 2,
            "sources": ["STUDIO", "WEB"],
            "discarded_intervals": 0,
        }
    ]
    assert [event["kind"] for event in journal if event["source"] == "WEB"] == [
        item["kind"] for item in BATCH["events"]
    ]
    studio = [(event["kind"], event["actor"]) for event in journal if event["source"] == "STUDIO"]
    assert studio == [("SESSION_STARTED", "STUDIO"), ("SESSION_ENDED", "STUDIO")]
    assert all(event["session_code"] == CODE for event in journal)
    assert sections["BRIEF"]["journal"] == {
        "opened": 1,
        "dwell_seconds": 30.0,
        "details_opened": 1,
        "why_opened": 0,
        "mockups_opened": 0,
    }
    assert sections["DESIGN"]["journal"] == {
        "opened": 1,
        "dwell_seconds": 60.0,
        "details_opened": 0,
        "why_opened": 0,
        "mockups_opened": 1,
    }
    assert "CLIENT_CLOCK_NOT_VERIFIED" in document["limits"]
    assert document["totals"]["events"] == len(document["events"])
    text = json.dumps(document)
    assert not [value for value in private(scene) if value in text]


def stay_outside(scene: Scene, origin: str) -> None:
    stranger = StudioApi(origin)
    registered = stranger.register(STRANGER_EMAIL, TEST_PASSWORD)
    assert registered.status == 201, f"registration answered {registered.status}"
    for method, suffix, body in (
        ("GET", "", None),
        ("GET", "/session", None),
        ("POST", "/sessions", {"session_code": "SES-X01"}),
        ("POST", f"/sessions/{CODE}/end", None),
        ("POST", "/events", BATCH),
    ):
        answer = stranger.request(method, f"/projects/{scene.project_id}/activity{suffix}", body)
        refused(answer, 404, "PROJECT_NOT_FOUND")
    assert scene.document("/activity")["sessions"][0]["events"] == len(BATCH["events"]) + 2
