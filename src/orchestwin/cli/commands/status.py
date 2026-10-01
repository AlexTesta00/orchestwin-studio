from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.api import usage
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.costs import usd_text
from orchestwin.cli.errors import SIGN_IN_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import design_state
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.messages import known
from orchestwin.cli.project import STEP_STAGES, read_json

if TYPE_CHECKING:
    from orchestwin.cli.api.sections import Sections
    from orchestwin.cli.api.tests import AcceptanceSummary
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.folder import FolderSummary, StateSummary
    from orchestwin.cli.project import ProjectFolder, ProjectLink

NAME = "status"
SCHEMA_VERSION: Final = 1
HEALTHY: Final = 200
SERVER_ERROR: Final = 500
SHORT_COMMIT: Final = 7
DESIGN_STAGE: Final = "design"
TWINS_STAGE: Final = "twins"
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
class TwinLearning:
    twin_id: str
    name: str
    label: str
    observations: int

    def document(self) -> dict[str, object]:
        return {
            "twin_id": self.twin_id,
            "name": self.name,
            "label": self.label,
            "observations": self.observations,
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
    stale_reviews: int = 0
    learning: tuple[TwinLearning, ...] | None = None
    billing: str = usage.API_BILLING
    sections: Sections | None = None

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
                    "billing": self.billing,
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
                    "stale_reviews": self.stale_reviews,
                }
            ),
            "tests": None if self.tests is None else self.tests.document(),
            "learning": (
                {"twins": [twin.document() for twin in self.learning]} if self.learning else None
            ),
            "sections": None if self.sections is None else dict(self.sections.document),
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
    stale_reviews: int = 0
    learning: tuple[TwinLearning, ...] | None = None
    billing: str = usage.API_BILLING
    sections: Sections | None = None


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
        stale_reviews=found.stale_reviews,
        learning=found.learning if found.learning is not None else local_learning(project),
        billing=found.billing,
        sections=found.sections,
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
    found = report.sections
    if found is not None and found.first_pass_complete:
        sections_command.table(context, found)
    else:
        steps_table(context, report.steps)
    console.write()
    for line in () if found is None else sections_command.sentences(context, found):
        console.write(line)
    next_lines(context, report)
    _folder_lines(context, report)
    if report.alignment is not None:
        show_alignment(context, report.alignment, stale_reviews=report.stale_reviews)
    if report.tests is not None:
        show_tests(context, report.tests)
    show_learning(context, report.learning)
    _spending_line(context, report)


def steps_table(context: CommandContext, steps: tuple[project_api.StepState, ...]) -> None:
    context.console.table(
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
            for step in steps
        ],
    )


def next_lines(context: CommandContext, report: Report) -> None:
    console = context.console
    found = report.sections
    if found is not None and any(
        section.key != sections_api.PACKAGE or section.blocked is None
        for section in found.behind(
            sections_api.SECTION_KEYS if found.first_pass_complete else sections_api.UPSTREAM
        )
    ):
        return
    if found is not None and found.first_pass_complete:
        waiting = found.in_progress()
        action = None if waiting is None else project_api.STAGE_ACTIONS.get(waiting.key)
        if action is not None:
            console.say("status.next", action=next_action_text(context, action))
            return
    if report.next_action == project_api.DOWNLOAD_FOLDER and report.folder_current:
        console.say("status.next", action=context.text("status.next_folder_current"))
        design_state.show_next_commands(context)
        return
    console.say("status.next", action=next_action_text(context, report.next_action))


def show_alignment(
    context: CommandContext, summary: StateSummary, *, stale_reviews: int = 0
) -> None:
    if summary.changes == 0:
        line = context.text("status.alignment_none")
    elif summary.aligned_commit is None:
        line = context.text(
            "status.alignment_not_aligned",
            recorded=summary.changes,
            pending=summary.pending_changes,
            tasks=summary.open_tasks,
        )
    else:
        line = context.text(
            "status.alignment",
            recorded=summary.changes,
            pending=summary.pending_changes,
            commit=summary.aligned_commit[:SHORT_COMMIT],
            tasks=summary.open_tasks,
        )
    if stale_reviews > 0:
        stale = context.text("status.stale_reviews", count=stale_reviews)
        line = f"{line} {stale}"
    context.console.write(line)


def show_learning(context: CommandContext, learning: tuple[TwinLearning, ...] | None) -> None:
    if not learning or not any(twin.observations > 0 for twin in learning):
        return
    twins = "; ".join(
        context.text(
            "status.learning_twin", name=twin.name, label=twin.label, count=twin.observations
        )
        for twin in learning
    )
    context.console.say("status.learning", twins=twins)


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


def local_learning(project: ProjectFolder) -> tuple[TwinLearning, ...] | None:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    feedback = manifest.get("feedback") if isinstance(manifest, Mapping) else None
    named = feedback.get("learned") if isinstance(feedback, Mapping) else None
    if not isinstance(named, str) or not _inside(named):
        return None
    document = read_json(project.knowledge.joinpath(*named.split("/")))
    if not isinstance(document, Mapping):
        return None
    return learning_of(document.get("twins"))


def local_stale_reviews(project: ProjectFolder) -> int:
    manifest = read_json(project.knowledge / knowledge.MANIFEST_NAME)
    state = manifest.get("state") if isinstance(manifest, Mapping) else None
    value = state.get("stale_reviews") if isinstance(state, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def learning_of(entries: object) -> tuple[TwinLearning, ...]:
    found: list[TwinLearning] = []
    for entry in entries if isinstance(entries, list | tuple) else ():
        if not isinstance(entry, Mapping):
            continue
        twin_id = entry.get("twin_id")
        if not isinstance(twin_id, str) or not twin_id:
            continue
        name = entry.get("twin_name")
        observations = entry.get("observations")
        count = (
            sum(1 for item in observations if isinstance(item, Mapping))
            if isinstance(observations, list)
            else 0
        )
        found.append(
            TwinLearning(
                twin_id=twin_id,
                name=" ".join(name.split()) if isinstance(name, str) and name.strip() else "-",
                label=learning_label(entry),
                observations=count,
            )
        )
    return tuple(found)


def learning_label(entry: Mapping[str, object]) -> str:
    label = entry.get("label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    profile = entry.get("profile_version_number")
    development = entry.get("development_version_number")
    if all(
        isinstance(value, int) and not isinstance(value, bool) for value in (profile, development)
    ):
        return f"{profile}.{development}"
    return "-"


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
        sections = studio_sections(client, link.project_id)
        approved = _design_approved(steps)
        development = changes_api.development(client, link.project_id) if approved else None
        tests = tests_api.summary(client, link.project_id) if approved else None
        learning = studio_learning(client, link.project_id) if _twins_approved(steps) else None
        has_budget, spent, remaining, billing = _spending(client, link.project_id)
    except CliError as error:
        reason = _offline_reason(error)
        if reason is None:
            raise
        return reason
    return _Studio(
        found,
        steps,
        has_budget,
        spent,
        remaining,
        alignment=None if development is None else development.summary,
        tests=tests,
        stale_reviews=0 if development is None else development.stale_reviews,
        learning=learning,
        billing=billing,
        sections=sections,
    )


def studio_sections(client: StudioClient, project_id: str) -> Sections | None:
    try:
        return sections_api.sections(client, project_id)
    except ApiFailure as failure:
        if failure.http_status >= SERVER_ERROR or failure.http_status == HEALTHY:
            return None
        raise


def studio_learning(client: StudioClient, project_id: str) -> tuple[TwinLearning, ...] | None:
    try:
        document = client.get(f"/projects/{project_id}/twin-learning")
    except ApiFailure as failure:
        if failure.http_status in changes_api.MISSING_ROUTE or failure.http_status >= SERVER_ERROR:
            return None
        raise
    return learning_of(document.get("twins") if isinstance(document, Mapping) else None)


def _design_approved(steps: tuple[project_api.StepState, ...]) -> bool:
    return any(step.stage == DESIGN_STAGE and step.approved for step in steps)


def _twins_approved(steps: tuple[project_api.StepState, ...]) -> bool:
    return any(step.stage == TWINS_STAGE and step.approved for step in steps)


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


def _spending(
    client: StudioClient, project_id: str
) -> tuple[bool, float | None, float | None, str]:
    try:
        budget = usage.budget(client)
        if budget is None:
            return False, None, None, usage.API_BILLING
        used = usage.project_usage(client, project_id)
    except ApiFailure as failure:
        if failure.http_status >= 500:
            return False, None, None, usage.API_BILLING
        raise
    spent = None if used is None else usage.spent_usd(used)
    return True, spent, usage.remaining_usd(budget), usage.billing(budget)


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
    alignment = state if _design_approved(steps) else None
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
        alignment=alignment,
        local_complete=local is not None
        and local.complete
        and set(knowledge.FOLDER_STAGES) <= set(local.progress),
        tests=local_tests(project),
        stale_reviews=0 if alignment is None else local_stale_reviews(project),
        learning=local_learning(project),
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
    if report.billing == usage.SUBSCRIPTION_BILLING:
        context.console.say("status.subscription")
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
