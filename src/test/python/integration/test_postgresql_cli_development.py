from __future__ import annotations

import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from orchestwin.cli import costs
from orchestwin.cli.console import format_elapsed
from orchestwin.cli.flows import code_order
from orchestwin.cli.flows.test_report import moment_text
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    KNOWLEDGE,
    PROJECT_NAME,
    RENEWAL_PATH,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Repository,
    Run,
    Scene,
    StudioApi,
    StudioProcess,
    approved_reference,
    choose_through_the_api,
    git_available,
    insert_change_review,
    insert_test_plan,
    insert_test_run_review,
    journey_scene,
    read_json,
    say,
    stay_on_the_studio,
    table_rows,
    utc_now,
)
from src.test.python.integration.test_postgresql_cli_alignment import (
    APP,
    APPROVAL_ANSWERS,
    BOLD_TEXT,
    FOURTH_MESSAGE,
    FOURTH_MOMENT,
    MCP_TOOLS,
    ROUND_LINE,
    SECOND_MESSAGE,
    STYLE,
    STYLE_TEXT,
    THIRD_MESSAGE,
    THIRD_MOMENT,
    Development,
    app_source,
    approve_the_design,
    create_the_repository,
    isolate_git,
    json_lines,
    local_twins,
    record_without_reviewing,
    reference_sentence,
    review_operations,
    tool_document,
)

pytestmark = pytest.mark.integration

COMPLETE_FOLDER = 5
KNOWLEDGE_LABEL = f"{KNOWLEDGE}/"
LOCALE = "en-US"
OPEN = "OPEN"
DONE = "DONE"
DROPPED = "DROPPED"
OWNER = "OWNER"
CODE_CHANGE = "CODE_CHANGE"
TEST_RUN = "TEST_RUN"
ALIGNED = "ALIGNED"
CODE_TASKS = "CODE_TASKS"
TASK_KEYS = (
    "code",
    "text",
    "about",
    "origin",
    "from_commit",
    "created_at",
    "status",
    "closed_at",
    "note",
)
ORIGIN_KEYS = ("kind", "commit", "test_run_id", "twin_id", "twin_name", "finding")
OWNER_TASKS = (
    "Label the tip field with its unit",
    "Show the total before the split",
    "Keep the last bill after a reload",
)
DONE_NOTE = "Done in the bill form"
DROP_NOTE = "Not wanted any more"
DECISION_TASK = "Add a hint under the tip field"
LATE_TASK = "Try the page on a small phone"
SCREEN = "SCR-001"
REVIEW_SUMMARY = "The commit follows the approved requirements and design."
CHANGE_SUMMARY = "The change helps my group, with a few points to fix."
RUN_SUMMARY = "The run shows that my group cannot finish the split yet."
CONCERN = "CONCERN"
CHANGE_FINDINGS = (
    (
        "MEDIUM",
        "The tip field does not say it is a percentage.",
        "Label the tip field as a percentage.",
    ),
    ("LOW", "Each share is shown without the currency.", "Show the currency next to each share."),
    ("LOW", "The old total stays after a new bill.", None),
)
OTHER_CHANGE_FINDINGS = (
    ("LOW", "The button label is small on a phone.", "Make the button label larger."),
)
RUN_FINDINGS = (
    ("MEDIUM", "The share does not appear after the button.", "Show the share after the button."),
    ("LOW", "The status line is easy to miss.", "Make the status line stand out."),
    ("LOW", "The total field accepts a negative amount.", None),
)
OTHER_RUN_FINDINGS = (("LOW", "The page title is generic.", "Name the page after the bill."),)
APPLICATION: Mapping[str, str] = {"kind": "STATIC", "address": "app"}
BROWSER: Mapping[str, str] = {"name": "chrome", "version": "151.0.7922.76"}
PATH_CODE = "TP-001"
PAGE_TITLE = "Split the bill"
PAGE_ADDRESS = "http://127.0.0.1:5173/"
EXPECTED_TEXT = "Each person pays"
FIRST_LEARNED = "People split the bill at the table with one phone."
SECOND_LEARNED = "People read each share aloud to the table."
FORGET_REASON = "The groups changed their habit"
LEARNING_PATH = "twins/feedback/learned.json"
LEARNING_SCHEMA = "schema/learned.schema.json"
LEARNING_KIND = "orchestwin.twin-learning"
LEARNING_EXTRAS = ("pending_update", "new_material")
SCHEMA_VERSION = 3
NO_REVIEW_MODEL = "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"
BUDGET_PATH = "/model-runtime/budget"
AGENT_NOTE = "src/agent-note.txt"
AGENT_SCRIPT = (
    "import sys",
    "from pathlib import Path",
    "",
    'order = Path(sys.argv[1]).read_text(encoding="utf-8")',
    'note = Path.cwd() / "src" / "agent-note.txt"',
    'note.write_text(order.splitlines()[0] + "\\n", encoding="utf-8", newline="\\n")',
)
CUSTOM_AGENT = "custom"
PROMPT_PLACEHOLDER = "{prompt_file}"
CODE_FOLDER = ("code",)
MCP_SERVER = "orchestwin-twins"
MCP_PROTOCOL = "2025-06-18"
MCP_CLIENT = {"name": "journey", "version": "1"}
MINUTE_FORMAT = "%Y-%m-%d %H:%M"
DAY_FORMAT = "%Y-%m-%d"


@dataclass
class Flow:
    development: Development
    database_url: str
    agent: Path
    folder: int = COMPLETE_FOLDER
    twins: list[tuple[str, str]] = field(default_factory=list)
    requirement: str = ""
    criterion: str = ""
    test_run: dict[str, object] = field(default_factory=dict)


def test_ut_develops_the_application_with_the_real_studio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not git_available():
        pytest.skip("the development path needs the git program, which is not installed")
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        flow = Flow(Development(Repository(scene.project)), database_url, tmp_path / "agent.py")
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
        ("1 ut tasks add, list, --json, done, drop and reopen, folder published", owner_tasks),
        ("2 findings of the twins on a commit and on a test run become tasks", findings_to_tasks),
        ("3 ut align --decide aligned closes what the rule closes, the rest stays", close_tasks),
        ("4 a new design version makes a review stale: status and --recheck", stale_reviews),
        ("5 ut twins learn, forget, list, show and update without a model", twins_that_learn),
        ("6 ut code --dry-run, then the agent of the test in a real run", code_with_an_agent),
        ("7 ut mcp lists thirteen tools and answers from the folder", serve_the_agent),
    )
    for name, action in steps:
        with journey.step(name):
            action(scene, flow)
        if journey.problems:
            break
    with journey.step("8 every request of ut went to the Studio of the test"):
        stay_on_the_studio(scene)


def owner_tasks(scene: Scene, flow: Flow) -> None:
    base = scene.base
    empty = scene.ut("tasks")
    assert empty.status == 0, empty.transcript()
    assert_gaps(empty, say("tasks.heading_open", name=PROJECT_NAME), say("tasks.none"))
    assert requests_of(empty) == [f"GET {base}/code-tasks?status=open -> 200"], empty.transcript()
    for number, text in enumerate(OWNER_TASKS, start=1):
        added = scene.ut("tasks", "add", *text.split())
        assert added.status == 0, added.transcript()
        flow.folder += 1
        assert_gaps(added, say("tasks.added", task=task_code(number), text=text), folder_line(flow))
        assert writes_of(added) == [f"POST {base}/code-tasks -> 201", published(scene)], (
            added.transcript()
        )
        check_folder(scene, flow)
    for task, text in zip(tasks_of(scene), OWNER_TASKS, strict=True):
        assert_task(task, text=text, origin=origin_of(OWNER))
    listed = scene.ut("tasks")
    assert listed.status == 0, listed.transcript()
    assert table_rows(listed.output) == [
        [task_code(number), say("tasks.status_open"), text, say("tasks.origin_owner")]
        for number, text in enumerate(OWNER_TASKS, start=1)
    ], listed.transcript()
    assert listed.shows(say("tasks.hint")), listed.transcript()
    as_json = scene.ut("tasks", "--json")
    assert (as_json.status, as_json.errors) == (0, ""), as_json.transcript()
    assert json.loads(as_json.output) == {"tasks": tasks_of(scene, every=False)}
    done = scene.ut("tasks", "done", "TSK-001", "--note", DONE_NOTE)
    assert done.status == 0, done.transcript()
    flow.folder += 1
    assert_gaps(
        done,
        say("tasks.changed_done", count=1),
        f"- TSK-001: {OWNER_TASKS[0]}",
        folder_line(flow),
    )
    assert writes_of(done) == [status_write(scene, "TSK-001"), published(scene)], done.transcript()
    check_folder(scene, flow)
    dropped = scene.ut("tasks", "drop", "tsk-002", "TSK-003", "--note", DROP_NOTE)
    assert dropped.status == 0, dropped.transcript()
    flow.folder += 1
    assert_gaps(
        dropped,
        say("tasks.changed_dropped", count=2),
        f"- TSK-002: {OWNER_TASKS[1]}",
        f"- TSK-003: {OWNER_TASKS[2]}",
        folder_line(flow),
    )
    assert writes_of(dropped) == [
        status_write(scene, "TSK-002"),
        status_write(scene, "TSK-003"),
        published(scene),
    ], dropped.transcript()
    check_folder(scene, flow)
    reopened = scene.ut("tasks", "reopen", "TSK-003")
    assert reopened.status == 0, reopened.transcript()
    flow.folder += 1
    assert_gaps(
        reopened,
        say("tasks.changed_reopened", count=1),
        f"- TSK-003: {OWNER_TASKS[2]}",
        folder_line(flow),
    )
    assert writes_of(reopened) == [status_write(scene, "TSK-003"), published(scene)]
    check_folder(scene, flow)
    first, second, third = tasks_of(scene)
    assert_task(first, text=OWNER_TASKS[0], origin=origin_of(OWNER), status=DONE, note=DONE_NOTE)
    assert_task(
        second, text=OWNER_TASKS[1], origin=origin_of(OWNER), status=DROPPED, note=DROP_NOTE
    )
    assert_task(third, text=OWNER_TASKS[2], origin=origin_of(OWNER))
    every = scene.ut("tasks", "--all")
    assert every.status == 0, every.transcript()
    assert_gaps(every, say("tasks.heading_all", name=PROJECT_NAME))
    statuses = ("tasks.status_done", "tasks.status_dropped", "tasks.status_open")
    assert table_rows(every.output) == [
        [task_code(number), say(key), text, say("tasks.origin_owner")]
        for number, (key, text) in enumerate(zip(statuses, OWNER_TASKS, strict=True), start=1)
    ], every.transcript()
    assert requests_of(every) == [f"GET {base}/code-tasks?status=all -> 200"], every.transcript()


def findings_to_tasks(scene: Scene, flow: Flow) -> None:
    base = scene.base
    second = flow.development.commits[1]
    versions = scene.document("/user-modeling/snapshots/current")["snapshot"]["twin_versions"]
    flow.twins = [(item["twin_id"], " ".join(item["profile"]["name"].split())) for item in versions]
    specification = scene.document("/requirements/current")["specification"]
    flow.requirement = specification["requirements"][0]["code"]
    flow.criterion = specification["acceptance_criteria"][0]["code"]
    reference = approved_reference(scene)
    review = insert_change_review(
        scene, second, change_review(flow), database_url=flow.database_url
    )
    assert scene.document(f"/code-changes/{second}/reviews") == {"items": [review]}
    assert scene.document(f"/code-changes/{second}")["review"] == {
        "run_id": review["id"],
        "reviewed_at": review["reviewed_at"],
        "verdict": ALIGNED,
        "summary": REVIEW_SUMMARY,
        "reference": reference,
        "stale": False,
    }
    plan = plan_document(flow, reference)
    insert_test_plan(scene, plan, database_url=flow.database_url)
    run = insert_test_run_review(
        scene, plan, run_document(plan), run_review(flow), database_url=flow.database_url
    )
    flow.test_run = run
    assert scene.document(f"/test-runs/{run['id']}") == run
    overview = scene.document("/acceptance-tests")
    assert (overview["latest_run"]["id"], overview["latest_run_stale"]) == (run["id"], False)
    assert overview["latest_review"] == {
        "run_id": run["id"],
        "finished_at": run["finished_at"],
        "reviewed_at": run["reviewed_at"],
        "critiques": run["critiques"],
    }
    twin = flow.twins[0]
    change_findings = review["critiques"][0]["findings"]
    run_findings = run["critiques"][0]["findings"]
    commit_heading = say("tasks.commit_heading", commit=second[:7], line=SECOND_MESSAGE)
    chosen = scene.ut("tasks", "from-commit", answers=["1"])
    assert chosen.status == 0, chosen.transcript()
    flow.folder += 1
    assert_gaps(
        chosen,
        commit_heading,
        *candidate_lines(review["critiques"], {}),
        say("tasks.choose_question"),
        say("tasks.created", count=1),
        f"- TSK-004: {finding_task(change_findings[0])}",
        say("tasks.created_next"),
        folder_line(flow),
    )
    assert_requests(
        chosen,
        f"GET {base}/code-changes?pending=true -> 200",
        f"GET {base}/code-changes/{second}/reviews -> 200",
        f"GET {base}/code-tasks?status=open -> 200",
    )
    assert writes_of(chosen) == [f"POST {base}/code-tasks -> 201", published(scene)]
    check_folder(scene, flow)
    again = scene.ut("tasks", "from-commit", second[:7], answers=[""])
    assert again.status == 0, again.transcript()
    assert_gaps(
        again,
        commit_heading,
        *candidate_lines(review["critiques"], {(twin[0], 0): "TSK-004"}),
        say("tasks.choose_question"),
        say("tasks.created_none"),
    )
    assert writes_of(again) == [], again.transcript()
    run_heading = say("tasks.test_heading", date=moment_text(run["finished_at"]))
    tested = scene.ut("tasks", "from-test", answers=["1 3"])
    assert tested.status == 0, tested.transcript()
    flow.folder += 1
    assert_gaps(
        tested,
        run_heading,
        *candidate_lines(run["critiques"], {}),
        say("tasks.choose_question"),
        say("tasks.created", count=2),
        f"- TSK-005: {finding_task(run_findings[0])}",
        f"- TSK-006: {finding_task(run_findings[2])}",
        folder_line(flow),
    )
    assert_requests(
        tested,
        f"GET {base}/acceptance-tests -> 200",
        f"GET {base}/code-tasks?status=open -> 200",
    )
    assert writes_of(tested) == [f"POST {base}/code-tasks -> 201", published(scene)]
    check_folder(scene, flow)
    retested = scene.ut("tasks", "from-test", "--run", str(run["id"]), answers=[""])
    assert retested.status == 0, retested.transcript()
    assert_gaps(
        retested,
        run_heading,
        *candidate_lines(run["critiques"], {(twin[0], 0): "TSK-005", (twin[0], 2): "TSK-006"}),
        say("tasks.created_none"),
    )
    assert writes_of(retested) == [], retested.transcript()
    decided = scene.ut("align", "--decide", second, answers=["tasks", DECISION_TASK, "", "1"])
    assert decided.status == 0, decided.transcript()
    flow.folder += 1
    assert_gaps(
        decided,
        say("align.heading", name=PROJECT_NAME),
        say("align.review_heading", commit=second[:7], line=SECOND_MESSAGE),
        say("align.decision_heading", commit=second[:7], line=SECOND_MESSAGE),
        say("align.tasks_intro", limit=10),
        say("align.findings_intro"),
        *candidate_lines(review["critiques"], {(twin[0], 0): "TSK-004"}),
        say("align.findings_question"),
        say("align.decided_tasks", count=2),
        f"- TSK-007: {DECISION_TASK}",
        f"- TSK-008: {finding_task(change_findings[1])}",
        say("align.folder_updated", version=flow.folder),
        say("status.alignment_not_aligned", recorded=2, pending=2, tasks=6),
    )
    assert writes_of(decided) == [
        f"POST {base}/code-changes/{second}/decision -> 200",
        published(scene),
    ], decided.transcript()
    decision = scene.document(f"/code-changes/{second}")["decision"]
    assert (decision["kind"], decision["note"]) == (CODE_TASKS, None), decision
    tasks = by_code(tasks_of(scene))
    change_about = about(requirements=[flow.requirement], screens=[SCREEN])
    run_about = about(requirements=[flow.requirement], screens=[SCREEN], criteria=[flow.criterion])
    for code, finding in (("TSK-004", change_findings[0]), ("TSK-008", change_findings[1])):
        assert_task(
            tasks[code],
            text=finding_task(finding),
            origin=origin_of(CODE_CHANGE, commit=second, twin=twin, finding=finding["text"]),
            about_codes=change_about,
        )
    for code, finding in (("TSK-005", run_findings[0]), ("TSK-006", run_findings[2])):
        assert_task(
            tasks[code],
            text=finding_task(finding),
            origin=origin_of(TEST_RUN, test_run_id=run["id"], twin=twin, finding=finding["text"]),
            about_codes=run_about,
        )
    assert_task(
        tasks["TSK-007"],
        text=DECISION_TASK,
        origin=origin_of(CODE_CHANGE, commit=second),
        about_codes=about(requirements=[flow.requirement]),
    )
    listed = scene.ut("tasks")
    assert listed.status == 0, listed.transcript()
    finding_origin = say("tasks.origin_commit", twin=twin[1], commit=second[:7])
    test_origin = say("tasks.origin_test", twin=twin[1])
    opened = say("tasks.status_open")
    assert table_rows(listed.output) == [
        ["TSK-003", opened, OWNER_TASKS[2], say("tasks.origin_owner")],
        ["TSK-004", opened, finding_task(change_findings[0]), finding_origin],
        ["TSK-005", opened, finding_task(run_findings[0]), test_origin],
        ["TSK-006", opened, finding_task(run_findings[2]), test_origin],
        ["TSK-007", opened, DECISION_TASK, say("tasks.origin_verdict", commit=second[:7])],
        ["TSK-008", opened, finding_task(change_findings[1]), finding_origin],
    ], listed.transcript()


def close_tasks(scene: Scene, flow: Flow) -> None:
    base = scene.base
    development = flow.development
    third = development.repository.commit(
        THIRD_MESSAGE, {APP: app_source(ROUND_LINE)}, THIRD_MOMENT
    )
    development.commits.append(third)
    recorded = scene.ut("align", "--dry-run")
    assert recorded.status == 0, recorded.transcript()
    assert writes_of(recorded) == [f"POST {base}/code-changes -> 201"], recorded.transcript()
    moment = datetime.fromisoformat(scene.document(f"/code-changes/{third}")["recorded_at"])
    earlier = tasks_of(scene)
    assert all(datetime.fromisoformat(task["created_at"]) < moment for task in earlier), earlier
    insert_change_review(scene, third, change_review(flow), database_url=flow.database_url)
    remaining = flow.test_run["critiques"][0]["findings"][1]
    late_finding = scene.ut("tasks", "from-test", answers=["1"])
    assert late_finding.status == 0, late_finding.transcript()
    flow.folder += 1
    assert_gaps(
        late_finding,
        say("tasks.created", count=1),
        f"- TSK-009: {finding_task(remaining)}",
        folder_line(flow),
    )
    late_owner = scene.ut("tasks", "add", *LATE_TASK.split())
    assert late_owner.status == 0, late_owner.transcript()
    flow.folder += 1
    assert_gaps(late_owner, say("tasks.added", task="TSK-010", text=LATE_TASK), folder_line(flow))
    before = by_code(tasks_of(scene))
    aligned = scene.ut("align", "--decide", third, answers=["aligned"])
    assert aligned.status == 0, aligned.transcript()
    flow.folder += 1
    assert_gaps(
        aligned,
        say("align.decision_heading", commit=third[:7], line=THIRD_MESSAGE),
        say("align.decided_aligned", commit=third[:7]),
        say("align.folder_updated", version=flow.folder),
        say("status.alignment", recorded=3, pending=0, commit=third[:7], tasks=2),
    )
    assert writes_of(aligned) == [
        f"POST {base}/code-changes/{third}/decision -> 200",
        published(scene),
    ], aligned.transcript()
    decision = scene.document(f"/code-changes/{third}")["decision"]
    assert decision["kind"] == ALIGNED, decision
    after = by_code(tasks_of(scene))
    covered = set(development.commits)
    closed: list[str] = []
    for code, task in before.items():
        if task["status"] == OPEN and closed_by_the_rule(task, covered, moment):
            closed.append(code)
            assert after[code] == {
                **task,
                "status": DONE,
                "closed_at": after[code]["closed_at"],
                "note": None,
            }, after[code]
            assert same_moment(after[code]["closed_at"], decision["decided_at"]), after[code]
        else:
            assert after[code] == task, (task, after[code])
    assert closed == [task_code(number) for number in range(3, 9)], closed
    still_open = [code for code, task in after.items() if task["status"] == OPEN]
    assert still_open == ["TSK-009", "TSK-010"], after
    alignment = scene.document("/alignment")
    assert alignment["aligned"]["commit"] == third
    assert (alignment["pending_changes"], alignment["stale_reviews"]) == (0, 0)
    assert alignment["tasks"] == tasks_of(scene, every=False)
    check_folder(scene, flow)
    state = read_json(scene.knowledge / "state" / "state.json")
    assert state["aligned"] == alignment["aligned"]


def stale_reviews(scene: Scene, flow: Flow) -> None:
    base = scene.base
    development = flow.development
    third = development.commits[2]
    fourth = development.repository.commit(
        FOURTH_MESSAGE, {STYLE: STYLE_TEXT + BOLD_TEXT}, FOURTH_MOMENT
    )
    development.commits.append(fourth)
    recorded = scene.ut("align", "--dry-run")
    assert recorded.status == 0, recorded.transcript()
    assert writes_of(recorded) == [f"POST {base}/code-changes -> 201"], recorded.transcript()
    review = insert_change_review(
        scene, fourth, change_review(flow), database_url=flow.database_url
    )
    earlier = review["reference"]
    chosen = scene.ut("tasks", "from-commit", answers=["1"])
    assert chosen.status == 0, chosen.transcript()
    flow.folder += 1
    assert_gaps(
        chosen,
        say("tasks.commit_heading", commit=fourth[:7], line=FOURTH_MESSAGE),
        say("tasks.created", count=1),
        f"- TSK-011: {finding_task(review['critiques'][0]['findings'][0])}",
        folder_line(flow),
    )
    before = scene.document("/alignment")
    assert (before["stale_reviews"], before["latest_change"]["review"]["stale"]) == (0, False)
    design = scene.document("/design/current")
    alternative = design["package"]["alternatives"][1]
    choose_through_the_api(scene, design, alternative["id"])
    approval = scene.ut("--yes", "design", answers=APPROVAL_ANSWERS)
    assert approval.status == 0, approval.transcript()
    flow.folder += 1
    version = scene.document("/design/current")["version_number"]
    assert version == design["version_number"] + 1, version
    approved = say(
        "design.approved", code=alternative["code"], title=alternative["title"], version=version
    )
    assert approval.shows(approved), approval.transcript()
    assert [item.status for item in approval.requests("POST", "/design/gate/submit")] == [200]
    current = approved_reference(scene)
    assert current == {
        "requirements_version_number": earlier["requirements_version_number"],
        "design_version_number": version,
        "alternative_code": alternative["code"],
    }
    alignment = scene.document("/alignment")
    latest = alignment["latest_change"]
    assert alignment["stale_reviews"] == 1, alignment
    assert (latest["commit"], latest["review"]["reference"], latest["review"]["stale"]) == (
        fourth,
        earlier,
        True,
    )
    pending = scene.document("/code-changes?pending=true")["items"]
    assert [(item["commit"], item["review"]["stale"]) for item in pending] == [(fourth, True)]
    assert scene.document(f"/code-changes/{third}")["review"]["stale"] is True
    assert scene.document("/acceptance-tests")["latest_run_stale"] is True
    manifest = check_folder(scene, flow)
    assert manifest["state"]["stale_reviews"] == 1
    assert scene.folders()[0]["state"]["stale_reviews"] == 1
    state = read_json(scene.knowledge / "state" / "state.json")
    assert (state["changes"][0]["commit"], state["changes"][0]["review"]["stale"]) == (fourth, True)
    development_line = say("status.alignment", recorded=4, pending=1, commit=third[:7], tasks=3)
    line = f"{development_line} {say('status.stale_reviews', count=1)}"
    status = scene.ut("status")
    assert status.status == 0, status.transcript()
    assert status.shows(line), f"missing: {line}\n{status.transcript()}"
    as_json = scene.ut("status", "--json")
    assert as_json.status == 0, as_json.transcript()
    assert json.loads(as_json.output)["alignment"] == {
        "recorded": 4,
        "pending": 1,
        "aligned_commit": third,
        "open_tasks": 3,
        "stale_reviews": 1,
    }, as_json.transcript()
    offline = scene.ut("status", "--offline")
    assert (offline.status, offline.exchanges) == (0, ()), offline.transcript()
    assert offline.shows(line), f"missing: {line}\n{offline.transcript()}"
    point = alignment["aligned"]
    estimate = costs.estimate(review_operations(local_twins(scene), 1))
    listing = (
        say(
            "align.recheck_list",
            count=1,
            requirements=current["requirements_version_number"],
            design=current["design_version_number"],
            alternative=current["alternative_code"],
        ),
        "- "
        + say(
            "align.recheck_line",
            commit=fourth[:7],
            date=minute_text(latest["committed_at"]),
            line=FOURTH_MESSAGE,
            requirements=earlier["requirements_version_number"],
            design=earlier["design_version_number"],
            alternative=earlier["alternative_code"],
        ),
    )
    dry = scene.ut("align", "--recheck", "--dry-run")
    assert dry.status == 0, dry.transcript()
    assert_gaps(
        dry,
        say("align.heading", name=PROJECT_NAME),
        reference_sentence(alignment["reference"]),
        say(
            "align.aligned",
            commit=third[:7],
            date=minute_text(point["decided_at"]),
            requirements=point["requirements_version_number"],
            design=point["design_version_number"],
        ),
        say("align.open_tasks", count=3),
        *listing,
        say("align.recheck_dry_run"),
        say(
            "align.dry_run_estimate",
            amount=costs.amount_text(estimate, "en"),
            minutes=costs.minutes_text(estimate.minutes),
        ),
        development_line,
        say("align.recheck_hint", count=1),
    )
    assert (writes_of(dry), dry.errors) == ([], ""), dry.transcript()
    recheck = scene.ut("align", "--recheck")
    assert recheck.status == 1, recheck.transcript()
    assert_gaps(recheck, *listing)
    assert say(f"align.errors.{NO_REVIEW_MODEL}") in recheck.errors, recheck.transcript()
    reviewing = say("align.recheck_reviewing", count=1, twins=local_twins(scene))
    assert not recheck.shows(reviewing), recheck.transcript()
    assert writes_of(recheck) == [], recheck.transcript()
    assert recheck.requests("GET", BUDGET_PATH) == [], recheck.transcript()
    assert scene.document(f"/code-changes/{fourth}/reviews") == {"items": [review]}


def twins_that_learn(scene: Scene, flow: Flow) -> None:
    base = scene.base
    twin_id, name = flow.twins[0]
    overview = scene.document("/twin-learning")
    entry = overview["twins"][0]
    assert overview["update_available"] is False, overview
    assert (entry["twin_id"], entry["label"], entry["development_version_number"]) == (
        twin_id,
        "1.0",
        0,
    )
    assert (entry["observations"], entry["retired"], entry["pending_update"]) == ([], [], None)
    assert entry["new_material"] == {"changes": 3, "tests": 1}, entry
    observations = f"{base}/user-twins/{twin_id}/observations"
    learned = scene.ut("twins", "learn", "1", *FIRST_LEARNED.split())
    assert learned.status == 0, learned.transcript()
    flow.folder += 1
    assert_gaps(
        learned,
        say("twins.learn_done", name=name, code="OBS-001", label="1.1"),
        say("twins.folder_updated", version=flow.folder),
    )
    assert writes_of(learned) == [f"POST {observations} -> 201", published(scene)]
    check_folder(scene, flow)
    forgot = scene.ut("twins", "forget", "1", "obs-001", "--reason", FORGET_REASON)
    assert forgot.status == 0, forgot.transcript()
    flow.folder += 1
    assert_gaps(
        forgot,
        say("twins.forget_done", name=name, code="OBS-001", label="1.2"),
        say("twins.folder_updated", version=flow.folder),
    )
    assert writes_of(forgot) == [f"POST {observations}/OBS-001/retire -> 200", published(scene)]
    check_folder(scene, flow)
    again = scene.ut("twins", "learn", "1", *SECOND_LEARNED.split())
    assert again.status == 0, again.transcript()
    flow.folder += 1
    assert_gaps(
        again,
        say("twins.learn_done", name=name, code="OBS-002", label="1.3"),
        say("twins.folder_updated", version=flow.folder),
    )
    overview = scene.document("/twin-learning")
    entry = overview["twins"][0]
    assert (entry["label"], entry["development_version_number"], entry["pending_update"]) == (
        "1.3",
        3,
        None,
    )
    [observation] = entry["observations"]
    assert {key: value for key, value in observation.items() if key != "approved_at"} == {
        "code": "OBS-002",
        "statement": SECOND_LEARNED,
        "basis": None,
        "source": OWNER,
        "about": {"requirement": None, "screen": None},
        "contradicts_profile": None,
        "added_in_version": 3,
        "update_id": None,
    }
    [retired] = entry["retired"]
    assert {key: value for key, value in retired.items() if key != "retired_at"} == {
        "code": "OBS-001",
        "statement": FIRST_LEARNED,
        "retired_in_version": 2,
        "reason": FORGET_REASON,
    }
    manifest = check_folder(scene, flow)
    assert read_json(scene.knowledge.joinpath(*LEARNING_PATH.split("/"))) == {
        "schema_version": SCHEMA_VERSION,
        "kind": LEARNING_KIND,
        "project_id": scene.project_id,
        "twins": [
            {key: value for key, value in item.items() if key not in LEARNING_EXTRAS}
            for item in overview["twins"]
        ],
    }
    assert (manifest["feedback"]["learned"], manifest["feedback"]["learned_observations"]) == (
        LEARNING_PATH,
        1,
    )
    assert manifest["schemas"]["learning"] == LEARNING_SCHEMA
    assert scene.folders()[0]["feedback"]["learned_observations"] == 1
    assert_learning_texts(scene, name, observation)
    day = datetime.fromisoformat(observation["approved_at"]).astimezone(UTC).strftime(DAY_FORMAT)
    learned_line = "- " + say(
        "twins.learned_observation",
        code="OBS-002",
        statement=SECOND_LEARNED,
        origin=say("twins.learned_from_owner", date=day),
    )
    source = say("twins.source_folder", path=KNOWLEDGE_LABEL, version=flow.folder)
    notice = say("twins.offline_unreachable", studio=scene.origin, source=source)
    for offline in (False, True):
        listing = scene.ut("twins", "list", offline=offline)
        assert listing.status == 0, listing.transcript()
        assert listing.shows(notice) is offline, listing.transcript()
        for header in ("twins.column_version", "twins.column_learned"):
            assert listing.shows(say(header)), listing.transcript()
        rows = table_rows(listing.output)
        assert (rows[0][0], rows[0][-2:]) == ("1", ["1.3", "1"]), listing.transcript()
        shown = scene.ut("twins", "show", "1", offline=offline)
        assert shown.status == 0, shown.transcript()
        assert_gaps(
            shown,
            name,
            say("twins.section_learned", label="1.3"),
            learned_line,
            say("twins.learned_retired", count=1),
        )
    update = scene.ut("twins", "update")
    assert (update.status, update.output) == (1, ""), update.transcript()
    assert say("twins.update_no_model") in update.errors, update.transcript()
    assert requests_of(update) == [
        f"GET {base}/user-modeling/readiness -> 200",
        f"GET {base}/user-modeling/snapshots/current -> 200",
        f"GET {base}/twin-learning -> 200",
    ], update.transcript()
    verify = scene.ut("package", "verify")
    latest = scene.folders()[0]
    assert (verify.status, verify.exchanges) == (0, ()), verify.transcript()
    verified = say(
        "package.verified",
        path=KNOWLEDGE_LABEL,
        version=flow.folder,
        project=PROJECT_NAME,
        files=latest["file_count"],
        hash=latest["content_hash"][:12],
    )
    assert verified in verify.output, verify.transcript()


def code_with_an_agent(scene: Scene, flow: Flow) -> None:
    flow.agent.write_text("\n".join(AGENT_SCRIPT) + "\n", encoding="utf-8", newline="\n")
    python = sys.executable
    command = command_line(python, str(flow.agent), PROMPT_PLACEHOLDER)
    opened = tasks_of(scene, every=False)
    codes = [task["code"] for task in opened]
    assert codes == ["TSK-009", "TSK-010", "TSK-011"], codes
    folder = scene.local.joinpath(*CODE_FOLDER)
    dry = scene.ut("code", "--dry-run", "--agent", CUSTOM_AGENT, "--command", command)
    assert (dry.status, dry.exchanges, dry.errors) == (0, (), ""), dry.transcript()
    [first] = run_folders(folder)
    prompt = first / "prompt.md"
    assert_gaps(
        dry,
        say("code.heading", name=PROJECT_NAME),
        say("code.agent_custom", program=python),
        say("code.mode_interactive"),
        say("code.work_all_tasks", codes=", ".join(codes)),
        say("code.order", path=str(prompt)),
        say("code.own_account"),
        say("code.words"),
        python,
        str(flow.agent),
        str(prompt),
        say("code.dry_run", folder=str(first)),
    )
    settings = {
        "schema_version": 1,
        "agent": CUSTOM_AGENT,
        "command": [python, str(flow.agent), PROMPT_PLACEHOLDER],
        "model": None,
        "headless": False,
    }
    assert read_json(scene.local / "code.json") == settings
    assert (folder / ".gitignore").read_bytes() == b"*\n"
    assert sorted(item.name for item in first.iterdir()) == ["mcp.json", "prompt.md"]
    assert not (folder / "latest.json").exists()
    content = prompt.read_bytes()
    order = content.decode("utf-8")
    assert b"\r" not in content, order
    assert order.splitlines()[0] == code_order.TITLE, order
    gaps = line_gaps(order, work_lines(opened))
    assert gaps == [], "\n".join([*gaps, order])
    server = read_json(first / "mcp.json")["mcpServers"][MCP_SERVER]
    assert (server["command"], server["args"][:2], server["args"][-1]) == (
        python,
        ["-m", "orchestwin.cli"],
        "mcp",
    ), server
    assert Path(server["cwd"]).resolve() == scene.project.resolve(), server
    machine = dict(os.environ)
    real = scene.ut_on_machine(
        "--yes", "code", "--agent", CUSTOM_AGENT, "--command", command, machine=machine
    )
    assert (real.status, real.exchanges) == (0, ()), real.transcript()
    latest = read_json(folder / "latest.json")
    second = folder / latest["folder"]
    assert second != first and second.parent == folder, latest
    outcome = read_json(second / "outcome.json")
    changed = outcome["changed_files"]
    assert changed == [AGENT_NOTE], outcome
    assert outcome == {
        "schema_version": 1,
        "started_at": outcome["started_at"],
        "finished_at": outcome["finished_at"],
        "seconds": outcome["seconds"],
        "agent": CUSTOM_AGENT,
        "program": Path(python).name,
        "headless": False,
        "model": None,
        "spend": False,
        "tasks": codes,
        "request": None,
        "exit_status": 0,
        "changed_files": changed,
    }, outcome
    assert latest == {
        "schema_version": 1,
        "folder": second.name,
        "started_at": outcome["started_at"],
        "finished_at": outcome["finished_at"],
        "agent": CUSTOM_AGENT,
        "exit_status": 0,
        "changed_files": changed,
    }, latest
    started, finished = (
        datetime.fromisoformat(outcome[key]) for key in ("started_at", "finished_at")
    )
    assert started <= finished, outcome
    assert sorted(item.name for item in second.iterdir()) == [
        "mcp.json",
        "outcome.json",
        "prompt.md",
    ]
    note = scene.project.joinpath(*AGENT_NOTE.split("/"))
    assert note.read_bytes() == f"{code_order.TITLE}\n".encode(), note.read_bytes()
    assert_gaps(
        real,
        say("code.agent_custom", program=python),
        say("code.starting", program=Path(python).name),
        say("code.ended", elapsed=format_elapsed(outcome["seconds"])),
        say("code.changed", count=len(changed)),
        *(f"- {path}" for path in changed),
        say("code.next_steps"),
    )
    touched = say("code.knowledge_touched", folder=KNOWLEDGE)
    assert not real.shows(touched), real.transcript()
    assert read_json(scene.local / "code.json") == settings


def serve_the_agent(scene: Scene, flow: Flow) -> None:
    twin_id = flow.twins[0][0]
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL,
                "capabilities": {},
                "clientInfo": MCP_CLIENT,
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        tool_message(3, "get_tasks", {}),
        tool_message(4, "get_tasks", {"status": "all"}),
        tool_message(5, "get_twin", {"twin": "1"}),
        tool_message(6, "list_twins", {}),
        tool_message(7, "project_state", {}),
    ]
    run = scene.ut("mcp", answers=[json.dumps(message) for message in messages])
    assert (run.status, run.exchanges) == (0, ()), run.transcript()
    answers = json_lines(run.output)
    assert [answer.get("id") for answer in answers] == [1, 2, 3, 4, 5, 6, 7], run.transcript()
    assert all(answer.get("jsonrpc") == "2.0" and "result" in answer for answer in answers)
    names = [tool["name"] for tool in answers[1]["result"]["tools"]]
    assert (len(names), names) == (15, list(MCP_TOOLS)), names
    state = read_json(scene.knowledge / "state" / "state.json")
    opened = [task for task in state["tasks"] if task["status"] == OPEN]
    assert opened == tasks_of(scene, every=False)
    assert state["tasks"] == tasks_of(scene)
    assert tool_document(answers[2]) == {"tasks": opened}
    assert tool_document(answers[3]) == {"tasks": state["tasks"]}
    learned = read_json(scene.knowledge.joinpath(*LEARNING_PATH.split("/")))
    entries = {item["twin_id"]: item for item in learned["twins"]}
    twin = tool_document(answers[4])
    assert (twin["twin"]["number"], twin["twin"]["twin_id"]) == (1, twin_id), twin
    assert twin["learned"] == entries[twin_id], twin
    listed = tool_document(answers[5])["twins"]
    assert [
        (item["number"], item["twin_id"], item["label"], item["learned_observations"])
        for item in listed
    ] == [
        (number, identifier, entries[identifier]["label"], len(entries[identifier]["observations"]))
        for number, (identifier, _) in enumerate(flow.twins, start=1)
    ], listed
    assert (listed[0]["label"], listed[0]["learned_observations"]) == ("1.3", 1), listed
    project = tool_document(answers[6])
    assert (project["stale_reviews"], project["open_tasks"]) == (1, opened), project


def change_review(flow: Flow) -> dict[str, object]:
    critiques = []
    for position, (twin_id, name) in enumerate(flow.twins):
        findings = CHANGE_FINDINGS if position == 0 else OTHER_CHANGE_FINDINGS
        critiques.append(
            {
                "twin_id": twin_id,
                "twin_name": name,
                "verdict": CONCERN,
                "summary": CHANGE_SUMMARY,
                "findings": [
                    {
                        "severity": severity,
                        "text": text,
                        "about": {"requirement": flow.requirement, "screen": SCREEN, "file": APP},
                        "action": action,
                    }
                    for severity, text, action in findings
                ],
            }
        )
    return {
        "locale": LOCALE,
        "critiques": critiques,
        "alignment": {
            "status": ALIGNED,
            "summary": REVIEW_SUMMARY,
            "affected": {"requirements": [flow.requirement], "screens": []},
            "design_request": None,
            "requirements_request": None,
            "code_tasks": [],
        },
    }


def run_review(flow: Flow) -> dict[str, object]:
    critiques = []
    for position, (twin_id, name) in enumerate(flow.twins):
        findings = RUN_FINDINGS if position == 0 else OTHER_RUN_FINDINGS
        critiques.append(
            {
                "twin_id": twin_id,
                "twin_name": name,
                "verdict": CONCERN,
                "summary": RUN_SUMMARY,
                "findings": [
                    {
                        "severity": severity,
                        "text": text,
                        "about": {
                            "criterion": flow.criterion,
                            "requirement": flow.requirement,
                            "screen": SCREEN,
                        },
                        "action": action,
                    }
                    for severity, text, action in findings
                ],
            }
        )
    return {"locale": LOCALE, "critiques": critiques}


def plan_document(flow: Flow, reference: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "created_at": utc_now().replace(microsecond=0).isoformat(),
        "locale": LOCALE,
        "reference": dict(reference),
        "application": dict(APPLICATION),
        "criteria": [flow.criterion],
        "replan_of": [],
        "paths": [
            {
                "code": PATH_CODE,
                "heading": f'The page shows "{EXPECTED_TEXT}"',
                "criteria": [flow.criterion],
                "steps": [
                    {"action": "OPEN", "target": None, "value": "/", "expect": None},
                    {
                        "action": "CHECK",
                        "target": None,
                        "value": None,
                        "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": EXPECTED_TEXT},
                    },
                ],
            }
        ],
        "not_covered": [],
        "cost_microusd": 0,
    }


def run_document(plan: Mapping[str, object]) -> dict[str, object]:
    finished = utc_now().replace(microsecond=0)
    started = finished - timedelta(seconds=5)
    return {
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "application": dict(APPLICATION),
        "browsers": [dict(BROWSER)],
        "results": [
            {
                "path": plan["paths"][0],
                "browser": BROWSER["name"],
                "status": "FAILED",
                "seconds": 1.5,
                "steps": [
                    step_result(1, "DONE", None),
                    step_result(2, "FAILED", f"expectation not met: TEXT_VISIBLE: {EXPECTED_TEXT}"),
                ],
                "page_text": PAGE_TITLE,
            }
        ],
        "not_covered": [],
    }


def step_result(index: int, status: str, detail: str | None) -> dict[str, object]:
    return {
        "index": index,
        "status": status,
        "detail": detail,
        "url": PAGE_ADDRESS,
        "title": PAGE_TITLE,
        "screenshot": f"{PATH_CODE}/{BROWSER['name']}/{index:02d}.png",
    }


def candidate_lines(
    critiques: Sequence[Mapping[str, object]], existing: Mapping[tuple[str, int], str]
) -> list[str]:
    lines: list[str] = []
    number = 0
    for critique in critiques:
        for index, finding in enumerate(critique["findings"]):
            line = say(
                "tasks.choice_finding",
                who=critique["twin_name"],
                importance=say(f"tasks.importance_{str(finding['severity']).lower()}"),
                finding=finding["text"],
            )
            code = existing.get((str(critique["twin_id"]), index))
            if code is None:
                number += 1
                lines.append(f"{number}. {line}")
            else:
                lines.append(f"-  {say('tasks.choice_existing', line=line, code=code)}")
            text = finding_task(finding)
            if text != finding["text"]:
                lines.append(say("tasks.choice_task", text=text))
    return lines


def finding_task(finding: Mapping[str, object]) -> str:
    action = finding.get("action")
    return " ".join(str(action or finding["text"]).split())


def work_lines(tasks: Sequence[Mapping[str, object]]) -> list[str]:
    lines = [code_order.WORK_HEADING, code_order.TASKS_INTRODUCTION]
    for task in tasks:
        lines.append(code_order.TASK_LINE.format(code=task["code"], text=task["text"]))
        lines.append(code_order.FROM_LINE.format(origin=work_origin(task)))
        subjects = [
            *task["about"]["requirements"],
            *task["about"]["screens"],
            *task["about"]["criteria"],
        ]
        if subjects:
            lines.append(code_order.ABOUT_LINE.format(codes=", ".join(subjects)))
    return lines


def work_origin(task: Mapping[str, object]) -> str:
    origin = task["origin"]
    if origin["kind"] == OWNER:
        return code_order.WRITTEN_BY_OWNER
    twin = code_order.NAMED_TWIN.format(name=origin["twin_name"])
    finding = code_order.QUOTED_FINDING.format(text=origin["finding"])
    if origin["kind"] == TEST_RUN:
        return code_order.TEST_FINDING.format(twin=twin, finding=finding)
    commit = code_order.NAMED_COMMIT.format(commit=str(origin["commit"])[:7])
    return code_order.COMMIT_FINDING.format(twin=twin, commit=commit, finding=finding)


def assert_learning_texts(scene: Scene, name: str, observation: Mapping[str, object]) -> None:
    label = f"{name}, version 1.3"
    when = datetime.fromisoformat(str(observation["approved_at"])).isoformat(
        sep=" ", timespec="minutes"
    )
    index = (scene.knowledge / "ORCHESTWIN.md").read_text(encoding="utf-8").splitlines()
    for line in ("## What the twins learned", f"- {label}:", f"  - OBS-002: {SECOND_LEARNED}"):
        assert line in index, f"missing in ORCHESTWIN.md: {line}"
    feedback = (
        (scene.knowledge / "twins" / "feedback" / "feedback.md")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    paragraph = (
        f"{label}, has 1 active learned observation. OBS-002 (written by the owner on {when}): "
        f"{SECOND_LEARNED} Retired observation: OBS-001."
    )
    for line in ("## Learned during development", paragraph):
        assert line in feedback, f"missing in feedback.md: {line}"
    state = (scene.knowledge / "state" / "state.md").read_text(encoding="utf-8")
    assert "## What the twins learned" in state.splitlines(), state
    assert f"{label}, 1 observation" in state, state


def check_folder(scene: Scene, flow: Flow) -> Mapping[str, object]:
    latest = scene.folders()[0]
    assert latest["version_number"] == flow.folder, (latest["version_number"], flow.folder)
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert manifest["package"]["version_number"] == flow.folder, manifest["package"]
    every = tasks_of(scene)
    opened = sum(1 for task in every if task["status"] == OPEN)
    state = read_json(scene.knowledge / "state" / "state.json")
    assert state["tasks"] == every, state["tasks"]
    assert (latest["state"]["open_tasks"], manifest["state"]["open_tasks"]) == (opened, opened)
    return manifest


def assert_task(
    task: Mapping[str, object],
    *,
    text: str,
    origin: Mapping[str, object],
    status: str = OPEN,
    note: str | None = None,
    about_codes: Mapping[str, list[str]] | None = None,
) -> None:
    assert tuple(task) == TASK_KEYS, list(task)
    assert tuple(task["origin"]) == ORIGIN_KEYS, list(task["origin"])
    assert (task["text"], task["origin"], task["from_commit"]) == (
        text,
        dict(origin),
        origin["commit"],
    ), task
    assert task["about"] == (about_codes or about()), task
    assert (task["status"], task["note"]) == (status, note), task
    assert (task["closed_at"] is None) == (status == OPEN), task
    assert datetime.fromisoformat(str(task["created_at"])).tzinfo is not None, task


def origin_of(
    kind: str,
    *,
    commit: str | None = None,
    test_run_id: object = None,
    twin: tuple[str, str] | None = None,
    finding: object = None,
) -> dict[str, object]:
    twin_id, twin_name = (None, None) if twin is None else twin
    return {
        "kind": kind,
        "commit": commit,
        "test_run_id": test_run_id,
        "twin_id": twin_id,
        "twin_name": twin_name,
        "finding": finding,
    }


def about(
    *,
    requirements: Sequence[str] = (),
    screens: Sequence[str] = (),
    criteria: Sequence[str] = (),
) -> dict[str, list[str]]:
    return {
        "requirements": list(requirements),
        "screens": list(screens),
        "criteria": list(criteria),
    }


def closed_by_the_rule(task: Mapping[str, object], covered: set[str], recorded: datetime) -> bool:
    origin = task["origin"]
    if origin["kind"] == CODE_CHANGE:
        return origin["commit"] in covered
    return datetime.fromisoformat(str(task["created_at"])) <= recorded


def same_moment(left: object, right: object) -> bool:
    return datetime.fromisoformat(str(left)) == datetime.fromisoformat(str(right))


def minute_text(value: object) -> str:
    return datetime.fromisoformat(str(value)).strftime(MINUTE_FORMAT)


def tasks_of(scene: Scene, *, every: bool = True) -> list[dict[str, object]]:
    return scene.document(f"/code-tasks?status={'all' if every else 'open'}")["items"]


def by_code(tasks: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {str(task["code"]): task for task in tasks}


def task_code(number: int) -> str:
    return f"TSK-{number:03d}"


def folder_line(flow: Flow) -> str:
    return say("tasks.folder_updated", path=KNOWLEDGE_LABEL, version=flow.folder)


def published(scene: Scene) -> str:
    return f"POST {scene.base}/knowledge-packages -> 201"


def status_write(scene: Scene, code: str) -> str:
    return f"POST {scene.base}/code-tasks/{code}/status -> 200"


def requests_of(run: Run) -> list[str]:
    return [exchange.line() for exchange in run.exchanges if exchange.path != RENEWAL_PATH]


def writes_of(run: Run) -> list[str]:
    return [exchange.line() for exchange in run.writes()]


def assert_gaps(run: Run, *sentences: str) -> None:
    gaps = run.order_gaps(*sentences)
    assert gaps == [], "\n".join([*gaps, run.transcript()])


def assert_requests(run: Run, *lines: str) -> None:
    sent = requests_of(run)
    position = 0
    for line in lines:
        assert line in sent[position:], f"missing, or not in this order: {line}\n{run.transcript()}"
        position = sent.index(line, position) + 1


def line_gaps(text: str, lines: Sequence[str]) -> list[str]:
    written = text.splitlines()
    position = 0
    gaps: list[str] = []
    for line in lines:
        if line not in written[position:]:
            gaps.append(f"missing, or not in this order: {line}")
            continue
        position = written.index(line, position) + 1
    return gaps


def run_folders(folder: Path) -> list[Path]:
    return sorted(item for item in folder.iterdir() if item.is_dir())


def command_line(*words: str) -> str:
    if sys.platform == "win32":
        return " ".join(f'"{word}"' for word in words)
    return shlex.join(words)


def tool_message(identifier: int, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)},
    }
