from __future__ import annotations

import json
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest

from orchestwin.cli.browser import BrowserProgram
from orchestwin.cli.flows import test_run as run_flow
from orchestwin.cli.http import UrlTransport

from .support.browsers import FAKE_PNG
from .support.fake_studio import FakeProject, FakeStudio, RecordedRequest
from .support.terminal import TEST_PASSWORD, Run, link_folder, run_ut
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
FOLDER_VERSIONS = (2, 4)


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
            title="Tip calculator", text=TEXTS[language] if text is None else text, fetch=fetch
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
    assert run.status == 0, run.errors
    assert run.errors == ""
    assert lines[:12] == [
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
        "Cost of the plan: 0.20 USD.",
        "Path TP-001 in Google Chrome: With 30 euros and 15 percent the tip is 4.50 euros...",
        "Path TP-001 in Google Chrome: With 30 euros and 15 percent the tip is 4.50 euros: done "
        "in 0 s.",
    ]
    table = lines.index("Criterion  Status  Paths   Browsers")
    assert lines[table : table + 8] == [
        "Criterion  Status  Paths   Browsers",
        "---------  ------  ------  ------------------------------",
        "AC-001     passed  TP-001  Google Chrome, Mozilla Firefox",
        "AC-002     passed  TP-002  Google Chrome, Mozilla Firefox",
        "AC-003     passed  TP-003  Google Chrome, Mozilla Firefox",
        "AC-004     passed  TP-004  Google Chrome, Mozilla Firefox",
        "Criteria: 4 passed, 0 failed, 0 blocked, 0 not covered, 0 not run.",
        f"Report with the steps and the screenshots: {report}",
    ]
    assert lines[table + 8 : table + 14] == [
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
    assert lines[-2:] == [
        "",
        "Some criteria failed or were blocked: the report shows every step with its screenshot. "
        "Fix the application, then launch `ut test` again.",
    ]
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
    assert list(document)[-1] == "tests"
