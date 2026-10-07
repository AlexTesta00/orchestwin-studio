from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.projects.knowledge_alignment import (
    KnowledgeAlignmentRun,
    ProposalOrigin,
    ProposalSubjects,
    create_proposed_update,
    create_run,
)
from orchestwin.projects.persistence.knowledge_alignment import (
    SqlAlchemyKnowledgeAlignmentRepository,
)
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    PROJECT_NAME,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Repository,
    Run,
    Scene,
    StudioApi,
    StudioProcess,
    approved_reference,
    database_runtime,
    git_available,
    journey_scene,
    read_json,
    run_coroutine,
    say,
    stay_on_the_studio,
    utc_now,
)
from src.test.python.integration.test_postgresql_cli_verify import (
    APP,
    COMPLETE_FOLDER,
    ROUND_LINE,
    THIRD_MESSAGE,
    THIRD_MOMENT,
    TIP_LINE,
    Development,
    app_source,
    approve_the_design,
    commit_line,
    create_the_repository,
    isolate_git,
    record_without_reviewing,
)

pytestmark = pytest.mark.integration

LOCALE = "en-US"
ACCOUNT_PATH = "/auth/me"
NO_MODEL = "KNOWLEDGE_ALIGNMENT_MODEL_NOT_CONFIGURED"
REQUIREMENTS = "REQUIREMENTS"
DESIGN = "DESIGN"
TESTS = "TESTS"
PROPOSED = "PROPOSED"
APPLIED = "APPLIED"
SKIPPED = "SKIPPED"
CODES = ("ALN-001", "ALN-002", "ALN-003")
SUMMARY = (
    "The second commit adds the tip to each share; the Definition, the Design and the test "
    "plan do not mention the tip yet."
)
TITLES = {
    REQUIREMENTS: "Add the tip to the share of each person",
    DESIGN: "Show the tip on the bill screen",
    TESTS: "Cover the tip in the test plan",
}
REQUESTS = {
    REQUIREMENTS: (
        "Change the requirement about the split so that the share of each person includes "
        "the tip percentage typed by the group."
    ),
    DESIGN: "Add the tip percentage to the bill screen, next to the total, before the shares.",
    TESTS: "Add a test path that types a tip and checks that each share includes it.",
}
RATIONALE = "The share function now multiplies the total by the tip percentage."
SKIP_REASON = "The Definition already says it"
MENU = {"apply": "1", "edit": "2", "skip": "3", "later": "4"}
RUN_KEYS = (
    "id",
    "project_id",
    "from_commit",
    "to_commit",
    "commits",
    "locale",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
    "created_at",
    "cost_microusd",
    "generation_ids",
    "proposals",
)
PROPOSAL_KEYS = (
    "id",
    "run_id",
    "code",
    "section",
    "title",
    "request",
    "rationale",
    "subjects",
    "origin",
    "status",
    "created_at",
    "decided_at",
    "decision_note",
    "applied_text",
    "applied_diff_id",
)
LATEST_RUN_KEYS = (
    "id",
    "from_commit",
    "to_commit",
    "created_at",
    "requirements_version_number",
    "design_version_number",
    "alternative_code",
    "summary",
)
LATEST_FILE_KEYS = (
    "schema_version",
    "run_id",
    "finished_at",
    "from_commit",
    "to_commit",
    "proposals",
    "waiting",
    "applied",
    "skipped",
)
ALIGN_FOLDER = "align"
LATEST_NAME = "latest.json"
REDO_PATH = ("tests", "redo.json")


@dataclass
class Flow:
    development: Development
    database_url: str
    run: dict[str, object] = field(default_factory=dict)


def test_ut_aligns_the_knowledge_with_the_real_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not git_available():
        pytest.skip("the alignment path needs the git program, which is not installed")
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        flow = Flow(Development(Repository(scene.project)), database_url)
        with journey.step("0 the approved design and a repository with two recorded commits"):
            approve_the_design(scene)
            isolate_git(monkeypatch, tmp_path)
            create_the_repository(scene, flow.development)
            record_without_reviewing(scene, flow.development)
        if not journey.problems:
            walk(scene, journey, flow)
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def walk(scene: Scene, journey: Journey, flow: Flow) -> None:
    steps: tuple[tuple[str, Callable[[Scene, Flow], None]], ...] = (
        ("1 a knowledge alignment run with three proposals is inserted in the Studio", insert_run),
        ("2 the proposals route answers the shape of the contract", read_proposals),
        ("3 ut align --pending skips one proposal, leaves one and applies the TESTS one", decide),
        ("4 ut status shows the knowledge line, also as JSON and offline", read_status),
        ("5 ut align without a model records the commit and reports the refusal", refuse_run),
    )
    for name, action in steps:
        with journey.step(name):
            action(scene, flow)
        if journey.problems:
            break
    with journey.step("6 every request of ut went to the Studio of the test"):
        stay_on_the_studio(scene)


def insert_run(scene: Scene, flow: Flow) -> None:
    first, second = flow.development.commits
    account = scene.api.document(ACCOUNT_PATH)
    reference = approved_reference(scene)
    specification = scene.document("/requirements/current")["specification"]
    requirement = str(specification["requirements"][0]["code"])
    criterion = str(specification["acceptance_criteria"][0]["code"])
    origin = ProposalOrigin(commits=(second,), files=(APP,), excerpt=f"+{TIP_LINE}")
    run = create_run(
        project_id=UUID(scene.project_id),
        owner_user_id=UUID(str(account["id"])),
        from_commit=None,
        commits=(first, second),
        locale=LOCALE,
        requirements_version_number=int(reference["requirements_version_number"]),
        design_version_number=int(reference["design_version_number"]),
        alternative_code=str(reference["alternative_code"]),
        summary=SUMMARY,
        created_at=utc_now(),
        proposals=(
            create_proposed_update(
                section=REQUIREMENTS,
                title=TITLES[REQUIREMENTS],
                request=REQUESTS[REQUIREMENTS],
                rationale=RATIONALE,
                origin=origin,
                subjects=ProposalSubjects(requirements=(requirement,)),
            ),
            create_proposed_update(
                section=DESIGN,
                title=TITLES[DESIGN],
                request=REQUESTS[DESIGN],
                rationale=RATIONALE,
                origin=origin,
            ),
            create_proposed_update(
                section=TESTS,
                title=TITLES[TESTS],
                request=REQUESTS[TESTS],
                rationale=RATIONALE,
                origin=origin,
                subjects=ProposalSubjects(criteria=(criterion,)),
            ),
        ),
    )
    stored = run_coroutine(store_alignment_run(flow.database_url, run))
    assert isinstance(stored, KnowledgeAlignmentRun)
    snapshot = stored.to_snapshot()
    flow.run = snapshot
    assert tuple(snapshot) == RUN_KEYS, list(snapshot)
    assert (snapshot["from_commit"], snapshot["to_commit"], snapshot["commits"]) == (
        None,
        second,
        [first, second],
    )
    assert [(item["code"], item["section"], item["status"]) for item in snapshot["proposals"]] == [
        (CODES[0], REQUIREMENTS, PROPOSED),
        (CODES[1], DESIGN, PROPOSED),
        (CODES[2], TESTS, PROPOSED),
    ]
    for item in snapshot["proposals"]:
        assert tuple(item) == PROPOSAL_KEYS, list(item)
        assert item["origin"] == {"commits": [second], "files": [APP], "excerpt": f"+{TIP_LINE}"}
    listed = {key: value for key, value in snapshot.items() if key != "proposals"}
    assert scene.document("/alignment/runs") == {
        "items": [{**listed, "waiting": 3, "proposals_count": 3}]
    }
    assert scene.document(f"/alignment/runs/{snapshot['id']}") == {"run": snapshot}


async def store_alignment_run(
    database_url: str, run: KnowledgeAlignmentRun
) -> KnowledgeAlignmentRun:
    runtime = database_runtime(database_url)
    try:
        async with runtime.session_factory() as session, session.begin():
            repository = SqlAlchemyKnowledgeAlignmentRepository(
                session, owner_user_id=run.owner_user_id
            )
            return await repository.create_run(run)
    finally:
        await runtime.dispose()


def read_proposals(scene: Scene, flow: Flow) -> None:
    run = flow.run
    proposals = run["proposals"]
    document = scene.document("/alignment/proposals")
    assert tuple(document) == ("items", "latest_run"), list(document)
    assert document["items"] == list(reversed(proposals))
    assert all(tuple(item) == PROPOSAL_KEYS for item in document["items"])
    latest = document["latest_run"]
    assert tuple(latest) == LATEST_RUN_KEYS, list(latest)
    assert latest == latest_run_of(run)
    assert scene.document("/alignment/proposals?status=all") == document
    assert scene.document("/alignment/proposals?status=waiting") == document
    refused = scene.api.request("GET", f"{scene.base}/alignment/proposals?status=maybe")
    assert refused.status == 422, refused.status
    unknown = scene.api.request(
        "POST", f"{scene.base}/alignment/proposals/ALN-009/skip", {"reason": None}
    )
    assert (unknown.status, unknown.code) == (404, "ALIGNMENT_PROPOSAL_NOT_FOUND")


def decide(scene: Scene, flow: Flow) -> None:
    run = flow.run
    second = flow.development.commits[1]
    requirement, design, tests = run["proposals"]
    aligned = scene.ut(
        "align",
        "--pending",
        answers=[MENU["skip"], SKIP_REASON, MENU["later"], MENU["apply"]],
    )
    assert aligned.status == 0, aligned.transcript()
    assert_gaps(
        aligned,
        say("align.heading", name=PROJECT_NAME),
        say("align.pending_intro", count=3),
        say("align.proposal", code=CODES[0], title=TITLES[REQUIREMENTS]),
        REQUESTS[REQUIREMENTS],
        say("align.rationale", text=RATIONALE),
        say("align.origin_files", files=APP),
        say("align.excerpt"),
        f"+{TIP_LINE}",
        say("align.hypothesis"),
        say("align.decision_heading", code=CODES[0], title=TITLES[REQUIREMENTS]),
        say("align.decision_question"),
        say("align.skipped", code=CODES[0]),
        say("align.proposal", code=CODES[1], title=TITLES[DESIGN]),
        say("align.decision_heading", code=CODES[1], title=TITLES[DESIGN]),
        say("align.decided_later"),
        say("align.proposal", code=CODES[2], title=TITLES[TESTS]),
        say("align.decision_heading", code=CODES[2], title=TITLES[TESTS]),
        say("align.applied", code=CODES[2]),
        say("align.tests_marked"),
        knowledge_line(run, second, waiting=1),
    )
    assert aligned.errors == "", aligned.transcript()
    assert writes_of(aligned) == [
        f"POST {scene.base}/alignment/proposals/{CODES[0]}/skip -> 200",
        f"POST {scene.base}/alignment/proposals/{CODES[2]}/apply -> 200",
    ], aligned.transcript()
    everything = scene.document("/alignment/proposals?status=all")["items"]
    assert [(item["code"], item["status"]) for item in everything] == [
        (CODES[2], APPLIED),
        (CODES[1], PROPOSED),
        (CODES[0], SKIPPED),
    ]
    applied, waiting, skipped = everything
    assert (applied["applied_text"], applied["applied_diff_id"], applied["decision_note"]) == (
        REQUESTS[TESTS],
        None,
        None,
    )
    assert datetime.fromisoformat(str(applied["decided_at"])).tzinfo is not None
    assert (skipped["decision_note"], skipped["applied_text"], skipped["applied_diff_id"]) == (
        SKIP_REASON,
        None,
        None,
    )
    assert waiting == design
    pending = scene.document("/alignment/proposals")
    assert pending == {"items": [design], "latest_run": latest_run_of(run)}
    listed = scene.document("/alignment/runs")["items"][0]
    assert (listed["waiting"], listed["proposals_count"]) == (1, 3)
    stored = scene.document(f"/alignment/runs/{run['id']}")["run"]
    assert [item["status"] for item in stored["proposals"]] == [SKIPPED, PROPOSED, APPLIED]
    assert stored["proposals"][0]["title"] == requirement["title"]
    assert stored["proposals"][2]["title"] == tests["title"]
    assert read_json(scene.local / ALIGN_FOLDER / f"{run['id']}.json") == stored
    latest = read_json(scene.local / ALIGN_FOLDER / LATEST_NAME)
    assert tuple(latest) == LATEST_FILE_KEYS, list(latest)
    assert {key: value for key, value in latest.items() if key != "finished_at"} == {
        "schema_version": 1,
        "run_id": run["id"],
        "from_commit": None,
        "to_commit": second,
        "proposals": 3,
        "waiting": 1,
        "applied": 1,
        "skipped": 1,
    }
    assert datetime.fromisoformat(str(latest["finished_at"])).tzinfo is not None
    redo = read_json(scene.local.joinpath(*REDO_PATH))
    assert {key: value for key, value in redo.items() if key != "written_at"} == {
        "schema_version": 1,
        "proposals": [{"code": CODES[2], "request": REQUESTS[TESTS]}],
    }
    assert datetime.fromisoformat(str(redo["written_at"])).tzinfo is not None
    assert scene.folder_numbers() == list(range(COMPLETE_FOLDER, 0, -1))
    flow.run = stored


def read_status(scene: Scene, flow: Flow) -> None:
    run = flow.run
    second = flow.development.commits[1]
    line = knowledge_line(run, second, waiting=1)
    status = scene.ut("status")
    assert status.status == 0, status.transcript()
    assert status.shows(line), status.transcript()
    as_json = scene.ut("status", "--json")
    assert (as_json.status, as_json.errors) == (0, ""), as_json.transcript()
    document = json.loads(as_json.output)
    assert list(document)[-1] == "knowledge_alignment", list(document)
    assert document["knowledge_alignment"] == {"latest_run": latest_run_of(run), "waiting": 1}
    offline = scene.ut("status", "--offline")
    assert offline.status == 0, offline.transcript()
    assert offline.exchanges == (), offline.transcript()
    assert offline.shows(line), offline.transcript()
    offline_json = scene.ut("status", "--offline", "--json")
    assert offline_json.status == 0, offline_json.transcript()
    local = json.loads(offline_json.output)
    assert local["knowledge_alignment"] == {"latest_run": latest_run_of(run), "waiting": 1}


def refuse_run(scene: Scene, flow: Flow) -> None:
    second = flow.development.commits[1]
    third = flow.development.repository.commit(
        THIRD_MESSAGE, {APP: app_source(ROUND_LINE)}, THIRD_MOMENT
    )
    flow.development.commits.append(third)
    run = scene.ut("align")
    assert run.status == 1, run.transcript()
    assert_gaps(
        run,
        say("align.heading", name=PROJECT_NAME),
        say("align.start_run", commit=second[:7]),
        say("align.commits", count=1),
        commit_line(third, THIRD_MOMENT, THIRD_MESSAGE, 1),
        say("align.recorded", count=1),
        say("align.reading"),
    )
    refusal = say(f"align.errors.{NO_MODEL}")
    assert refusal in run.errors, run.transcript()
    assert not run.shows(say("align.run_heading", count=1, commit=third[:7])), run.transcript()
    writes = writes_of(run)
    assert [line.split(" -> ")[0] for line in writes] == [
        f"POST {scene.base}/code-changes",
        f"POST {scene.base}/alignment/runs",
    ], run.transcript()
    assert writes[0].endswith("-> 201"), run.transcript()
    assert writes[1].split(" -> ", 1)[1] in ("202", f"503 {NO_MODEL}"), run.transcript()
    assert [item["commit"] for item in scene.document("/code-changes")["items"]] == (
        flow.development.commits[::-1]
    )
    assert [item["id"] for item in scene.document("/alignment/runs")["items"]] == [flow.run["id"]]
    assert scene.document("/alignment/proposals")["latest_run"] == latest_run_of(flow.run)
    direct = scene.api.request(
        "POST",
        f"{scene.base}/alignment/runs",
        {"locale": LOCALE, "from_commit": second, "to_commit": third, "commits": [third]},
    )
    assert (direct.status, direct.code) == (503, NO_MODEL)


def latest_run_of(run: dict[str, object]) -> dict[str, object]:
    return {key: run[key] for key in LATEST_RUN_KEYS}


def knowledge_line(run: dict[str, object], commit: str, *, waiting: int) -> str:
    moment = datetime.fromisoformat(str(run["created_at"])).astimezone()
    return say(
        "status.knowledge",
        commit=commit[:7],
        date=moment.strftime("%Y-%m-%d %H:%M"),
        count=waiting,
    )


def writes_of(run: Run) -> list[str]:
    return [exchange.line() for exchange in run.writes()]


def assert_gaps(run: Run, *sentences: str) -> None:
    gaps = run.order_gaps(*sentences)
    assert gaps == [], "\n".join([*gaps, run.transcript()])
