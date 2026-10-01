from __future__ import annotations

from pathlib import Path

import pytest

from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api.sections import Alignment, Gesture, Result, Section
from orchestwin.cli.errors import ApiFailure
from orchestwin.projects.progress import ProjectStage
from orchestwin.projects.sections import SectionBlock, SectionReason, SectionState
from orchestwin.projects.sections_service import SectionOutcome, SectionsAlignmentStatus

from .support.terminal import PROJECT_ID, command_context, store_session, terminal
from .support.transports import API, ScriptedTransport

SECTIONS = f"{API}/projects/{PROJECT_ID}/sections"
ALIGNMENT = f"{SECTIONS}/alignment"
CONTRACT = {
    "first_pass_complete": True,
    "sections": [
        {
            "key": "BRIEF",
            "state": "FINE",
            "version_number": 2,
            "reasons": [],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "TEAM",
            "state": "FINE",
            "version_number": 2,
            "reasons": [],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "USER_TWINS",
            "state": "TO_UPDATE",
            "version_number": 1,
            "reasons": ["PERSPECTIVES_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "state": "TO_UPDATE",
            "version_number": 3,
            "reasons": ["PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "DESIGN",
            "state": "TO_UPDATE",
            "version_number": 4,
            "reasons": ["REQUIREMENTS_CHANGED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "PACKAGE",
            "state": "TO_UPDATE",
            "version_number": 6,
            "reasons": ["FOLDER_BEHIND"],
            "blocked": None,
            "codes": [],
        },
    ],
    "alignment": {
        "available": True,
        "sections": ["USER_TWINS", "REQUIREMENTS", "DESIGN"],
        "uncovered_codes": [],
    },
}
GESTURE = {
    "status": "PARTIAL",
    "results": [
        {
            "key": "USER_TWINS",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": 2,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "outcome": "BLOCKED",
            "issue": "TWIN_NO_LONGER_AVAILABLE",
            "version_number": None,
            "codes": [],
        },
        {
            "key": "DESIGN",
            "outcome": "SKIPPED",
            "issue": None,
            "version_number": None,
            "codes": [],
        },
    ],
    "sections": CONTRACT,
}


def client_for(tmp_path: Path, transport: ScriptedTransport):
    store_session(tmp_path)
    return command_context(terminal(tmp_path, transport=transport).environment).client()


def test_the_sections_of_the_contract_are_read_field_by_field(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("GET", SECTIONS, body=CONTRACT)

    found = sections_api.sections(client_for(tmp_path, transport), PROJECT_ID)

    assert found is not None
    assert found.first_pass_complete is True
    assert [item.key for item in found.sections] == list(sections_api.SECTION_KEYS)
    assert found.section("REQUIREMENTS") == Section(
        key="REQUIREMENTS",
        state="TO_UPDATE",
        version_number=3,
        reasons=("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED"),
    )
    assert found.alignment == Alignment(
        available=True, sections=("USER_TWINS", "REQUIREMENTS", "DESIGN")
    )
    assert [item.key for item in found.behind()] == ["USER_TWINS", "REQUIREMENTS", "DESIGN"]
    assert [item.key for item in found.behind(sections_api.SECTION_KEYS)][-1] == "PACKAGE"
    assert found.in_progress() is None
    assert found.section("USER_TWINS").stage == "twins"
    assert found.document == CONTRACT
    transport.assert_done()


@pytest.mark.parametrize(
    ("status", "body"),
    [(404, {"detail": "Not Found"}), (405, {"detail": "Method Not Allowed"})],
)
def test_an_older_studio_without_the_routes_gives_nothing(
    tmp_path: Path, status: int, body: dict[str, object]
) -> None:
    transport = ScriptedTransport()
    transport.expect("GET", SECTIONS, status=status, body=body)
    transport.expect("POST", ALIGNMENT, status=status, body=body)
    client = client_for(tmp_path, transport)

    assert sections_api.sections(client, PROJECT_ID) is None
    assert sections_api.align(client, PROJECT_ID) is None
    transport.assert_done()


@pytest.mark.parametrize(
    ("method", "status", "body", "code"),
    [
        ("GET", 404, {"detail": {"code": "PROJECT_NOT_FOUND"}}, "PROJECT_NOT_FOUND"),
        ("POST", 404, {"detail": {"code": "PROJECT_NOT_FOUND"}}, "PROJECT_NOT_FOUND"),
        ("GET", 404, {"detail": "project_not_found"}, "project_not_found"),
        (
            "GET",
            503,
            {"detail": {"code": "SECTIONS_SERVICE_UNAVAILABLE"}},
            "SECTIONS_SERVICE_UNAVAILABLE",
        ),
        (
            "POST",
            503,
            {"detail": {"code": "SECTIONS_SERVICE_UNAVAILABLE"}},
            "SECTIONS_SERVICE_UNAVAILABLE",
        ),
        ("GET", 200, {"sections": "none"}, "API_FAILURE"),
        ("POST", 200, {"status": "ALIGNED"}, "API_FAILURE"),
    ],
)
def test_other_answers_are_failures(
    tmp_path: Path, method: str, status: int, body: dict[str, object], code: str
) -> None:
    path = SECTIONS if method == "GET" else ALIGNMENT
    transport = ScriptedTransport().expect(method, path, status=status, body=body)
    client = client_for(tmp_path, transport)

    with pytest.raises(ApiFailure) as caught:
        if method == "GET":
            sections_api.sections(client, PROJECT_ID)
        else:
            sections_api.align(client, PROJECT_ID)

    assert caught.value.code == code


def test_the_gesture_is_sent_without_a_body_and_its_answer_is_read(tmp_path: Path) -> None:
    transport = ScriptedTransport().expect("POST", ALIGNMENT, body=GESTURE)

    found = sections_api.align(client_for(tmp_path, transport), PROJECT_ID)

    assert isinstance(found, Gesture)
    assert found.status == "PARTIAL"
    assert found.aligned == (Result(key="USER_TWINS", outcome="ALIGNED", version_number=2),)
    assert found.blocked == (
        Result(key="REQUIREMENTS", outcome="BLOCKED", issue="TWIN_NO_LONGER_AVAILABLE"),
    )
    assert found.results[-1].outcome == "SKIPPED"
    assert found.sections is not None and found.sections.document == CONTRACT
    assert transport.sent[0].body is None


def test_parts_that_cannot_be_read_are_left_out_or_emptied() -> None:
    found = sections_api.sections_of(
        {
            "first_pass_complete": "yes",
            "sections": [
                "noise",
                {"key": "", "state": "FINE"},
                {"key": "BRIEF"},
                {
                    "key": "DESIGN",
                    "state": "UPDATE_AVAILABLE",
                    "version_number": True,
                    "reasons": "REQUIREMENTS_NOT_COVERED",
                    "blocked": "",
                    "codes": ["REQ-004", 5, ""],
                },
            ],
            "alignment": None,
        }
    )

    assert found is not None
    assert found.first_pass_complete is False
    assert found.sections == (Section(key="DESIGN", state="UPDATE_AVAILABLE", codes=("REQ-004",)),)
    assert found.alignment == Alignment()
    assert sections_api.sections_of({"sections": None}) is None
    assert sections_api.sections_of([]) is None
    assert sections_api.gesture_of({"status": "", "results": []}) is None
    assert sections_api.gesture_of({"status": "ALIGNED", "results": [{"key": "DESIGN"}]}) == (
        Gesture(status="ALIGNED", results=(), sections=None)
    )


@pytest.mark.parametrize(
    ("issue", "block"),
    [
        ("REQUIREMENT_NO_LONGER_AVAILABLE", "REQUIREMENT_NO_LONGER_AVAILABLE"),
        ("TWIN_SET_CHANGED", "TWIN_SET_CHANGED"),
        ("UPSTREAM_NOT_READY", "UPSTREAM_NOT_READY"),
        ("DESIGN_REVISION_PENDING", "REVISION_PENDING"),
        ("USER_TWIN_REVISION_PENDING", "REVISION_PENDING"),
        ("REQUIREMENTS_REVISION_PENDING", "REVISION_PENDING"),
        ("GATE_STATE_CONFLICT", None),
        (None, None),
    ],
)
def test_the_issue_of_a_gesture_names_its_obstacle(issue: str | None, block: str | None) -> None:
    assert sections_api.block_of(issue) == block


def test_the_copied_keys_are_those_of_the_studio() -> None:
    assert tuple(stage.value for stage in ProjectStage) == sections_api.SECTION_KEYS
    assert set(sections_api.STAGE_OF) == set(sections_api.SECTION_KEYS)
    assert sections_api.ALIGNABLE == ("TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN")
    assert tuple(item.value for item in SectionState) == sections_api.STATES
    assert tuple(item.value for item in SectionReason) == (
        *sections_api.BEHIND_REASONS,
        *sections_api.MATERIAL_REASONS,
    )
    assert tuple(item.value for item in SectionBlock) == sections_api.BLOCKS
    assert tuple(item.value for item in SectionOutcome) == sections_api.OUTCOMES
    assert tuple(item.value for item in SectionsAlignmentStatus) == sections_api.GESTURE_STATUSES
