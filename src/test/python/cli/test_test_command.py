from __future__ import annotations

import html
import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli import messages
from orchestwin.cli.browser import BrowserProgram
from orchestwin.cli.flows import test_run as run_flow
from orchestwin.cli.http import UrlTransport

from .support.browsers import FAKE_PNG
from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.terminal import TEST_PASSWORD, Run, command_context, link_folder, run_ut, terminal
from .support.transports import NoNetwork
from .test_test_run_flow import FakeSite

EMAIL = "owner@example.com"
NAME = "Calcolo mancia"
ADDRESS = "http://127.0.0.1:5173/"
TEXTS = {
    "en": (
        "Tip calculator With 30 euros and 15 percent the tip is 4.50 euros. The list of "
        "percentages shows 5, 10 and 15. With 3 people each share is a third of the total. The "
        "result appears within one second."
    ),
    "it": (
        "Calcolo mancia Con 30 euro e il 15 per cento la mancia è di 4,50 euro. L'elenco delle "
        "percentuali mostra 5, 10 e 15. Con 3 persone ogni quota è un terzo del totale. Il "
        "risultato compare entro un secondo."
    ),
}
LAST_SENTENCES = {
    "en": "The result appears within one second.",
    "it": "Il risultato compare entro un secondo.",
}
HIDDEN = {"en": "Result Total Each person pays", "it": "Risultato Totale A testa"}
SNAPSHOT_KEYS = ["url", "title", "text", "hidden_text", "elements"]
FOLDER_VERSIONS = (2, 4)
FIRST_SENTENCES = {
    "en": "With 30 euros and 15 percent the tip is 4.50 euros.",
    "it": "Con 30 euro e il 15 per cento la mancia è di 4,50 euro.",
}
EXAMPLES = {
    "en": "Example: with 30 euros and 15 percent the tip is 4.50 euros.",
    "it": "Esempio: con 30 euro e il 15 per cento la mancia è di 4,50 euro.",
}
WEAK_CRITERION = (
    "{code} passed only through expectations that prove little: confirm by hand, with the "
    "report, that the application does what the criterion asks."
)
VISIBLE_SENTENCE = (
    'TP-00{number}, step 2: the page shows "{text}" as soon as it opens, so this expectation '
    "holds before anything is done."
)
TOTALS = {"en": "Total", "it": "Totale"}


@dataclass(frozen=True, slots=True)
class Session:
    studio: FakeStudio
    project: FakeProject
    tmp_path: Path
    site: FakeSite
    programs: dict[str, BrowserProgram]

    @property
    def root(self) -> Path:
        return self.tmp_path / "project"

    @property
    def tests(self) -> Path:
        return self.root / ".orchestwin" / "tests"

    def ut(self, *arguments: str, answers: Sequence[str] = (), language: str = "en") -> Run:
        return run_ut(
            ["--lang", language, *arguments],
            self.tmp_path,
            transport=UrlTransport(),
            answers=answers,
        )

    def plan_document(self) -> dict[str, object]:
        return json.loads((self.tests / "plan.json").read_text(encoding="utf-8"))

    def fit_plan(self) -> None:
        document = self.plan_document()
        requirements, design = FOLDER_VERSIONS
        document["plan"]["reference"]["requirements_version_number"] = requirements
        document["plan"]["reference"]["design_version_number"] = design
        (self.tests / "plan.json").write_text(json.dumps(document), encoding="utf-8")

    def latest(self) -> dict[str, object]:
        return json.loads((self.tests / "latest.json").read_text(encoding="utf-8"))

    def run_folder(self) -> Path:
        return self.tests / str(self.latest()["folder"])

    def local_run(self) -> dict[str, object]:
        return json.loads((self.run_folder() / "run.json").read_text(encoding="utf-8"))

    def requests(self, method: str, suffix: str) -> list[RecordedRequest]:
        return [
            item
            for item in self.studio.requests
            if item.method == method and item.path.endswith(suffix)
        ]

    def local_tests(self) -> dict[str, object]:
        path = self.root / "orchestwin" / "twins" / "feedback" / "tests.json"
        return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    hosted: bool = True,
    language: str = "en",
    twins: int = 2,
    browsers: Sequence[str] = ("chrome", "firefox"),
    text: str | None = None,
    publish: bool = True,
    fetch: bool = False,
    hidden: str | None = None,
    later: str = "",
) -> Iterator[Session]:
    with FakeStudio(language=language, hosted=hosted, twins=twins) as studio:
        studio.add_account(EMAIL, TEST_PASSWORD)
        project = studio.seed_project(owner=EMAIL, name=NAME, through="design")
        login = run_ut(
            ["login", "--studio", studio.address, "--email", EMAIL, "--password-stdin"],
            tmp_path,
            transport=UrlTransport(),
            answers=[TEST_PASSWORD],
        )
        assert login.status == 0, login.errors
        link_folder(tmp_path / "project", project_id=project.id, name=NAME, studio=studio.address)
        if publish:
            published = run_ut(["package", "publish"], tmp_path, transport=UrlTransport())
            assert published.status == 0, published.errors
        site = FakeSite(
            title="Tip calculator",
            text=TEXTS[language] if text is None else text,
            fetch=fetch,
            hidden_text=HIDDEN[language] if hidden is None else hidden,
            later=later,
        )
        programs = site.programs(tmp_path / "programs", ("chrome", "firefox"))
        available = tuple(browsers)

        def finder(
            environment: object, *, names: Sequence[str] = ("chrome", "firefox"), **_: object
        ) -> tuple:
            return tuple(programs[name] for name in names if name in available)

        monkeypatch.setattr(run_flow, "open_page", site.open_page)
        monkeypatch.setattr(run_flow, "find_browsers", finder)
        yield Session(studio, project, tmp_path, site, programs)
        assert studio.errors == []


def lines_of(run: Run) -> list[str]:
    return run.output.splitlines()


def hidden_example(language: str) -> dict[str, str]:
    first = FIRST_SENTENCES[language]
    return {
        "text": " ".join(TEXTS[language].replace(first, "").split()),
        "hidden": f"{HIDDEN[language]} {EXAMPLES[language]}",
        "later": first,
    }


def listed(lines: Sequence[str], header: int) -> list[str]:
    items: list[str] = []
    for line in lines[header + 1 :]:
        if line.startswith("- "):
            items.append(line[2:])
        elif line.startswith("  ") and items:
            items[-1] = f"{items[-1]} {line.strip()}"
        else:
            break
    return items


def checked_texts(document: dict[str, object]) -> dict[str, str]:
    plans = [document["plan"], *document["replans"]]
    return {
        path["code"]: path["steps"][1]["expect"]["text"] for plan in plans for path in plan["paths"]
    }


def test_a_first_run_plans_runs_both_browsers_records_and_is_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        run = work.ut("test", "--url", ADDRESS)
        latest = work.latest()
        stored = work.project.test_runs()
        plans = work.project.test_plans()
        reviews = work.project.test_reviews()
        tests = work.local_tests()
        plan_body = work.requests("POST", "/test-plans")[0]

    report = work.run_folder() / "report.html"
    lines = lines_of(run)
    checks = ["With 30 euros", "The list of", "With 3 people", "The result appears"]
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert lines[:10] == [
        'Acceptance tests of "Calcolo mancia"',
        "====================================",
        "Application: the address http://127.0.0.1:5173/.",
        "Browsers: Google Chrome 151.0.7922.76, Mozilla Firefox 156.0.1.",
        "The Studio now writes a test plan: the model reads the page as it opens and writes the "
        "paths for the acceptance criteria.",
        "Estimate: 0.15-0.30 USD, about 2 min. Credit left in the Studio: 60.00 USD.",
        "Test plan...",
        "Test plan: done in 9 s.",
        "New test plan: 4 paths, 0 criteria not covered.",
        "Expectations that prove little: 4.",
    ]
    assert listed(lines, 9) == [
        VISIBLE_SENTENCE.format(number=number, text=text)
        for number, text in enumerate(checks, start=1)
    ]
    cost = lines.index("Cost of the plan: 0.20 USD.")
    assert all(line.startswith(("- ", "  ")) for line in lines[10:cost])
    assert lines[cost + 1 : cost + 3] == [
        "Path TP-001 in Google Chrome: With 30 euros and 15 percent the tip is 4.50 euros...",
        "Path TP-001 in Google Chrome: With 30 euros and 15 percent the tip is 4.50 euros: done "
        "in 0 s.",
    ]
    table = lines.index("Criterion  Status  Paths   Browsers")
    assert lines[table : table + 12] == [
        "Criterion  Status  Paths   Browsers",
        "---------  ------  ------  ------------------------------",
        "AC-001     passed  TP-001  Google Chrome, Mozilla Firefox",
        "AC-002     passed  TP-002  Google Chrome, Mozilla Firefox",
        "AC-003     passed  TP-003  Google Chrome, Mozilla Firefox",
        "AC-004     passed  TP-004  Google Chrome, Mozilla Firefox",
        "Criteria: 4 passed, 0 failed, 0 blocked, 0 not covered, 0 not run.",
        *(WEAK_CRITERION.format(code=f"AC-00{number}") for number in range(1, 5)),
        f"Report with the steps and the screenshots: {report}",
    ]
    assert work.plan_document()["weak_expectations"] == [
        {"path": f"TP-00{number}", "step": 2, "kind": "VISIBLE_AT_OPENING", "text": text}
        for number, text in enumerate(checks, start=1)
    ]
    assert lines[table + 12 : table + 18] == [
        "",
        "The twins now criticize the run: 2 twins, one generation each.",
        "Estimate: 0.20-0.40 USD, about 2 min. Credit left in the Studio: 59.80 USD.",
        "Critiques of the twins...",
        "Critiques of the twins: done in 9 s.",
        "",
    ]
    assert "Pizzeria owner: the results raise a concern" in lines
    assert "Evening shift waiter: the results are fine" in lines
    assert "Cost of the critiques: 0.30 USD." in lines
    assert lines[-1] == (
        "Knowledge folder updated in orchestwin/ (version 2): orchestwin/twins/feedback/tests.json "
        "holds the runs with the critiques of the twins."
    )
    assert sum("Path TP-" in line and line.endswith("...") for line in lines) == 8
    body = json.loads(plan_body.body.decode("utf-8"))
    assert body["criteria"] is None and body["earlier"] is None
    assert body["locale"] == "en-US"
    assert body["application"] == {"kind": "URL", "address": ADDRESS}
    assert body["snapshot"]["url"] == ADDRESS
    assert body["snapshot"]["title"] == "Tip calculator"
    assert list(body["snapshot"]) == SNAPSHOT_KEYS
    assert body["snapshot"]["hidden_text"] == HIDDEN["en"]
    assert work.site.opened[0] == ("chrome", ADDRESS)
    assert len(plans) == 1
    assert len(stored) == 1 and len(reviews) == 1
    recorded = stored[0]
    assert recorded["id"] == latest["run_id"]
    assert recorded["summary"] == {
        "passed": 4,
        "failed": 0,
        "blocked": 0,
        "not_covered": 0,
        "not_run": 0,
    }
    assert [(item["path"]["code"], item["browser"]) for item in recorded["results"]] == [
        (f"TP-00{number}", browser) for number in range(1, 5) for browser in ("chrome", "firefox")
    ]
    assert recorded["browsers"] == [
        {"name": "chrome", "version": "151.0.7922.76"},
        {"name": "firefox", "version": "156.0.1"},
    ]
    assert recorded["results"][0]["steps"][1]["screenshot"] == "TP-001/chrome/02.png"
    assert len(recorded["critiques"]) == 2
    assert [item["id"] for item in tests["runs"]] == [recorded["id"]]
    assert tests["runs"][0]["critiques"] == recorded["critiques"]
    local = work.local_run()
    assert local["id"] == recorded["id"]
    assert local["critiques"] == recorded["critiques"]
    assert "first_attempt" not in local
    assert (work.run_folder() / "TP-004" / "firefox" / "02.png").read_bytes() == FAKE_PNG
    page = report.read_text(encoding="utf-8")
    assert "<script" not in page.lower()
    assert "Pizzeria owner" in page
    assert page.count('<span class="chip weak">proves little</span>') == 8
    assert '<p class="weak">Expectations that prove little: 4. Each one is marked' in page
    assert work.plan_document()["plan"]["id"] == plans[0]["id"]
    settings = json.loads((work.root / ".orchestwin" / "test.json").read_text(encoding="utf-8"))
    assert settings == {
        "schema_version": 1,
        "application": {"kind": "URL", "address": ADDRESS},
        "browser": "all",
    }
    assert work.site.starts[0] == ("chrome", "en-US", True)
    assert all(direct for _, _, direct in work.site.starts)
    assert all(page_item.closed for page_item in work.site.pages)


def test_a_saved_plan_that_fits_the_folder_is_reused_without_spending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        first = work.ut("test", "--url", ADDRESS, "--no-review")
        opened = work.site.opens["chrome"]
        work.fit_plan()
        second = work.ut("test", "--no-review")
        plans = work.project.test_plans()
        runs = work.project.test_runs()
        planned = work.requests("POST", "/test-plans")
        reopened = work.site.opens["chrome"] - opened

    assert (first.status, second.status) == (0, 0)
    assert len(planned) == len(plans) == 1
    assert len(runs) == 2
    lines = lines_of(second)
    assert lines[2:5] == [
        "Application: the address http://127.0.0.1:5173/.",
        "Browsers: Google Chrome 151.0.7922.76, Mozilla Firefox 156.0.1.",
        "Test plan reused, written on 2026-09-29 08:00 UTC: 4 paths, 0 criteria not covered.",
    ]
    assert not any("Estimate" in line for line in lines)
    assert not any("twins" in line and "criticize" in line for line in lines)
    assert (opened, reopened) == (5, 4)


def test_a_plan_written_for_other_versions_is_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.ut("test", "--url", ADDRESS, "--no-review")
        again = work.ut("test", "--no-review")
        forced = work.ut("test", "--no-review", "--plan", "new")
        planned = len(work.requests("POST", "/test-plans"))

    assert (again.status, forced.status) == (0, 0)
    assert (
        "The saved test plan was written for requirements version 1 and design version 2; the "
        "knowledge folder has requirements version 2 and design version 4: a new plan is needed."
        in lines_of(again)
    )
    assert not any("saved test plan" in line for line in lines_of(forced))
    assert planned == 3


def test_the_criteria_keep_only_their_paths_and_unknown_codes_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.ut("test", "--url", ADDRESS, "--no-review")
        work.fit_plan()
        chosen = work.ut(
            "test", "--criteria", "ac-003, AC-001", "--no-review", "--browser", "chrome"
        )
        unknown = work.ut("test", "--criteria", "AC-001,AC-999,XYZ", "--no-review")
        recorded = work.project.test_runs()[0]
        runs = len(work.project.test_runs())

    assert chosen.status == 0, chosen.errors
    assert [(item["path"]["code"], item["browser"]) for item in recorded["results"]] == [
        ("TP-001", "chrome"),
        ("TP-003", "chrome"),
    ]
    assert [(item["code"], item["status"]) for item in recorded["criteria"]] == [
        ("AC-001", "PASSED"),
        ("AC-002", "NOT_RUN"),
        ("AC-003", "PASSED"),
        ("AC-004", "NOT_RUN"),
    ]
    assert recorded["browsers"] == [{"name": "chrome", "version": "151.0.7922.76"}]
    assert "Browsers: Google Chrome 151.0.7922.76." in lines_of(chosen)
    assert unknown.status == 2
    assert unknown.errors == (
        "These codes are not acceptance criteria of the approved requirements: AC-999, XYZ "
        "(TEST_CRITERION_UNKNOWN). Use the codes of the folder orchestwin/requirements, for "
        "example AC-001.\n"
    )
    assert runs == 2


def test_a_static_folder_is_served_on_the_loopback_only_while_the_command_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch, fetch=True) as work:
        dist = work.root / "web" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text(
            f"<!doctype html><title>Mancia</title><main>{TEXTS['en']}</main>", encoding="utf-8"
        )
        run = work.ut("test", "--static", "web/dist", "--no-review", "--browser", "firefox")
        missing = work.ut("test", "--static", "web/missing", "--no-review")
        (work.root / "empty").mkdir()
        empty = work.ut("test", "--static", "empty", "--no-review")
        recorded = work.project.test_runs()[0]
        opened = list(work.site.opened)

    assert run.status == 0, run.errors
    served = next(line for line in lines_of(run) if line.startswith("Application:"))
    assert served.startswith("Application: the folder web/dist, served by this computer at ")
    assert served.endswith("/.")
    assert all(url.startswith("http://127.0.0.1:") for _, url in opened)
    assert recorded["application"] == {"kind": "STATIC", "address": "web/dist"}
    assert recorded["summary"]["passed"] == 4
    assert not any(thread.name == "ut-static-server" for thread in threading.enumerate())
    assert missing.status == empty.status == 2
    assert "TEST_STATIC_INVALID" in missing.errors
    assert "The folder empty does not exist or has no index.html" in empty.errors


def test_the_saved_application_and_browser_are_used_when_no_option_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        nothing = work.ut("test", "--no-review")
        first = work.ut(
            "test", "--url", "https://shop.example/", "--browser", "firefox", "--no-review"
        )
        again = work.ut("test", "--no-review")
        starts = list(work.site.starts)

    assert nothing.status == 2
    assert nothing.errors == (
        "Which application to verify is not known yet (TEST_APPLICATION_REQUIRED): launch "
        "`ut test --url ADDRESS` or `ut test --static FOLDER`; the next times `ut test` "
        "remembers it.\n"
    )
    assert (first.status, again.status) == (0, 0)
    assert "Application: the address https://shop.example/." in lines_of(again)
    assert {name for name, _, _ in starts} == {"firefox"}
    assert not any(direct for _, _, direct in starts)


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_missing_application_is_named_with_the_words_of_the_usage(
    tmp_path: Path, language: str
) -> None:
    run = run_ut(
        ["--lang", language, "test", "--help"],
        tmp_path,
        transport=NoNetwork(),
        variables={"COLUMNS": "400"},
    )
    sentence = messages.text("test.errors.TEST_APPLICATION_REQUIRED", language)

    usage = run.output.splitlines()[0]
    assert run.status == 0
    assert usage.startswith("usage: ut test ")
    assert "[--url ADDRESS | --static FOLDER]" in usage
    assert "`ut test --url ADDRESS`" in sentence
    assert "`ut test --static FOLDER`" in sentence


def test_a_blocked_path_is_planned_again_once_and_its_new_path_runs_everywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.site.fail_open("chrome", 3)
        run = work.ut("test", "--url", ADDRESS, "--no-review")
        recorded = work.project.test_runs()[0]
        plans = work.project.test_plans()
        replan_body = json.loads(work.requests("POST", "/test-plans")[1].body.decode("utf-8"))
        document = work.plan_document()
        local = work.local_run()
        page = (work.run_folder() / "report.html").read_text(encoding="utf-8")

    lines = lines_of(run)
    assert run.status == 0, run.errors
    assert (
        "TP-002 in Google Chrome blocked at step 1: the page did not open: "
        "net::ERR_CONNECTION_REFUSED" in lines
    )
    assert "Blocked paths sent back to the Studio for a new plan: TP-002." in lines
    assert "New paths in place of the blocked ones: TP-005. They now run in every browser." in lines
    assert replan_body["criteria"] == ["AC-002"]
    assert [item["code"] for item in replan_body["earlier"]] == ["TP-002"]
    assert replan_body["earlier"][0]["blocked_step"] == 1
    assert replan_body["earlier"][0]["detail"] == (
        "the page did not open: net::ERR_CONNECTION_REFUSED"
    )
    assert replan_body["earlier"][0]["snapshot"] is None
    assert replan_body["snapshot"]["hidden_text"] == HIDDEN["en"]
    assert [plan["replan_of"] for plan in plans] == [["TP-002"], []]
    assert [(item["path"]["code"], item["browser"]) for item in recorded["results"]] == [
        (code, browser)
        for code in ("TP-001", "TP-003", "TP-004", "TP-005")
        for browser in ("chrome", "firefox")
    ]
    assert [item["status"] for item in recorded["criteria"]] == ["PASSED"] * 4
    assert recorded["cost_microusd"] == 400000
    assert [item["id"] for item in document["replans"]] == [plans[0]["id"]]
    assert [item["path"]["code"] for item in local["first_attempt"]] == ["TP-002"]
    assert local["first_attempt"][0]["status"] == "BLOCKED"
    assert "First attempt of the blocked paths" in page


def test_a_replan_sends_the_page_of_the_blocked_step_with_its_hidden_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.site.fail_screenshot("chrome", 4)
        run = work.ut("test", "--url", ADDRESS, "--no-review")
        replan_body = json.loads(work.requests("POST", "/test-plans")[1].body.decode("utf-8"))

    lines = lines_of(run)
    assert run.status == 0, run.errors
    assert "Blocked paths sent back to the Studio for a new plan: TP-002." in lines
    assert "New paths in place of the blocked ones: TP-005. They now run in every browser." in lines
    (earlier,) = replan_body["earlier"]
    assert (earlier["code"], earlier["blocked_step"]) == ("TP-002", 2)
    assert list(earlier["snapshot"]) == SNAPSHOT_KEYS
    assert (earlier["snapshot"]["url"], earlier["snapshot"]["hidden_text"]) == (
        ADDRESS,
        HIDDEN["en"],
    )
    assert replan_body["snapshot"]["hidden_text"] == HIDDEN["en"]


def test_without_room_in_max_usd_a_blocked_path_stays_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.site.fail_open("chrome", 3)
        run = work.ut("test", "--url", ADDRESS, "--no-review", "--max-usd", "0.4")
        planned = len(work.requests("POST", "/test-plans"))
        recorded = work.project.test_runs()[0]
        wrong = work.ut("test", "--max-usd", "-1")

    lines = lines_of(run)
    assert run.status == 1
    assert (
        "The blocked paths are not planned again: a new plan would bring the spending to 0.50 "
        "USD, over the limit of --max-usd (0.40 USD)." in lines
    )
    assert planned == 1
    assert [(item["code"], item["status"]) for item in recorded["criteria"]][1] == (
        "AC-002",
        "BLOCKED",
    )
    assert lines[-2:] == ["", messages.text("test.failed_summary", "en")]
    assert wrong.status == 2
    assert "(TEST_MAX_USD_INVALID)" in wrong.errors


def test_a_failed_expectation_fails_the_criterion_and_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = TEXTS["en"].replace("The result appears within one second.", "")
    with session(tmp_path, monkeypatch, text=text) as work:
        run = work.ut("test", "--url", ADDRESS, "--no-review")
        recorded = work.project.test_runs()[0]

    lines = lines_of(run)
    assert run.status == 1
    assert (
        "TP-004 in Google Chrome failed at step 2: expectation not met: TEXT_VISIBLE: The result "
        "appears" in lines
    )
    assert "AC-004     failed  TP-004  Google Chrome, Mozilla Firefox" in lines
    assert recorded["summary"]["failed"] == 1
    assert recorded["results"][6]["steps"][1]["detail"] == (
        "expectation not met: TEXT_VISIBLE: The result appears"
    )
    assert run.slept >= 2.4


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_failed_criterion_ends_the_run_with_what_to_do_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    text = TEXTS[language].replace(LAST_SENTENCES[language], "")
    with session(tmp_path, monkeypatch, language=language, text=text) as work:
        run = work.ut("test", "--url", ADDRESS, "--no-review", language=language)
        recorded = work.project.test_runs()[0]

    assert run.status == 1
    assert recorded["summary"]["failed"] == 1
    assert lines_of(run)[-2:] == ["", messages.text("test.failed_summary", language)]
    assert lines_of(run)[-1].endswith("`ut test --plan new`.")


def test_the_review_asks_before_spending_for_three_twins_and_can_be_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch, twins=3) as work:
        (work.root / "orchestwin" / "twins" / "twins.json").unlink()
        refused = work.ut("test", "--url", ADDRESS, answers=["n"])
        refused_reviews = len(work.project.test_reviews())
        (work.root / "orchestwin" / "twins" / "twins.json").unlink()
        accepted = work.ut("test", answers=["y"])
        reviews = work.project.test_reviews()

    refused_lines = lines_of(refused)
    assert refused.status == 0, refused.errors
    assert "The twins now criticize the run: 3 twins, one generation each." in refused_lines
    assert "Go ahead with this spending? [Y/n] " in refused_lines
    assert (
        "The twins do not criticize this run: the spending was not confirmed. The run stays "
        "recorded." in refused_lines
    )
    assert refused_lines[-1].startswith("Knowledge folder updated in orchestwin/ (version 2)")
    assert refused_reviews == 0
    assert accepted.status == 0, accepted.errors
    assert len(reviews) == 1
    assert len(reviews[0]["critiques"]) == 3
    assert "Cost of the critiques: 0.45 USD." in lines_of(accepted)


@pytest.mark.parametrize(
    ("trouble", "sentence"),
    [
        (
            "provider",
            "The model gave an answer that the Studio cannot use (INVALID_PROVIDER_OUTPUT): "
            "nothing was stored. Launching `ut test` again tries once more, and it is a new "
            "spending.",
        ),
        (
            "lost",
            "Critiques of the twins: the generation was lost, perhaps because the Studio "
            "restarted. Launch `ut test` again (a new generation is a new spending).",
        ),
        (
            "ceiling",
            "The generation would go over the spending ceiling of a single generation (2.00 "
            "USD), so it did not start. Whoever runs the Studio can raise it, then launch "
            "`ut test` again.",
        ),
        (
            "twins",
            "The User Twins are not approved at the moment (USER_MODELING_APPROVAL_REQUIRED), "
            "so they cannot criticize the run, which stays recorded: approve them with `ut init`.",
        ),
    ],
)
def test_a_review_that_does_not_happen_leaves_the_run_recorded_and_the_folder_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trouble: str, sentence: str
) -> None:
    reviews = "/projects/{project_id}/test-runs/{run_id}/reviews"
    with session(tmp_path, monkeypatch) as work:
        if trouble == "provider":
            work.studio.fail_job("TEST_REVIEW", code="INVALID_PROVIDER_OUTPUT", status=502)
        elif trouble == "lost":
            work.studio.lose_job("TEST_REVIEW")
        elif trouble == "ceiling":
            work.studio.fail_next(
                "POST",
                reviews,
                status=402,
                body={"detail": {"code": "GENERATION_BUDGET_EXCEEDED", "stage": "MODEL_PROPOSAL"}},
            )
        else:
            work.studio.fail_next(
                "POST",
                reviews,
                status=409,
                body={"detail": {"code": "USER_MODELING_APPROVAL_REQUIRED"}},
            )
        run = work.ut("test", "--url", ADDRESS)
        stored = work.project.test_runs()
        written = work.project.test_reviews()

    lines = lines_of(run)
    assert run.status == 0, run.errors
    assert sentence in lines
    assert lines[-1].startswith("Knowledge folder updated in orchestwin/ (version 2)")
    assert len(stored) == 1
    assert written == []
    assert stored[0]["critiques"] == []


def test_json_prints_only_the_recorded_run_and_the_sentences_go_to_the_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        run = work.ut("test", "--url", ADDRESS, "--json", "--open")
        recorded = work.project.test_runs()[0]
        report = work.run_folder() / "report.html"

    document = json.loads(run.output)
    assert run.status == 0
    assert document == recorded
    assert run.output.startswith("{\n  ")
    assert list(document)[:3] == ["id", "started_at", "finished_at"]
    assert run.errors.startswith('Acceptance tests of "Calcolo mancia"\n')
    assert "Criteria: 4 passed, 0 failed, 0 blocked, 0 not covered, 0 not run." in run.errors
    assert f"I asked the browser to open {report}." in run.errors
    assert run.opened == (report.as_uri(),)


def test_without_a_model_a_new_plan_is_refused_before_any_spending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch, hosted=False) as work:
        run = work.ut("test", "--url", ADDRESS)
        planned = work.requests("POST", "/test-plans")
        starts = list(work.site.starts)

    assert run.status == 1
    assert run.output == ""
    assert run.errors == (
        "This Studio has no model connected, so it cannot write a new test plan "
        "(TEST_MODEL_NOT_CONFIGURED). A plan already saved on this computer still runs with "
        "`ut test`; whoever runs the Studio can connect a model.\n"
    )
    assert planned == []
    assert starts == []


def test_without_a_model_a_saved_plan_still_runs_and_the_review_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.ut("test", "--url", ADDRESS, "--no-review")
        work.fit_plan()
        work.studio.hosted = False
        work.site.fail_open("chrome", work.site.opens["chrome"] + 2)
        run = work.ut("test")
        runs = work.project.test_runs()
        planned = len(work.requests("POST", "/test-plans"))
        reviewed = work.requests("POST", "/reviews")

    lines = lines_of(run)
    assert run.status == 1
    assert "The blocked paths are not planned again: the Studio has no model connected." in lines
    assert (
        "The twins cannot criticize the run, because the Studio has no model connected "
        "(TEST_MODEL_NOT_CONFIGURED). The run stays recorded." in lines
    )
    assert len(runs) == 2
    assert planned == 1
    assert reviewed == []


def test_no_browser_found_is_an_error_naming_the_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch, browsers=()) as work:
        run = work.ut("test", "--url", ADDRESS)
        saved = (work.root / ".orchestwin" / "test.json").is_file()

    assert run.status == 1
    assert "ORCHESTWIN_CHROME" in run.errors and "ORCHESTWIN_FIREFOX" in run.errors
    assert "(TEST_NO_BROWSER)" in run.errors
    assert saved


def test_a_browser_that_does_not_start_is_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.site.broken.add("firefox")
        run = work.ut("test", "--url", ADDRESS, "--no-review")
        recorded = work.project.test_runs()[0]
        work.site.broken.add("chrome")
        none = work.ut("test", "--no-review")

    assert run.status == 0
    assert "Mozilla Firefox did not start and stays out of this run: exited with 1" in lines_of(run)
    assert recorded["browsers"] == [{"name": "chrome", "version": "151.0.7922.76"}]
    assert none.status == 1
    assert "(TEST_NO_BROWSER)" in none.errors


def test_the_command_needs_a_linked_folder_a_sign_in_and_the_approved_design(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch, publish=False) as work:
        folderless = work.ut("test", "--url", ADDRESS)
        outside = run_ut(
            ["test", "--url", ADDRESS],
            tmp_path,
            transport=UrlTransport(),
            working_directory=tmp_path / "elsewhere",
        )
        run_ut(["logout"], tmp_path, transport=UrlTransport())
        signed_out = work.ut("test", "--url", ADDRESS)

    assert folderless.status == 1
    assert "(TEST_DESIGN_REQUIRED)" in folderless.errors
    assert outside.status == 6
    assert signed_out.status == 3


def test_a_plan_the_studio_does_not_know_keeps_the_results_on_this_computer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.ut("test", "--url", ADDRESS, "--no-review")
        work.fit_plan()
        document = work.plan_document()
        document["plan"]["id"] = "00000000-0000-4000-8000-0000000000aa"
        (work.tests / "plan.json").write_text(json.dumps(document), encoding="utf-8")
        before = {path.name for path in work.tests.iterdir() if path.is_dir()}
        run = work.ut("test", "--no-review")
        after = {path.name for path in work.tests.iterdir() if path.is_dir()}
        (folder,) = after - before
        body = json.loads((work.tests / folder / "run.json").read_text(encoding="utf-8"))

    assert run.status == 1
    assert "(TEST_PLAN_NOT_FOUND)" in run.errors
    assert len(after) == 2
    assert body["plan_id"] == "00000000-0000-4000-8000-0000000000aa"
    assert len(body["results"]) == 8


def test_the_command_speaks_italian(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with session(tmp_path, monkeypatch, language="it") as work:
        run = work.ut("test", "--url", ADDRESS, "--no-review", language="it")

    lines = lines_of(run)
    assert run.status == 0, run.errors
    assert lines[:4] == [
        "Verifica dei criteri di «Calcolo mancia»",
        "========================================",
        "Applicazione: l'indirizzo http://127.0.0.1:5173/.",
        "Browser: Google Chrome 151.0.7922.76, Mozilla Firefox 156.0.1.",
    ]
    assert "Piano dei test nuovo: percorsi 4, criteri non coperti 0." in lines
    assert "Criterio  Esito     Percorsi  Browser" in lines
    assert "Criteri: 4 superati, 0 falliti, 0 bloccati, 0 non coperti, 0 non eseguiti." in lines
    assert work.site.starts[0][1] == "it-IT"


def test_the_status_names_the_latest_run_from_the_studio_and_from_the_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = TEXTS["en"].replace("The result appears within one second.", "")
    with session(tmp_path, monkeypatch, text=text) as work:
        before = json.loads(work.ut("status", "--json").output)
        work.ut("test", "--url", ADDRESS, "--no-review")
        studio = work.ut("status")
        document = json.loads(work.ut("status", "--json").output)
        offline = json.loads(work.ut("status", "--offline", "--json").output)
        recorded = work.project.test_runs()[0]

    line = (
        "Acceptance tests: latest run on 2026-09-29 09:00 UTC: 3 passed, 1 failed, 0 blocked, "
        "0 not covered."
    )
    assert before["tests"] is None
    assert line in lines_of(studio)
    expected = {
        "runs": 1,
        "latest": {
            "id": recorded["id"],
            "finished_at": recorded["finished_at"],
            "summary": recorded["summary"],
        },
    }
    assert document["tests"] == expected
    assert offline["tests"] == expected
    assert list(document)[-2:] == ["tests", "learning"]


def folder_tasks(work: Session) -> list[dict[str, object]]:
    path = work.root / "orchestwin" / "state" / "state.json"
    return json.loads(path.read_text(encoding="utf-8"))["tasks"]


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_findings_chosen_after_the_critiques_become_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    with session(tmp_path, monkeypatch, language=language) as work:
        run = work.ut("test", "--url", ADDRESS, answers=["1"], language=language)
        tasks = work.project.tasks()
        recorded = work.project.test_runs()[0]
        folder = folder_tasks(work)
        posts = [json.loads(item.body) for item in work.requests("POST", "/code-tasks")]

    def said(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    lines = lines_of(run)
    assert run.status == 0, run.errors
    intro = lines.index(said("test.tasks_intro"))
    cost = said("test.review_cost", amount="0.30" if language == "en" else "0,30")
    assert lines[intro - 2 : intro] == [cost, ""]
    question = lines.index(said("test.tasks_question") + " ")
    assert [line[:5] for line in lines[intro + 1 : question] if not line.startswith("     ")] == [
        "  1. ",
        "  2. ",
    ]
    (task,) = tasks
    created = lines.index(said("test.tasks_created", count=1))
    following = lines.index(said("test.tasks_next"))
    assert created == question + 1
    assert " ".join(" ".join(lines[created + 1 : following]).split()) == (
        f"- TSK-001: {task['text']}"
    )
    assert lines[following + 1] == ""
    assert lines[-1] == said("test.folder_updated", version=2)
    first = recorded["critiques"][0]
    assert task["origin"] == {
        "kind": "TEST_RUN",
        "commit": None,
        "test_run_id": recorded["id"],
        "twin_id": first["twin_id"],
        "twin_name": first["twin_name"],
        "finding": first["findings"][0]["text"],
    }
    assert task["about"]["criteria"] == ["AC-001"]
    assert posts == [
        {
            "tasks": [
                {
                    "text": None,
                    "source": {
                        "kind": "TEST_RUN",
                        "test_run_id": recorded["id"],
                        "twin_id": first["twin_id"],
                        "finding": 0,
                    },
                }
            ]
        }
    ]
    assert folder == tasks


def test_no_finding_chosen_or_a_closed_input_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        none = work.ut("test", "--url", ADDRESS, answers=[""])
        closed = work.ut("test")
        tasks = work.project.tasks()
        runs = work.project.test_runs()
        posts = work.requests("POST", "/code-tasks")

    assert (none.status, closed.status) == (0, 0)
    assert (none.errors, closed.errors) == ("", "")
    assert messages.text("test.tasks_none", "en") in lines_of(none)
    assert messages.text("test.tasks_later", "en") in lines_of(closed)
    assert "ut tasks from-test" in messages.text("test.tasks_later", "en")
    assert lines_of(closed)[-1].startswith("Knowledge folder updated in orchestwin/")
    assert tasks == [] and posts == []
    assert len(runs) == 2 and all(len(run["critiques"]) == 2 for run in runs)


def test_no_tasks_and_json_never_ask(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with session(tmp_path, monkeypatch) as work:
        quiet = work.ut("test", "--url", ADDRESS, "--no-tasks", answers=["1"])
        as_json = work.ut("test", "--json", answers=["1"])
        tasks = work.project.tasks()

    intro = messages.text("test.tasks_intro", "en")
    assert (quiet.status, as_json.status) == (0, 0)
    assert intro not in quiet.output and intro not in as_json.errors
    assert json.loads(as_json.output)["critiques"]
    assert tasks == []


def test_the_flow_with_a_default_request_never_asks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        bundle = terminal(tmp_path, transport=UrlTransport(), answers=["1"])
        request = run_flow.TestRequest(application={"kind": "URL", "address": ADDRESS})
        outcome = run_flow.execute(command_context(bundle.environment), request)
        tasks = work.project.tasks()

    assert request.offer_tasks is False
    assert len(outcome.critiques) == 2
    assert [(item["path"], item["kind"]) for item in outcome.weak] == [
        (f"TP-00{number}", "VISIBLE_AT_OPENING") for number in range(1, 5)
    ]
    assert messages.text("test.tasks_intro", "en") not in bundle.output
    assert bundle.environment.stdin.readline() == "1\n"
    assert tasks == []


def test_an_open_task_about_a_criterion_that_now_passes_gets_a_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.project.seed_tasks()
        run = work.ut("test", "--url", ADDRESS, "--no-review")
        statuses = [task["status"] for task in work.project.tasks()]

    lines = lines_of(run)
    report = next(index for index, line in enumerate(lines) if line.startswith("Report with"))
    assert run.status == 0, run.errors
    assert lines[report + 1] == messages.text(
        "test.task_maybe_done", "en", task="TSK-003", criteria="AC-001"
    )
    assert sum(line.startswith("The open task") for line in lines) == 1
    assert statuses == ["OPEN"] * 4


def test_a_task_about_a_criterion_that_fails_gets_no_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = TEXTS["en"].replace("With 30 euros and 15 percent the tip is 4.50 euros.", "")
    with session(tmp_path, monkeypatch, text=text) as work:
        work.project.seed_tasks()
        run = work.ut("test", "--url", ADDRESS, "--no-review")

    assert run.status == 1
    assert not any(line.startswith("The open task") for line in lines_of(run))


def test_a_refusal_when_the_tasks_are_created_is_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.studio.fail_next(
            "POST",
            "/projects/{project_id}/code-tasks",
            status=503,
            body={"detail": {"code": "DATABASE_UNAVAILABLE"}},
        )
        run = work.ut("test", "--url", ADDRESS, answers=["a"])
        tasks = work.project.tasks()

    assert run.status == 0, run.errors
    assert messages.text("test.tasks_failed", "en", code="DATABASE_UNAVAILABLE") in lines_of(run)
    assert lines_of(run)[-1].startswith("Knowledge folder updated in orchestwin/")
    assert tasks == []


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_new_plan_names_the_expectations_that_prove_little_and_the_criteria_resting_on_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    example = hidden_example(language)
    with session(
        tmp_path,
        monkeypatch,
        language=language,
        text=example["text"],
        hidden=example["hidden"],
        later=example["later"],
    ) as work:
        work.site.fail_open("chrome", 3)
        run = work.ut("test", "--url", ADDRESS, "--no-review", language=language)
        document = work.plan_document()
        recorded = work.project.test_runs()[0]
        sent = json.loads(work.requests("POST", "/test-plans")[0].body.decode("utf-8"))
        page = (work.run_folder() / "report.html").read_text(encoding="utf-8")

    def said(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    lines = lines_of(run)
    checks = checked_texts(document)
    assert run.status == 0, run.errors
    assert sent["snapshot"]["hidden_text"] == example["hidden"]
    assert example["later"] not in sent["snapshot"]["text"]
    written = lines.index(said("test.plan_written", paths=4, not_covered=0))
    assert lines[written + 1] == said("test.weak_count", count=4)
    assert listed(lines, written + 1) == [
        said("test.weak_hidden", path="TP-001", step=2, text=checks["TP-001"]),
        *(
            said("test.weak_visible", path=code, step=2, text=checks[code])
            for code in ("TP-002", "TP-003", "TP-004")
        ),
    ]
    done = lines.index(said("test.replan_done", codes="TP-005"))
    assert lines[done + 1] == said("test.weak_count", count=1)
    assert listed(lines, done + 1) == [
        said("test.weak_visible", path="TP-005", step=2, text=checks["TP-005"])
    ]
    summary = lines.index(
        said("test.summary", passed=4, failed=0, blocked=0, not_covered=0, not_run=0)
    )
    assert lines[summary + 1 : summary + 4] == [
        said("test.weak_criterion", code=code) for code in ("AC-001", "AC-003", "AC-004")
    ]
    assert lines[summary + 4].startswith(said("test.report_written", path=""))
    assert [item["status"] for item in recorded["criteria"]] == ["PASSED"] * 4
    assert document["weak_expectations"] == [
        {"path": "TP-001", "step": 2, "kind": "HIDDEN_AT_OPENING", "text": checks["TP-001"]},
        *(
            {"path": code, "step": 2, "kind": "VISIBLE_AT_OPENING", "text": checks[code]}
            for code in ("TP-003", "TP-004", "TP-005")
        ),
    ]
    mark = messages.text("test.report_weak_mark", language)
    assert page.count(f'<span class="chip weak">{mark}</span>') == 8
    assert said("test.report_weak", count=4) in page


def test_a_reused_plan_counts_the_expectations_that_prove_little_in_one_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with session(tmp_path, monkeypatch) as work:
        work.ut("test", "--url", ADDRESS, "--no-review")
        work.fit_plan()
        again = work.ut("test", "--no-review")
        chosen = work.ut("test", "--no-review", "--criteria", "AC-002")
        document = work.plan_document()
        del document["weak_expectations"]
        (work.tests / "plan.json").write_text(json.dumps(document), encoding="utf-8")
        older = work.ut("test", "--no-review")
        planned = len(work.requests("POST", "/test-plans"))

    reused = "Test plan reused, written on 2026-09-29 08:00 UTC: 4 paths, 0 criteria not covered."
    lines = lines_of(again)
    assert (again.status, chosen.status, older.status) == (0, 0, 0)
    assert planned == 1
    start = lines.index(reused)
    assert lines[start + 1] == (
        "Expectations that prove little in the paths of this run: 4. The report marks them on "
        "their steps."
    )
    assert lines[start + 2].startswith("Path TP-001 in Google Chrome")
    assert not any(line.startswith(("- TP-", "Expectations that prove little: ")) for line in lines)
    assert sum(line.endswith("the criterion asks.") for line in lines) == 4
    assert lines_of(chosen)[lines_of(chosen).index(reused) + 1] == (
        "Expectations that prove little in the paths of this run: 1. The report marks them on "
        "their steps."
    )
    assert [line for line in lines_of(chosen) if line.endswith("the criterion asks.")] == [
        WEAK_CRITERION.format(code="AC-002")
    ]
    assert not any("prove little" in line for line in lines_of(older))
    assert "weak_expectations" not in work.plan_document()


@pytest.mark.parametrize("language", ["en", "it"])
def test_a_plan_expecting_the_absence_of_a_text_shown_at_opening_says_it_cannot_be_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, language: str
) -> None:
    word = TOTALS[language]
    with session(tmp_path, monkeypatch, language=language) as work:
        work.ut("test", "--url", ADDRESS, "--no-review", language=language)
        stored = work.project.acceptance_plans[0]
        stored["paths"][0]["steps"][1]["expect"] = {
            "kind": "TEXT_ABSENT",
            "target": None,
            "text": word,
        }
        work.studio.fail_next(
            "POST",
            "/projects/{project_id}/test-plans",
            status=201,
            body={"status": "PLANNED", "plan": stored},
        )
        run = work.ut("test", "--no-review", "--plan", "new", language=language)
        recorded = work.project.test_runs()[0]
        document = work.plan_document()
        page = (work.run_folder() / "report.html").read_text(encoding="utf-8")
        work.fit_plan()
        again = work.ut("test", "--no-review", language=language)

    def said(key: str, **values: object) -> str:
        return messages.text(key, language, **values)

    lines = lines_of(run)
    checks = checked_texts(document)
    sentence = said("test.weak_absent_visible", path="TP-001", step=2, text=word)
    assert word.casefold() in TEXTS[language].casefold()
    assert word in HIDDEN[language]
    assert (run.status, again.status) == (1, 1)
    written = lines.index(said("test.plan_written", paths=4, not_covered=0))
    assert lines[written + 1] == said("test.weak_count", count=4)
    assert listed(lines, written + 1) == [
        sentence,
        *(
            said("test.weak_visible", path=code, step=2, text=checks[code])
            for code in ("TP-002", "TP-003", "TP-004")
        ),
    ]
    summary = lines.index(
        said("test.summary", passed=3, failed=1, blocked=0, not_covered=0, not_run=0)
    )
    assert lines[summary + 1 : summary + 4] == [
        said("test.weak_criterion", code=code) for code in ("AC-002", "AC-003", "AC-004")
    ]
    assert lines[summary + 4].startswith(said("test.report_written", path=""))
    assert [item["status"] for item in recorded["criteria"]] == [
        "FAILED",
        "PASSED",
        "PASSED",
        "PASSED",
    ]
    assert document["weak_expectations"][0] == {
        "path": "TP-001",
        "step": 2,
        "kind": "ABSENT_VISIBLE_AT_OPENING",
        "text": word,
    }
    mark = messages.text("test.report_weak_mark", language)
    assert page.count(f'<span class="chip weak">{mark}</span>') == 8
    assert page.count(f'<p class="weak">{html.escape(sentence, quote=True)}</p>') == 2
    reused = lines_of(again)
    assert said("test.weak_reused", count=4) in reused
    assert not any(line.startswith("- TP-") for line in reused)
