from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orchestwin.cli import costs
from orchestwin.cli.commands.watch import DEFAULT_INTERVAL
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    GIT_BRANCH,
    GIT_CLEARED,
    GIT_NAME,
    KNOWLEDGE,
    PROJECT_NAME,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Repository,
    Scene,
    StudioApi,
    StudioProcess,
    choose_through_the_api,
    git_available,
    git_variables,
    journey_scene,
    read_json,
    say,
    short_wait,
    stay_on_the_studio,
)

pytestmark = pytest.mark.integration

STAGES = ("brief", "team", "twins", "requirements", "design")
INIT_FOLDER = 4
COMPLETE_FOLDER = 5
ALIGNED_FOLDER = 6
SCHEMA_VERSION = 3
DESIGN_ANSWERS = ("choose", "1", "approve", "leave")
APPROVAL_ANSWERS = ("approve", "leave")
KNOWLEDGE_LABEL = f"{KNOWLEDGE}/"
ZONE = timezone(timedelta(hours=2))
FIRST_MOMENT = datetime(2026, 9, 29, 10, 15, tzinfo=ZONE)
SECOND_MOMENT = datetime(2026, 9, 29, 10, 20, tzinfo=ZONE)
THIRD_MOMENT = datetime(2026, 9, 29, 10, 25, tzinfo=ZONE)
FOURTH_MOMENT = datetime(2026, 9, 29, 10, 30, tzinfo=ZONE)
FIRST_MESSAGE = "Add the bill form"
SECOND_MESSAGE = "Show the tip of each person"
THIRD_MESSAGE = "Round each share to the cent"
FOURTH_MESSAGE = "Show each share in bold"
APP = "src/app.js"
STYLE = "src/style.css"
SECRETS = ".env"
FAKE_SECRET = "test-token-not-real"
APP_LINES = (
    'const total = document.querySelector("#total");',
    'const tip = document.querySelector("#tip");',
    "export function share(people) {",
    "  return Number(total.value) / people;",
    "}",
)
TIP_LINE = "  return (Number(total.value) * (1 + Number(tip.value) / 100)) / people;"
ROUND_LINE = (
    "  return Math.round((Number(total.value) * (100 + Number(tip.value))) / people) / 100;"
)
STYLE_TEXT = "form {\n  display: grid;\n}\n"
BOLD_TEXT = "strong {\n  font-weight: 700;\n}\n"
EXCLUDED_SECRETS = f"[excluded: {SECRETS}]"
CONSIDERED_LIMIT = 50
WATCH_SECONDS = 7
REVIEW_OPERATION = "CODE_CHANGE_REVIEW"
ALIGNMENT_OPERATION = "CODE_ALIGNMENT"
CHANGE_KEYS = (
    "commit",
    "parent",
    "committed_at",
    "author",
    "message",
    "files",
    "recorded_at",
    "review",
    "decision",
)
NO_REVIEW_MODEL = "CHANGE_REVIEW_MODEL_NOT_CONFIGURED"
MCP_PROTOCOL = "2025-06-18"
MCP_SERVER = "orchestwin-twins"
MCP_CLIENT = {"name": "journey", "version": "1"}
MCP_TOOLS = (
    "project_state",
    "list_twins",
    "get_twin",
    "get_requirements",
    "get_design",
    "get_feedback",
    "ask_twin",
    "review_changes",
)


@dataclass
class Development:
    repository: Repository
    commits: list[str] = field(default_factory=list)


def test_ut_aligns_the_code_with_the_real_studio(
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
        with journey.step("1-2 ut login, ut init and ut design approve the five steps"):
            approve_the_design(scene)
        if not journey.problems:
            isolate_git(monkeypatch, tmp_path)
            walk(scene, journey, Development(Repository(scene.project)))
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def walk(scene: Scene, journey: Journey, development: Development) -> None:
    with journey.step("3 a git repository with two commits in the project folder"):
        create_the_repository(scene, development)
    with journey.step("4 ut align --dry-run records the two commits and reviews nothing"):
        record_without_reviewing(scene, development)
    with journey.step("5 ut align without a model records nothing new and reviews nothing"):
        refuse_the_review(scene, development)
    with journey.step("6 ut watch --once finds both commits known"):
        watch_once(scene, development)
    with journey.step("6 a third commit, then ut watch --once records it"):
        watch_once_records(scene, development)
    with journey.step("6 ut watch records the commit made while it waits"):
        watch_a_new_commit(scene, development)
    with journey.step("7 decision through the API, ut status, ut package publish and verify"):
        decide_without_a_review(scene, development)
    with journey.step("8 ut mcp answers from the folder with JSON only"):
        serve_the_agents(scene, development)
    with journey.step("every request stayed on the Studio of the test"):
        stay_on_the_studio(scene)


def isolate_git(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    for name in GIT_CLEARED:
        monkeypatch.delenv(name, raising=False)
    for name, value in git_variables(root).items():
        monkeypatch.setenv(name, value)


def approve_the_design(scene: Scene) -> None:
    login = scene.ut(
        "login",
        "--studio",
        scene.origin,
        "--email",
        TEST_EMAIL,
        "--password-stdin",
        directory=scene.outside,
        answers=[TEST_PASSWORD],
    )
    assert login.status == 0, login.transcript()
    init = scene.ut("--yes", "init", "--answers", str(scene.answers))
    assert init.status == 0, init.transcript()
    scene.project_id = read_json(scene.local / "project.json")["project_id"]
    assert scene.folder_numbers() == list(range(INIT_FOLDER, 0, -1)), init.transcript()
    generated = scene.ut("--yes", "design", answers=DESIGN_ANSWERS)
    assert generated.status == 0, generated.transcript()
    design = scene.document("/design/current")
    choose_through_the_api(scene, design, design["package"]["alternatives"][0]["id"])
    approval = scene.ut("--yes", "design", answers=APPROVAL_ANSWERS)
    assert approval.status == 0, approval.transcript()
    assert scene.folder_numbers() == list(range(COMPLETE_FOLDER, 0, -1)), approval.transcript()
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert (manifest["progress"]["complete"], manifest["state"]["changes"]) == (True, 0)


def create_the_repository(scene: Scene, development: Development) -> None:
    repository = development.repository
    repository.create()
    first = repository.commit(
        FIRST_MESSAGE, {APP: app_source(APP_LINES[3]), STYLE: STYLE_TEXT}, FIRST_MOMENT
    )
    second = repository.commit(
        SECOND_MESSAGE,
        {APP: app_source(TIP_LINE), SECRETS: f"API_TOKEN={FAKE_SECRET}\n"},
        SECOND_MOMENT,
    )
    development.commits.extend([first, second])
    top = Path(repository.git("rev-parse", "--show-toplevel").strip())
    assert top.resolve() == scene.project.resolve(), top
    untracked = sorted(repository.git("status", "--porcelain").splitlines())
    assert untracked == ["?? .orchestwin/", f"?? {KNOWLEDGE_LABEL}"], untracked
    assert scene.document("/code-changes") == {"items": []}


def record_without_reviewing(scene: Scene, development: Development) -> None:
    first, second = development.commits
    reference = scene.document("/alignment")["reference"]
    lines = (
        commit_line(first, FIRST_MOMENT, FIRST_MESSAGE, 2),
        commit_line(second, SECOND_MOMENT, SECOND_MESSAGE, 2),
    )
    estimate = costs.estimate(review_operations(local_twins(scene), 2))
    run = scene.ut("align", "--dry-run")
    assert run.status == 0, run.transcript()
    gaps = run.order_gaps(
        say("align.heading", name=PROJECT_NAME),
        reference_sentence(reference),
        say("align.not_aligned"),
        say("align.considered_all", count=2, limit=CONSIDERED_LIMIT),
        *lines,
        say("align.recorded", count=2),
        say("align.dry_run", count=2),
        *lines,
        say(
            "align.dry_run_estimate",
            amount=costs.amount_text(estimate, "en"),
            minutes=costs.minutes_text(estimate.minutes),
        ),
        say("status.alignment_not_aligned", recorded=2, pending=2, tasks=0),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    assert not run.shows(say("align.uncommitted")), run.transcript()
    assert run.errors == "", run.transcript()
    assert [exchange.line() for exchange in run.writes()] == [
        f"POST {scene.base}/code-changes -> 201"
    ] * 2, run.transcript()
    items = scene.document("/code-changes")["items"]
    assert [item["commit"] for item in items] == [second, first]
    assert_change(
        items[1],
        (first, None, FIRST_MOMENT, FIRST_MESSAGE),
        {(APP, "ADDED", 5, 0), (STYLE, "ADDED", 3, 0)},
    )
    assert_change(
        items[0],
        (second, first, SECOND_MOMENT, SECOND_MESSAGE),
        {(SECRETS, "ADDED", 1, 0), (APP, "MODIFIED", 1, 1)},
    )
    stored = scene.document(f"/code-changes/{second}")
    assert {key: value for key, value in stored.items() if key != "diff"} == items[0]
    assert list(stored)[-1] == "diff"
    diff = stored["diff"].splitlines()
    assert EXCLUDED_SECRETS in diff, stored["diff"]
    assert f"+{TIP_LINE}" in diff, stored["diff"]
    assert FAKE_SECRET not in stored["diff"], "the fake secret of .env reached the Studio"
    older = scene.document(f"/code-changes/{first[:7]}")
    assert older["commit"] == first
    assert f"+{APP_LINES[0]}" in older["diff"].splitlines(), older["diff"]
    assert "[excluded:" not in older["diff"], older["diff"]
    alignment = scene.document("/alignment")
    assert (alignment["aligned"], alignment["pending_changes"], alignment["tasks"]) == (None, 2, [])
    assert (alignment["latest_change"], alignment["review_available"]) == (items[0], False)
    assert_no_run(scene, development.commits)


def refuse_the_review(scene: Scene, development: Development) -> None:
    first, second = development.commits
    reference = scene.document("/alignment")["reference"]
    lines = (
        commit_line(first, FIRST_MOMENT, FIRST_MESSAGE, 2),
        commit_line(second, SECOND_MOMENT, SECOND_MESSAGE, 2),
    )
    run = scene.ut("align")
    assert run.status == 1, run.transcript()
    gaps = run.order_gaps(
        say("align.heading", name=PROJECT_NAME),
        reference_sentence(reference),
        say("align.not_aligned"),
        say("align.considered_all", count=2, limit=CONSIDERED_LIMIT),
        *lines,
        say("align.recorded", count=0),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    refusal = say(f"align.errors.{NO_REVIEW_MODEL}")
    assert refusal in run.errors, run.transcript()
    assert NO_REVIEW_MODEL in refusal
    reviewing = say("align.reviewing", count=2, twins=local_twins(scene))
    assert not run.shows(reviewing), run.transcript()
    assert run.writes() == [], run.transcript()
    assert [item["commit"] for item in scene.document("/code-changes")["items"]] == [second, first]
    direct = scene.api.request(
        "POST", f"{scene.base}/code-changes/{second}/reviews", {"locale": "en-US", "again": False}
    )
    assert (direct.status, direct.code) == (503, NO_REVIEW_MODEL)
    assert_no_run(scene, development.commits)


def watch_once(scene: Scene, development: Development) -> None:
    run = scene.ut("watch", "--once")
    assert run.status == 0, run.transcript()
    gaps = run.order_gaps(
        *watch_introduction(scene, development.commits[-1]),
        say("watch.nothing_new"),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    assert not run.shows(say("watch.waiting", seconds=f"{DEFAULT_INTERVAL:g}")), run.transcript()
    assert run.writes() == [], run.transcript()
    assert [exchange.line() for exchange in run.requests("GET", "/alignment")] == [
        f"GET {scene.base}/alignment -> 200"
    ], run.transcript()
    listed = [item["commit"] for item in scene.document("/code-changes")["items"]]
    assert listed == development.commits[::-1]


def watch_once_records(scene: Scene, development: Development) -> None:
    first, second = development.commits
    third = development.repository.commit(
        THIRD_MESSAGE, {APP: app_source(ROUND_LINE)}, THIRD_MOMENT
    )
    development.commits.append(third)
    run = scene.ut("watch", "--once")
    assert run.status == 0, run.transcript()
    gaps = run.order_gaps(
        *watch_introduction(scene, second),
        say("watch.new_commits", count=1),
        commit_line(third, THIRD_MOMENT, THIRD_MESSAGE, 1),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    assert not run.shows(say("watch.nothing_new")), run.transcript()
    assert [exchange.line() for exchange in run.writes()] == [
        f"POST {scene.base}/code-changes -> 201"
    ], run.transcript()
    items = scene.document("/code-changes")["items"]
    assert [item["commit"] for item in items] == [third, second, first]
    assert_change(items[0], (third, second, THIRD_MOMENT, THIRD_MESSAGE), {(APP, "MODIFIED", 1, 1)})
    alignment = scene.document("/alignment")
    assert (alignment["pending_changes"], alignment["latest_change"]) == (3, items[0])


def watch_a_new_commit(scene: Scene, development: Development) -> None:
    repository = development.repository
    made: list[str] = []
    waits: list[float] = []

    def commit_while_waiting(seconds: float) -> None:
        if seconds != WATCH_SECONDS:
            short_wait(seconds)
            return
        waits.append(seconds)
        if len(waits) > 1:
            raise KeyboardInterrupt
        made.append(
            repository.commit(FOURTH_MESSAGE, {STYLE: STYLE_TEXT + BOLD_TEXT}, FOURTH_MOMENT)
        )

    run = scene.ut("watch", "--interval", str(WATCH_SECONDS), sleep=commit_while_waiting)
    assert run.status == 0, run.transcript()
    assert (len(made), len(waits)) == (1, 2), run.transcript()
    third = development.commits[-1]
    fourth = made[0]
    development.commits.append(fourth)
    gaps = run.order_gaps(
        *watch_introduction(scene, third),
        say("watch.waiting", seconds=WATCH_SECONDS),
        say("watch.new_commits", count=1),
        commit_line(fourth, FOURTH_MOMENT, FOURTH_MESSAGE, 1),
        say("watch.stopped"),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    assert [exchange.line() for exchange in run.writes()] == [
        f"POST {scene.base}/code-changes -> 201"
    ], run.transcript()
    items = scene.document("/code-changes")["items"]
    assert [item["commit"] for item in items] == development.commits[::-1]
    assert_change(
        items[0], (fourth, third, FOURTH_MOMENT, FOURTH_MESSAGE), {(STYLE, "MODIFIED", 3, 0)}
    )
    alignment = scene.document("/alignment")
    assert (alignment["pending_changes"], alignment["latest_change"]) == (len(items), items[0])


def decide_without_a_review(scene: Scene, development: Development) -> None:
    newest = development.commits[-1]
    recorded = len(development.commits)
    reference = scene.document("/alignment")["reference"]
    answer = scene.api.request(
        "POST", f"{scene.base}/code-changes/{newest}/decision", {"kind": "ALIGNED", "note": None}
    )
    assert answer.status == 200, f"the decision answered {answer.status} {answer.code}"
    decided = answer.json()
    change = decided["change"]
    assert (decided["status"], change["commit"], change["review"]) == ("DECIDED", newest, None)
    assert (change["decision"]["kind"], change["decision"]["note"]) == ("ALIGNED", None)
    alignment = decided["alignment"]
    aligned = alignment["aligned"]
    assert aligned == {
        "commit": newest,
        "decided_at": change["decision"]["decided_at"],
        "requirements_version_number": reference["requirements"]["version_number"],
        "design_version_number": reference["design"]["version_number"],
    }
    assert (alignment["pending_changes"], alignment["tasks"]) == (0, [])
    assert alignment == scene.document("/alignment")
    assert scene.document("/code-changes?pending=true") == {"items": []}
    development_line = say(
        "status.alignment", recorded=recorded, pending=0, commit=newest[:7], tasks=0
    )
    status = scene.ut("status")
    assert status.status == 0, status.transcript()
    for sentence in (
        say("status.next", action=say("status.next_folder_current")),
        say("status.folder_both", local=COMPLETE_FOLDER, studio=COMPLETE_FOLDER),
        development_line,
    ):
        assert sentence in status.output, f"missing: {sentence}\n{status.transcript()}"
    as_json = scene.ut("status", "--json")
    assert as_json.status == 0, as_json.transcript()
    document = json.loads(as_json.output)
    assert (document["next_action"], document["next_command"], document["alignment"]) == (
        "DOWNLOAD_FOLDER",
        "ut align",
        {"recorded": recorded, "pending": 0, "aligned_commit": newest, "open_tasks": 0},
    ), as_json.transcript()
    publish_the_state(scene, newest, aligned, reference)
    offline = scene.ut("status", "--offline")
    assert offline.status == 0, offline.transcript()
    assert offline.exchanges == (), offline.transcript()
    for sentence in (development_line, say("status.folder_only_local", local=ALIGNED_FOLDER)):
        assert sentence in offline.output, f"missing: {sentence}\n{offline.transcript()}"


def publish_the_state(
    scene: Scene, newest: str, aligned: Mapping[str, object], reference: Mapping[str, object]
) -> None:
    listed = scene.document("/code-changes")["items"]
    publish = scene.ut("package", "publish")
    assert publish.status == 0, publish.transcript()
    versions = scene.folders()
    latest = versions[0]
    assert [item["version_number"] for item in versions] == list(range(ALIGNED_FOLDER, 0, -1))
    published = say(
        "package.published",
        version=ALIGNED_FOLDER,
        path=KNOWLEDGE_LABEL,
        files=latest["file_count"],
    )
    assert published in publish.output, publish.transcript()
    assert [item.status for item in publish.requests("POST", "/knowledge-packages")] == [201]
    counts = {
        "changes": len(listed),
        "pending_changes": 0,
        "aligned_commit": newest,
        "open_tasks": 0,
    }
    assert latest["state"] == counts
    assert (latest["progress"]["complete"], latest["feedback"]["change_reviews"]) == (True, 0)
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert manifest["package"]["version_number"] == ALIGNED_FOLDER
    assert manifest["state"] == {"document": "state/state.json", "text": "state/state.md", **counts}
    state = read_json(scene.knowledge / "state" / "state.json")
    assert state["aligned"] == aligned
    assert state["changes"] == listed
    assert (state["tasks"], state["reference"]) == ([], reference)
    text = (scene.knowledge / "state" / "state.md").read_text(encoding="utf-8")
    assert newest[:7] in text, text
    reviews = read_json(scene.knowledge / "twins" / "feedback" / "changes.json")
    assert reviews["runs"] == []
    verify = scene.ut("package", "verify")
    assert verify.status == 0, verify.transcript()
    assert verify.exchanges == (), verify.transcript()
    verified = say(
        "package.verified",
        path=KNOWLEDGE_LABEL,
        version=ALIGNED_FOLDER,
        project=PROJECT_NAME,
        files=latest["file_count"],
        hash=latest["content_hash"][:12],
    )
    assert verified in verify.output, verify.transcript()


def serve_the_agents(scene: Scene, development: Development) -> None:
    newest = development.commits[-1]
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
        tool_call(3, "project_state"),
        tool_call(4, "get_requirements"),
        tool_call(5, "list_twins"),
    ]
    run = scene.ut("mcp", answers=[json.dumps(message) for message in messages])
    assert run.status == 0, run.transcript()
    assert run.exchanges == (), run.transcript()
    answers = json_lines(run.output)
    assert [answer.get("id") for answer in answers] == [1, 2, 3, 4, 5], run.transcript()
    answered = all(answer.get("jsonrpc") == "2.0" and "result" in answer for answer in answers)
    assert answered, run.transcript()
    started = answers[0]["result"]
    assert (started["protocolVersion"], started["serverInfo"]["name"]) == (MCP_PROTOCOL, MCP_SERVER)
    assert [tool["name"] for tool in answers[1]["result"]["tools"]] == list(MCP_TOOLS)
    for sentence in (
        say(
            "mcp.started", project=PROJECT_NAME, folder=str(scene.project), paid=say("mcp.paid_off")
        ),
        say(
            "mcp.client",
            client=f"{MCP_CLIENT['name']} {MCP_CLIENT['version']}",
            version=MCP_PROTOCOL,
        ),
        say("mcp.stopped"),
    ):
        assert sentence in run.errors, f"missing: {sentence}\n{run.transcript()}"
    check_the_state_tool(scene, tool_document(answers[2]), newest)
    check_the_requirements_tool(scene, tool_document(answers[3]))
    versions = scene.document("/user-modeling/snapshots/current")["snapshot"]["twin_versions"]
    twins = tool_document(answers[4])["twins"]
    assert [(twin["number"], twin["twin_id"], twin["name"]) for twin in twins] == [
        (number, version["twin_id"], " ".join(version["profile"]["name"].split()))
        for number, version in enumerate(versions, start=1)
    ]


def check_the_state_tool(scene: Scene, state: Mapping[str, object], newest: str) -> None:
    local = read_json(scene.knowledge / "state" / "state.json")
    link = read_json(scene.local / "project.json")
    assert state["project"] == {
        "id": scene.project_id,
        "name": PROJECT_NAME,
        "mode": link["mode"],
        "language": link["language"],
        "studio": scene.origin,
    }
    assert state["folder"] == {
        "schema_version": SCHEMA_VERSION,
        "version_number": ALIGNED_FOLDER,
        "approved_stages": list(STAGES),
        "pending_stage": None,
        "complete": True,
    }
    assert (state["reference"], state["aligned"]) == (local["reference"], local["aligned"])
    assert state["aligned"]["commit"] == newest
    assert (state["pending_changes"], state["open_tasks"]) == ([], [])
    assert state["next"] == say("mcp.next_aligned", commit=newest[:7])


def check_the_requirements_tool(scene: Scene, requirements: Mapping[str, object]) -> None:
    current = scene.document("/requirements/current")
    specification = current["specification"]
    codes = {item["id"]: item["code"] for item in specification["requirements"]}
    assert requirements["version_number"] == current["version_number"]
    assert requirements["requirements"] == [
        {key: item[key] for key in ("code", "title", "statement", "kind", "priority")}
        for item in specification["requirements"]
    ]
    assert [(item["code"], item["requirement_codes"]) for item in requirements["user_stories"]] == [
        (item["code"], [codes[identifier] for identifier in item["requirement_ids"]])
        for item in specification["user_stories"]
    ]
    assert [
        (item["code"], item["statement"], item["requirement_codes"])
        for item in requirements["acceptance_criteria"]
    ] == [
        (
            item["code"],
            item["statement"],
            [codes[identifier] for identifier in item["requirement_ids"]],
        )
        for item in specification["acceptance_criteria"]
    ]


def local_twins(scene: Scene) -> int:
    document = read_json(scene.knowledge / "twins" / "twins.json")
    return len(document["snapshot"]["twin_versions"])


def review_operations(twins: int, commits: int) -> list[str]:
    return ([REVIEW_OPERATION] * twins + [ALIGNMENT_OPERATION]) * commits


def app_source(line: str) -> str:
    lines = list(APP_LINES)
    lines[3] = line
    return "\n".join(lines) + "\n"


def commit_line(commit: str, moment: datetime, message: str, files: int) -> str:
    return say(
        "align.commit_line",
        commit=commit[:7],
        date=moment.strftime("%Y-%m-%d %H:%M"),
        line=message,
        files=files,
    )


def reference_sentence(reference: Mapping[str, Mapping[str, object]]) -> str:
    return say(
        "align.reference",
        requirements=reference["requirements"]["version_number"],
        design=reference["design"]["version_number"],
        alternative=reference["design"]["alternative_code"],
    )


def watch_introduction(scene: Scene, recorded: str) -> tuple[str, ...]:
    return (
        say("watch.heading", name=PROJECT_NAME),
        say("watch.folder", path=str(scene.project)),
        say("watch.branch", branch=GIT_BRANCH),
        say("watch.not_aligned", commit=recorded[:7]),
        say("watch.twins_off"),
    )


def assert_change(
    item: Mapping[str, object],
    expected: tuple[str, str | None, datetime, str],
    files: set[tuple[str, str, int, int]],
) -> None:
    commit, parent, moment, message = expected
    assert tuple(item) == CHANGE_KEYS, list(item)
    assert (item["commit"], item["parent"], item["author"], item["message"]) == (
        commit,
        parent,
        GIT_NAME,
        message,
    )
    assert item["committed_at"].endswith("+00:00"), item["committed_at"]
    assert datetime.fromisoformat(item["committed_at"]) == moment
    assert datetime.fromisoformat(item["recorded_at"]).tzinfo is not None
    listed = [
        (entry["path"], entry["kind"], entry["added"], entry["removed"]) for entry in item["files"]
    ]
    assert (len(listed), set(listed)) == (len(files), files), listed
    assert (item["review"], item["decision"]) == (None, None)


def assert_no_run(scene: Scene, commits: Sequence[str]) -> None:
    for commit in commits:
        assert scene.document(f"/code-changes/{commit}/reviews") == {"items": []}, commit


def tool_call(identifier: int, name: str) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


def tool_document(answer: Mapping[str, object]) -> Mapping[str, object]:
    result = answer["result"]
    assert result["isError"] is False, result
    document = result["structuredContent"]
    assert [item["type"] for item in result["content"]] == ["text"], result
    assert json.loads(result["content"][0]["text"]) == document
    return document


def json_lines(output: str) -> list[Mapping[str, object]]:
    answers: list[Mapping[str, object]] = []
    for line in output.splitlines():
        try:
            answers.append(json.loads(line))
        except ValueError:
            raise AssertionError(f"stdout holds a line that is not JSON: {line!r}") from None
    return answers
