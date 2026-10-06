from __future__ import annotations

import contextlib
import os
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final
from urllib.parse import urljoin, urlsplit, urlunsplit

from orchestwin.cli import costs, jobs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.browser import (
    BrowserError,
    PageSnapshot,
    find_browsers,
    matches_text,
    open_page,
    resolve_target,
)
from orchestwin.cli.console import ProgressOutcome
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import (
    publish,
    task_selection,
    test_plan,
    test_report,
    test_settings,
    verify_review,
)
from orchestwin.cli.flows.test_server import StaticServer
from orchestwin.cli.http import is_loopback
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.browser import BrowserProgram, Page
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.test_plan import PlanChoice, SavedPlan
    from orchestwin.cli.flows.test_report import Names
    from orchestwin.cli.flows.test_settings import TestSettings
    from orchestwin.cli.folder import FolderSummary
    from orchestwin.cli.project import ProjectFolder

COMMAND: Final = "test"
APPROVED: Final = "APPROVED"
INDEX_PAGE: Final = "index.html"
EXPECT_ATTEMPTS: Final = 4
EXPECT_PAUSE_SECONDS: Final = 0.4
REVIEW_LIMIT_SECONDS: Final = 900.0
TOLERANCE: Final = 1e-9
UNKNOWN_VERSION: Final = "unknown"
WEB_SCHEMES: Final = ("http", "https")
STAGES: Final = ("requirements", "design")
SPENDING_REFUSED: Final = "SPENDING_REFUSED"
INTERRUPTED: Final = "GENERATION_INTERRUPTED"
INPUT_CLOSED: Final = "INPUT_CLOSED"
CRITERION_PATTERN: Final = re.compile(r"AC-[0-9]{3,6}")
UNSAFE_SEGMENT: Final = re.compile(r"[^A-Za-z0-9_-]+")
UNSAFE_FOLDER: Final = re.compile(r"[\\:]+")
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
class Application:
    kind: str
    address: str
    location: str
    saved: Mapping[str, str]
    direct: bool

    @property
    def static(self) -> bool:
        return self.kind == tests_api.STATIC

    def document(self) -> dict[str, str]:
        return {"kind": self.kind, "address": self.address}


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
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    link = project.link()
    client = context.client()
    session = context.sessions.read(client.studio)
    if session is None or not session.signed_in:
        raise CliError("NOT_SIGNED_IN", values={"studio": client.studio.origin})
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


def chosen_application(
    context: CommandContext,
    project: ProjectFolder,
    requested: Mapping[str, object] | None,
    settings: TestSettings | None,
) -> Application:
    if requested is not None:
        return application_of(project, requested, base=context.directory)
    if settings is not None and settings.application is not None:
        return application_of(project, settings.application, base=project.root)
    raise CliError("TEST_APPLICATION_REQUIRED", status=USAGE_STATUS)


def application_of(
    project: ProjectFolder, value: Mapping[str, object], *, base: Path
) -> Application:
    kind = str(value.get("kind") or "").strip().upper()
    address = str(value.get("address") or "").strip()
    if kind == tests_api.URL:
        return url_application(address)
    if kind == tests_api.STATIC:
        return static_application(project, address, base=base)
    raise CliError("TEST_APPLICATION_REQUIRED", status=USAGE_STATUS)


def url_application(address: str) -> Application:
    try:
        parts = urlsplit(address)
        host = parts.hostname
    except ValueError:
        parts, host = None, None
    if (
        parts is None
        or not host
        or parts.scheme.lower() not in WEB_SCHEMES
        or len(address) > tests_api.MAX_ADDRESS_LENGTH
        or any(character.isspace() for character in address)
    ):
        raise CliError("TEST_URL_INVALID", status=USAGE_STATUS, values={"address": address})
    return Application(
        kind=tests_api.URL,
        address=address,
        location=address,
        saved={"kind": tests_api.URL, "address": address},
        direct=is_loopback(host),
    )


def static_application(project: ProjectFolder, address: str, *, base: Path) -> Application:
    path = Path(address) if address else Path()
    folder = Path(os.path.abspath(path if path.is_absolute() else base / path))
    if not address or not folder.is_dir() or not (folder / INDEX_PAGE).is_file():
        raise CliError(
            "TEST_STATIC_INVALID", status=USAGE_STATUS, values={"folder": address or "-"}
        )
    root = Path(os.path.abspath(project.root))
    try:
        relative: PurePosixPath | None = PurePosixPath(folder.relative_to(root).as_posix())
    except ValueError:
        relative = None
    return Application(
        kind=tests_api.STATIC,
        address=static_address(folder, relative),
        location=str(folder),
        saved={
            "kind": tests_api.STATIC,
            "address": str(folder) if relative is None else relative.as_posix(),
        },
        direct=True,
    )


def static_address(folder: Path, relative: PurePosixPath | None) -> str:
    if relative is None:
        parts = [folder.name]
    else:
        parts = [part for part in relative.parts if part not in ("", ".")]
        if not parts:
            return "."
    cleaned = [UNSAFE_FOLDER.sub("-", part).strip() or "-" for part in parts]
    cleaned = ["-" if part in (".", "..") else part for part in cleaned]
    text = "/".join(cleaned)[: tests_api.MAX_ADDRESS_LENGTH].strip("/")
    return text or "-"


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
        saved_at=_now_text(context),
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
    updated = saved.with_replan(plan, saved_at=_now_text(context), weak=weak)
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


def run_body(
    ready: Prepared,
    execution: Execution,
    browsers: Sequence[Browser],
    *,
    started: object,
    finished: object,
) -> dict[str, object]:
    wanted = set(ready.criteria)
    not_covered = [
        {
            "criterion": str(item["criterion"]),
            "reason": _cut(_text(item.get("reason")), tests_api.MAX_REASON_LENGTH),
        }
        for item in execution.saved.not_covered()
        if _text(item.get("reason")) and (not wanted or item.get("criterion") in wanted)
    ]
    return {
        "plan_id": execution.saved.plan_id,
        "replan_ids": execution.saved.replan_ids,
        "started_at": _moment(started),
        "finished_at": _moment(finished),
        "application": ready.application.document(),
        "browsers": [browser.document() for browser in browsers],
        "results": [outcome.document() for outcome in execution.results][: tests_api.MAX_RESULTS],
        "not_covered": not_covered,
    }


def recorded_run(document: Mapping[str, object]) -> Mapping[str, object]:
    run = document.get("run")
    if not isinstance(run, Mapping) or not isinstance(run.get("id"), str):
        raise ApiFailure("API_FAILURE", http_status=201)
    return run


def write_files(
    context: CommandContext,
    ready: Prepared,
    folder: Path,
    run: Mapping[str, object],
    names: Names,
    labels: Mapping[str, str],
    first_attempt: Sequence[Mapping[str, object]],
    weak: Sequence[Mapping[str, object]] = (),
) -> Path:
    test_report.write_run(folder, run, first_attempt=first_attempt)
    test_report.write_latest(test_plan.tests_folder(ready.project), folder, run)
    return test_report.write_report(
        context,
        folder,
        run,
        project_name=ready.project_name,
        names=names,
        labels=labels,
        first_attempt=first_attempt,
        weak=weak,
    )


def review_run(
    context: CommandContext,
    ready: Prepared,
    run: Mapping[str, object],
    *,
    available: bool,
) -> Mapping[str, object] | None:
    console = context.console
    console.write()
    if not available:
        console.say("test.review_unavailable")
        return None
    try:
        return reviewed(context, ready, run)
    except CliError as error:
        if error.code == INTERRUPTED:
            raise
        if error.code == SPENDING_REFUSED:
            console.say("test.review_skipped")
        elif error.code == tests_api.NO_TEST_MODEL:
            console.say("test.review_unavailable")
        else:
            say_error(context, error)
        return None


def reviewed(
    context: CommandContext, ready: Prepared, run: Mapping[str, object]
) -> Mapping[str, object]:
    twins = verify_review.twins_count(ready.client, ready.project)
    context.console.say("test.reviewing", twins=twins)
    costs.confirm_spending(context, ready.client, [tests_api.REVIEW_OPERATION] * twins)
    run_id = str(run.get("id") or "")
    result = jobs.generate(
        context,
        ready.client,
        ready.project_id,
        tests_api.review_path(ready.project_id, run_id),
        tests_api.review_body(ready.locale),
        label=context.text("test.review_label"),
        limit_seconds=REVIEW_LIMIT_SECONDS,
    )
    if result.status_code < 400:
        review = result.body.get("review") if isinstance(result.body, Mapping) else None
        if not isinstance(review, Mapping):
            raise ApiFailure("API_FAILURE", http_status=result.status_code)
        return review
    if tests_api.code_of(result.body) == tests_api.REVIEW_EXISTS:
        found = tests_api.reviews(ready.client, ready.project_id, run_id)
        if found:
            return found[0]
    raise test_plan.refusal(
        context,
        ready.client,
        ready.project,
        result.status_code,
        result.body,
        tests_api.REVIEW_OPERATION,
    )


def with_review(run: Mapping[str, object], review: Mapping[str, object]) -> dict[str, object]:
    cost = run.get("cost_microusd")
    added = review.get("cost_microusd")
    total = cost if isinstance(cost, int) and not isinstance(cost, bool) else 0
    if isinstance(added, int) and not isinstance(added, bool):
        total += added
    return {
        **run,
        "critiques": [dict(item) for item in tests_api.critiques_of(review)],
        "reviewed_at": review.get("reviewed_at"),
        "cost_microusd": total,
    }


def open_tasks(ready: Prepared) -> tuple[Mapping[str, object], ...]:
    try:
        document = changes_api.alignment(ready.client, ready.project_id)
    except CliError:
        return ()
    return tuple(changes_api.open_tasks(document))


def passed_tasks(
    context: CommandContext, run: Mapping[str, object], tasks: Sequence[Mapping[str, object]]
) -> None:
    passed = {
        str(item.get("code"))
        for item in tests_api.criteria_of(run)
        if item.get("status") == tests_api.PASSED and isinstance(item.get("code"), str)
    }
    if not passed:
        return
    for task in tasks:
        codes = [code for code in tasks_api.criteria_of(task) if code in passed]
        if tasks_api.is_open(task) and codes:
            code = tasks_api.task_code(task)
            context.console.say("test.task_maybe_done", task=code, criteria=", ".join(codes))


def offer_tasks(
    context: CommandContext,
    ready: Prepared,
    run: Mapping[str, object],
    tasks: Sequence[Mapping[str, object]],
) -> None:
    console = context.console
    candidates = task_selection.candidates_of_run(run, tasks)
    if not any(item.offered for item in candidates):
        return
    console.write()
    console.say("test.tasks_intro")
    try:
        chosen = task_selection.choose(context, candidates, question_key="test.tasks_question")
    except CliError as error:
        if error.code != INPUT_CLOSED:
            raise
        console.say("test.tasks_later")
        return
    if not chosen:
        console.say("test.tasks_none")
        return
    items = [tasks_api.finding_item(item.source) for item in chosen if item.source is not None]
    try:
        count, created = tasks_api.create_all(ready.client, ready.project_id, items)
    except CliError as error:
        console.say("test.tasks_failed", code=_error_code(error))
        return
    console.say("test.tasks_created", count=count)
    console.items([f"{tasks_api.task_code(task)}: {tasks_api.task_text(task)}" for task in created])
    console.say("test.tasks_next")


def publish_folder(context: CommandContext, ready: Prepared) -> None:
    console = context.console
    console.write()
    try:
        found = publish.publish_and_pull(context, ready.client, ready.project)
    except CliError as error:
        console.say("test.folder_not_updated", code=_error_code(error))
        return
    console.say("test.folder_updated", version=found.version_number)


def say_error(context: CommandContext, error: CliError) -> None:
    key = error_key(error)
    if key is None:
        context.console.say("test.review_failed", code=error.code)
        return
    context.console.say(key, **error.values)


def error_key(error: CliError) -> str | None:
    reason = error.values.get("reason")
    candidates: list[str] = []
    if isinstance(reason, str) and reason:
        candidates.extend(
            (f"{COMMAND}.errors.{error.code}.{reason}", f"errors.{error.code}.{reason}")
        )
    candidates.extend((f"{COMMAND}.errors.{error.code}", f"errors.{error.code}"))
    return next((key for key in candidates if known(key)), None)


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


def _error_code(error: CliError) -> str:
    inner = error.values.get("code")
    return str(inner) if isinstance(inner, str) and inner else error.code


def _heading(path: Mapping[str, object]) -> str:
    return _text(path.get("heading")).rstrip(". ") or "-"


def _segment(value: str) -> str:
    cleaned = UNSAFE_SEGMENT.sub("_", value).strip("_")
    return cleaned or "path"


def _moment(value: object) -> str:
    isoformat = getattr(value, "isoformat", None)
    return str(isoformat(timespec="seconds")) if callable(isoformat) else str(value)


def _now_text(context: CommandContext) -> str:
    return context.environment.now().isoformat(timespec="seconds")


def _url(snapshot: PageSnapshot | None) -> str | None:
    return None if snapshot is None else snapshot.url


def _title(snapshot: PageSnapshot | None) -> str | None:
    return None if snapshot is None else snapshot.title


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
