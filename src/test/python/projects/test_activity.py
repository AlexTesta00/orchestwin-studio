from __future__ import annotations

import json
import random
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone

import pytest

from orchestwin import activity
from orchestwin.activity import (
    ACTIVITY_KIND,
    ACTIVITY_SCHEMA_VERSION,
    ACTORS,
    JOURNAL_KINDS,
    MAX_BATCH_EVENTS,
    MAX_DURATION_MS,
    MAX_DWELL_INTERVAL_SECONDS,
    MAX_JOURNAL_EVENTS,
    SECTIONS,
    SESSION_CODE_PATTERN,
    SESSION_KINDS,
    STATUS_PATTERN,
    TARGET_PATTERN,
    ActivityError,
    active_session,
    journal_rows,
    project_activity,
    validate_session_code,
)

START = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
ROME = timezone(timedelta(hours=2))
WESTERN = timezone(timedelta(hours=-4, minutes=-30))
CLIENT = "2026-10-04T10:00:00+02:00"
LIMITS = [
    "ACTOR_DERIVED_FROM_RECORD_KIND",
    "ELAPSED_INCLUDES_IDLE_TIME",
    "FAILED_EVALUATION_RUNS_NOT_RECORDED",
    "GENERATION_JOBS_NOT_PERSISTED",
    "PRE_MODEL_REFUSALS_NOT_RECORDED",
    "VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS",
]
ROW_KEYS = [
    "session_code",
    "source",
    "kind",
    "section",
    "target",
    "client_at",
    "duration_ms",
    "status",
]
EVENT_KEYS = [
    "number",
    "at",
    "source",
    "section",
    "kind",
    "actor",
    "code",
    "version_number",
    "duration_ms",
    "outcome",
    "purpose",
    "role",
    "session_code",
    "target",
]
MANDATORY = {
    "SECTION_OPENED": {"section": "BRIEF"},
    "DETAIL_OPENED": {"target": "brief-assumptions"},
    "WHY_OPENED": {"target": "BRF-001"},
    "MOCKUP_OPENED": {"target": "ALT-2"},
    "MODE_CHANGED": {"status": "EXPERT"},
    "LOCALE_SET": {"status": "it"},
    "PAGE_HIDDEN": {},
    "PAGE_VISIBLE": {},
    "REQUEST_FAILED": {"status": "409"},
    "COMMAND_STARTED": {"target": "design"},
    "COMMAND_FINISHED": {"target": "design", "status": "0", "duration_ms": 1200},
    "GENERATION_WAITED": {"target": "design", "duration_ms": 45000},
}


def moment(seconds, zone=UTC):
    return (START + timedelta(seconds=seconds)).astimezone(zone).isoformat()


def fact(seconds, section, kind, actor="OWNER", **values):
    return {
        "at": moment(seconds),
        "section": section,
        "kind": kind,
        "actor": actor,
        "code": None,
        "version_number": None,
        "duration_ms": None,
        "outcome": None,
        "purpose": None,
        "role": None,
        **values,
    }


def generation(seconds, section, duration_ms, outcome, **values):
    return fact(
        seconds,
        section,
        "GENERATION",
        "MODEL",
        duration_ms=duration_ms,
        outcome=outcome,
        purpose=section.lower(),
        **values,
    )


def row(sequence, kind, client=None, *, received=None, source="WEB", code="SES-P01", **values):
    return {
        "sequence": sequence,
        "session_code": code,
        "source": source,
        "kind": kind,
        "section": None,
        "target": None,
        "client_at": None if client is None else moment(client),
        "received_at": moment(client if received is None else received),
        "duration_ms": None,
        "status": None,
        **values,
    }


def command(sequence, kind, client, **values):
    return row(sequence, kind, client, **{"source": "UT", "target": "design", **values})


def started(sequence, received, code="SES-P01"):
    return row(sequence, "SESSION_STARTED", received=received, source="STUDIO", code=code)


def ended(sequence, received, code="SES-P01"):
    return row(sequence, "SESSION_ENDED", received=received, source="STUDIO", code=code)


def event(kind, **values):
    return {"kind": kind, "client_at": CLIENT, **MANDATORY[kind], **values}


def document_for(facts=(), journal=()):
    return project_activity(project_id="project", facts=list(facts), journal=list(journal))


def section(document, key):
    return next(item for item in document["sections"] if item["key"] == key)


def timing(document, key):
    item = section(document, key)
    return (
        item["first_event_at"],
        item["last_event_at"],
        item["first_approved_at"],
        item["approved_at"],
        item["elapsed_seconds"],
    )


def dwell(document):
    return {item["key"]: item["journal"]["dwell_seconds"] for item in document["sections"]}


def scenario():
    facts = [
        fact(0, "BRIEF", "PROJECT_CREATED"),
        fact(30, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
        fact(42.5, "BRIEF", "BRIEF_QUESTION_ANSWERED", duration_ms=12500, outcome="UNKNOWN"),
        fact(60, "BRIEF", "GATE_SUBMITTED", version_number=1),
        fact(61, "BRIEF", "GATE_APPROVED", version_number=1),
        generation(120, "TEAM", 30000, "SUCCEEDED"),
        fact(150, "TEAM", "TEAM_VERSION_SAVED", "MODEL", version_number=1, outcome="MODEL"),
        fact(200, "TEAM", "GATE_APPROVED", version_number=1),
        generation(300, "DESIGN", 90000, "TIMEOUT", role="PRIMARY"),
    ]
    journal = [
        started(1, received=20),
        row(2, "SECTION_OPENED", 21, section="BRIEF"),
        row(3, "MODE_CHANGED", 22, section="BRIEF", status="GUIDED"),
        row(4, "LOCALE_SET", 23, section="BRIEF", status="it"),
        row(5, "SECTION_OPENED", 100, section="TEAM"),
        row(6, "DETAIL_OPENED", 130, section="TEAM", target="team-roles"),
        row(7, "PAGE_HIDDEN", 240, section="TEAM"),
        command(8, "COMMAND_STARTED", 299),
        command(9, "GENERATION_WAITED", 390, duration_ms=90000),
        command(10, "COMMAND_FINISHED", 391, duration_ms=92000, status="1"),
        ended(11, received=400),
    ]
    return facts, journal


def test_constants_and_public_names_follow_the_contract():
    assert SECTIONS == ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
    assert ACTORS == ("OWNER", "MODEL", "STUDIO")
    assert JOURNAL_KINDS == {
        "WEB": (
            "SECTION_OPENED",
            "DETAIL_OPENED",
            "WHY_OPENED",
            "MOCKUP_OPENED",
            "MODE_CHANGED",
            "LOCALE_SET",
            "PAGE_HIDDEN",
            "PAGE_VISIBLE",
            "REQUEST_FAILED",
        ),
        "UT": ("COMMAND_STARTED", "COMMAND_FINISHED", "GENERATION_WAITED"),
    }
    assert SESSION_KINDS == ("SESSION_STARTED", "SESSION_ENDED")
    assert SESSION_CODE_PATTERN == r"SES-[A-Z0-9][A-Z0-9-]{0,19}"
    assert TARGET_PATTERN == r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}"
    assert STATUS_PATTERN == r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}"
    assert MAX_BATCH_EVENTS == 50 and MAX_JOURNAL_EVENTS == 20000
    assert MAX_DURATION_MS == 86_400_000 and MAX_DWELL_INTERVAL_SECONDS == 14_400
    assert (ACTIVITY_KIND, ACTIVITY_SCHEMA_VERSION) == ("orchestwin.project-activity", 1)
    assert set(activity.__all__) == {
        "ACTIVITY_KIND",
        "ACTIVITY_SCHEMA_VERSION",
        "ACTORS",
        "JOURNAL_KINDS",
        "MAX_BATCH_EVENTS",
        "MAX_DURATION_MS",
        "MAX_DWELL_INTERVAL_SECONDS",
        "MAX_JOURNAL_EVENTS",
        "SECTIONS",
        "SESSION_CODE_PATTERN",
        "SESSION_KINDS",
        "STATUS_PATTERN",
        "TARGET_PATTERN",
        "ActivityError",
        "active_session",
        "journal_rows",
        "project_activity",
        "validate_session_code",
    }


def test_events_merge_facts_and_journal_by_instant_then_source_then_sequence():
    facts = [
        fact(10, "BRIEF", "PROJECT_CREATED"),
        fact(5, "BRIEF", "BRIEF_VERSION_SAVED", version_number=1),
        generation(10, "TEAM", 1500, "SUCCEEDED"),
    ]
    journal = [
        command(4, "COMMAND_STARTED", 10),
        row(3, "MODE_CHANGED", 10, received=11, section="BRIEF", status="GUIDED"),
        row(2, "SECTION_OPENED", 10, received=12, section="BRIEF"),
        started(1, received=10),
        row(6, "WHY_OPENED", 4, received=30, section="BRIEF", target="BRF-001"),
        command(7, "COMMAND_FINISHED", 60, duration_ms=50000, status="0"),
    ]
    events = document_for(facts, journal)["events"]
    assert [(item["number"], item["source"], item["kind"]) for item in events] == [
        (1, "WEB", "WHY_OPENED"),
        (2, "SERVER", "BRIEF_VERSION_SAVED"),
        (3, "SERVER", "PROJECT_CREATED"),
        (4, "SERVER", "GENERATION"),
        (5, "STUDIO", "SESSION_STARTED"),
        (6, "WEB", "SECTION_OPENED"),
        (7, "WEB", "MODE_CHANGED"),
        (8, "UT", "COMMAND_STARTED"),
        (9, "UT", "COMMAND_FINISHED"),
    ]
    assert events[0] == {
        "number": 1,
        "at": moment(4),
        "source": "WEB",
        "section": "BRIEF",
        "kind": "WHY_OPENED",
        "actor": "OWNER",
        "code": None,
        "version_number": None,
        "duration_ms": None,
        "outcome": None,
        "purpose": None,
        "role": None,
        "session_code": "SES-P01",
        "target": "BRF-001",
    }
    assert events[3] == {
        "number": 4,
        "at": moment(10),
        "source": "SERVER",
        "section": "TEAM",
        "kind": "GENERATION",
        "actor": "MODEL",
        "code": None,
        "version_number": None,
        "duration_ms": 1500,
        "outcome": "SUCCEEDED",
        "purpose": "team",
        "role": None,
        "session_code": None,
        "target": None,
    }
    assert (events[1]["version_number"], events[1]["session_code"], events[1]["target"]) == (
        1,
        None,
        None,
    )
    assert [item["at"] for item in events[2:8]] == [moment(10)] * 6
    assert [item["actor"] for item in events[4:]] == ["STUDIO", "OWNER", "OWNER", "OWNER", "OWNER"]
    assert (events[6]["outcome"], events[8]["duration_ms"], events[8]["outcome"]) == (
        "GUIDED",
        50000,
        "0",
    )
    swapped = document_for(facts[::-1], journal)["events"]
    assert [item["kind"] for item in swapped[1:4]] == [
        "BRIEF_VERSION_SAVED",
        "GENERATION",
        "PROJECT_CREATED",
    ]
    assert [item["number"] for item in swapped] == list(range(1, 10))


def test_sections_are_always_the_six_in_contract_order_even_without_facts():
    empty = document_for()
    blank = {
        "first_event_at": None,
        "last_event_at": None,
        "first_approved_at": None,
        "approved_at": None,
        "elapsed_seconds": None,
        "owner_actions": 0,
        "gate": {"submissions": 0, "approvals": 0, "revision_requests": 0, "rejections": 0},
        "generations": {"count": 0, "succeeded": 0, "failed": 0, "retries": 0, "wait_seconds": 0},
        "journal": {
            "opened": 0,
            "dwell_seconds": 0.0,
            "details_opened": 0,
            "why_opened": 0,
            "mockups_opened": 0,
        },
    }
    assert empty["sections"] == [{"key": key, **blank} for key in SECTIONS]
    assert (empty["kind"], empty["schema_version"], empty["project_id"]) == (
        "orchestwin.project-activity",
        1,
        "project",
    )
    assert (empty["events"], empty["sessions"], empty["limits"]) == ([], [], LIMITS)
    assert empty["brief_dialogue"] == {
        "questions": 0,
        "answered": 0,
        "unknown_answers": 0,
        "answer_seconds": [],
    }
    assert empty["totals"] == {
        "events": 0,
        "owner_actions": 0,
        "generations": 0,
        "generation_wait_seconds": 0.0,
        "first_event_at": None,
        "last_event_at": None,
    }
    assert isinstance(empty["totals"]["generation_wait_seconds"], float)
    assert all(
        isinstance(item["generations"]["wait_seconds"], float)
        and isinstance(item["journal"]["dwell_seconds"], float)
        for item in empty["sections"]
    )
    design_only = document_for([fact(0, "DESIGN", "DESIGN_VERSION_SAVED", "STUDIO")])
    assert [item["key"] for item in design_only["sections"]] == list(SECTIONS)
    assert [item["first_event_at"] for item in design_only["sections"]] == [
        None,
        None,
        None,
        None,
        moment(0),
        None,
    ]


def test_approval_instants_and_elapsed_time_come_from_server_facts_only():
    facts = [
        fact(900, "REQUIREMENTS", "GATE_APPROVED", "STUDIO", version_number=2, outcome="ALIGNED"),
        fact(1000, "REQUIREMENTS", "DEFINITION_CHANGE_PROPOSED"),
        fact(400.26, "REQUIREMENTS", "GATE_APPROVED", version_number=1),
        fact(250, "REQUIREMENTS", "GATE_SUBMITTED", version_number=1),
        fact(100, "REQUIREMENTS", "DEFINITION_VERSION_SAVED", "STUDIO", version_number=1),
        fact(2000, "DESIGN", "DESIGN_VERSION_SAVED", "STUDIO", version_number=1),
        fact(50, "BRIEF", "PROJECT_CREATED"),
    ]
    journal = [started(1, received=0), row(2, "SECTION_OPENED", 20, section="REQUIREMENTS")]
    document = document_for(facts, journal)
    assert timing(document, "REQUIREMENTS") == (
        moment(100),
        moment(1000),
        "2026-10-04T08:06:40.260000+00:00",
        moment(900),
        300.3,
    )
    assert timing(document, "DESIGN") == (moment(2000), moment(2000), None, None, None)
    assert timing(document, "BRIEF") == (moment(50), moment(50), None, None, None)
    assert timing(document, "TEAM") == (None, None, None, None, None)


def test_gates_owner_actions_and_generations_are_counted_per_section_from_facts():
    facts = [
        fact(10, "DESIGN", "GATE_SUBMITTED"),
        generation(15, "DESIGN", 1500, "SUCCEEDED"),
        fact(20, "DESIGN", "GATE_REVISION_REQUESTED"),
        generation(25, "DESIGN", 2000, "TIMEOUT"),
        fact(30, "DESIGN", "GATE_SUBMITTED", "STUDIO"),
        generation(35, "DESIGN", 1234, "SUCCEEDED", role="PRIMARY"),
        fact(40, "DESIGN", "GATE_REJECTED"),
        generation(45, "DESIGN", None, "PROVIDER_REFUSED", role="PRIMARY"),
        fact(50, "DESIGN", "GATE_SUBMITTED"),
        fact(60, "DESIGN", "GATE_APPROVED"),
        fact(70, "DESIGN", "GATE_PAUSED"),
        generation(5, "TEAM", 40000, "SUCCEEDED"),
        fact(6, "TEAM", "TEAM_VERSION_SAVED", version_number=2, outcome="OWNER_EDITED"),
    ]
    journal = [
        started(1, received=0),
        row(2, "SECTION_OPENED", 8, section="DESIGN"),
        command(3, "GENERATION_WAITED", 9, duration_ms=9999),
    ]
    document = document_for(facts, journal)
    design, team = section(document, "DESIGN"), section(document, "TEAM")
    assert design["gate"] == {
        "submissions": 3,
        "approvals": 1,
        "revision_requests": 1,
        "rejections": 1,
    }
    assert design["generations"] == {
        "count": 4,
        "succeeded": 2,
        "failed": 2,
        "retries": 1,
        "wait_seconds": 4.7,
    }
    assert team["gate"] == dict.fromkeys(design["gate"], 0)
    assert team["generations"] == {
        "count": 1,
        "succeeded": 1,
        "failed": 0,
        "retries": 0,
        "wait_seconds": 40.0,
    }
    assert (design["owner_actions"], team["owner_actions"]) == (6, 1)
    assert document["totals"] == {
        "events": 16,
        "owner_actions": 7,
        "generations": 5,
        "generation_wait_seconds": 44.7,
        "first_event_at": moment(0),
        "last_event_at": moment(70),
    }


def test_retries_count_only_generations_with_a_role_that_did_not_succeed():
    facts = [
        generation(1, "USER_TWINS", 1000, "SUCCEEDED", role="DIRECTION"),
        generation(2, "USER_TWINS", 1000, "SUCCEEDED", role="TWIN_REVIEW"),
        generation(3, "USER_TWINS", 1000, "TIMEOUT", role="PRIMARY"),
        generation(4, "USER_TWINS", 1000, "RESPONSE_SCHEMA_ERROR"),
        generation(5, "USER_TWINS", 1000, "SUCCEEDED"),
    ]
    assert section(document_for(facts), "USER_TWINS")["generations"] == {
        "count": 5,
        "succeeded": 3,
        "failed": 2,
        "retries": 1,
        "wait_seconds": 5.0,
    }
    assert section(document_for(facts[:2]), "USER_TWINS")["generations"]["retries"] == 0
    assert section(document_for(facts[2:3]), "USER_TWINS")["generations"]["retries"] == 1


def test_brief_dialogue_counts_questions_answers_unknowns_and_durations_in_order():
    facts = [
        fact(0, "BRIEF", "BRIEF_DIALOGUE_STARTED"),
        fact(10, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
        fact(14.2, "BRIEF", "BRIEF_QUESTION_ANSWERED", duration_ms=4200, outcome="TEXT"),
        fact(20, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
        fact(81.049, "BRIEF", "BRIEF_QUESTION_ANSWERED", duration_ms=61049, outcome="UNKNOWN"),
        fact(90, "BRIEF", "BRIEF_QUESTION_ASKED", "MODEL"),
        fact(95, "BRIEF", "BRIEF_QUESTION_ANSWERED", outcome="UNKNOWN"),
        fact(99, "BRIEF", "BRIEF_DIALOGUE_COMPLETED", "STUDIO"),
    ]
    assert document_for(facts[::-1])["brief_dialogue"] == {
        "questions": 3,
        "answered": 3,
        "unknown_answers": 2,
        "answer_seconds": [4.2, 61.0],
    }


def test_sessions_report_bounds_event_counts_and_sources_in_start_order():
    journal = [
        started(1, received=0),
        row(2, "SECTION_OPENED", 5, section="BRIEF"),
        command(3, "COMMAND_STARTED", 7),
        command(4, "COMMAND_FINISHED", 9, duration_ms=2000, status="0"),
        ended(5, received=30),
        started(6, received=100, code="SES-P02"),
        row(7, "LOCALE_SET", 101, code="SES-P02", section="BRIEF", status="en"),
    ]
    document = document_for(journal=journal[::-1])
    assert document["sessions"] == [
        {
            "code": "SES-P01",
            "started_at": moment(0),
            "ended_at": moment(30),
            "events": 5,
            "sources": ["STUDIO", "UT", "WEB"],
            "discarded_intervals": 0,
        },
        {
            "code": "SES-P02",
            "started_at": moment(100),
            "ended_at": None,
            "events": 2,
            "sources": ["STUDIO", "WEB"],
            "discarded_intervals": 0,
        },
    ]
    assert dwell(document)["BRIEF"] == 0.0
    assert active_session(journal) == {"code": "SES-P02", "started_at": moment(100)}


def test_dwell_follows_section_changes_hidden_pages_and_the_session_end():
    journal = [
        started(1, received=0),
        row(2, "SECTION_OPENED", 10, section="BRIEF"),
        row(3, "DETAIL_OPENED", 40, section="BRIEF", target="brief-assumptions"),
        row(4, "SECTION_OPENED", 70, section="TEAM"),
        row(5, "PAGE_HIDDEN", 100, section="TEAM"),
        row(6, "PAGE_VISIBLE", 400, section="TEAM"),
        row(7, "WHY_OPENED", 430.5, section="TEAM", target="TEAM-1"),
        command(8, "COMMAND_STARTED", 450),
        ended(9, received=900),
        started(10, received=1000, code="SES-P02"),
        row(11, "SECTION_OPENED", 1000.04, code="SES-P02", section="TEAM"),
        row(12, "PAGE_HIDDEN", 1012.37, code="SES-P02", section="TEAM"),
        ended(13, received=1100, code="SES-P02"),
    ]
    document = document_for(journal=journal)
    assert dwell(document) == {
        "BRIEF": 60.0,
        "TEAM": 72.8,
        "USER_TWINS": 0.0,
        "REQUIREMENTS": 0.0,
        "DESIGN": 0.0,
        "PACKAGE": 0.0,
    }
    assert [item["discarded_intervals"] for item in document["sessions"]] == [0, 0]


def test_dwell_discards_negative_and_too_long_intervals_and_counts_them_per_session():
    limit = MAX_DWELL_INTERVAL_SECONDS
    journal = [
        started(1, received=0, code="SES-P03"),
        row(2, "SECTION_OPENED", 1000, code="SES-P03", section="DESIGN"),
        row(3, "SECTION_OPENED", 990, code="SES-P03", section="REQUIREMENTS"),
        row(4, "PAGE_HIDDEN", 990 + limit + 1, code="SES-P03", section="REQUIREMENTS"),
        row(5, "PAGE_VISIBLE", 20_000, code="SES-P03", section="REQUIREMENTS"),
        row(6, "PAGE_HIDDEN", 20_000 + limit, code="SES-P03", section="REQUIREMENTS"),
        ended(7, received=40_000, code="SES-P03"),
        started(8, received=50_000, code="SES-P04"),
        row(9, "SECTION_OPENED", 50_000, code="SES-P04", section="PACKAGE"),
        row(10, "DETAIL_OPENED", 50_000 + limit + 1, code="SES-P04", target="package"),
        ended(11, received=70_000, code="SES-P04"),
    ]
    document = document_for(journal=journal)
    assert dwell(document)["REQUIREMENTS"] == float(limit)
    assert dwell(document)["DESIGN"] == dwell(document)["PACKAGE"] == 0.0
    assert [(item["code"], item["discarded_intervals"]) for item in document["sessions"]] == [
        ("SES-P03", 2),
        ("SES-P04", 1),
    ]


def test_dwell_reopens_the_previous_section_and_skips_unopened_or_unfinished_intervals():
    journal = [
        started(1, received=0),
        row(2, "PAGE_VISIBLE", 5, section="BRIEF"),
        row(3, "PAGE_HIDDEN", 8, section="BRIEF"),
        row(4, "SECTION_OPENED", 10, section="USER_TWINS"),
        row(5, "PAGE_VISIBLE", 20, section="USER_TWINS"),
        row(6, "PAGE_HIDDEN", 30, section="USER_TWINS"),
        row(7, "PAGE_VISIBLE", 50, section="PACKAGE"),
        row(8, "PAGE_HIDDEN", 55, section="PACKAGE"),
        row(9, "SECTION_OPENED", 60, section="PACKAGE"),
        row(10, "MODE_CHANGED", 4000, section="PACKAGE", status="EXPERT"),
    ]
    document = document_for(journal=journal)
    assert dwell(document) == {**dict.fromkeys(SECTIONS, 0.0), "USER_TWINS": 25.0}
    assert document["sessions"][0]["discarded_intervals"] == 0


def test_section_journal_counts_only_web_rows_of_that_section():
    journal = [
        started(1, received=0),
        row(2, "SECTION_OPENED", 1, section="BRIEF"),
        row(3, "DETAIL_OPENED", 2, section="BRIEF", target="brief-goals"),
        row(4, "DETAIL_OPENED", 3, section="BRIEF", target="details"),
        row(5, "SECTION_OPENED", 4, section="DESIGN"),
        row(6, "WHY_OPENED", 5, section="DESIGN", target="why"),
        row(7, "MOCKUP_OPENED", 6, section="DESIGN", target="ALT-1"),
        row(8, "MOCKUP_OPENED", 7, section="DESIGN", target="mockup"),
        row(9, "DETAIL_OPENED", 8, target="details"),
        command(10, "COMMAND_STARTED", 9, section="DESIGN"),
        row(11, "SECTION_OPENED", 10, section="BRIEF"),
    ]
    journals = {item["key"]: item["journal"] for item in document_for(journal=journal)["sections"]}
    assert journals["BRIEF"] == {
        "opened": 2,
        "dwell_seconds": 3.0,
        "details_opened": 2,
        "why_opened": 0,
        "mockups_opened": 0,
    }
    assert journals["DESIGN"] == {
        "opened": 1,
        "dwell_seconds": 6.0,
        "details_opened": 0,
        "why_opened": 1,
        "mockups_opened": 2,
    }
    assert [key for key in SECTIONS if any(journals[key].values())] == ["BRIEF", "DESIGN"]


def test_active_session_is_the_last_started_session_without_a_later_end():
    assert active_session([]) is None
    first = [started(1, received=0, code="SES-A1")]
    assert active_session(first) == {"code": "SES-A1", "started_at": moment(0)}
    closed = [*first, row(2, "PAGE_HIDDEN", 3, code="SES-A1"), ended(3, received=10, code="SES-A1")]
    assert active_session(closed) is None
    assert active_session([started(4, received=20, code="SES-B2"), *closed[::-1]]) == {
        "code": "SES-B2",
        "started_at": moment(20),
    }
    overlapping = [
        started(1, received=0, code="SES-A1"),
        started(2, received=5, code="SES-B2"),
        ended(3, received=9, code="SES-B2"),
    ]
    assert active_session(overlapping) == {"code": "SES-A1", "started_at": moment(0)}
    rome = [{**started(1, received=0, code="SES-C3"), "received_at": moment(0, ROME)}]
    assert active_session(rome) == {"code": "SES-C3", "started_at": moment(0)}


@pytest.mark.parametrize("value", ["SES-P01", "SES-1", "SES-A-B-", "SES-" + "X" * 20])
def test_validate_session_code_accepts_codes_of_the_pattern(value):
    assert validate_session_code(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "SES-",
        "SES--P01",
        "ses-p01",
        "SES-p01",
        "SES_P01",
        "P01",
        " SES-P01",
        "SES-P01 ",
        "SES-P01\n",
        "SES-MARIO.ROSSI",
        "SES-" + "X" * 21,
        "",
        None,
        101,
        ["SES-P01"],
    ],
)
def test_validate_session_code_and_journal_rows_reject_other_codes(value):
    with pytest.raises(ActivityError) as raised:
        validate_session_code(value)
    assert raised.value.code == "ACTIVITY_INPUT_INVALID"
    with pytest.raises(ActivityError) as raised:
        journal_rows(source="WEB", events=[event("PAGE_HIDDEN")], session_code=value)
    assert raised.value.code == "ACTIVITY_INPUT_INVALID"


def test_journal_rows_return_one_normalized_row_per_event_in_batch_order():
    web_kinds, ut_kinds = JOURNAL_KINDS["WEB"], JOURNAL_KINDS["UT"]
    web = journal_rows(source="WEB", session_code="SES-P01", events=[event(k) for k in web_kinds])
    ut = journal_rows(source="UT", session_code="SES-P01", events=[event(k) for k in ut_kinds])
    assert [item["kind"] for item in web + ut] == [*web_kinds, *ut_kinds]
    assert all(list(item) == ROW_KEYS for item in web + ut)
    assert web[0] == {
        "session_code": "SES-P01",
        "source": "WEB",
        "kind": "SECTION_OPENED",
        "section": "BRIEF",
        "target": None,
        "client_at": "2026-10-04T08:00:00+00:00",
        "duration_ms": None,
        "status": None,
    }
    assert ut[1] == {
        "session_code": "SES-P01",
        "source": "UT",
        "kind": "COMMAND_FINISHED",
        "section": None,
        "target": "design",
        "client_at": "2026-10-04T08:00:00+00:00",
        "duration_ms": 1200,
        "status": "0",
    }


def test_journal_rows_accept_the_boundaries_of_the_contract():
    ut = journal_rows(
        source="UT",
        session_code="SES-" + "9" * 20,
        events=[
            event("COMMAND_FINISHED", duration_ms=0, target="a" * 80, status="Z" * 64),
            event("GENERATION_WAITED", duration_ms=MAX_DURATION_MS, target="d:r_2.v-1"),
        ],
    )
    assert [(item["duration_ms"], item["status"]) for item in ut] == [
        (0, "Z" * 64),
        (MAX_DURATION_MS, None),
    ]
    web = journal_rows(
        source="WEB",
        session_code="SES-P01",
        events=[
            event("REQUEST_FAILED", status="422", target="GATE_STALE", client_at=moment(n))
            for n in range(MAX_BATCH_EVENTS)
        ],
    )
    assert len(web) == MAX_BATCH_EVENTS
    assert (web[0]["target"], web[-1]["client_at"]) == ("GATE_STALE", moment(49))


REQUIRED = [
    ("WEB", "SECTION_OPENED", "section"),
    ("WEB", "DETAIL_OPENED", "target"),
    ("WEB", "WHY_OPENED", "target"),
    ("WEB", "MOCKUP_OPENED", "target"),
    ("WEB", "MODE_CHANGED", "status"),
    ("WEB", "LOCALE_SET", "status"),
    ("WEB", "REQUEST_FAILED", "status"),
    ("UT", "COMMAND_STARTED", "target"),
    ("UT", "COMMAND_FINISHED", "target"),
    ("UT", "COMMAND_FINISHED", "status"),
    ("UT", "COMMAND_FINISHED", "duration_ms"),
    ("UT", "GENERATION_WAITED", "target"),
    ("UT", "GENERATION_WAITED", "duration_ms"),
    ("WEB", "PAGE_VISIBLE", "client_at"),
    ("UT", "COMMAND_STARTED", "client_at"),
]


@pytest.mark.parametrize("absent", [True, False], ids=["absent", "null"])
@pytest.mark.parametrize("source,kind,field", REQUIRED)
def test_journal_rows_require_the_fields_of_each_kind(source, kind, field, absent):
    complete = event(kind)
    assert journal_rows(source=source, events=[complete], session_code="SES-P01")[0]["kind"] == kind
    incomplete = {key: value for key, value in complete.items() if key != field}
    if not absent:
        incomplete[field] = None
    with pytest.raises(ActivityError) as raised:
        journal_rows(source=source, events=[incomplete], session_code="SES-P01")
    assert raised.value.code == "ACTIVITY_INPUT_INVALID"


REJECTED = {
    "unknown-key": ("WEB", [event("PAGE_HIDDEN", note="typed text")]),
    "web-kind-from-ut": ("UT", [event("SECTION_OPENED")]),
    "ut-kind-from-web": ("WEB", [event("COMMAND_STARTED")]),
    "session-kind-from-web": ("WEB", [{"kind": "SESSION_STARTED", "client_at": CLIENT}]),
    "studio-source": ("STUDIO", [{"kind": "SESSION_ENDED", "client_at": CLIENT}]),
    "unknown-source": ("CLI", [event("PAGE_HIDDEN")]),
    "missing-source": (None, [event("PAGE_HIDDEN")]),
    "unknown-kind": ("WEB", [{"kind": "BUTTON_CLICKED", "client_at": CLIENT}]),
    "unknown-section": ("WEB", [event("SECTION_OPENED", section="SETTINGS")]),
    "lowercase-section": ("WEB", [event("SECTION_OPENED", section="brief")]),
    "empty-target": ("WEB", [event("DETAIL_OPENED", target="")]),
    "target-with-spaces": ("WEB", [event("DETAIL_OPENED", target="Mario Rossi")]),
    "target-starting-with-dash": ("WEB", [event("WHY_OPENED", target="-why")]),
    "target-too-long": ("UT", [event("COMMAND_STARTED", target="a" * 81)]),
    "target-not-text": ("WEB", [event("MOCKUP_OPENED", target=7)]),
    "status-with-spaces": ("WEB", [event("REQUEST_FAILED", status="not found")]),
    "status-too-long": ("UT", [event("COMMAND_FINISHED", status="0" * 65)]),
    "status-not-text": ("WEB", [event("REQUEST_FAILED", status=404)]),
    "mode-not-guided-or-expert": ("WEB", [event("MODE_CHANGED", status="guided")]),
    "locale-not-it-or-en": ("WEB", [event("LOCALE_SET", status="fr")]),
    "negative-duration": ("UT", [event("GENERATION_WAITED", duration_ms=-1)]),
    "duration-over-a-day": ("UT", [event("GENERATION_WAITED", duration_ms=MAX_DURATION_MS + 1)]),
    "boolean-duration": ("UT", [event("COMMAND_FINISHED", duration_ms=True)]),
    "fractional-duration": ("UT", [event("COMMAND_FINISHED", duration_ms=1.5)]),
    "textual-duration": ("UT", [event("COMMAND_FINISHED", duration_ms="1200")]),
    "instant-without-zone": ("WEB", [event("PAGE_HIDDEN", client_at="2026-10-04T10:00:00")]),
    "date-without-time": ("WEB", [event("PAGE_HIDDEN", client_at="2026-10-04")]),
    "instant-not-iso": ("WEB", [event("PAGE_HIDDEN", client_at="yesterday")]),
    "empty-instant": ("WEB", [event("PAGE_HIDDEN", client_at="")]),
    "instant-as-number": ("WEB", [event("PAGE_HIDDEN", client_at=1_791_100_800)]),
    "instant-as-datetime": ("WEB", [event("PAGE_HIDDEN", client_at=START)]),
    "instant-out-of-range": ("WEB", [event("PAGE_HIDDEN", client_at="0001-01-01T00:00:00+01:00")]),
    "empty-batch": ("WEB", []),
    "batch-over-fifty": ("WEB", [event("PAGE_HIDDEN")] * (MAX_BATCH_EVENTS + 1)),
    "batch-not-a-list": ("WEB", event("PAGE_HIDDEN")),
    "missing-batch": ("WEB", None),
    "event-not-an-object": ("WEB", ["PAGE_HIDDEN"]),
    "one-bad-event": ("WEB", [event("PAGE_HIDDEN"), event("PAGE_HIDDEN", status="a b")]),
}


@pytest.mark.parametrize("source,events", list(REJECTED.values()), ids=list(REJECTED))
def test_journal_rows_reject_invalid_batches(source, events):
    with pytest.raises(ActivityError) as raised:
        journal_rows(source=source, events=events, session_code="SES-P01")
    assert raised.value.code == "ACTIVITY_INPUT_INVALID"


INVALID_FACTS = {
    "instant-without-zone": {"at": "2026-10-04T08:00:01"},
    "naive-datetime": {"at": datetime(2026, 10, 4, 8, 0, 1)},
    "instant-not-iso": {"at": "today"},
    "missing-instant": {"at": None},
    "unknown-section": {"section": "SETTINGS"},
    "missing-section": {"section": None},
    "unknown-actor": {"actor": "ADMIN"},
    "missing-actor": {"actor": None},
    "kind-not-text": {"kind": 7},
    "boolean-version": {"version_number": True},
    "textual-duration": {"duration_ms": "1500"},
    "outcome-not-text": {"outcome": 3},
}


@pytest.mark.parametrize("change", list(INVALID_FACTS.values()), ids=list(INVALID_FACTS))
def test_project_activity_rejects_invalid_facts(change):
    facts = [fact(0, "BRIEF", "PROJECT_CREATED"), {**fact(1, "BRIEF", "PROJECT_CREATED"), **change}]
    with pytest.raises(ActivityError) as raised:
        document_for(facts)
    assert raised.value.code == "ACTIVITY_RECORDS_INVALID"


INVALID_ROWS = {
    "server-source": {"source": "SERVER"},
    "unknown-source": {"source": "CLI"},
    "session-kind-from-web": {"kind": "SESSION_STARTED"},
    "web-kind-from-studio": {"source": "STUDIO"},
    "web-kind-from-ut": {"source": "UT"},
    "textual-sequence": {"sequence": "2"},
    "boolean-sequence": {"sequence": True},
    "invalid-session-code": {"session_code": "P01"},
    "received-without-zone": {"received_at": "2026-10-04T08:00:05"},
    "missing-received": {"received_at": None},
    "client-without-zone": {"client_at": "2026-10-04T08:00:05"},
    "web-row-without-client-clock": {"client_at": None},
    "unknown-section": {"section": "SETTINGS"},
    "section-opened-without-section": {"section": None},
    "free-text-target": {"target": "Mario Rossi"},
    "free-text-status": {"status": "typed by the owner"},
    "negative-duration": {"duration_ms": -5},
}


@pytest.mark.parametrize("change", list(INVALID_ROWS.values()), ids=list(INVALID_ROWS))
def test_project_activity_and_active_session_reject_invalid_journal_rows(change):
    journal = [started(1, received=0), {**row(2, "SECTION_OPENED", 5, section="BRIEF"), **change}]
    with pytest.raises(ActivityError) as raised:
        document_for(journal=journal)
    assert raised.value.code == "ACTIVITY_RECORDS_INVALID"
    with pytest.raises(ActivityError) as raised:
        active_session(journal)
    assert raised.value.code == "ACTIVITY_RECORDS_INVALID"


def test_instants_are_normalized_to_utc_isoformat():
    rows = journal_rows(
        source="WEB",
        session_code="SES-P01",
        events=[
            event("PAGE_HIDDEN", client_at="2026-10-04T10:00:00+02:00"),
            event("PAGE_HIDDEN", client_at="2026-10-04T08:00:00Z"),
            event("PAGE_HIDDEN", client_at="2026-10-04T03:30:00.250000-04:30"),
        ],
    )
    assert [item["client_at"] for item in rows] == [
        "2026-10-04T08:00:00+00:00",
        "2026-10-04T08:00:00+00:00",
        "2026-10-04T08:00:00.250000+00:00",
    ]
    approved = START.astimezone(ROME) + timedelta(seconds=15)
    facts = [
        {**fact(0, "BRIEF", "PROJECT_CREATED"), "at": moment(5, ROME)},
        {**fact(0, "BRIEF", "GATE_APPROVED"), "at": approved},
    ]
    journal = [
        {**started(1, received=0), "received_at": "2026-10-04T08:00:00Z"},
        {
            **row(2, "SECTION_OPENED", 0, section="BRIEF"),
            "client_at": moment(10, WESTERN),
            "received_at": START + timedelta(seconds=11),
        },
        {**ended(3, received=0), "received_at": moment(20, WESTERN)},
    ]
    document = document_for(facts, journal)
    assert [item["at"] for item in document["events"]] == [
        moment(0),
        moment(5),
        moment(10),
        moment(15),
        moment(20),
    ]
    assert timing(document, "BRIEF") == (moment(5), moment(15), moment(15), moment(15), 10.0)
    assert (document["sessions"][0]["started_at"], document["sessions"][0]["ended_at"]) == (
        moment(0),
        moment(20),
    )
    assert active_session(journal[:2]) == {"code": "SES-P01", "started_at": moment(0)}


def test_full_document_for_a_short_study_session():
    facts, journal = scenario()
    document = document_for(facts, journal)
    assert [item["kind"] for item in document["events"]] == [
        "PROJECT_CREATED",
        "SESSION_STARTED",
        "SECTION_OPENED",
        "MODE_CHANGED",
        "LOCALE_SET",
        "BRIEF_QUESTION_ASKED",
        "BRIEF_QUESTION_ANSWERED",
        "GATE_SUBMITTED",
        "GATE_APPROVED",
        "SECTION_OPENED",
        "GENERATION",
        "DETAIL_OPENED",
        "TEAM_VERSION_SAVED",
        "GATE_APPROVED",
        "PAGE_HIDDEN",
        "COMMAND_STARTED",
        "GENERATION",
        "GENERATION_WAITED",
        "COMMAND_FINISHED",
        "SESSION_ENDED",
    ]
    assert timing(document, "BRIEF") == (moment(0), moment(61), moment(61), moment(61), 61.0)
    assert timing(document, "TEAM") == (moment(120), moment(200), moment(200), moment(200), 80.0)
    assert timing(document, "DESIGN") == (moment(300), moment(300), None, None, None)
    assert [item["owner_actions"] for item in document["sections"]] == [4, 1, 0, 0, 0, 0]
    assert section(document, "BRIEF")["gate"]["submissions"] == 1
    assert section(document, "DESIGN")["generations"] == {
        "count": 1,
        "succeeded": 0,
        "failed": 1,
        "retries": 1,
        "wait_seconds": 90.0,
    }
    assert dwell(document) == {**dict.fromkeys(SECTIONS, 0.0), "BRIEF": 79.0, "TEAM": 140.0}
    assert section(document, "TEAM")["journal"]["details_opened"] == 1
    assert document["brief_dialogue"] == {
        "questions": 1,
        "answered": 1,
        "unknown_answers": 1,
        "answer_seconds": [12.5],
    }
    assert document["sessions"] == [
        {
            "code": "SES-P01",
            "started_at": moment(20),
            "ended_at": moment(400),
            "events": 11,
            "sources": ["STUDIO", "UT", "WEB"],
            "discarded_intervals": 0,
        }
    ]
    assert document["totals"] == {
        "events": 20,
        "owner_actions": 5,
        "generations": 2,
        "generation_wait_seconds": 120.0,
        "first_event_at": moment(0),
        "last_event_at": moment(400),
    }
    assert document["limits"] == [
        "ACTOR_DERIVED_FROM_RECORD_KIND",
        "CLIENT_CLOCK_NOT_VERIFIED",
        "ELAPSED_INCLUDES_IDLE_TIME",
        "FAILED_EVALUATION_RUNS_NOT_RECORDED",
        "GENERATION_JOBS_NOT_PERSISTED",
        "PRE_MODEL_REFUSALS_NOT_RECORDED",
        "VIEW_ACTIONS_ONLY_IN_STUDY_SESSIONS",
    ]


def test_same_inputs_in_any_order_give_the_same_document_without_mutation():
    facts, journal = scenario()
    before = deepcopy((facts, journal))
    expected = document_for(facts, journal)
    shuffler = random.Random(37)
    for _ in range(5):
        shuffled_facts, shuffled_journal = facts[:], journal[:]
        shuffler.shuffle(shuffled_facts)
        shuffler.shuffle(shuffled_journal)
        assert document_for(shuffled_facts, shuffled_journal) == expected
        assert active_session(shuffled_journal) is None
    assert json.dumps(document_for(facts, journal)) == json.dumps(expected)
    assert (facts, journal) == before


def test_document_carries_only_the_contract_fields():
    facts, journal = scenario()
    private = {
        "title": "Palestra di Mario Rossi",
        "owner_email": "mario.rossi@example.com",
        "content": "testo libero del brief",
        "owner_user_id": "00000000-0000-4000-8000-0000000000aa",
    }
    document = document_for(
        [{**item, **private} for item in facts], [{**item, **private} for item in journal]
    )
    assert document == document_for(facts, journal)
    assert list(document) == [
        "kind",
        "schema_version",
        "project_id",
        "events",
        "sections",
        "brief_dialogue",
        "sessions",
        "totals",
        "limits",
    ]
    assert all(list(item) == EVENT_KEYS for item in document["events"])
    assert all(
        list(item)
        == [
            "key",
            "first_event_at",
            "last_event_at",
            "first_approved_at",
            "approved_at",
            "elapsed_seconds",
            "owner_actions",
            "gate",
            "generations",
            "journal",
        ]
        and list(item["gate"]) == ["submissions", "approvals", "revision_requests", "rejections"]
        and list(item["generations"]) == ["count", "succeeded", "failed", "retries", "wait_seconds"]
        and list(item["journal"])
        == ["opened", "dwell_seconds", "details_opened", "why_opened", "mockups_opened"]
        for item in document["sections"]
    )
    assert list(document["brief_dialogue"]) == [
        "questions",
        "answered",
        "unknown_answers",
        "answer_seconds",
    ]
    assert all(
        list(item) == ["code", "started_at", "ended_at", "events", "sources", "discarded_intervals"]
        for item in document["sessions"]
    )
    assert list(document["totals"]) == [
        "events",
        "owner_actions",
        "generations",
        "generation_wait_seconds",
        "first_event_at",
        "last_event_at",
    ]
    text = json.dumps(document)
    assert not any(value in text for value in private.values())


def test_limits_are_sorted_and_flag_client_clocks_only_with_web_or_ut_rows():
    with_clock = sorted([*LIMITS, "CLIENT_CLOCK_NOT_VERIFIED"])
    assert document_for(journal=[started(1, received=0), ended(2, received=5)])["limits"] == LIMITS
    web = [started(1, received=0), row(2, "PAGE_HIDDEN", 3)]
    ut = [started(1, received=0), command(2, "COMMAND_STARTED", 3)]
    assert document_for(journal=web)["limits"] == with_clock
    assert document_for(journal=ut)["limits"] == with_clock


def test_activity_error_is_a_value_error_carrying_one_of_two_codes():
    error = ActivityError("ACTIVITY_INPUT_INVALID")
    assert isinstance(error, ValueError)
    assert (error.code, str(error)) == ("ACTIVITY_INPUT_INVALID", "ACTIVITY_INPUT_INVALID")
    with pytest.raises(ActivityError) as raised:
        journal_rows(source="WEB", events=[event("PAGE_HIDDEN")], session_code="SES-P1 ")
    assert raised.value.code == "ACTIVITY_INPUT_INVALID"
    for facts, journal in ((["PROJECT_CREATED"], []), ([], ["SESSION_STARTED"])):
        with pytest.raises(ActivityError) as raised:
            document_for(facts, journal)
        assert raised.value.code == "ACTIVITY_RECORDS_INVALID"
