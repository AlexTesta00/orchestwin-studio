from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.console import format_elapsed
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows import code_agents, code_order, code_run
from orchestwin.cli.flows.changes import visible
from orchestwin.cli.flows.code_agents import AGENTS, CLAUDE

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.code_order import OrderFacts, Work
    from orchestwin.cli.flows.code_run import Changes, CodeSettings, Finished, Launch

NAME = "code"
CODE_SEPARATORS: Final = re.compile(r"[\s,;]+")
LISTED_FILES: Final = 40
DEFAULT_PYTHON: Final = "python"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("request", nargs="*", metavar="REQUEST", help="code.option_request")
    parser.add_argument("--task", metavar="CODES", help="code.option_task")
    parser.add_argument("--agent", choices=AGENTS, help="code.option_agent")
    parser.add_argument(
        "--command", dest="agent_command", metavar="TEXT", help="code.option_command"
    )
    parser.add_argument("--model", metavar="NAME", help="code.option_model")
    parser.add_argument("--headless", action="store_true", help="code.option_headless")
    parser.add_argument("--max-agent-usd", metavar="USD", help="code.option_max_agent_usd")
    parser.add_argument("--spend", action="store_true", help="code.option_spend")
    parser.add_argument("--dry-run", action="store_true", help="code.option_dry_run")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    summary = code_order.approved_folder(project)
    design = summary.stage(code_order.DESIGN_STAGE)
    settings = code_run.chosen_settings(
        code_run.read_settings(project),
        agent=arguments.agent,
        command=arguments.agent_command,
        model=arguments.model,
        headless=arguments.headless,
        platform=context.environment.platform,
    )
    max_usd = code_agents.budget(
        arguments.max_agent_usd, agent=settings.agent, headless=settings.headless
    )
    code_run.write_settings(project, settings)
    work = code_order.work_for(
        code_order.open_tasks(project), codes(arguments.task), request_of(arguments.request)
    )
    program = code_run.claude_program(context) if settings.agent == CLAUDE else None
    facts = code_order.facts_of(project, summary, language=context.language)
    files = code_run.write_run_files(
        project,
        context.environment.now(),
        code_order.work_order(facts, work, spend=arguments.spend),
        spend=arguments.spend,
        python=sys.executable or DEFAULT_PYTHON,
    )
    launch = code_run.Launch(
        project=project,
        files=files,
        arguments=code_run.agent_arguments(
            project, settings, files, program=program, max_usd=max_usd
        ),
        settings=settings,
        work=work,
        spend=arguments.spend,
        design_version_number=None if design is None else design.version_number,
    )
    announce(context, facts, launch, max_usd=max_usd)
    if arguments.dry_run:
        show_words(context, launch)
        return 0
    if not context.assume_yes and not context.console.confirm("code.confirm", default=True):
        raise CliError("SPENDING_REFUSED")
    context.console.say("code.starting", program=launch.program)
    finished = code_run.start(context, launch)
    if finished.outcome.exit_status == 0 and launch.design_version_number is not None:
        code_run.write_design_point(
            project,
            version=launch.design_version_number,
            folder=launch.files.name,
            reason=code_run.CODE_RUN_REASON,
            moment=context.environment.now(),
        )
    report(context, facts, launch, finished)
    return 0 if finished.outcome.exit_status == 0 else 1


def codes(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part for part in CODE_SEPARATORS.split(value) if part)


def request_of(words: Sequence[str] | None) -> str | None:
    text = " ".join(str(word) for word in words or ()).strip()
    return text or None


def announce(
    context: CommandContext, facts: OrderFacts, launch: Launch, *, max_usd: float | None
) -> None:
    console = context.console
    settings = launch.settings
    console.heading(context.text("code.heading", name=facts.project_name))
    agent_key = "code.agent_claude" if settings.agent == CLAUDE else "code.agent_custom"
    console.say(agent_key, program=launch.arguments[0])
    console.say(mode_key(settings))
    if settings.agent == CLAUDE and settings.model:
        console.say("code.model", model=settings.model)
    if max_usd is not None:
        console.say("code.budget", usd=costs.usd_text(max_usd, context.language))
    say_work(context, launch.work)
    console.say("code.order", path=str(launch.files.prompt))
    console.say("code.own_account_spend" if launch.spend else "code.own_account")


def mode_key(settings: CodeSettings) -> str:
    if not settings.headless:
        return "code.mode_interactive"
    return "code.mode_headless_claude" if settings.agent == CLAUDE else "code.mode_headless"


def say_work(context: CommandContext, work: Work) -> None:
    console = context.console
    listed = ", ".join(work.codes)
    if work.tasks and work.request is not None:
        console.say("code.work_tasks_request", codes=listed)
    elif work.tasks and work.every:
        console.say("code.work_all_tasks", codes=listed)
    elif work.tasks:
        console.say("code.work_tasks", codes=listed)
    elif work.request is not None:
        console.say("code.work_request")
    else:
        console.say("code.work_build")


def show_words(context: CommandContext, launch: Launch) -> None:
    console = context.console
    console.say("code.words")
    for word in launch.arguments:
        console.write(f"  {word}")
    console.say("code.dry_run", folder=str(launch.files.folder))


def report(context: CommandContext, facts: OrderFacts, launch: Launch, finished: Finished) -> None:
    console = context.console
    outcome = finished.outcome
    elapsed = format_elapsed(outcome.seconds)
    console.write()
    if outcome.exit_status == 0:
        console.say("code.ended", elapsed=elapsed)
    else:
        console.say("code.ended_status", status=outcome.exit_status, elapsed=elapsed)
    show_changes(context, launch, finished.changes)
    if finished.touched:
        console.say("code.knowledge_touched", folder=facts.knowledge_folder)
    if outcome.exit_status == 0:
        console.say("code.next_steps")
    else:
        console.say("code.next_steps_failed", folder=str(launch.files.folder))


def show_changes(context: CommandContext, launch: Launch, changes: Changes) -> None:
    console = context.console
    if changes.files is None:
        if changes.problem == code_run.NO_REPOSITORY:
            console.say("code.changes_no_git")
        else:
            console.say("code.changes_failed", detail=changes.problem or "-")
        return
    if not changes.files:
        console.say("code.changed_none")
        return
    console.say("code.changed", count=len(changes.files))
    for path in changes.files[:LISTED_FILES]:
        console.write(f"- {visible(path)}")
    if len(changes.files) > LISTED_FILES:
        console.say(
            "code.changed_more",
            count=len(changes.files) - LISTED_FILES,
            path=str(launch.files.folder / code_run.OUTCOME_NAME),
        )
