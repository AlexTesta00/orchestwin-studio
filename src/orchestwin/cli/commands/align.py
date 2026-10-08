from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import alignment as alignment_api
from orchestwin.cli.commands import status as status_command
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.flows import (
    align_apply,
    align_design,
    align_knowledge,
    verify_decision,
    verify_review,
)
from orchestwin.cli.flows import changes as git

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.verify_review import Workspace

NAME = "align"
BUDGET_OPERATION: Final = alignment_api.OPERATION
FROM_DESIGN: Final = "FROM_DESIGN"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", metavar="COMMIT", help="align.option_since")
    parser.add_argument("--dry-run", action="store_true", help="align.option_dry_run")
    parser.add_argument("--pending", action="store_true", help="align.option_pending")
    parser.add_argument("--from-design", action="store_true", help="align.option_from_design")
    parser.add_argument("--max-agent-usd", metavar="USD", help="align.option_max_agent_usd")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    if arguments.pending and arguments.from_design:
        raise CliError("ALIGN_PENDING_ALONE", status=USAGE_STATUS, values={"reason": FROM_DESIGN})
    if arguments.pending and (arguments.since is not None or arguments.dry_run):
        raise CliError("ALIGN_PENDING_ALONE", status=USAGE_STATUS)
    if arguments.max_agent_usd is not None and not arguments.from_design:
        raise CliError("ALIGN_BUDGET_NEEDS_DESIGN", status=USAGE_STATUS)
    if arguments.pending:
        return pending(context)
    if arguments.from_design:
        return align_design.run(
            context,
            since=arguments.since,
            dry_run=arguments.dry_run,
            max_usd=arguments.max_agent_usd,
        )
    workspace = verify_review.prepare(context)
    console = context.console
    console.heading(context.text("align.heading", name=workspace.project.link().project_name))
    before = align_knowledge.folder_version(workspace.project)
    document = alignment_api.proposals(workspace.client, workspace.project_id)
    latest = alignment_api.latest_run(document)
    waiting = len(alignment_api.waiting(document))
    start = align_knowledge.starting_point(context, workspace, arguments.since, latest)
    align_knowledge.say_start(context, start)
    commits = git.commits_after(context, workspace.root, start.commit)
    folder = verify_review.folder_commits(workspace, commits)
    if folder:
        console.say(
            "align.folder_only",
            count=len(folder),
            commits=", ".join(git.short(commit.hash) for commit in folder),
        )
    skipped = {commit.hash for commit in folder}
    reviewable = [commit for commit in commits if commit.hash not in skipped]
    if not reviewable:
        console.say("align.nothing")
        say_waiting(context, waiting)
        return 0
    align_knowledge.list_commits(context, reviewable)
    known = verify_review.known_changes(workspace)
    recorded = verify_review.record(context, workspace, reviewable, known)
    if recorded:
        console.say("align.recorded", count=recorded)
    if arguments.dry_run:
        align_knowledge.dry_run(context, workspace, reviewable)
        say_waiting(context, waiting)
        return 0
    locale = verify_review.locale(context, workspace.project)
    run_document = align_knowledge.start_run(
        context, workspace, reviewable, start.commit, locale=locale
    )
    names = verify_review.titles(workspace.project)
    lines = align_knowledge.commit_lines(reviewable)
    align_knowledge.show_run(context, run_document, names, lines)
    outcome = align_apply.decide_all(
        context,
        workspace,
        alignment_api.proposals_of(run_document),
        names=names,
        lines=lines,
        show=False,
    )
    say_waiting(context, waiting)
    return finish(context, workspace, str(run_document.get("id") or ""), outcome, before)


def pending(context: CommandContext) -> int:
    workspace = verify_review.prepare(context, repository=False)
    console = context.console
    console.heading(context.text("align.heading", name=workspace.project.link().project_name))
    before = align_knowledge.folder_version(workspace.project)
    document = alignment_api.proposals(workspace.client, workspace.project_id)
    items = alignment_api.waiting(document)
    latest = alignment_api.latest_run(document)
    run_id = "" if latest is None else str(latest.get("id") or "")
    if not items:
        console.say("align.pending_none")
        return finish(context, workspace, run_id, align_apply.Outcome(), before)
    console.say("align.pending_intro", count=len(items))
    outcome = align_apply.decide_all(
        context,
        workspace,
        items,
        names=verify_review.titles(workspace.project),
        lines=align_knowledge.known_lines(workspace),
        show=True,
    )
    return finish(context, workspace, run_id, outcome, before)


def say_waiting(context: CommandContext, waiting: int) -> None:
    if waiting > 0:
        context.console.say("align.waiting_hint", count=waiting)


def finish(
    context: CommandContext,
    workspace: Workspace,
    run_id: str,
    outcome: align_apply.Outcome,
    before: int | None,
) -> int:
    if outcome.approved and align_knowledge.folder_version(workspace.project) == before:
        verify_decision.refresh_folder(context, workspace)
    document = alignment_api.proposals(workspace.client, workspace.project_id)
    latest = alignment_api.latest_run(document)
    waiting = len(alignment_api.waiting(document))
    chosen = run_id or ("" if latest is None else str(latest.get("id") or ""))
    if chosen:
        run_document = alignment_api.run(workspace.client, workspace.project_id, chosen)
        if run_document is not None:
            align_knowledge.write_run(workspace.project, run_document)
            align_knowledge.write_latest(
                workspace.project,
                run_document,
                waiting=waiting,
                finished_at=align_apply.now_text(context),
            )
    if latest is not None:
        context.console.write()
        status_command.show_knowledge(context, status_command.KnowledgeAlignment(latest, waiting))
    return outcome.status
