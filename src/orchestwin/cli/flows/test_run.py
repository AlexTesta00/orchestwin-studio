from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from urllib.parse import urljoin, urlsplit, urlunsplit

from orchestwin.cli import costs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.browser import (
    BrowserError,
    PageSnapshot,
    find_browsers,
    matches_text,
    open_page,
    resolve_target,
)
from orchestwin.cli.client import ensure_access
from orchestwin.cli.console import ProgressOutcome
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import test_plan, test_report, test_settings, verify_review
from orchestwin.cli.flows.test_application import WEB_SCHEMES, Application, chosen_application
from orchestwin.cli.flows.test_results import (
    INTERRUPTED,
    offer_tasks,
    open_tasks,
    passed_tasks,
    publish_folder,
    recorded_run,
    review_run,
    run_body,
    with_review,
    write_files,
)
from orchestwin.cli.flows.test_results import cut as _cut
from orchestwin.cli.flows.test_results import error_code as _error_code
from orchestwin.cli.flows.test_server import StaticServer
from orchestwin.cli.http import is_loopback
from orchestwin.cli.shapes import squeezed as _text

if TYPE_CHECKING:
    from orchestwin.cli.browser import BrowserProgram, Page
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.test_plan import PlanChoice, SavedPlan
    from orchestwin.cli.flows.test_settings import TestSettings
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

APPROVED: Final = "APPROVED"
EXPECT_ATTEMPTS: Final = 4
EXPECT_PAUSE_SECONDS: Final = 0.4
TOLERANCE: Final = 1e-9
UNKNOWN_VERSION: Final = "unknown"
STAGES: Final = ("requirements", "design")
CRITERION_PATTERN: Final = re.compile(r"AC-[0-9]{3,6}")
UNSAFE_SEGMENT: Final = re.compile(r"[^A-Za-z0-9_-]+")
BROWSER_DETAIL_KEYS: Final[Mapping[str, str]] = {
    "PAGE_NOT_LOADED": "test.detail_page_not_loaded",
    "ACTION_FAILED": "test.detail_action_failed",
    "BROWSER_NOT_STARTED": "test.detail_browser_not_started",
    "BROWSER_NOT_FOUND": "test.detail_browser_not_started",
}


@dataclass(frozen=True, slots=True)
class TestRequest:
    __test__ = False

    application: Mapping[str, object] | None = None
    browsers: tuple[str, ...] = ("all",)
    criteria: tuple[str, ...] = ()
    new_plan: bool = False
    review: bool = True
    max_usd: float = 2.0
    offer_tasks: bool = False


@dataclass(frozen=True, slots=True)
class TestOutcome:
    __test__ = False

    run: Mapping[str, object]
    critiques: tuple[Mapping[str, object], ...]
    folder: Path
    report: Path
    weak: tuple[Mapping[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class Site:
    base: str
    static: bool
    direct: bool


@dataclass(frozen=True, slots=True)
class Browser:
    program: BrowserProgram
    version: str

    @property
    def name(self) -> str:
        return self.program.name

    @property
    def label(self) -> str:
        return self.program.label

    def document(self) -> dict[str, str]:
        return {"name": self.name, "version": self.version}


@dataclass(frozen=True, slots=True)
class StepOutcome:
    index: int
    status: str
    detail: str | None = None
    url: str | None = None
    title: str | None = None
    screenshot: str | None = None

    def document(self) -> dict[str, object]:
        return {
            "index": self.index,
            "status": self.status,
            "detail": self.detail,
            "url": self.url,
            "title": self.title,
            "screenshot": self.screenshot,
        }


@dataclass(frozen=True, slots=True)
class PathOutcome:
    path: Mapping[str, object]
    browser: str
    status: str
    seconds: float
    steps: tuple[StepOutcome, ...]
    page_text: str | None = None
    blocked_step: int | None = None
    blocked_snapshot: PageSnapshot | None = None

    @property
    def code(self) -> str:
        return str(self.path.get("code") or "")

    def stopped_at(self) -> StepOutcome | None:
        return next((step for step in self.steps if step.status != tests_api.DONE), None)

    def document(self) -> dict[str, object]:
        return {
            "path": dict(self.path),
            "browser": self.browser,
            "status": self.status,
            "seconds": self.seconds,
            "steps": [step.document() for step in self.steps],
            "page_text": self.page_text,
        }

    def earlier(self) -> dict[str, object]:
        stopped = self.stopped_at()
        return test_plan.earlier_item(
            self.path,
            self.blocked_step or 1,
            None if stopped is None else stopped.detail,
            None if self.blocked_snapshot is None else self.blocked_snapshot.document(),
        )


@dataclass(frozen=True, slots=True)
class Prepared:
    project: ProjectFolder
    client: StudioClient
    project_id: str
    project_name: str
    summary: FolderSummary
    application: Application
    choice: str
    criteria: tuple[str, ...]
    programs: tuple[BrowserProgram, ...]
    saved: SavedPlan | None
    locale: str

    @property
    def versions(self) -> tuple[int | None, int | None]:
        requirements, design = STAGES
        return (_stage_number(self.summary, requirements), _stage_number(self.summary, design))


@dataclass(frozen=True, slots=True)
class Execution:
    saved: SavedPlan
    results: tuple[PathOutcome, ...]
    first_attempt: tuple[PathOutcome, ...]


@dataclass(frozen=True, slots=True)
class Walk:
    status: str
    steps: tuple[StepOutcome, ...]
    page_text: str | None
    blocked_step: int | None
    blocked_snapshot: PageSnapshot | None


@dataclass(frozen=True, slots=True)
class Done:
    outcome: StepOutcome
    snapshot: PageSnapshot | None


def execute(context: CommandContext, request: TestRequest) -> TestOutcome:
    ready = prepare(context, request)
    overview = tests_api.overview(ready.client, ready.project_id)
    available = tests_api.plan_available(overview)
    choice = test_plan.decide(
        ready.saved,
        ready.versions,
        ready.criteria,
        new=request.new_plan,
        redo=test_plan.read_redo(ready.project),
    )
    if not choice.reuse and not available:
        raise CliError(tests_api.NO_TEST_MODEL)
    console = context.console
    console.heading(context.text("test.heading", name=ready.project_name))
    with serving(ready.application) as site:
        announce_application(context, ready.application, site)
        browsers, snapshot = start_browsers(context, ready, site, snapshot=not choice.reuse)
        console.say(
            "test.browsers",
            browsers=", ".join(f"{browser.label} {browser.version}" for browser in browsers),
        )
        saved, spent = plan_for(context, ready, choice, snapshot)
        started = context.environment.now()
        folder = test_report.run_folder(test_plan.tests_folder(ready.project), started)
        runner = PathRunner(context, site, folder, language=ready.locale)
        execution = run_paths(
            context,
            ready,
            runner,
            browsers,
            saved,
            spent=spent,
            max_usd=request.max_usd,
            available=available,
        )
        finished = context.environment.now()
    labels = {browser.name: browser.label for browser in browsers}
    first_attempt = [outcome.document() for outcome in execution.first_attempt]
    weak = tuple(execution.saved.weak_of(*(outcome.code for outcome in execution.results)))
    body = run_body(ready, execution, browsers, started=started, finished=finished)
    test_report.write_run(folder, body, first_attempt=first_attempt)
    _, document = tests_api.record(ready.client, ready.project_id, body)
    run = recorded_run(document)
    names = test_report.names(ready.project)
    report = write_files(context, ready, folder, run, names, labels, first_attempt, weak)
    console.write()
    test_report.show_table(context, run, labels)
    test_report.show_summary(context, run)
    for code in test_plan.weakly_passed(run, weak):
        console.say("test.weak_criterion", code=code)
    console.say("test.report_written", path=str(report))
    tasks = open_tasks(ready)
    passed_tasks(context, run, tasks)
    critiques: tuple[Mapping[str, object], ...] = ()
    if request.review:
        review = review_run(context, ready, run, available=available)
        if review is not None:
            critiques = tuple(tests_api.critiques_of(review))
            run = with_review(run, review)
            report = write_files(context, ready, folder, run, names, labels, first_attempt, weak)
            test_report.show_review(
                context, critiques, names, cost_microusd=review.get("cost_microusd")
            )
            if request.offer_tasks:
                offer_tasks(context, ready, run, tasks)
    publish_folder(context, ready)
    return TestOutcome(run=run, critiques=critiques, folder=folder, report=report, weak=weak)


def prepare(context: CommandContext, request: TestRequest) -> Prepared:
    project = context.linked_project()
    link = project.link()
    client = context.client()
    ensure_access(context, client)
    summary = approved_folder(project)
    settings = test_settings.read_settings(project)
    application = chosen_application(context, project, request.application, settings)
    choice = browser_choice(request.browsers, settings)
    saved = test_plan.read_plan(project)
    criteria = chosen_criteria(project, request.criteria, saved)
    test_settings.write_settings(
        project, test_settings.TestSettings(application=application.saved, browser=choice)
    )
    programs = browser_programs(context, choice)
    return Prepared(
        project=project,
        client=client,
        project_id=link.project_id,
        project_name=link.project_name,
        summary=summary,
        application=application,
        choice=choice,
        criteria=criteria,
        programs=programs,
        saved=saved,
        locale=verify_review.locale(context, project),
    )


def approved_folder(project: ProjectFolder) -> FolderSummary:
    found = knowledge.summary(project.knowledge)
    if found is None or not all(_approved(found, stage) for stage in STAGES):
        raise CliError("TEST_DESIGN_REQUIRED")
    return found


def browser_choice(requested: Sequence[str], settings: TestSettings | None) -> str:
    names = [str(item).strip().lower() for item in requested if str(item).strip()]
    if not names:
        return settings.browser if settings is not None else test_settings.ALL_BROWSERS
    if test_settings.ALL_BROWSERS in names:
        return test_settings.ALL_BROWSERS
    chosen = [name for name in dict.fromkeys(names) if name in tests_api.BROWSER_NAMES]
    return chosen[0] if len(chosen) == 1 else test_settings.ALL_BROWSERS


def browser_programs(context: CommandContext, choice: str) -> tuple[BrowserProgram, ...]:
    names = tests_api.BROWSER_NAMES if choice == test_settings.ALL_BROWSERS else (choice,)
    found = tuple(find_browsers(context.environment, names=names))
    if not found:
        raise CliError("TEST_NO_BROWSER")
    return found


def chosen_criteria(
    project: ProjectFolder, requested: Sequence[str], saved: SavedPlan | None
) -> tuple[str, ...]:
    codes = tests_api.ordered(
        [str(code).strip().upper() for code in requested if str(code).strip()]
    )
    if not codes:
        return ()
    known_codes = set(test_report.statements(project))
    if saved is not None:
        known_codes |= set(saved.criteria()) | saved.covered()
    unknown = [
        code
        for code in codes
        if CRITERION_PATTERN.fullmatch(code) is None or (known_codes and code not in known_codes)
    ]
    if unknown:
        raise CliError(
            "TEST_CRITERION_UNKNOWN", status=USAGE_STATUS, values={"codes": ", ".join(unknown)}
        )
    return tuple(codes)


@contextlib.contextmanager
def serving(application: Application) -> Iterator[Site]:
    if application.static:
        with StaticServer(Path(application.location)) as server:
            yield Site(base=server.address, static=True, direct=True)
        return
    yield Site(base=application.location, static=False, direct=application.direct)


def announce_application(context: CommandContext, application: Application, site: Site) -> None:
    if application.static:
        context.console.say(
            "test.application_static", folder=application.address, address=site.base
        )
    else:
        context.console.say("test.application_url", address=application.address)


def start_browsers(
    context: CommandContext, ready: Prepared, site: Site, *, snapshot: bool
) -> tuple[list[Browser], PageSnapshot | None]:
    started: list[Browser] = []
    taken: PageSnapshot | None = None
    for program in ready.programs:
        try:
            page = open_page(context, program, language=ready.locale, direct=site.direct)
        except BrowserError as error:
            context.console.say(
                "test.browser_failed", browser=program.label, detail=_error_detail(error)
            )
            continue
        try:
            version = _version(page)
            if snapshot and taken is None:
                page.open(site.base)
                taken = page.snapshot()
        finally:
            _close(page)
        started.append(Browser(program=program, version=version))
    if not started:
        raise CliError("TEST_NO_BROWSER")
    return started, taken


def plan_for(
    context: CommandContext,
    ready: Prepared,
    choice: PlanChoice,
    snapshot: PageSnapshot | None,
) -> tuple[SavedPlan, float]:
    console = context.console
    if choice.reuse and ready.saved is not None:
        saved = ready.saved
        console.say(
            "test.plan_reused",
            date=test_report.moment_text(saved.created_at),
            paths=len(saved.paths()),
            not_covered=len(saved.not_covered()),
        )
        selected = selection(saved.paths(), ready.criteria)
        weak = saved.weak_of(*(str(path.get("code")) for path in selected))
        if weak:
            console.say("test.weak_reused", count=len(weak))
        return saved, 0.0
    if choice.key is not None:
        console.say(choice.key, **choice.values)
    console.say("test.plan_requested")
    if snapshot is None:
        raise ApiFailure("API_FAILURE", http_status=200)
    costs.confirm_spending(context, ready.client, [tests_api.PLAN_OPERATION])
    sent = snapshot.document()
    body = test_plan.plan_body(ready.locale, ready.application.document(), sent)
    plan = test_plan.request_plan(
        context, ready.client, ready.project, body, label=context.text("test.plan_label")
    )
    weak = test_plan.weak_expectations(tests_api.mappings(plan.get("paths")), sent)
    saved = test_plan.SavedPlan(
        saved_at=context.now_text(),
        application=ready.application.document(),
        plan=plan,
        weak=tuple(weak),
    )
    test_plan.save_plan(ready.project, saved)
    test_plan.clear_redo(ready.project)
    console.say("test.plan_written", paths=len(saved.paths()), not_covered=len(saved.not_covered()))
    lines = [
        context.text(
            "test.not_covered_line",
            code=str(item.get("criterion") or "-"),
            reason=_text(item.get("reason")) or "-",
        )
        for item in saved.not_covered()
    ]
    if lines:
        console.items(lines)
    test_report.show_weak(context, weak)
    estimate = costs.ESTIMATES[tests_api.PLAN_OPERATION].high_usd
    spent = test_plan.plan_cost_usd(plan, estimate)
    if spent > 0:
        console.say("test.plan_cost", amount=costs.usd_text(spent, context.language))
    return saved, spent


def run_paths(
    context: CommandContext,
    ready: Prepared,
    runner: PathRunner,
    browsers: Sequence[Browser],
    saved: SavedPlan,
    *,
    spent: float,
    max_usd: float,
    available: bool,
) -> Execution:
    selected = selection(saved.paths(), ready.criteria)
    first, others = browsers[0], list(browsers[1:])
    firsts = [runner.run(first, path) for path in selected]
    replaced: list[PathOutcome] = []
    blocked = [outcome for outcome in firsts if outcome.status == tests_api.BLOCKED]
    if blocked:
        updated = replan(
            context,
            ready,
            runner,
            first,
            saved,
            blocked,
            spent=spent,
            max_usd=max_usd,
            available=available,
        )
        if updated is not None:
            latest = updated.replans[-1]
            gone = set(tests_api.texts(latest.get("replan_of")))
            replaced = [outcome for outcome in firsts if outcome.code in gone]
            kept = [outcome for outcome in firsts if outcome.code not in gone]
            fresh = selection(tests_api.mappings(latest.get("paths")), ready.criteria)
            firsts = kept + [runner.run(first, path) for path in fresh]
            saved = updated
            selected = selection(saved.paths(), ready.criteria)
    table = {first.name: firsts}
    for browser in others:
        table[browser.name] = [runner.run(browser, path) for path in selected]
    results = [
        table[browser.name][position]
        for position in range(len(selected))
        for browser in browsers
        if position < len(table[browser.name])
    ]
    return Execution(saved=saved, results=tuple(results), first_attempt=tuple(replaced))


def replan(
    context: CommandContext,
    ready: Prepared,
    runner: PathRunner,
    browser: Browser,
    saved: SavedPlan,
    blocked: Sequence[PathOutcome],
    *,
    spent: float,
    max_usd: float,
    available: bool,
) -> SavedPlan | None:
    console = context.console
    if not available:
        console.say("test.replan_unavailable")
        return None
    if len(saved.replans) >= tests_api.MAX_REPLANS:
        console.say("test.replan_limit", count=len(saved.replans))
        return None
    needed = spent + costs.ESTIMATES[tests_api.PLAN_OPERATION].high_usd
    if needed > max_usd + TOLERANCE:
        limit = costs.usd_text(max_usd, context.language)
        if costs.uses_subscription(ready.client):
            console.say("test.replan_over_budget_subscription", limit=limit)
        else:
            console.say(
                "test.replan_over_budget",
                amount=costs.usd_text(needed, context.language),
                limit=limit,
            )
        return None
    chosen = list(blocked[: tests_api.MAX_EARLIER_PATHS])
    console.say("test.replan", codes=", ".join(outcome.code for outcome in chosen))
    try:
        sent = runner.snapshot(browser).document()
        criteria = tests_api.ordered(
            [code for outcome in chosen for code in tests_api.texts(outcome.path.get("criteria"))]
        )
        body = test_plan.plan_body(
            ready.locale,
            ready.application.document(),
            sent,
            criteria=criteria,
            earlier=[outcome.earlier() for outcome in chosen],
        )
        costs.confirm_spending(context, ready.client, [tests_api.PLAN_OPERATION])
        plan = test_plan.request_plan(
            context, ready.client, ready.project, body, label=context.text("test.replan_label")
        )
    except CliError as error:
        if error.code == INTERRUPTED:
            raise
        console.say("test.replan_failed", code=_error_code(error))
        return None
    weak = test_plan.weak_expectations(tests_api.mappings(plan.get("paths")), sent)
    updated = saved.with_replan(plan, saved_at=context.now_text(), weak=weak)
    test_plan.save_plan(ready.project, updated)
    codes = [str(path.get("code") or "-") for path in tests_api.mappings(plan.get("paths"))]
    if codes:
        console.say("test.replan_done", codes=", ".join(codes))
    else:
        console.say("test.replan_empty")
    test_report.show_weak(context, weak)
    return updated


def selection(
    paths: Sequence[Mapping[str, object]], criteria: Sequence[str]
) -> list[Mapping[str, object]]:
    if not criteria:
        return list(paths)
    wanted = set(criteria)
    return [path for path in paths if wanted & set(tests_api.texts(path.get("criteria")))]


class PathRunner:
    def __init__(self, context: CommandContext, site: Site, folder: Path, *, language: str) -> None:
        self.context = context
        self.site = site
        self.folder = folder
        self.language = language

    def run(self, browser: Browser, path: Mapping[str, object]) -> PathOutcome:
        context = self.context
        environment = context.environment
        code = str(path.get("code") or "-")
        label = context.text(
            "test.path_label", code=code, browser=browser.label, heading=_heading(path)
        )
        steps = tests_api.mappings(path.get("steps"))
        with context.console.progress(label) as progress:
            started = environment.monotonic()
            walk = self._walk(browser, code, steps)
            seconds = round(max(environment.monotonic() - started, 0.0), 2)
            if walk.status != tests_api.PASSED:
                progress.set_outcome(ProgressOutcome.NOT_COMPLETED)
        outcome = PathOutcome(
            path=path,
            browser=browser.name,
            status=walk.status,
            seconds=float(seconds),
            steps=walk.steps,
            page_text=walk.page_text,
            blocked_step=walk.blocked_step,
            blocked_snapshot=walk.blocked_snapshot,
        )
        self._tell(browser, outcome)
        return outcome

    def snapshot(self, browser: Browser) -> PageSnapshot:
        page = open_page(
            self.context, browser.program, language=self.language, direct=self.site.direct
        )
        try:
            page.open(self.site.base)
            return page.snapshot()
        finally:
            _close(page)

    def _walk(self, browser: Browser, code: str, steps: Sequence[Mapping[str, object]]) -> Walk:
        outcomes: list[StepOutcome] = []
        status = tests_api.PASSED
        last: PageSnapshot | None = None
        blocked_step: int | None = None
        blocked_snapshot: PageSnapshot | None = None
        page: Page | None = None
        try:
            try:
                page = open_page(
                    self.context, browser.program, language=self.language, direct=self.site.direct
                )
            except BrowserError as error:
                outcomes.append(StepOutcome(1, tests_api.BLOCKED, self._browser_detail(error)))
                outcomes.extend(
                    StepOutcome(index, tests_api.SKIPPED) for index in range(2, len(steps) + 1)
                )
                return Walk(tests_api.BLOCKED, tuple(outcomes), None, 1, None)
            for index, step in enumerate(steps, start=1):
                if status != tests_api.PASSED:
                    outcomes.append(StepOutcome(index, tests_api.SKIPPED))
                    continue
                try:
                    done = self._step(page, browser, code, index, step)
                except BrowserError as error:
                    outcomes.append(
                        StepOutcome(
                            index,
                            tests_api.BLOCKED,
                            self._browser_detail(error),
                            _url(last),
                            _title(last),
                            self._screenshot_quietly(page, browser, code, index),
                        )
                    )
                    status, blocked_step, blocked_snapshot = tests_api.BLOCKED, index, last
                    continue
                outcomes.append(done.outcome)
                if done.snapshot is not None:
                    last = done.snapshot
                if done.outcome.status != tests_api.DONE:
                    status = done.outcome.status
                    if status == tests_api.BLOCKED:
                        blocked_step, blocked_snapshot = index, done.snapshot
        finally:
            if page is not None:
                _close(page)
        page_text = None if last is None else _cut(last.text, tests_api.MAX_PAGE_TEXT_LENGTH)
        return Walk(status, tuple(outcomes), page_text, blocked_step, blocked_snapshot)

    def _step(
        self,
        page: Page,
        browser: Browser,
        code: str,
        index: int,
        step: Mapping[str, object],
    ) -> Done:
        action = step.get("action")
        target = step.get("target")
        value = step.get("value")
        text = value if isinstance(value, str) else ""
        if action == tests_api.OPEN:
            page.open(open_address(self.site, text, program=browser.label))
        elif action in tests_api.TARGET_ACTIONS:
            snapshot = page.snapshot()
            element = (
                resolve_target(snapshot, target, action=str(action))
                if isinstance(target, Mapping)
                else None
            )
            if element is None:
                detail = self.context.text(
                    "test.detail_target_missing", target=test_report.target_text(target)
                )
                return Done(
                    StepOutcome(
                        index,
                        tests_api.BLOCKED,
                        _cut(detail, tests_api.MAX_STEP_DETAIL_LENGTH),
                        snapshot.url,
                        snapshot.title,
                        self._screenshot(page, browser, code, index),
                    ),
                    snapshot,
                )
            try:
                if action == tests_api.CLICK:
                    page.click(element)
                elif action == tests_api.TYPE:
                    page.type(element, text)
                else:
                    page.select(element, text)
            except BrowserError as error:
                return Done(
                    StepOutcome(
                        index,
                        tests_api.BLOCKED,
                        self._browser_detail(error),
                        snapshot.url,
                        snapshot.title,
                        self._screenshot_quietly(page, browser, code, index),
                    ),
                    snapshot,
                )
        elif action == tests_api.PRESS:
            page.press(text)
        elif action != tests_api.CHECK:
            raise BrowserError(
                "ACTION_FAILED", program=browser.label, detail=f"unknown action: {action}"
            )
        shot = self._screenshot(page, browser, code, index)
        expect = step.get("expect")
        if isinstance(expect, Mapping):
            met, snapshot = self._check(page, expect)
            if not met:
                detail = self.context.text(
                    "test.detail_expectation_failed",
                    expectation=test_report.expectation_text(expect),
                )
                return Done(
                    StepOutcome(
                        index,
                        tests_api.FAILED,
                        _cut(detail, tests_api.MAX_STEP_DETAIL_LENGTH),
                        snapshot.url,
                        snapshot.title,
                        shot,
                    ),
                    snapshot,
                )
        else:
            snapshot = page.snapshot()
        return Done(
            StepOutcome(index, tests_api.DONE, None, snapshot.url, snapshot.title, shot), snapshot
        )

    def _check(self, page: Page, expect: Mapping[str, object]) -> tuple[bool, PageSnapshot]:
        snapshot = page.snapshot()
        for _ in range(EXPECT_ATTEMPTS - 1):
            if expectation_met(snapshot, expect):
                return True, snapshot
            self.context.environment.sleep(EXPECT_PAUSE_SECONDS)
            snapshot = page.snapshot()
        return expectation_met(snapshot, expect), snapshot

    def _screenshot(self, page: Page, browser: Browser, code: str, index: int) -> str:
        data = page.screenshot()
        relative = screenshot_path(code, browser.name, index)
        target = self.folder.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative

    def _screenshot_quietly(
        self, page: Page, browser: Browser, code: str, index: int
    ) -> str | None:
        try:
            return self._screenshot(page, browser, code, index)
        except BrowserError:
            return None

    def _browser_detail(self, error: CliError) -> str:
        key = BROWSER_DETAIL_KEYS.get(error.code, "test.detail_browser_failed")
        text = self.context.text(key, detail=_error_detail(error))
        return _cut(text, tests_api.MAX_STEP_DETAIL_LENGTH)

    def _tell(self, browser: Browser, outcome: PathOutcome) -> None:
        stopped = outcome.stopped_at()
        if outcome.status == tests_api.PASSED or stopped is None:
            return
        key = "test.path_failed" if outcome.status == tests_api.FAILED else "test.path_blocked"
        self.context.console.say(
            key,
            code=outcome.code,
            browser=browser.label,
            step=stopped.index,
            detail=stopped.detail or "-",
        )


def expectation_met(snapshot: PageSnapshot, expect: Mapping[str, object]) -> bool:
    kind = expect.get("kind")
    text = expect.get("text")
    wanted = text if isinstance(text, str) else ""
    target = expect.get("target")
    if kind == tests_api.TEXT_VISIBLE:
        return bool(wanted.strip()) and matches_text(snapshot.text, wanted)
    if kind == tests_api.TEXT_ABSENT:
        return bool(wanted.strip()) and not matches_text(snapshot.text, wanted)
    if kind == tests_api.URL_CONTAINS:
        return bool(wanted.strip()) and matches_text(snapshot.url, wanted)
    if kind == tests_api.TITLE_CONTAINS:
        return bool(wanted.strip()) and matches_text(snapshot.title, wanted)
    if not isinstance(target, Mapping):
        return False
    element = resolve_target(snapshot, target)
    if kind == tests_api.ELEMENT_VISIBLE:
        return element is not None
    if kind == tests_api.ELEMENT_ABSENT:
        return element is None
    if kind == tests_api.VALUE_IS:
        return element is not None and _text(element.value) == _text(wanted)
    return False


def open_address(site: Site, value: str, *, program: str = "") -> str:
    text = value.strip()
    try:
        parts = urlsplit(text)
    except ValueError:
        raise BrowserError(
            "ACTION_FAILED", program=program, detail=f"not an address of the application: {text}"
        ) from None
    scheme = parts.scheme.lower()
    if scheme in WEB_SCHEMES and parts.netloc:
        if site.static and is_loopback(parts.hostname or ""):
            base = urlsplit(site.base)
            return urlunsplit(
                (base.scheme, base.netloc, parts.path or "/", parts.query, parts.fragment)
            )
        return text
    if scheme:
        raise BrowserError(
            "ACTION_FAILED", program=program, detail=f"not an address of the application: {text}"
        )
    relative = text.lstrip("/")
    if not relative:
        return site.base
    return urljoin(directory_of(site.base), relative)


def directory_of(address: str) -> str:
    parts = urlsplit(address)
    path = parts.path or "/"
    if not path.endswith("/"):
        last = path.rsplit("/", 1)[-1]
        path = path[: len(path) - len(last)] if "." in last else f"{path}/"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def screenshot_path(code: str, browser: str, index: int) -> str:
    return f"{_segment(code)}/{_segment(browser)}/{index:02d}.png"


def _approved(found: FolderSummary, stage: str) -> bool:
    entry = found.stage(stage)
    return (
        stage in found.progress
        and entry is not None
        and entry.version_number is not None
        and entry.gate_status == APPROVED
    )


def _stage_number(found: FolderSummary, stage: str) -> int | None:
    entry = found.stage(stage)
    return None if entry is None else entry.version_number


def _version(page: Page) -> str:
    version = getattr(page, "version", "")
    text = _text(version)[: tests_api.MAX_BROWSER_VERSION_LENGTH]
    return text or UNKNOWN_VERSION


def _close(page: Page) -> None:
    with contextlib.suppress(BrowserError):
        page.close()


def _error_detail(error: CliError) -> str:
    detail = error.values.get("detail")
    return str(detail) if detail else error.code


def _heading(path: Mapping[str, object]) -> str:
    return _text(path.get("heading")).rstrip(". ") or "-"


def _segment(value: str) -> str:
    cleaned = UNSAFE_SEGMENT.sub("_", value).strip("_")
    return cleaned or "path"


def _url(snapshot: PageSnapshot | None) -> str | None:
    return None if snapshot is None else snapshot.url


def _title(snapshot: PageSnapshot | None) -> str | None:
    return None if snapshot is None else snapshot.title
