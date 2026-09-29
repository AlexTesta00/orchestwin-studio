from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from src.test.python.integration.cli_journey_support import (
    API_PREFIX,
    BRIEF_ANSWERS,
    DATABASE_VARIABLE,
    IDEA,
    KNOWLEDGE,
    PROJECT_NAME,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Run,
    Scene,
    StudioApi,
    StudioProcess,
    choose_through_the_api,
    dash_rows,
    date_text,
    flat,
    journey_scene,
    read_json,
    say,
    stay_on_the_studio,
    table_rows,
)

pytestmark = pytest.mark.integration

INIT_STAGES = ("brief", "team", "twins", "requirements")
STAGES = (*INIT_STAGES, "design")
INIT_FOLDER = len(INIT_STAGES)
COMPLETE_FOLDER = len(STAGES)
SCHEMA_VERSION = 3
EMPTY_STATE = {"changes": 0, "pending_changes": 0, "aligned_commit": None, "open_tasks": 0}
STATE_KIND = "orchestwin.project-state"
CHANGES_KIND = "orchestwin.change-reviews"
DESIGN_ANSWERS = ("choose", "1", "approve", "leave")
APPROVAL_ANSWERS = ("approve", "leave")
KNOWLEDGE_LABEL = f"{KNOWLEDGE}/"
TAMPERED_FILE = "brief/brief.md"
APPROVED = "APPROVED"
MANDATORY = "MANDATORY"
NO_MODEL = {"generated_mockups": False, "iterations": False, "model": None, "static_check": False}
IMPORTED_STAGES = 5
ALTERNATIVES = 3
MANDATORY_SPECIALISTS: Mapping[str, str] = {
    "UX_UI_DESIGNER": "CORE_USER_CENTERED_DESIGN",
    "ACCESSIBILITY_REVIEWER": "CORE_ACCESSIBILITY_DISCIPLINE",
}
CRITIQUE_FIELDS = (
    "strengths",
    "concerns",
    "unmet_needs",
    "accessibility_observations",
    "trust_concerns",
    "questions",
    "suggested_changes",
)
DESIGN_WRITES = re.compile(r"/design/(?:revisions|gate|mockups|iterations|evaluations)(?:/|$)")
REFUSALS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("design", "choose", "1"), "design.no_model_choice"),
    (("design", "change", "Bigger buttons"), "design.no_model_change"),
    (("design", "approve"), "design.no_model_approve"),
)


def test_ut_walks_the_whole_path_against_the_real_studio(tmp_path: Path) -> None:
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        with journey.step("1 ut login --password-stdin"):
            sign_in(scene)
        with journey.step("2 ut status outside a project"):
            list_without_projects(scene)
        with journey.step("3 ut --yes init --answers"):
            create_the_project(scene)
        with journey.step("3 a partial folder after every approved step"):
            follow_the_partial_folders(scene)
        with journey.step("4 ut status, --offline and --json"):
            show_the_state(scene)
        with journey.step("5 ut --yes design without a model shows the design and chooses nothing"):
            show_the_design_without_a_model(scene)
        for arguments, key in REFUSALS:
            with journey.step(f"5 ut {' '.join(arguments)} refused without a model"):
                refuse_without_a_model(scene, arguments, key)
        with journey.step("5 continued from a choice prepared through the API"):
            continue_from_a_prepared_choice(scene)
        with journey.step("6 ut package verify, history and publish on the complete folder"):
            check_the_folder(scene)
        with journey.step("7 ut twins list and show, with the Studio and offline"):
            read_the_twins(scene)
        with journey.step("8 a file changed by hand, ut package verify and pull"):
            restore_a_changed_file(scene)
        with journey.step("9 ut package import and ut status --all"):
            import_the_folder(scene)
        with journey.step("10 ut logout and ut status"):
            sign_out(scene)
        with journey.step("every request stayed on the Studio of the test"):
            stay_on_the_studio(scene)
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def sign_in(scene: Scene) -> None:
    run = scene.ut(
        "login",
        "--studio",
        scene.origin,
        "--email",
        TEST_EMAIL,
        "--password-stdin",
        directory=scene.outside,
        answers=[TEST_PASSWORD],
    )
    assert run.status == 0, run.transcript()
    assert say("login.done", email=TEST_EMAIL, studio=scene.origin) in run.output, run.transcript()
    assert [exchange.line() for exchange in run.exchanges] == [
        "GET /health -> 200",
        "POST /auth/login -> 200",
    ], run.transcript()
    assert TEST_PASSWORD not in run.output + run.errors, "the password was written"
    assert TEST_PASSWORD.encode("utf-8") not in scene.terminal.sessions_file.read_bytes(), (
        "the password was stored"
    )
    document = scene.terminal.session_document()
    assert document.get("default_studio") == scene.origin
    session = document["sessions"][scene.origin]
    assert (session["email"], session["api_prefix"], session["cookie_name"]) == (
        TEST_EMAIL,
        API_PREFIX,
        "orchestwin_refresh",
    )
    kept = bool(session["refresh_token"])
    assert kept, "the renewal token was not kept"
    answer = scene.api.call(
        "GET",
        "/auth/me",
        headers={"Authorization": "Bearer " + str(session["access_token"])},
        authorized=False,
    )
    assert answer.status == 200, "the Studio refuses the access kept by ut login"
    assert answer.json()["email"] == TEST_EMAIL


def list_without_projects(scene: Scene) -> None:
    run = scene.ut("status", directory=scene.outside)
    assert run.status == 0, run.transcript()
    assert say("status.projects_heading", studio=scene.origin) in run.output, run.transcript()
    assert say("status.no_projects") in run.output, run.transcript()
    assert scene.api.document("/projects") == []


def create_the_project(scene: Scene) -> None:
    run = scene.ut("--yes", "init", "--answers", str(scene.answers))
    link_path = scene.local / "project.json"
    assert link_path.is_file(), run.transcript()
    link = read_json(link_path)
    scene.project_id = link["project_id"]
    assert run.status == 0, run.transcript()
    assert {
        key: value for key, value in link.items() if key not in {"project_id", "created_at"}
    } == {
        "schema_version": 1,
        "studio": scene.origin,
        "api_prefix": API_PREFIX,
        "project_name": PROJECT_NAME,
        "mode": "DESIGN_ONLY",
        "language": "en",
        "knowledge_folder": KNOWLEDGE,
    }
    assert datetime.fromisoformat(link["created_at"]).tzinfo is not None
    assert (scene.local / ".gitignore").read_bytes() == b"previews/\n"
    started = run.requests("POST", "/brief-dialogue")
    assert [(item.status, item.code) for item in started] == [
        (503, "BRIEF_DIALOGUE_MODEL_NOT_CONFIGURED")
    ], run.transcript()
    assert [item.status for item in run.requests("POST", "/brief-versions")] == [201]
    for sentence in (
        say("init.dialogue_unavailable"),
        say("init.manual_saved", version=1),
        say("init.done", name=PROJECT_NAME),
        say("init.next_design"),
    ):
        assert sentence in run.output, f"missing: {sentence}\n{run.transcript()}"
    gaps = run.order_gaps(
        *(
            sentence
            for number, stage in enumerate(INIT_STAGES, start=1)
            for sentence in (
                say(
                    "init.step_approved",
                    step=say(f"common.stage_{stage}"),
                    version=1,
                    path=f".orchestwin/steps/{stage}.json",
                ),
                say("init.folder_updated", version=number),
            )
        )
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    published = run.requests("POST", "/knowledge-packages")
    assert [item.status for item in published] == [201] * INIT_FOLDER, run.transcript()
    downloaded = run.requests("GET", "/archive")
    assert [item.status for item in downloaded] == [200] * INIT_FOLDER, run.transcript()
    project = scene.document("")
    assert (project["display_name"], project["current_stage"], project["next_action"]) == (
        PROJECT_NAME,
        "DESIGN",
        "APPROVE_DESIGN",
    )
    assert [item["id"] for item in scene.api.document("/projects")] == [scene.project_id]
    brief = scene.document("/brief-versions/current")["brief"]
    assert (brief["name"], brief["description"]) == (PROJECT_NAME, IDEA)
    assert {field: brief[field] for field in BRIEF_ANSWERS} == dict(BRIEF_ANSWERS)
    assert scene.document("/readiness")["status"] == "READY_FOR_MAIN_WORKFLOW"
    assert_mandatory_specialists(scene.document("/team-proposals/current"))
    modeling = scene.document("/user-modeling/readiness")
    assert (modeling["workflow_state"], modeling["approved_current_snapshot"]) == (
        "READY_FOR_REQUIREMENTS_DEFINITION",
        True,
    )
    assert scene.document("/requirements/readiness")["status"] == "READY_FOR_DESIGN_EXPLORATION"
    for stage, (version, gate) in approved_versions(scene).items():
        saved = read_json(scene.local / "steps" / f"{stage}.json")
        assert (saved["schema_version"], saved["stage"]) == (1, stage)
        assert identity(saved["version"]) == identity(version), stage
        assert (saved["gate"]["status"], gate["status"]) == (APPROVED, APPROVED), stage
        assert (gate["artifact"]["artifact_id"], gate["artifact"]["content_hash"]) == (
            version["id"],
            version["content_hash"],
        ), stage


def assert_mandatory_specialists(team: Mapping) -> None:
    constraints = {item["agent_id"]: item for item in team["role_constraints"]}
    members = {item["agent_id"]: item for item in team["members"]}
    for agent, code in MANDATORY_SPECIALISTS.items():
        assert agent in team["selected_agent_ids"], f"{agent} is not in the approved team"
        constraint = constraints.get(agent, {})
        reasons = [reason["code"] for reason in constraint.get("reasons", [])]
        assert (constraint.get("kind"), code in reasons) == (MANDATORY, True), (
            f"{agent}: {constraint.get('kind')} with the reasons {reasons}"
        )
        member = members.get(agent, {})
        justified = [item["code"] for item in member.get("justifications", [])]
        assert code in justified, f"{agent}: justified by {justified}"


def follow_the_partial_folders(scene: Scene) -> None:
    versions = scene.folders()
    assert [item["version_number"] for item in versions] == list(range(INIT_FOLDER, 0, -1))
    for version in versions:
        approved = list(STAGES[: version["version_number"]])
        number = version["version_number"]
        assert version["schema_version"] == SCHEMA_VERSION, number
        assert [item["stage"] for item in version["stages"]] == approved, number
        assert version["progress"] == {
            "approved": approved,
            "pending": STAGES[len(approved)],
            "complete": False,
        }, number
        assert version["state"] == EMPTY_STATE, number
        assert version["feedback"]["change_reviews"] == 0, number
    latest = versions[0]
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert (
        manifest["schema_version"],
        manifest["package"]["version_number"],
        manifest["package"]["content_hash"],
    ) == (SCHEMA_VERSION, INIT_FOLDER, latest["content_hash"])
    assert manifest["progress"] == {
        "approved": list(INIT_STAGES),
        "pending": "design",
        "complete": False,
    }
    assert sorted(manifest["stages"]) == sorted(INIT_STAGES)
    assert not (scene.knowledge / "design").exists()
    assert_empty_state(scene, design=None)
    history = scene.ut("package", "history")
    assert history.status == 0, history.transcript()
    assert say("package.history_heading", project=PROJECT_NAME) in history.output
    assert table_rows(history.output) == history_rows(versions), history.transcript()
    verify = scene.ut("package", "verify")
    assert verify.status == 0, verify.transcript()
    assert verify.exchanges == (), verify.transcript()
    assert (
        say(
            "package.verified",
            path=KNOWLEDGE_LABEL,
            version=INIT_FOLDER,
            project=PROJECT_NAME,
            files=latest["file_count"],
            hash=latest["content_hash"][:12],
        )
        in verify.output
    ), verify.transcript()


def assert_empty_state(scene: Scene, *, design: Mapping | None) -> None:
    requirements = scene.document("/requirements/current")
    state = read_json(scene.knowledge / "state" / "state.json")
    assert (state["schema_version"], state["kind"], state["project_id"]) == (
        SCHEMA_VERSION,
        STATE_KIND,
        scene.project_id,
    )
    assert (state["aligned"], state["changes"], state["tasks"]) == (None, [], [])
    assert state["reference"]["requirements"] == {
        "version_id": requirements["id"],
        "version_number": requirements["version_number"],
        "content_hash": requirements["content_hash"],
    }
    assert state["reference"]["design"] == design
    assert (scene.knowledge / "state" / "state.md").is_file()
    reviews = read_json(scene.knowledge / "twins" / "feedback" / "changes.json")
    assert (reviews["kind"], reviews["project_id"], reviews["runs"]) == (
        CHANGES_KIND,
        scene.project_id,
        [],
    )


def history_rows(versions: Sequence[Mapping]) -> list[list[str]]:
    return [
        [
            say("package.history_here", version=item["version_number"])
            if position == 0
            else str(item["version_number"]),
            date_text(item["created_at"]),
            item["content_hash"][:12],
            str(item["file_count"]),
        ]
        for position, item in enumerate(versions)
    ]


def show_the_state(scene: Scene) -> None:
    project = scene.document("")
    versions = {
        stage: version["version_number"] for stage, (version, _) in approved_versions(scene).items()
    }
    rows = [
        *(
            [say(f"common.stage_{stage}"), say("status.state_approved"), str(versions[stage])]
            for stage in INIT_STAGES
        ),
        [say("common.stage_design"), say("status.state_todo"), "-"],
        [say("common.stage_package"), say("status.state_later"), str(INIT_FOLDER)],
    ]
    next_step = say("status.next", action=say("common.next_approve_design"))
    run = scene.ut("status")
    assert run.status == 0, run.transcript()
    assert table_rows(run.output) == rows, run.transcript()
    assert next_step in run.output, run.transcript()
    assert say("status.folder_both", local=INIT_FOLDER, studio=INIT_FOLDER) in run.output, (
        run.transcript()
    )
    assert say("status.alignment_none") not in run.output, run.transcript()
    offline = scene.ut("status", "--offline")
    assert offline.status == 0, offline.transcript()
    assert offline.exchanges == (), offline.transcript()
    assert say("status.offline_requested") in offline.output, offline.transcript()
    assert table_rows(offline.output) == rows, offline.transcript()
    assert next_step in offline.output, offline.transcript()
    assert say("status.folder_only_local", local=INIT_FOLDER) in offline.output, (
        offline.transcript()
    )
    as_json = scene.ut("status", "--json")
    assert as_json.status == 0, as_json.transcript()
    budget = scene.api.request("GET", "/model-runtime/budget")
    assert (budget.status, budget.code) == (503, "REAL_MODEL_RUNTIME_NOT_CONFIGURED")
    assert scene.folder_numbers() == list(range(INIT_FOLDER, 0, -1))
    assert json.loads(as_json.output) == {
        "schema_version": 1,
        "kind": "project",
        "source": "studio",
        "reason": None,
        "studio": scene.origin,
        "project": {
            "id": project["id"],
            "name": project["display_name"],
            "mode": "DESIGN_ONLY",
            "language": "en",
            "root": str(scene.project),
        },
        "current_stage": project["current_stage"],
        "next_action": project["next_action"],
        "next_command": "ut design",
        "steps": [
            *(
                {"stage": stage, "state": APPROVED, "version": versions[stage], "approved": True}
                for stage in INIT_STAGES
            ),
            {"stage": "design", "state": "TODO", "version": None, "approved": False},
            {"stage": "package", "state": "LATER", "version": INIT_FOLDER, "approved": False},
        ],
        "knowledge_folder": {
            "local_version": INIT_FOLDER,
            "studio_version": INIT_FOLDER,
            "local_error": None,
        },
        "spending": None,
        "alignment": None,
    }, as_json.transcript()


def show_the_design_without_a_model(scene: Scene) -> None:
    run = scene.ut("--yes", "design", answers=DESIGN_ANSWERS)
    assert run.status == 0, run.transcript()
    assert scene.document("/design/mockups/capabilities") == NO_MODEL
    design = scene.document("/design/current")
    package = design["package"]
    alternatives = package["alternatives"]
    assert len(alternatives) == ALTERNATIVES, run.transcript()
    assert package["owner_selected_alternative_id"] is None, run.transcript()
    judgements = {(item.get("verdict"), item.get("quote")) for item in package["critiques"]}
    assert judgements == {(None, None)}, judgements
    shown = [say("design.heading", project=PROJECT_NAME), say("design.alternatives_heading")]
    for alternative in alternatives:
        recommended = alternative["id"] == package["recommended_alternative_id"]
        key = "design.alternative_recommended" if recommended else "design.alternative"
        shown.append(say(key, code=alternative["code"], title=alternative["title"]))
    for sentence in (*shown, say("design.verdicts_heading"), say("design.no_model")):
        assert run.shows(sentence), f"missing: {sentence}\n{run.transcript()}"
    gaps = critique_gaps(run.output, package)
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    assert dash_rows(run.output) == [], run.transcript()
    proposals = run.requests("POST", "/design/proposals")
    assert [item.status for item in proposals] == [202], run.transcript()
    assert design_writes(run) == [], run.transcript()
    assert run.requests("POST", "/knowledge-packages") == [], run.transcript()
    assert run.opened == (), run.transcript()
    assert not (scene.local / "previews").exists(), run.transcript()
    assert not (scene.local / "steps" / "design.json").exists(), run.transcript()
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert (manifest["package"]["version_number"], manifest["progress"]["pending"]) == (
        INIT_FOLDER,
        "design",
    ), run.transcript()
    assert scene.document("/design/readiness")["approved_current_package"] is False
    assert scene.folder_numbers() == list(range(INIT_FOLDER, 0, -1))


def refuse_without_a_model(scene: Scene, arguments: Sequence[str], key: str) -> None:
    before = scene.document("/design/current")
    run = scene.ut(*arguments)
    sentence = say(key)
    assert run.status == 1, run.transcript()
    assert run.shows(sentence), f"missing: {sentence}\n{run.transcript()}"
    assert run.writes() == [], run.transcript()
    assert run.opened == (), run.transcript()
    after = scene.document("/design/current")
    assert identity(after) == identity(before), run.transcript()
    assert after["package"]["owner_selected_alternative_id"] is None, run.transcript()
    assert not (scene.local / "previews").exists(), run.transcript()


def critique_gaps(output: str, package: Mapping) -> list[str]:
    text = flat(output)
    heading = say("design.verdicts_heading")
    position = text.find(heading)
    if position < 0:
        return [f"missing: {heading}"]
    blocks: list[tuple[str, int, list[Mapping]]] = []
    for alternative in package["alternatives"]:
        critiques = [
            item
            for item in package["critiques"]
            if item["design_alternative_id"] == alternative["id"]
        ]
        if not critiques:
            continue
        title = flat(
            say("design.alternative", code=alternative["code"], title=alternative["title"])
        )
        start = text.find(title, position)
        if start < 0:
            return [f"missing after {heading}: {title}"]
        blocks.append((title, start, critiques))
        position = start + len(title)
    gaps: list[str] = []
    for index, (title, start, critiques) in enumerate(blocks):
        end = blocks[index + 1][1] if index + 1 < len(blocks) else len(text)
        block = text[start:end]
        gaps.extend(
            f"missing under {title}: {fragment}"
            for critique in critiques
            for fragment in critique_fragments(critique)
            if fragment not in block
        )
    return gaps


def critique_fragments(critique: Mapping) -> list[str]:
    fragments = [str(critique["user_twin_reference"]["name"])]
    for field in CRITIQUE_FIELDS:
        texts = [item.strip() for item in critique.get(field) or [] if item.strip()]
        if texts:
            label = say(f"design.point_{field}")
            fragments.append(say("design.point", label=label, text=texts[0]))
            fragments.extend(texts[1:])
    return [flat(fragment) for fragment in fragments]


def design_writes(run: Run) -> list[str]:
    return [
        exchange.line()
        for exchange in run.writes()
        if DESIGN_WRITES.search(exchange.path.split("?", 1)[0])
    ]


def continue_from_a_prepared_choice(scene: Scene) -> None:
    design = scene.document("/design/current")
    first = design["package"]["alternatives"][0]
    if design["package"]["owner_selected_alternative_id"] is None:
        choose_through_the_api(scene, design, first["id"])
    review = scene.ut("design", "review")
    assert review.status == 1, review.transcript()
    assert say("design.review_about") in review.output, review.transcript()
    assert (
        say(
            "design.errors.DESIGN_EVALUATOR_NOT_CONFIGURED",
            code="DESIGN_EVALUATOR_NOT_CONFIGURED",
        )
        in review.errors
    ), review.transcript()
    assert scene.document("/design/evaluations") == []
    approval = scene.ut("--yes", "design", answers=APPROVAL_ANSWERS)
    assert approval.status == 0, approval.transcript()
    assert say("design.chosen_waiting", version=2) in approval.output, approval.transcript()
    chosen_without_a_model = say("design.no_model_chosen")
    assert approval.shows(chosen_without_a_model), (
        f"missing: {chosen_without_a_model}\n{approval.transcript()}"
    )
    assert_design_approved(scene, approval, first)


def assert_design_approved(scene: Scene, run: Run, alternative: Mapping) -> None:
    design = scene.document("/design/current")
    readiness = scene.document("/design/readiness")
    assert (readiness["status"], readiness["approved_current_package"]) == (
        "READY_FOR_ARCHITECTURE_PLANNING",
        True,
    ), run.transcript()
    assert design["package"]["owner_selected_alternative_id"] == alternative["id"]
    project = scene.document("")
    assert (project["current_stage"], project["next_action"]) == ("PACKAGE", "DOWNLOAD_FOLDER")
    versions = scene.folders()
    assert [item["version_number"] for item in versions] == list(range(COMPLETE_FOLDER, 0, -1)), (
        run.transcript()
    )
    for sentence in (
        say(
            "design.approved",
            code=alternative["code"],
            title=alternative["title"],
            version=design["version_number"],
        ),
        say(
            "design.folder_ready",
            path=str(scene.knowledge),
            version=COMPLETE_FOLDER,
            files=versions[0]["file_count"],
        ),
        say("design.folder_contents"),
    ):
        assert sentence in run.output, f"missing: {sentence}\n{run.transcript()}"
    assert [item.status for item in run.requests("POST", "/design/gate/submit")] == [200]
    assert [item.status for item in run.requests("POST", "/knowledge-packages")] == [201]
    saved = read_json(scene.local / "steps" / "design.json")
    gate = scene.document("/design/gate")
    assert identity(saved["version"]) == identity(design)
    assert (saved["gate"]["status"], gate["status"]) == (APPROVED, APPROVED)
    assert gate["artifact"]["artifact_id"] == design["id"]


def check_the_folder(scene: Scene) -> None:
    versions = scene.folders()
    assert [item["version_number"] for item in versions] == list(range(COMPLETE_FOLDER, 0, -1))
    latest = versions[0]
    assert latest["progress"] == {"approved": list(STAGES), "pending": None, "complete": True}
    assert latest["state"] == EMPTY_STATE
    assert latest["feedback"]["change_reviews"] == 0
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert manifest["project"]["id"] == scene.project_id
    assert manifest["package"]["content_hash"] == latest["content_hash"]
    assert (manifest["schema_version"], manifest["progress"]) == (
        SCHEMA_VERSION,
        {"approved": list(STAGES), "pending": None, "complete": True},
    )
    assert manifest["state"] == {
        "document": "state/state.json",
        "text": "state/state.md",
        **EMPTY_STATE,
    }
    assert (manifest["feedback"]["changes"], manifest["feedback"]["change_reviews"]) == (
        "twins/feedback/changes.json",
        0,
    )
    design = scene.document("/design/current")
    chosen = next(
        item
        for item in design["package"]["alternatives"]
        if item["id"] == design["package"]["owner_selected_alternative_id"]
    )
    assert_empty_state(
        scene,
        design={
            "version_id": design["id"],
            "version_number": design["version_number"],
            "content_hash": design["content_hash"],
            "alternative_code": chosen["code"],
        },
    )
    assert (scene.knowledge / ".gitattributes").read_bytes() == b"* -text\n"
    verify = scene.ut("package", "verify")
    assert verify.status == 0, verify.transcript()
    assert verify.exchanges == (), verify.transcript()
    assert (
        say(
            "package.verified",
            path=KNOWLEDGE_LABEL,
            version=COMPLETE_FOLDER,
            project=PROJECT_NAME,
            files=latest["file_count"],
            hash=latest["content_hash"][:12],
        )
        in verify.output
    ), verify.transcript()
    history = scene.ut("package", "history")
    assert history.status == 0, history.transcript()
    assert say("package.history_heading", project=PROJECT_NAME) in history.output
    assert table_rows(history.output) == history_rows(versions), history.transcript()
    publish = scene.ut("package", "publish")
    assert publish.status == 0, publish.transcript()
    assert (
        say("package.up_to_date", version=COMPLETE_FOLDER, path=KNOWLEDGE_LABEL) in publish.output
    ), publish.transcript()
    assert [item.status for item in publish.requests("POST", "/knowledge-packages")] == [200]
    assert publish.requests("GET", "/archive") == [], publish.transcript()
    assert scene.folder_numbers() == list(range(COMPLETE_FOLDER, 0, -1))


def read_the_twins(scene: Scene) -> None:
    versions = scene.document("/user-modeling/snapshots/current")["snapshot"]["twin_versions"]
    names = [version["profile"]["name"] for version in versions]
    role = observation(versions[0], "user_twin.role")
    details = [say("twins.section_observations")]
    if role is not None and role.casefold() != names[0].casefold():
        details.append(say("twins.role", role=role))
    local = read_json(scene.knowledge / "twins" / "twins.json")
    assert [item["profile"]["name"] for item in local["snapshot"]["twin_versions"]] == names
    heading = say("twins.list_heading", project=PROJECT_NAME)
    listing = scene.ut("twins", "list")
    assert listing.status == 0, listing.transcript()
    for sentence in (
        heading,
        *names,
        say("twins.hint_show", number=1),
        say("twins.hint_ask", number=1),
    ):
        assert sentence in listing.output, f"missing: {sentence}\n{listing.transcript()}"
    shown = scene.ut("twins", "show", "1")
    assert shown.status == 0, shown.transcript()
    assert shown.output.startswith(f"{names[0]}\n"), shown.transcript()
    for sentence in details:
        assert sentence in shown.output, f"missing: {sentence}\n{shown.transcript()}"
    notice = say(
        "twins.offline_unreachable",
        studio=scene.origin,
        source=say("twins.source_folder", path=KNOWLEDGE_LABEL, version=COMPLETE_FOLDER),
    )
    offline_listing = scene.ut("twins", "list", offline=True)
    assert offline_listing.status == 0, offline_listing.transcript()
    assert all(item.status is None for item in offline_listing.exchanges)
    for sentence in (notice, heading, *names, say("twins.hint_show", number=1)):
        assert sentence in offline_listing.output, (
            f"missing: {sentence}\n{offline_listing.transcript()}"
        )
    assert say("twins.hint_ask", number=1) not in offline_listing.output
    offline_show = scene.ut("twins", "show", "1", offline=True)
    assert offline_show.status == 0, offline_show.transcript()
    assert offline_show.output.startswith(f"{notice}\n{names[0]}\n"), offline_show.transcript()
    for sentence in details:
        assert sentence in offline_show.output, f"missing: {sentence}\n{offline_show.transcript()}"


def restore_a_changed_file(scene: Scene) -> None:
    target = scene.knowledge / TAMPERED_FILE
    original = target.read_bytes()
    target.write_bytes(original + b"\nA line added by hand.\n")
    latest = scene.folders()[0]
    verify = scene.ut("package", "verify")
    assert verify.status == 7, verify.transcript()
    assert (
        say(
            "package.verify_tampered",
            path=KNOWLEDGE_LABEL,
            file=TAMPERED_FILE,
            code="FOLDER_TAMPERED",
        )
        in verify.errors
    ), verify.transcript()
    pull = scene.ut("package", "pull", answers=["y"])
    assert pull.status == 0, pull.transcript()
    for sentence in (
        say(
            "package.changed_by_hand",
            path=KNOWLEDGE_LABEL,
            file=TAMPERED_FILE,
            code="FOLDER_TAMPERED",
        ),
        say("package.replace_anyway"),
        say(
            "package.pulled",
            version=COMPLETE_FOLDER,
            path=KNOWLEDGE_LABEL,
            files=latest["file_count"],
        ),
    ):
        assert sentence in pull.output, f"missing: {sentence}\n{pull.transcript()}"
    assert pull.requests("POST", "/knowledge-packages") == [], pull.transcript()
    assert target.read_bytes() == original
    again = scene.ut("package", "verify")
    assert again.status == 0, again.transcript()
    assert scene.folder_numbers() == list(range(COMPLETE_FOLDER, 0, -1))


def import_the_folder(scene: Scene) -> None:
    latest = scene.folders()[0]
    run = scene.ut("package", "import", KNOWLEDGE)
    assert run.status == 0, run.transcript()
    for sentence in (
        say("package.imported", name=PROJECT_NAME, origin=PROJECT_NAME, version=COMPLETE_FOLDER),
        say("package.import_approval", count=IMPORTED_STAGES),
        say("package.import_kept_link", linked=PROJECT_NAME, name=PROJECT_NAME),
    ):
        assert sentence in run.output, f"missing: {sentence}\n{run.transcript()}"
    projects = scene.api.document("/projects")
    others = [item for item in projects if item["id"] != scene.project_id]
    assert len(projects) == 2 and len(others) == 1, projects
    imported = others[0]
    assert (imported["display_name"], imported["current_stage"], imported["next_action"]) == (
        PROJECT_NAME,
        "BRIEF",
        "APPROVE_BRIEF",
    )
    origin = scene.api.document(f"/projects/{imported['id']}/import")["origin"]
    assert (origin["project_id"], origin["package_version"], origin["package_content_hash"]) == (
        scene.project_id,
        COMPLETE_FOLDER,
        latest["content_hash"],
    )
    assert read_json(scene.local / "project.json")["project_id"] == scene.project_id
    listing = scene.ut("status", "--all")
    assert listing.status == 0, listing.transcript()
    assert sorted(table_rows(listing.output)) == sorted(
        [
            [
                say("status.this_folder", name=PROJECT_NAME),
                say("status.step_position", number=6, total=6, stage=say("common.stage_package")),
                say("common.next_download_folder"),
            ],
            [
                PROJECT_NAME,
                say("status.step_position", number=1, total=6, stage=say("common.stage_brief")),
                say("common.next_approve_brief"),
            ],
        ]
    ), listing.transcript()


def sign_out(scene: Scene) -> None:
    kept = scene.terminal.session_document()["sessions"][scene.origin]["refresh_token"]
    design = scene.document("/design/current")
    run = scene.ut("logout")
    assert run.status == 0, run.transcript()
    assert say("logout.done", studio=scene.origin) in run.output, run.transcript()
    remembered = scene.origin in scene.terminal.session_document().get("sessions", {})
    assert not remembered, "ut logout left the session in the sessions file"
    renewal = scene.api.call(
        "POST",
        "/auth/refresh",
        headers={"Cookie": "orchestwin_refresh=" + str(kept)},
        authorized=False,
    ).status
    assert renewal == 401, "the Studio still renews the session closed by ut logout"
    status = scene.ut("status")
    assert status.status == 0, status.transcript()
    assert status.exchanges == (), status.transcript()
    assert say("status.offline_not_signed_in", studio=scene.origin) in status.output, (
        status.transcript()
    )
    approved = say("status.state_approved")
    assert table_rows(status.output) == [
        *([say(f"common.stage_{stage}"), approved, "1"] for stage in INIT_STAGES),
        [say("common.stage_design"), approved, str(design["version_number"])],
        [say("common.stage_package"), say("status.state_ready"), str(COMPLETE_FOLDER)],
    ], status.transcript()
    assert say("status.folder_only_local", local=COMPLETE_FOLDER) in status.output, (
        status.transcript()
    )
    assert say("status.alignment_none") in status.output, status.transcript()


def approved_versions(scene: Scene) -> dict[str, tuple[Mapping, Mapping]]:
    return {
        "brief": (
            scene.document("/brief-versions/current"),
            scene.document("/gates/project-brief/current"),
        ),
        "team": (
            scene.document("/team-proposals/current"),
            scene.document("/gates/agent-team/current"),
        ),
        "twins": (
            scene.document("/user-modeling/snapshots/current"),
            scene.document("/user-modeling/gate"),
        ),
        "requirements": (
            scene.document("/requirements/current"),
            scene.document("/requirements/gate"),
        ),
    }


def identity(version: Mapping) -> tuple[object, object, object]:
    return version.get("id"), version.get("version_number"), version.get("content_hash")


def observation(version: Mapping, key: str) -> str | None:
    for item in version["profile"]["observations"]:
        if item.get("observation_key") != key:
            continue
        value = item.get("value") or {}
        if isinstance(value.get("text"), str) and value["text"].strip():
            return value["text"].strip()
        items = [
            entry.strip()
            for entry in value.get("items") or []
            if isinstance(entry, str) and entry.strip()
        ]
        return items[0] if items else None
    return None
