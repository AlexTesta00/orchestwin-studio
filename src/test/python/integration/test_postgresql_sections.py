from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.api.design_mockups import MockupCommandError, ModelMockupApplication
from orchestwin.projects.design_runtime import SqlAlchemyDesignQueryService
from orchestwin.projects.requirements_runtime import SqlAlchemyRequirementsQueryService
from orchestwin.projects.sections_service import ALIGNMENT_REASON
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Scene,
    StudioApi,
    StudioProcess,
    database_runtime,
    journey_scene,
    run_coroutine,
    stay_on_the_studio,
)
from src.test.python.integration.test_postgresql_cli_verify import approve_the_design

pytestmark = pytest.mark.integration

KEYS = ("BRIEF", "TEAM", "USER_TWINS", "REQUIREMENTS", "DESIGN", "PACKAGE")
ALIGNABLE = ("USER_TWINS", "REQUIREMENTS", "DESIGN")
OFFERED = ("REQUIREMENTS_NOT_COVERED", "EVALUATION_MISSING")
PREFERRED_AGENT = "SECURITY_REVIEWER"
OWNER_REASON = "The owner wants the project looked at from this perspective too."
CHANGE = "Show the share of each person in bold"
COMPLETE_FOLDER = 5
NOT_CONTENT = {"grounding"}


def test_one_gesture_brings_the_sections_back_after_a_change_upstream(tmp_path: Path) -> None:
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        steps = (
            ("1 a project taken to the approved design", lambda: first_pass(scene)),
            (
                "2 a perspective switched on: twins, requirements and design follow",
                lambda: switch_a_perspective_on(scene),
            ),
            (
                "3 a requirements change: the design follows and the folder is accepted",
                lambda: change_the_requirements(scene, database_url),
            ),
            ("4 the folder published again: the Dossier is fine", lambda: publish(scene)),
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


def sections(scene: Scene) -> Mapping:
    return scene.document("/sections")


def by_key(document: Mapping) -> dict[str, Mapping]:
    return {section["key"]: section for section in document["sections"]}


def row(
    key: str,
    state: str,
    version: int | None,
    reasons: tuple[str, ...] = (),
    blocked: str | None = None,
    codes: tuple[str, ...] = (),
) -> dict[str, object]:
    return {
        "key": key,
        "state": state,
        "version_number": version,
        "reasons": list(reasons),
        "blocked": blocked,
        "codes": list(codes),
    }


def uncovered(scene: Scene) -> list[str]:
    specification = scene.document("/requirements/current")["specification"]
    prototype = scene.document("/design/current")["package"]["prototype"]
    cited = {
        identifier
        for screen in prototype["screens"]
        for traced in (screen, *screen["elements"])
        for identifier in traced["requirement_ids"]
    }
    return sorted(
        requirement["code"]
        for requirement in specification["requirements"]
        if requirement["id"] not in cited
    )


def design_row(scene: Scene, version: int) -> dict[str, object]:
    codes = tuple(uncovered(scene))
    reasons = OFFERED if codes else OFFERED[1:]
    return row("DESIGN", "UPDATE_AVAILABLE", version, reasons, codes=codes)


def twins(scene: Scene) -> list[tuple[str, str]]:
    versions = scene.document("/user-modeling/snapshots/current")["snapshot"]["twin_versions"]
    return [(version["twin_id"], version["profile"]["name"]) for version in versions]


def design_content(design: Mapping) -> dict[str, object]:
    package = design["package"]
    content = {key: value for key, value in package.items() if key not in NOT_CONTENT}
    content["alternatives"] = [
        {key: value for key, value in item.items() if key != "user_twin_references"}
        for item in package["alternatives"]
    ]
    content["critiques"] = [
        {key: value for key, value in item.items() if key != "user_twin_reference"}
        for item in package["critiques"]
    ]
    return content


def request(scene: Scene, method: str, path: str, body: object | None = None):
    return scene.api.request(method, f"{scene.base}{path}", body)


def approved(scene: Scene, method: str, path: str, body: object, statuses: set[int]) -> None:
    answer = request(scene, method, path, body)
    assert answer.status in statuses, f"{method} {path} answered {answer.status} {answer.code}"


def first_pass(scene: Scene) -> None:
    approve_the_design(scene)
    document = sections(scene)
    design = scene.document("/design/current")

    assert document["first_pass_complete"] is True, document
    assert [section["key"] for section in document["sections"]] == list(KEYS), document
    assert document["sections"] == [
        row("BRIEF", "FINE", 1),
        row("TEAM", "FINE", 1),
        row("USER_TWINS", "FINE", 1),
        row("REQUIREMENTS", "FINE", 1),
        design_row(scene, design["version_number"]),
        row("PACKAGE", "FINE", COMPLETE_FOLDER),
    ], document
    assert document["alignment"] == {"available": False, "sections": [], "uncovered_codes": []}


def optional_agent(proposal: Mapping) -> str:
    selected = set(proposal["selected_agent_ids"])
    candidates = [
        constraint["agent_id"]
        for constraint in proposal["role_constraints"]
        if constraint["kind"] == "OPTIONAL" and constraint["agent_id"] not in selected
    ]
    assert candidates, f"no optional perspective to switch on: {proposal['role_constraints']}"
    return PREFERRED_AGENT if PREFERRED_AGENT in candidates else candidates[0]


def switch_a_perspective_on(scene: Scene) -> None:
    proposal = scene.document("/team-proposals/current")
    agent = optional_agent(proposal)
    approved(
        scene,
        "PATCH",
        "/team-proposals/current",
        {
            "selected_agent_ids": [*proposal["selected_agent_ids"], agent],
            "owner_rationales": [{"agent_id": agent, "statement": OWNER_REASON}],
        },
        {201},
    )
    approved(scene, "POST", "/gates/agent-team/submit", None, {201})
    approved(scene, "POST", "/gates/agent-team/decisions", {"action": "APPROVE"}, {200})
    before = sections(scene)
    design = scene.document("/design/current")
    twins_before = twins(scene)

    assert before["sections"] == [
        row("BRIEF", "FINE", 1),
        row("TEAM", "FINE", 2),
        row("USER_TWINS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED",)),
        row("REQUIREMENTS", "TO_UPDATE", 1, ("PERSPECTIVES_CHANGED", "USER_TWINS_CHANGED")),
        row("DESIGN", "TO_UPDATE", design["version_number"], ("REQUIREMENTS_CHANGED",)),
        row("PACKAGE", "TO_UPDATE", COMPLETE_FOLDER, ("FOLDER_BEHIND",)),
    ], before
    assert before["alignment"] == {
        "available": True,
        "sections": list(ALIGNABLE),
        "uncovered_codes": uncovered(scene),
    }, before

    answer = request(scene, "POST", "/sections/alignment")
    assert answer.status == 200, f"the gesture answered {answer.status} {answer.code}"
    result = answer.json()

    assert result["status"] == "ALIGNED", result
    assert result["results"] == [
        {
            "key": "USER_TWINS",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": 2,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": 2,
            "codes": [],
        },
        {
            "key": "DESIGN",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": design["version_number"] + 1,
            "codes": [],
        },
    ], result
    assert result["sections"] == sections(scene)
    assert result["sections"]["sections"] == [
        row("BRIEF", "FINE", 1),
        row("TEAM", "FINE", 2),
        row("USER_TWINS", "FINE", 2),
        row("REQUIREMENTS", "FINE", 2),
        design_row(scene, design["version_number"] + 1),
        row("PACKAGE", "TO_UPDATE", COMPLETE_FOLDER, ("FOLDER_BEHIND",)),
    ], result
    assert twins(scene) == twins_before
    assert design_content(scene.document("/design/current")) == design_content(design)
    for path in ("/user-modeling/gate", "/requirements/gate", "/design/gate"):
        assert scene.document(path)["status"] == "APPROVED", path
    approvals = [
        event for event in scene.document("/requirements/gate/events") if event["kind"] == "APPROVE"
    ]
    assert [event["reason"] for event in approvals] == [ALIGNMENT_REASON], approvals


async def mockup_grounding(database_url: str, owner_user_id: UUID, project_id: UUID) -> str | None:
    runtime = database_runtime(database_url)
    try:
        application = ModelMockupApplication(
            SimpleNamespace(
                proposal_evidence_store=None,
                design_query_service=SqlAlchemyDesignQueryService(runtime.session_factory),
                requirements_query_service=SqlAlchemyRequirementsQueryService(
                    runtime.session_factory
                ),
            )
        )
        current = await application.current(owner_user_id, project_id)
        try:
            await application.grounded_requirements(owner_user_id, project_id, current)
        except MockupCommandError as error:
            return error.code
        return None
    finally:
        await runtime.dispose()


def change_the_requirements(scene: Scene, database_url: str) -> None:
    owner = UUID(str(scene.api.document("/auth/me")["id"]))
    project = UUID(scene.project_id)
    requested = request(scene, "POST", "/requirements/change-requests", {"request": CHANGE})
    assert requested.status == 201, f"the change answered {requested.status} {requested.code}"
    revision = requested.json()["diff"]["id"]
    approved(
        scene,
        "POST",
        f"/requirements/revisions/{revision}/decision",
        {"decision": "APPROVE"},
        {200},
    )
    approved(scene, "POST", "/requirements/gate/submit", None, {200})
    approved(scene, "POST", "/requirements/gate/decision", {"action": "APPROVE"}, {200})
    design = scene.document("/design/current")
    before = sections(scene)

    assert by_key(before)["REQUIREMENTS"] == row("REQUIREMENTS", "FINE", 3), before
    assert by_key(before)["DESIGN"] == row(
        "DESIGN", "TO_UPDATE", design["version_number"], ("REQUIREMENTS_CHANGED",)
    ), before
    assert before["alignment"] == {
        "available": True,
        "sections": ["DESIGN"],
        "uncovered_codes": uncovered(scene),
    }, before
    refused = request(scene, "POST", "/knowledge-packages")
    assert (refused.status, refused.code) == (409, "DESIGN_OUTDATED")
    assert run_coroutine(mockup_grounding(database_url, owner, project)) == (
        "DESIGN_CONTEXT_CHANGED"
    )

    answer = request(scene, "POST", "/sections/alignment")
    assert answer.status == 200, f"the gesture answered {answer.status} {answer.code}"
    result = answer.json()

    assert result["status"] == "ALIGNED", result
    assert result["results"] == [
        {
            "key": "DESIGN",
            "outcome": "ALIGNED",
            "issue": None,
            "version_number": design["version_number"] + 1,
            "codes": [],
        }
    ], result
    assert by_key(result["sections"])["DESIGN"] == design_row(scene, design["version_number"] + 1)
    assert design_content(scene.document("/design/current")) == design_content(design)
    assert run_coroutine(mockup_grounding(database_url, owner, project)) is None


def publish(scene: Scene) -> None:
    published = request(scene, "POST", "/knowledge-packages")
    assert published.status == 201, f"the folder answered {published.status} {published.code}"
    version = published.json()["version"]
    document = sections(scene)

    assert [item["stage"] for item in version["stages"]] == [
        "brief",
        "team",
        "twins",
        "requirements",
        "design",
    ]
    assert by_key(document)["PACKAGE"] == row("PACKAGE", "FINE", version["version_number"])
    assert document["alignment"] == {"available": False, "sections": [], "uncovered_codes": []}
    assert [section["state"] for section in document["sections"][:4]] == ["FINE"] * 4
