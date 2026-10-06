from __future__ import annotations

import html
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

from orchestwin.cli.browser import BrowserProgram
from src.test.python.integration.cli_journey_support import (
    DATABASE_VARIABLE,
    KNOWLEDGE,
    PROJECT_NAME,
    RENEWAL_PATH,
    TEST_EMAIL,
    TEST_PASSWORD,
    Journey,
    Run,
    Scene,
    StudioApi,
    StudioProcess,
    date_text,
    git_available,
    insert_test_plan,
    installed_browsers,
    journey_scene,
    read_json,
    say,
    stay_on_the_studio,
    table_rows,
    utc_now,
    write_json,
)
from src.test.python.integration.test_postgresql_cli_verify import (
    MCP_TOOLS,
    approve_the_design,
    json_lines,
    local_twins,
    tool_document,
)

pytestmark = [pytest.mark.integration, pytest.mark.browser]

SKIP_VARIABLE = "ORCHESTWIN_SKIP_BROWSER_TESTS"
HOME_FOLDER = "home"
APP_FOLDER = "app"
INDEX_PAGE = "index.html"
PAGE_TITLE = "Split the bill"
PAGE_HEADING = "Split the bill among friends"
FIELD_LABEL = "Total of the bill"
BUTTON_LABEL = "Show each share"
SHARE_SCRIPT = (
    'document.getElementById("split").addEventListener("click", () => {',
    '  const total = Number(document.getElementById("total").value);',
    "  const share = (total / 4).toFixed(2);",
    '  document.getElementById("share").textContent = `Each of 4 friends pays ${share} EUR`;',
    "});",
)
CHECK_WORDS = 3
PLAN_LOCALE = "en-US"
STATIC = "STATIC"
APPLICATION: Mapping[str, str] = {"kind": STATIC, "address": APP_FOLDER}
ALL_BROWSERS = "all"
FIRST_RUN_FOLDER = 6
SECOND_RUN_FOLDER = 7
NO_TEST_MODEL = "TEST_MODEL_NOT_CONFIGURED"
PASSING_PATH = "TP-001"
FAILING_PATH = "TP-002"
TESTS_FOLDER = "tests"
PLAN_FILE = "plan.json"
SETTINGS_FILE = "test.json"
LATEST_FILE = "latest.json"
RUN_FILE = "run.json"
REPORT_FILE = "report.html"
FOLDER_FORMAT = "%Y%m%d-%H%M%S"
RUN_FOLDER = re.compile(r"\d{8}-\d{6}(?:-\d+)?")
SERVED_ADDRESS = r"http://127\.0\.0\.1:\d+/"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TABLE_COLUMNS = 4
RUN_KEYS = (
    "id",
    "started_at",
    "finished_at",
    "recorded_at",
    "application",
    "browsers",
    "reference",
    "summary",
    "criteria",
    "not_covered",
    "results",
    "critiques",
    "reviewed_at",
    "cost_microusd",
)
SUMMARY: Mapping[str, int] = {
    "passed": 1,
    "failed": 1,
    "blocked": 0,
    "not_covered": 0,
    "not_run": 0,
}
TESTS_PATH = "twins/feedback/tests.json"
TESTS_DOCUMENT = tuple(TESTS_PATH.split("/"))
TESTS_KIND = "orchestwin.test-reviews"
TESTS_SECTION = "## Acceptance tests"
SCHEMA_VERSION = 3
MCP_PROTOCOL = "2025-06-18"
MCP_CLIENT = {"name": "journey", "version": "1"}
GET_TEST_RESULTS = "get_test_results"
RUN_TESTS = "run_tests"
GET_TASKS = "get_tasks"
SPEND_REQUIRED = "SPEND_REQUIRED"


@dataclass
class Acceptance:
    machine: Mapping[str, str]
    browser: BrowserProgram
    database_url: str
    statement: str = ""
    passing: str = ""
    failing: str = ""
    present: str = ""
    absent: str = ""
    plan: dict[str, object] = field(default_factory=dict)
    runs: list[str] = field(default_factory=list)


def test_ut_test_verifies_the_criteria_with_the_real_studio(tmp_path: Path) -> None:
    if not git_available():
        pytest.skip("the journey starts from the alignment scene, which needs the git program")
    machine = dict(os.environ)
    if machine.get(SKIP_VARIABLE) == "1":
        pytest.skip(f"{SKIP_VARIABLE} is 1")
    browsers = installed_browsers(machine, tmp_path / HOME_FOLDER)
    if not browsers:
        pytest.skip("no browser that ut test can drive is installed on this machine")
    database_url = os.environ.get(DATABASE_VARIABLE, "")
    assert database_url, "the integration fixture gives this test a database schema of its own"
    journey = Journey()
    with StudioProcess(tmp_path / "studio", database_url) as studio:
        api = StudioApi(studio.origin)
        registered = api.register(TEST_EMAIL, TEST_PASSWORD)
        assert registered.status == 201, f"registration answered {registered.status}"
        scene = journey_scene(tmp_path, studio.origin, studio.port, api)
        with journey.step("0 ut login, ut init and ut design approve the five steps"):
            approve_the_design(scene)
        if not journey.problems:
            walk(scene, journey, Acceptance(machine, browsers[0], studio.database_url))
    if journey.problems:
        pytest.fail(f"{journey.report()}\n\n{studio.diagnostics()}", pytrace=False)


def walk(scene: Scene, journey: Journey, acceptance: Acceptance) -> None:
    with journey.step("1 a static application in app/ written from the approved criteria"):
        write_the_application(scene, acceptance)
    with journey.step("2 ut test --static app without a saved plan stops before any spending"):
        refuse_without_a_plan(scene, acceptance)
    with journey.step("3 a plan stored in the Studio and saved in .orchestwin/tests/plan.json"):
        save_the_plan(scene, acceptance)
    with journey.step("4 ut test --no-review runs the plan in the first browser and records it"):
        run_without_a_review(scene, acceptance)
    with journey.step("5 ut test records the run, cannot review it and publishes the folder"):
        run_with_a_review(scene, acceptance)
    with journey.step("6 ut status, --json and --offline show the latest run"):
        show_the_tests(scene, acceptance)
    with journey.step("7 ut mcp answers get_test_results and refuses run_tests without --spend"):
        serve_the_results(scene, acceptance)
    with journey.step("every request stayed on the Studio of the test"):
        stay_on_the_studio(scene)


def write_the_application(scene: Scene, acceptance: Acceptance) -> None:
    specification = scene.document("/requirements/current")["specification"]
    criteria = specification["acceptance_criteria"]
    assert len(criteria) >= 2, criteria
    first, second = criteria[:2]
    local = read_json(scene.knowledge / "requirements" / "requirements.json")
    statements = {
        item["code"]: item["statement"] for item in local["specification"]["acceptance_criteria"]
    }
    assert statements == {item["code"]: item["statement"] for item in criteria}
    acceptance.statement = first["statement"]
    acceptance.passing, acceptance.failing = first["code"], second["code"]
    acceptance.present = " ".join(first["statement"].split()[:CHECK_WORDS])
    acceptance.absent = requirement_words(second["statement"])
    page = application_page(first["statement"])
    target = scene.project / APP_FOLDER / INDEX_PAGE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(page.encode("utf-8"))
    assert acceptance.present.casefold() in page.casefold(), page
    assert acceptance.absent.casefold() not in page.casefold(), page


def refuse_without_a_plan(scene: Scene, acceptance: Acceptance) -> None:
    run = scene.ut_on_machine("test", "--static", APP_FOLDER, machine=acceptance.machine)
    assert run.status == 1, run.transcript()
    assert run.output == "", run.transcript()
    assert say(f"test.errors.{NO_TEST_MODEL}") in run.errors, run.transcript()
    assert requests_of(run) == [f"GET {scene.base}/acceptance-tests -> 200"], run.transcript()
    overview = scene.document("/acceptance-tests")
    assert (
        overview["plan_available"],
        overview["plans"],
        overview["runs"],
        overview["latest_run"],
    ) == (False, 0, 0, None)
    assert scene.document("/test-plans") == {"items": []}
    assert scene.document("/test-runs") == {"items": []}
    assert read_json(scene.local / SETTINGS_FILE) == {
        "schema_version": 1,
        "application": dict(APPLICATION),
        "browser": ALL_BROWSERS,
    }
    assert not (scene.local / TESTS_FOLDER).exists(), run.transcript()
    body = {
        "locale": PLAN_LOCALE,
        "application": dict(APPLICATION),
        "snapshot": {"url": "http://127.0.0.1/", "title": PAGE_TITLE, "text": "", "elements": []},
    }
    direct = scene.api.request("POST", f"{scene.base}/test-plans", body)
    assert (direct.status, direct.code) == (503, NO_TEST_MODEL)
    assert scene.document("/test-plans") == {"items": []}


def save_the_plan(scene: Scene, acceptance: Acceptance) -> None:
    stages = read_json(scene.knowledge / "orchestwin.json")["stages"]
    reference = scene.document("/acceptance-tests")["reference"]
    versions = (stages["requirements"]["version_number"], stages["design"]["version_number"])
    assert versions == (
        reference["requirements"]["version_number"],
        reference["design"]["version_number"],
    )
    plan: dict[str, object] = {
        "id": str(uuid4()),
        "created_at": utc_now().replace(microsecond=0).isoformat(),
        "locale": PLAN_LOCALE,
        "reference": {
            "requirements_version_number": versions[0],
            "design_version_number": versions[1],
            "alternative_code": reference["design"]["alternative_code"],
        },
        "application": dict(APPLICATION),
        "criteria": [acceptance.passing, acceptance.failing],
        "replan_of": [],
        "paths": [
            plan_path(PASSING_PATH, acceptance.passing, acceptance.present),
            plan_path(FAILING_PATH, acceptance.failing, acceptance.absent),
        ],
        "not_covered": [],
        "cost_microusd": 0,
    }
    insert_test_plan(scene, plan, database_url=acceptance.database_url)
    acceptance.plan = plan
    write_json(
        scene.local / TESTS_FOLDER / PLAN_FILE,
        {
            "schema_version": 1,
            "saved_at": plan["created_at"],
            "application": dict(APPLICATION),
            "plan": plan,
            "replans": [],
        },
    )
    assert scene.document(f"/test-plans/{plan['id']}") == plan
    assert scene.document("/test-plans") == {"items": [plan]}
    overview = scene.document("/acceptance-tests")
    assert (overview["plans"], overview["runs"], overview["latest_run"]) == (1, 0, None)


def run_without_a_review(scene: Scene, acceptance: Acceptance) -> None:
    name = acceptance.browser.name
    run = scene.ut_on_machine(
        "test",
        "--static",
        APP_FOLDER,
        "--no-review",
        "--browser",
        name,
        machine=acceptance.machine,
    )
    assert run.status == 1, run.transcript()
    items = scene.document("/test-runs")["items"]
    assert len(items) == 1, run.transcript()
    recorded = items[0]
    acceptance.runs.insert(0, recorded["id"])
    assert_recorded_run(scene, acceptance, recorded)
    folder = assert_run_files(scene, recorded)
    assert_run_output(scene, acceptance, run, recorded, folder, FIRST_RUN_FOLDER)
    assert not run.shows(say("test.review_unavailable")), run.transcript()
    assert [exchange.line() for exchange in run.writes()] == [
        f"POST {scene.base}/test-runs -> 201",
        f"POST {scene.base}/knowledge-packages -> 201",
    ], run.transcript()
    assert read_json(scene.local / SETTINGS_FILE) == {
        "schema_version": 1,
        "application": dict(APPLICATION),
        "browser": name,
    }
    assert scene.folder_numbers() == list(range(FIRST_RUN_FOLDER, 0, -1))


def run_with_a_review(scene: Scene, acceptance: Acceptance) -> None:
    run = scene.ut_on_machine("test", "--static", APP_FOLDER, machine=acceptance.machine)
    assert run.status == 1, run.transcript()
    items = scene.document("/test-runs")["items"]
    assert [item["id"] for item in items[1:]] == acceptance.runs, run.transcript()
    recorded = items[0]
    acceptance.runs.insert(0, recorded["id"])
    assert_recorded_run(scene, acceptance, recorded)
    folder = assert_run_files(scene, recorded)
    assert_run_output(scene, acceptance, run, recorded, folder, SECOND_RUN_FOLDER)
    gaps = run.order_gaps(
        say("test.report_written", path=str(folder / REPORT_FILE)),
        say("test.review_unavailable"),
        say("test.folder_updated", version=SECOND_RUN_FOLDER),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    reviewing = say("test.reviewing", twins=local_twins(scene))
    assert not run.shows(reviewing), run.transcript()
    assert [exchange.line() for exchange in run.writes()] == [
        f"POST {scene.base}/test-runs -> 201",
        f"POST {scene.base}/knowledge-packages -> 201",
    ], run.transcript()
    review = scene.api.request(
        "POST",
        f"{scene.base}/test-runs/{recorded['id']}/reviews",
        {"locale": PLAN_LOCALE, "again": False},
    )
    assert (review.status, review.code) == (503, NO_TEST_MODEL)
    assert scene.document(f"/test-runs/{recorded['id']}/reviews") == {"items": []}
    assert_published_folder(scene, items)


def show_the_tests(scene: Scene, acceptance: Acceptance) -> None:
    latest = scene.document(f"/test-runs/{acceptance.runs[0]}")
    line = say(
        "status.tests",
        date=date_text(latest["finished_at"]),
        passed=SUMMARY["passed"],
        failed=SUMMARY["failed"],
        blocked=SUMMARY["blocked"],
        not_covered=SUMMARY["not_covered"],
    )
    status = scene.ut("status")
    assert status.status == 0, status.transcript()
    assert status.shows(line), f"missing: {line}\n{status.transcript()}"
    overview = [exchange.line() for exchange in status.requests("GET", "/acceptance-tests")]
    assert overview == [f"GET {scene.base}/acceptance-tests -> 200"], status.transcript()
    as_json = scene.ut("status", "--json")
    assert as_json.status == 0, as_json.transcript()
    document = json.loads(as_json.output)
    assert list(document)[-4:] == [
        "tests",
        "learning",
        "sections",
        "knowledge_alignment",
    ], as_json.transcript()
    assert document["tests"] == {
        "runs": len(acceptance.runs),
        "latest": {
            "id": latest["id"],
            "finished_at": latest["finished_at"],
            "summary": dict(SUMMARY),
        },
    }, as_json.transcript()
    offline = scene.ut("status", "--offline")
    assert offline.status == 0, offline.transcript()
    assert offline.exchanges == (), offline.transcript()
    for sentence in (say("status.offline_requested"), line):
        assert offline.shows(sentence), f"missing: {sentence}\n{offline.transcript()}"


def serve_the_results(scene: Scene, acceptance: Acceptance) -> None:
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
        tool_message(3, GET_TEST_RESULTS, {"limit": 1}),
        tool_message(4, RUN_TESTS, {}),
    ]
    run = scene.ut("mcp", answers=[json.dumps(message) for message in messages])
    assert run.status == 0, run.transcript()
    assert run.exchanges == (), run.transcript()
    answers = json_lines(run.output)
    assert [answer.get("id") for answer in answers] == [1, 2, 3, 4], run.transcript()
    answered = all(answer.get("jsonrpc") == "2.0" and "result" in answer for answer in answers)
    assert answered, run.transcript()
    names = [tool["name"] for tool in answers[1]["result"]["tools"]]
    assert len(names) == 15, names
    assert names == list(MCP_TOOLS), names
    assert names[8:13] == [GET_TEST_RESULTS, RUN_TESTS, GET_TASKS, "get_evidence", "get_why"], names
    assert names[13:] == ["get_validation", "get_scenario_walkthrough"], names
    document = read_json(scene.knowledge.joinpath(*TESTS_DOCUMENT))
    assert tool_document(answers[2]) == {"runs": document["runs"][:1]}
    assert document["runs"][0]["id"] == acceptance.runs[0]
    refused = answers[3]["result"]
    message = f"{say(f'mcp.errors.{SPEND_REQUIRED}', tool=RUN_TESTS)} ({SPEND_REQUIRED})"
    assert refused["isError"] is True, refused
    assert refused["structuredContent"] == {
        "code": SPEND_REQUIRED,
        "message": message,
        "tool": RUN_TESTS,
    }
    assert refused["content"] == [{"type": "text", "text": message}], refused
    listed = [item["id"] for item in scene.document("/test-runs")["items"]]
    assert listed == acceptance.runs


def assert_recorded_run(scene: Scene, acceptance: Acceptance, recorded: Mapping) -> None:
    name = acceptance.browser.name
    plan = acceptance.plan
    assert tuple(recorded) == RUN_KEYS, list(recorded)
    assert (recorded["application"], recorded["reference"], recorded["not_covered"]) == (
        dict(APPLICATION),
        plan["reference"],
        [],
    )
    assert [browser["name"] for browser in recorded["browsers"]] == [name]
    assert recorded["browsers"][0]["version"], recorded["browsers"]
    assert recorded["criteria"] == [
        {"code": acceptance.passing, "status": "PASSED", "paths": [PASSING_PATH]},
        {"code": acceptance.failing, "status": "FAILED", "paths": [FAILING_PATH]},
    ]
    assert recorded["summary"] == dict(SUMMARY)
    assert (recorded["critiques"], recorded["reviewed_at"], recorded["cost_microusd"]) == (
        [],
        None,
        0,
    )
    started, finished, stored = (
        datetime.fromisoformat(recorded[key])
        for key in ("started_at", "finished_at", "recorded_at")
    )
    assert started <= finished <= stored, recorded
    results = recorded["results"]
    assert [(item["path"], item["browser"], item["status"]) for item in results] == [
        (plan["paths"][0], name, "PASSED"),
        (plan["paths"][1], name, "FAILED"),
    ]
    for item in results:
        code = item["path"]["code"]
        steps = item["steps"]
        assert [step["index"] for step in steps] == [1, 2], item
        assert [step["screenshot"] for step in steps] == [
            f"{code}/{name}/01.png",
            f"{code}/{name}/02.png",
        ]
        assert all(step["title"] == PAGE_TITLE for step in steps), steps
        assert all(re.fullmatch(SERVED_ADDRESS, step["url"]) for step in steps), steps
        assert isinstance(item["seconds"], float), item
        assert acceptance.statement in item["page_text"], item["page_text"]
    assert [(step["status"], step["detail"]) for step in results[0]["steps"]] == [
        ("DONE", None),
        ("DONE", None),
    ]
    assert [(step["status"], step["detail"]) for step in results[1]["steps"]] == [
        ("DONE", None),
        ("FAILED", failed_detail(acceptance)),
    ]
    assert scene.document(f"/test-runs/{recorded['id']}") == recorded


def assert_run_files(scene: Scene, recorded: Mapping) -> Path:
    tests = scene.local / TESTS_FOLDER
    latest = read_json(tests / LATEST_FILE)
    folder = tests / latest["folder"]
    assert latest == {
        "schema_version": 1,
        "run_id": recorded["id"],
        "folder": folder.name,
        "report": f"{folder.name}/{REPORT_FILE}",
        "finished_at": recorded["finished_at"],
    }
    assert RUN_FOLDER.fullmatch(folder.name), folder.name
    started = datetime.fromisoformat(recorded["started_at"]).strftime(FOLDER_FORMAT)
    assert folder.name.startswith(started), (folder.name, started)
    assert read_json(folder / RUN_FILE) == recorded
    report = (folder / REPORT_FILE).read_text(encoding="utf-8")
    assert "<script" not in report.lower()
    assert html.escape(say("test.report_title", name=PROJECT_NAME), quote=True) in report
    for item in recorded["results"]:
        for step in item["steps"]:
            image = folder.joinpath(*step["screenshot"].split("/"))
            assert image.read_bytes().startswith(PNG_SIGNATURE), image
            assert f'src="{step["screenshot"]}"' in report, step["screenshot"]
    return folder


def assert_run_output(
    scene: Scene,
    acceptance: Acceptance,
    run: Run,
    recorded: Mapping,
    folder: Path,
    version: int,
) -> None:
    label = acceptance.browser.label
    plan = acceptance.plan
    shown = recorded["browsers"][0]["version"]
    failed = failed_detail(acceptance)
    gaps = run.order_gaps(
        say("test.heading", name=PROJECT_NAME),
        say("test.browsers", browsers=f"{label} {shown}"),
        say("test.plan_reused", date=date_text(plan["created_at"]), paths=2, not_covered=0),
        progress_line(label, plan["paths"][0]),
        progress_line(label, plan["paths"][1]),
        say("test.path_failed", code=FAILING_PATH, browser=label, step=2, detail=failed),
        say("test.summary", **SUMMARY),
        say("test.report_written", path=str(folder / REPORT_FILE)),
        say("test.folder_updated", version=version),
        say("test.failed_summary"),
    )
    assert gaps == [], "\n".join([*gaps, run.transcript()])
    application = re.escape(
        say("test.application_static", folder=APP_FOLDER, address="ADDRESS")
    ).replace("ADDRESS", SERVED_ADDRESS)
    assert re.search(application, run.output), run.transcript()
    rows = [row for row in table_rows(run.output) if len(row) == TABLE_COLUMNS]
    assert rows == [
        [acceptance.passing, say("test.status_passed"), PASSING_PATH, label],
        [acceptance.failing, say("test.status_failed"), FAILING_PATH, label],
    ], run.transcript()
    assert run.errors == "", run.transcript()
    assert scene.folder_numbers()[0] == version


def assert_published_folder(scene: Scene, items: list[Mapping]) -> None:
    assert scene.folder_numbers() == list(range(SECOND_RUN_FOLDER, 0, -1))
    latest = scene.folders()[0]
    assert latest["feedback"]["test_runs"] == len(items), latest["feedback"]
    manifest = read_json(scene.knowledge / "orchestwin.json")
    assert (manifest["schema_version"], manifest["package"]["version_number"]) == (
        SCHEMA_VERSION,
        SECOND_RUN_FOLDER,
    )
    assert (manifest["feedback"]["tests"], manifest["feedback"]["test_runs"]) == (
        TESTS_PATH,
        len(items),
    )
    document = read_json(scene.knowledge.joinpath(*TESTS_DOCUMENT))
    assert (document["schema_version"], document["kind"], document["project_id"]) == (
        SCHEMA_VERSION,
        TESTS_KIND,
        scene.project_id,
    )
    assert document["runs"] == items
    assert [(run["critiques"], run["reviewed_at"]) for run in document["runs"]] == [
        ([], None)
    ] * len(items)
    index = (scene.knowledge / "ORCHESTWIN.md").read_text(encoding="utf-8")
    assert TESTS_SECTION in index.splitlines(), index
    verify = scene.ut("package", "verify")
    assert verify.status == 0, verify.transcript()
    assert verify.exchanges == (), verify.transcript()
    verified = say(
        "package.verified",
        path=f"{KNOWLEDGE}/",
        version=SECOND_RUN_FOLDER,
        project=PROJECT_NAME,
        files=latest["file_count"],
        hash=latest["content_hash"][:12],
    )
    assert verified in verify.output, verify.transcript()


def application_page(statement: str) -> str:
    lines = (
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{PAGE_TITLE}</title>",
        "</head>",
        "<body>",
        f"<h1>{PAGE_HEADING}</h1>",
        f"<p>{html.escape(statement)}</p>",
        f'<label for="total">{FIELD_LABEL}</label>',
        '<input id="total" name="total" type="number" min="0" step="0.01">',
        f'<button type="button" id="split">{BUTTON_LABEL}</button>',
        '<p role="status" id="share"></p>',
        "<script>",
        *SHARE_SCRIPT,
        "</script>",
        "</body>",
        "</html>",
    )
    return "\n".join(lines) + "\n"


def requirement_words(statement: str) -> str:
    return " ".join(statement.split(":", 1)[-1].split())


def plan_path(code: str, criterion: str, text: str) -> dict[str, object]:
    return {
        "code": code,
        "heading": f'The page shows "{text}"',
        "criteria": [criterion],
        "steps": [
            {"action": "OPEN", "target": None, "value": "/", "expect": None},
            {
                "action": "CHECK",
                "target": None,
                "value": None,
                "expect": {"kind": "TEXT_VISIBLE", "target": None, "text": text},
            },
        ],
    }


def failed_detail(acceptance: Acceptance) -> str:
    return say("test.detail_expectation_failed", expectation=f"TEXT_VISIBLE: {acceptance.absent}")


def progress_line(label: str, path: Mapping) -> str:
    heading = path["heading"].rstrip(". ")
    return say(
        "common.progress_started",
        label=say("test.path_label", code=path["code"], browser=label, heading=heading),
    )


def requests_of(run: Run) -> list[str]:
    return [exchange.line() for exchange in run.exchanges if exchange.path != RENEWAL_PATH]


def tool_message(identifier: int, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": identifier,
        "method": "tools/call",
        "params": {"name": name, "arguments": dict(arguments)},
    }
