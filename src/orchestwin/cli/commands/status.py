from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import projects as project_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.api import usage
from orchestwin.cli.commands import sections as sections_command
from orchestwin.cli.costs import usd_text
from orchestwin.cli.errors import NOT_SIGNED_IN, SESSION_EXPIRED, UNREACHABLE, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import design_state
from orchestwin.cli.flows.status_report import (
    FROM_STUDIO,
    PROJECT_MISSING,
    REQUESTED,
    SCHEMA_VERSION,
    KnowledgeAlignment,
    project_report,
)
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.messages import known

if TYPE_CHECKING:
    from orchestwin.cli.api.tests import AcceptanceSummary
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.status_report import Report, TwinLearning
    from orchestwin.cli.folder import StateSummary
    from orchestwin.cli.project import ProjectFolder

NAME = "status"
SHORT_COMMIT: Final = 7
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


def show(context: CommandContext, report: Report) -> None:
    console = context.console
    console.heading(report.name)
    console.say(
        "status.studio_local" if report.local_access else "status.studio", studio=report.studio
    )
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
        show_code_design(context, report.aligned_design_version, report.current_design_version)
    if report.knowledge is not None:
        show_knowledge(context, report.knowledge)
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
    if report.next_action in {project_api.PREPARE_TWINS, project_api.PREPARE_DESIGN}:
        console.say("status.next", action=next_action_text(context, report.next_action))
        return
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


def show_code_design(context: CommandContext, aligned: int | None, current: int | None) -> None:
    if aligned is None or current is None:
        return
    key = "status.code_design_behind" if current > aligned else "status.code_design_current"
    context.console.say(key, aligned=aligned, current=current)


def show_knowledge(context: CommandContext, knowledge: KnowledgeAlignment) -> None:
    latest = knowledge.latest_run
    if latest is None:
        return
    context.console.say(
        "status.knowledge",
        commit=str(latest.get("to_commit") or "")[:SHORT_COMMIT],
        date=git.commit_date(local_moment(str(latest.get("created_at") or ""))),
        count=knowledge.waiting,
    )


def local_moment(text: str) -> str:
    try:
        moment = datetime.fromisoformat(text.strip())
        return (moment if moment.tzinfo is None else moment.astimezone()).isoformat()
    except (ValueError, OverflowError, OSError):
        return text


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


def next_action_text(context: CommandContext, code: str) -> str:
    if code == project_api.UPDATE_SECTIONS:
        return context.text("status.next_update_sections")
    if code == project_api.PREPARE_TWINS:
        return context.text("status.next_prepare_twins")
    if code == project_api.PREPARE_DESIGN:
        return context.text("status.next_prepare_design")
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


def _print_json(context: CommandContext, document: Mapping[str, object]) -> None:
    context.console.write(json.dumps(document, indent=2, ensure_ascii=True))
