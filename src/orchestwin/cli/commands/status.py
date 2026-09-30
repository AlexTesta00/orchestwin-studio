from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.api import usage
from orchestwin.cli.costs import usd_text
from orchestwin.cli.errors import SIGN_IN_STATUS, ApiFailure, CliError
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.messages import known
from orchestwin.cli.project import STEP_STAGES, read_json

if TYPE_CHECKING:
    from orchestwin.cli.api.tests import AcceptanceSummary
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary, StateSummary
    from orchestwin.cli.project import ProjectFolder, ProjectLink

NAME = "status"
SCHEMA_VERSION: Final = 1
HEALTHY: Final = 200
SHORT_COMMIT: Final = 7
DESIGN_STAGE: Final = "design"
FEEDBACK_TESTS: Final = "twins/feedback/tests.json"
FROM_STUDIO: Final = "studio"
FROM_FOLDER: Final = "folder"
REQUESTED: Final = "requested"
UNREACHABLE: Final = "unreachable"
NOT_SIGNED_IN: Final = "not_signed_in"
SESSION_EXPIRED: Final = "session_expired"
PROJECT_MISSING: Final = "project_missing"
REASONS: Final = (REQUESTED, UNREACHABLE, NOT_SIGNED_IN, SESSION_EXPIRED, PROJECT_MISSING)
STATE_KEYS: Final = {
    project_api.APPROVED: "status.state_approved",
    project_api.WAITING: "status.state_waiting",
    project_api.TODO: "status.state_todo",
    project_api.LATER: "status.state_later",
    project_api.READY: "status.state_ready",
}
MODE_KEYS: Final = {
    "DESIGN_ONLY": "status.mode_design_only",
    "DESIGN_AND_CODE": "status.mode_design_and_code",
}
STAGE_ORDER: Final = {
    code: index
    for index, code in enumerate(project_api.STAGE_CODES[stage] for stage in project_api.STAGES)
}


@dataclass(frozen=True, slots=True)
class Report:
    source: str
    reason: str | None
    studio: str
    project_id: str
    name: str
    mode: str
    language: str | None
    root: str
    current_stage: str
    next_action: str
    steps: tuple[project_api.StepState, ...]
    local_version: int | None
    local_error: str | None
    studio_version: int | None
    has_budget: bool
    spent_usd: float | None
    remaining_usd: float | None
    alignment: StateSummary | None = None
    local_complete: bool = False
    tests: AcceptanceSummary | None = None

    @property
    def folder_current(self) -> bool:
        if self.studio_version is not None:
            return self.local_version is not None and self.local_version == self.studio_version
        return self.source == FROM_FOLDER and self.local_complete

    def document(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "kind": "project",
            "source": self.source,
            "reason": self.reason,
            "studio": self.studio,
            "project": {
                "id": self.project_id,
                "name": self.name,
                "mode": self.mode,
                "language": self.language,
                "root": self.root,
            },
            "current_stage": self.current_stage,
            "next_action": self.next_action,
            "next_command": project_api.next_command(
                self.next_action, folder_current=self.folder_current
            ),
            "steps": [
                {
                    "stage": step.stage,
                    "state": step.state,
                    "version": step.version,
                    "approved": step.approved,
                }
                for step in self.steps
            ],
            "knowledge_folder": {
                "local_version": self.local_version,
                "studio_version": self.studio_version,
                "local_error": self.local_error,
            },
            "spending": (
                {
                    "currency": "USD",
                    "project_spent_usd": _rounded(self.spent_usd),
                    "remaining_usd": _rounded(self.remaining_usd),
                }
                if self.has_budget
                else None
            ),
            "alignment": (
                None
                if self.alignment is None
                else {
                    "recorded": self.alignment.changes,
                    "pending": self.alignment.pending_changes,
                    "aligned_commit": self.alignment.aligned_commit,
                    "open_tasks": self.alignment.open_tasks,
                }
            ),
            "tests": None if self.tests is None else self.tests.document(),
        }


@dataclass(frozen=True, slots=True)
class _Studio:
    project: Mapping[str, object]
    steps: tuple[project_api.StepState, ...]
    has_budget: bool
    spent_usd: float | None
    remaining_usd: float | None
    alignment: StateSummary | None = None
    tests: AcceptanceSummary | None = None


def configure(parser: argparse.ArgumentParser) -> None:
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--offline", action="store_true", help="status.option_offline")
    sources.add_argument("--all", action="store_true", help="status.option_all")
    parser.add_argument("--json", action="store_true", help="status.option_json")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project(required=False)
    if project is None or arguments.all:
        if arguments.offline:
            raise CliError("PROJECT_NOT_LINKED")
        return _projects(context, project, as_json=arguments.json)
    report = project_report(context, project, offline=arguments.offline)
    if arguments.json:
        _print_json(context, report.document())
    else:
        show(context, report)
    return 0


def project_report(context: CommandContext, project: ProjectFolder, *, offline: bool) -> Report:
    link = project.link()
    local, local_error = _local_summary(project)
    client = context.client()
    if offline:
        return _folder_report(project, link, local, local_error, client.studio.origin, REQUESTED)
    found = _studio_facts(context, client, link)
    if isinstance(found, str):
        return _folder_report(project, link, local, local_error, client.studio.origin, found)
    name = found.project.get("display_name")
    stage = found.project.get("current_stage")
    action = found.project.get("next_action")
    current = project_api.current_stage(found.steps)
    return Report(
        source=FROM_STUDIO,
        reason=None,
        studio=client.studio.origin,
        project_id=link.project_id,
        name=name if isinstance(name, str) and name else link.project_name,
        mode=link.mode,
        language=link.language,
        root=str(project.root),
        current_stage=stage if isinstance(stage, str) else current,
        next_action=action if isinstance(action, str) else project_api.STAGE_ACTIONS[current],
        steps=found.steps,
        local_version=None if local is None else local.version_number,
        local_error=local_error,
        studio_version=found.steps[-1].version,
        has_budget=found.has_budget,
        spent_usd=found.spent_usd,
        remaining_usd=found.remaining_usd,
        alignment=found.alignment,
        tests=found.tests if found.tests is not None else local_tests(project),
    )


def show(context: CommandContext, report: Report) -> None:
    console = context.console
    console.heading(report.name)
    console.say("status.studio", studio=report.studio)
    mode_key = MODE_KEYS.get(report.mode)
    console.say("status.mode", mode=context.text(mode_key) if mode_key else report.mode)
    if report.reason is not None:
        console.say(f"status.offline_{report.reason}", studio=report.studio)
    console.write()
    console.table(
        [
            context.text("status.column_step"),
            context.text("status.column_state"),
            context.text("status.column_version"),
        ],
        [
            [
                context.text(f"common.stage_{step.stage}"),
                context.text(STATE_KEYS[step.state]),
                "-" if step.version is None else str(step.version),
            ]
            for step in report.steps
        ],
    )
    console.write()
    if report.next_action == project_api.DOWNLOAD_FOLDER and report.folder_current:
        console.say("status.next", action=context.text("status.next_folder_current"))
    else:
        console.say("status.next", action=next_action_text(context, report.next_action))
    _folder_lines(context, report)
    if report.alignment is not None:
        show_alignment(context, report.alignment)
    if report.tests is not None:
        show_tests(context, report.tests)
    _spending_line(context, report)


def show_alignment(context: CommandContext, summary: StateSummary) -> None:
    console = context.console
    if summary.changes == 0:
        console.say("status.alignment_none")
    elif summary.aligned_commit is None:
        console.say(
            "status.alignment_not_aligned",
            recorded=summary.changes,
            pending=summary.pending_changes,
            tasks=summary.open_tasks,
        )
    else:
        console.say(
            "status.alignment",
            recorded=summary.changes,
            pending=summary.pending_changes,
            commit=summary.aligned_commit[:SHORT_COMMIT],
            tasks=summary.open_tasks,
        )


def show_tests(context: CommandContext, tests: AcceptanceSummary) -> None:
    if tests.runs <= 0 or (tests.latest_id is None and tests.finished_at is None):
        return
    numbers = tests.summary
    context.console.say(
        "status.tests",
        date=moment_text(tests.finished_at),
        passed=numbers.get("passed", 0),
        failed=numbers.get("failed", 0),
        blocked=numbers.get("blocked", 0),
        not_covered=numbers.get("not_covered", 0),
    )


def local_tests(project: ProjectFolder) -> AcceptanceSummary | None:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    feedback = manifest.get("feedback") if isinstance(manifest, Mapping) else None
    count = feedback.get("test_runs") if isinstance(feedback, Mapping) else None
    if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
        return None
    named = feedback.get("tests")
    relative = named if isinstance(named, str) and _inside(named) else FEEDBACK_TESTS
    document = read_json(project.knowledge.joinpath(*relative.split("/")))
    runs = tests_api.mappings(document.get("runs")) if isinstance(document, Mapping) else []
    return tests_api.run_summary_of(runs[0] if runs else None, count)


def next_action_text(context: CommandContext, code: str) -> str:
    key = f"common.next_{code.lower()}"
    if code and known(key):
        return context.text(key)
    return context.text("common.next_unknown", code=code)


def _projects(context: CommandContext, project: ProjectFolder | None, *, as_json: bool) -> int:
    client = context.client()
    items = project_api.list_projects(client)
    linked = _linked_project(project)
    if as_json:
        _print_json(
            context,
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "projects",
                "studio": client.studio.origin,
                "projects": [
                    {
                        "id": item.get("id"),
                        "name": item.get("display_name"),
                        "current_stage": item.get("current_stage"),
                        "next_action": item.get("next_action"),
                        "next_command": project_api.NEXT_COMMANDS.get(str(item.get("next_action"))),
                        "linked": linked is not None and item.get("id") == linked,
                    }
                    for item in items
                ],
            },
        )
        return 0
    console = context.console
    console.heading(context.text("status.projects_heading", studio=client.studio.origin))
    if not items:
        console.say("status.no_projects")
        return 0
    console.table(
        [
            context.text("status.column_project"),
            context.text("status.column_step"),
            context.text("status.column_turn"),
        ],
        [_project_row(context, item, linked) for item in items],
    )
    return 0


def _project_row(
    context: CommandContext, item: Mapping[str, object], linked: str | None
) -> list[str]:
    name = str(item.get("display_name") or "")
    if linked is not None and item.get("id") == linked:
        name = context.text("status.this_folder", name=name)
    stage = str(item.get("current_stage") or "")
    index = STAGE_ORDER.get(stage)
    position = (
        stage
        if index is None
        else context.text(
            "status.step_position",
            number=index + 1,
            total=len(project_api.STAGES),
            stage=context.text(f"common.stage_{project_api.STAGES[index]}"),
        )
    )
    return [name, position, next_action_text(context, str(item.get("next_action") or ""))]


def _studio_facts(
    context: CommandContext, client: StudioClient, link: ProjectLink
) -> _Studio | str:
    session = context.sessions.read(client.studio)
    if session is None or not session.signed_in:
        return NOT_SIGNED_IN
    try:
        if client.health().status != HEALTHY:
            return UNREACHABLE
        found = project_api.get_project(client, link.project_id)
        steps = project_api.step_states(client, link.project_id)
        approved = _design_approved(steps)
        alignment = changes_api.summary(client, link.project_id) if approved else None
        tests = tests_api.summary(client, link.project_id) if approved else None
        has_budget, spent, remaining = _spending(client, link.project_id)
    except CliError as error:
        reason = _offline_reason(error)
        if reason is None:
            raise
        return reason
    return _Studio(found, steps, has_budget, spent, remaining, alignment, tests)


def _design_approved(steps: tuple[project_api.StepState, ...]) -> bool:
    return any(step.stage == DESIGN_STAGE and step.approved for step in steps)


def _offline_reason(error: CliError) -> str | None:
    if error.code == "STUDIO_UNREACHABLE":
        return UNREACHABLE
    if error.code == "NOT_SIGNED_IN":
        return NOT_SIGNED_IN
    if error.status == SIGN_IN_STATUS:
        return SESSION_EXPIRED
    if isinstance(error, ApiFailure) and error.http_status == 404:
        return PROJECT_MISSING
    return None


def _spending(client: StudioClient, project_id: str) -> tuple[bool, float | None, float | None]:
    try:
        budget = usage.budget(client)
        if budget is None:
            return False, None, None
        used = usage.project_usage(client, project_id)
    except ApiFailure as failure:
        if failure.http_status >= 500:
            return False, None, None
        raise
    spent = None if used is None else usage.spent_usd(used)
    return True, spent, usage.remaining_usd(budget)


def _local_summary(project: ProjectFolder) -> tuple[FolderSummary | None, str | None]:
    try:
        return knowledge.summary(project.knowledge), None
    except CliError as error:
        return None, str(error.values.get("code", error.code))


def _folder_report(
    project: ProjectFolder,
    link: ProjectLink,
    local: FolderSummary | None,
    local_error: str | None,
    studio: str,
    reason: str,
) -> Report:
    steps = folder_steps(project, local)
    current = project_api.current_stage(steps)
    state = None if local is None else local.state
    return Report(
        source=FROM_FOLDER,
        reason=reason,
        studio=studio,
        project_id=link.project_id,
        name=link.project_name,
        mode=link.mode,
        language=link.language,
        root=str(project.root),
        current_stage=current,
        next_action=project_api.STAGE_ACTIONS[current],
        steps=steps,
        local_version=None if local is None else local.version_number,
        local_error=local_error,
        studio_version=None,
        has_budget=False,
        spent_usd=None,
        remaining_usd=None,
        alignment=state if _design_approved(steps) else None,
        local_complete=local is not None
        and local.complete
        and set(knowledge.FOLDER_STAGES) <= set(local.progress),
        tests=local_tests(project),
    )


def folder_steps(
    project: ProjectFolder, local: FolderSummary | None
) -> tuple[project_api.StepState, ...]:
    saved = project.steps()
    facts: list[tuple[str, int | None, bool]] = []
    for stage in STEP_STAGES:
        entry = None if local is None or stage not in local.progress else local.stage(stage)
        if entry is not None and entry.version_number is not None:
            facts.append((stage, entry.version_number, entry.gate_status == project_api.APPROVED))
            continue
        document = saved.get(stage)
        version = None if document is None else document.get("version")
        number = version.get("version_number") if isinstance(version, Mapping) else None
        valid = isinstance(number, int) and not isinstance(number, bool)
        facts.append((stage, number if valid else None, document is not None))
    facts.append(("package", None if local is None else local.version_number, facts[-1][2]))
    return project_api.arrange(facts)


def _folder_lines(context: CommandContext, report: Report) -> None:
    console = context.console
    if report.local_error is not None:
        console.say("status.folder_unreadable", code=report.local_error)
    local, studio = report.local_version, report.studio_version
    if local is not None and studio is not None:
        console.say("status.folder_both", local=local, studio=studio)
        if local < studio:
            console.say("status.folder_older")
    elif studio is not None:
        console.say("status.folder_only_studio", studio=studio)
    elif local is not None:
        console.say("status.folder_only_local", local=local)
    elif report.source == FROM_STUDIO and report.local_error is None:
        console.say("status.folder_none")


def _spending_line(context: CommandContext, report: Report) -> None:
    if not report.has_budget:
        return
    language = context.language
    spent, remaining = report.spent_usd, report.remaining_usd
    if spent is not None and remaining is not None:
        context.console.say(
            "status.spending",
            spent=usd_text(spent, language),
            remaining=usd_text(remaining, language),
        )
    elif spent is not None:
        context.console.say("status.spending_no_credit", spent=usd_text(spent, language))
    elif remaining is not None:
        context.console.say("status.credit_only", remaining=usd_text(remaining, language))


def _linked_project(project: ProjectFolder | None) -> str | None:
    if project is None:
        return None
    try:
        return project.link().project_id
    except CliError:
        return None


def _inside(path: str) -> bool:
    parts = path.split("/")
    return (
        bool(path)
        and "\\" not in path
        and ":" not in path
        and all(part not in ("", ".", "..") for part in parts)
    )


def _print_json(context: CommandContext, document: Mapping[str, object]) -> None:
    context.console.write(json.dumps(document, indent=2, ensure_ascii=True))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)
