from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.commands import status as status_command
from orchestwin.cli.errors import BUDGET_CODES, USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import verify_decision, verify_review

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.verify_review import Workspace

NAME = "verify"
BUDGET_OPERATION: Final = "CODE_ALIGNMENT"
DECISION_KEYS: Final[Mapping[str, str]] = {
    changes_api.ALIGNED: "verify.kind_aligned",
    changes_api.DESIGN_CHANGE: "verify.kind_design_change",
    changes_api.REQUIREMENTS_CHANGE: "verify.kind_requirements_change",
    changes_api.CODE_TASKS: "verify.kind_code_tasks",
    changes_api.DISMISSED: "verify.kind_dismissed",
}


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--since", metavar="COMMIT", help="verify.option_since")
    parser.add_argument("--latest", action="store_true", help="verify.option_latest")
    parser.add_argument("--dry-run", action="store_true", help="verify.option_dry_run")
    parser.add_argument("--decide", metavar="COMMIT", help="verify.option_decide")
    parser.add_argument("--recheck", action="store_true", help="verify.option_recheck")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    if arguments.recheck and (arguments.since is not None or arguments.decide is not None):
        raise CliError("ALIGN_RECHECK_ALONE", status=USAGE_STATUS)
    if arguments.decide is not None and (
        arguments.since is not None or arguments.latest or arguments.dry_run
    ):
        raise CliError("ALIGN_DECIDE_ALONE", status=USAGE_STATUS)
    if arguments.recheck:
        return recheck(context, latest=arguments.latest, dry_run=arguments.dry_run)
    workspace = verify_review.prepare(context)
    console = context.console
    console.heading(context.text("verify.heading", name=workspace.project.link().project_name))
    show_reference(context, workspace.alignment)
    if arguments.decide is not None:
        return decide_again(context, workspace, arguments.decide)
    since = starting_point(context, workspace, arguments.since)
    commits = git.commits_after(context, workspace.root, since)
    if verify_review.uncommitted(context, workspace):
        console.say("verify.uncommitted")
    if not commits:
        console.say("verify.nothing")
        finish(context, workspace)
        return 0
    list_commits(context, workspace, commits, since, given=arguments.since is not None)
    known = verify_review.known_changes(workspace)
    recorded = verify_review.record(context, workspace, commits, known)
    console.say("verify.recorded", count=recorded)
    if recorded:
        known = verify_review.known_changes(workspace)
    folder = verify_review.folder_commits(workspace, commits)
    if folder:
        dismissed = not arguments.dry_run and verify_review.dismiss_folder_commit(
            context, workspace, commits, folder, known
        )
        console.say(
            "verify.folder_only_dismissed" if dismissed else "verify.folder_only",
            count=len(folder),
            commits=", ".join(git.short(commit.hash) for commit in folder),
        )
    skipped = {commit.hash for commit in folder}
    reviewable = [commit for commit in commits if commit.hash not in skipped]
    candidates = reviewable[-1:] if arguments.latest else reviewable
    waiting = [
        commit
        for commit in candidates
        if changes_api.verdict_of(known.get(commit.hash, {})) is None
    ]
    if arguments.dry_run:
        dry_run(context, workspace, waiting)
        finish(context, workspace)
        return 0
    if candidates and not waiting:
        console.say("verify.reviews_none")
    runs = review_all(context, workspace, waiting)
    known = verify_review.known_changes(workspace)
    items = decision_items(workspace, reviewable, known, runs)
    status = verify_decision.decide(context, workspace, items)
    finish(context, workspace)
    return status


def decide_again(context: CommandContext, workspace: Workspace, value: str) -> int:
    console = context.console
    found = git.resolve(context, workspace.root, value)
    if found is None:
        raise CliError("ALIGN_DECIDE_UNKNOWN", status=USAGE_STATUS, values={"commit": value})
    change = changes_api.change(workspace.client, workspace.project_id, found)
    run = None if change is None else verify_review.latest_run(workspace, found)
    if change is None or run is None:
        raise CliError("ALIGN_NOT_REVIEWED", values={"commit": git.short(found)})
    earlier = changes_api.decision_of(change)
    key = DECISION_KEYS.get(earlier) if earlier is not None else None
    if earlier is not None:
        console.say("verify.earlier_decision", decision=context.text(key) if key else earlier)
    line = git.first_line(str(change.get("message") or ""))
    verify_review.show_run(context, run, verify_review.titles(workspace.project), message=line)
    status = verify_decision.decide(
        context, workspace, [verify_decision.Reviewed(found, line, run)]
    )
    finish(context, workspace)
    return status


def show_reference(context: CommandContext, document: Mapping[str, object]) -> None:
    console = context.console
    requirements = changes_api.reference(document, "requirements")
    design = changes_api.reference(document, "design") or {}
    console.say(
        "verify.reference",
        requirements=_number(requirements),
        design=_number(design),
        alternative=design.get("alternative_code") or "-",
    )
    point = changes_api.aligned(document)
    if point is None:
        console.say("verify.not_aligned")
    else:
        console.say(
            "verify.aligned",
            commit=git.short(point.get("commit")),
            date=git.commit_date(str(point.get("decided_at") or "")),
            requirements=_number(point, "requirements_version_number"),
            design=_number(point, "design_version_number"),
        )
    tasks = changes_api.open_tasks(document)
    if tasks:
        console.say("verify.open_tasks", count=len(tasks))
        console.items([f"{task.get('code') or '-'}: {task.get('text') or ''}" for task in tasks])


def starting_point(context: CommandContext, workspace: Workspace, value: str | None) -> str | None:
    if value is not None:
        found = git.resolve(context, workspace.root, value)
        if found is None:
            raise CliError("ALIGN_SINCE_UNKNOWN", status=USAGE_STATUS, values={"commit": value})
        return found
    point = changes_api.aligned(workspace.alignment)
    commit = None if point is None else point.get("commit")
    return commit if isinstance(commit, str) and commit else None


def list_commits(
    context: CommandContext,
    workspace: Workspace,
    commits: Sequence[git.Commit],
    since: str | None,
    *,
    given: bool,
) -> None:
    console = context.console
    if given and since is not None:
        console.say("verify.considered_since", commit=git.short(since), count=len(commits))
    elif since is not None:
        console.say("verify.considered_after", count=len(commits))
    else:
        console.say("verify.considered_all", count=len(commits), limit=git.DEFAULT_LIMIT)
    console.items([verify_review.commit_line(context, commit) for commit in commits])


def dry_run(context: CommandContext, workspace: Workspace, commits: Sequence[git.Commit]) -> None:
    console = context.console
    if not commits:
        console.say("verify.dry_run_none")
        return
    console.say("verify.dry_run", count=len(commits))
    console.items([verify_review.commit_line(context, commit) for commit in commits])
    twins = verify_review.twins_count(workspace.client, workspace.project)
    say_estimate(context, workspace, verify_review.review_operations(twins, len(commits)))


def say_estimate(context: CommandContext, workspace: Workspace, operations: Sequence[str]) -> None:
    total = costs.estimate(operations)
    minutes = costs.minutes_text(total.minutes)
    if costs.uses_subscription(workspace.client):
        context.console.say("verify.dry_run_subscription", minutes=minutes)
        return
    context.console.say(
        "verify.dry_run_estimate",
        amount=costs.amount_text(total, context.language),
        minutes=minutes,
    )


def review_all(
    context: CommandContext, workspace: Workspace, commits: Sequence[git.Commit]
) -> dict[str, Mapping[str, object]]:
    console = context.console
    if not commits:
        return {}
    if not changes_api.review_available(workspace.alignment):
        raise CliError(changes_api.NO_REVIEW_MODEL)
    twins = verify_review.twins_count(workspace.client, workspace.project)
    console.say("verify.reviewing", count=len(commits), twins=twins)
    costs.confirm_spending(
        context, workspace.client, verify_review.review_operations(twins, len(commits))
    )
    names = verify_review.titles(workspace.project)
    locale = verify_review.locale(context, workspace.project)
    runs: dict[str, Mapping[str, object]] = {}
    for commit in commits:
        run = review_commit(context, workspace, commit.hash, locale=locale)
        runs[commit.hash] = run
        verify_review.show_run(context, run, names, message=git.first_line(commit.message))
    return runs


def review_commit(
    context: CommandContext,
    workspace: Workspace,
    commit: str,
    *,
    locale: str,
    again: bool = False,
) -> Mapping[str, object]:
    try:
        return verify_review.review(context, workspace, commit, locale=locale, again=again)
    except ApiFailure as failure:
        if failure.http_status == 402 or failure.code in BUDGET_CODES:
            raise budget_error(context, workspace, failure.code) from None
        raise


def recheck(context: CommandContext, *, latest: bool, dry_run: bool) -> int:
    workspace = verify_review.prepare(context, repository=False)
    console = context.console
    console.heading(context.text("verify.heading", name=workspace.project.link().project_name))
    show_reference(context, workspace.alignment)
    stale = stale_changes(workspace, latest=latest)
    if not stale:
        console.say("verify.recheck_none")
        finish(context, workspace)
        return 0
    console.say("verify.recheck_list", count=len(stale), **current_versions(workspace.alignment))
    console.items([recheck_line(context, change) for change in stale])
    twins = verify_review.twins_count(workspace.client, workspace.project)
    operations = verify_review.review_operations(twins, len(stale))
    if dry_run:
        console.say("verify.recheck_dry_run")
        say_estimate(context, workspace, operations)
        finish(context, workspace)
        return 0
    if not changes_api.review_available(workspace.alignment):
        raise CliError(changes_api.NO_REVIEW_MODEL)
    console.say("verify.recheck_reviewing", count=len(stale), twins=twins)
    costs.confirm_spending(context, workspace.client, operations)
    names = verify_review.titles(workspace.project)
    locale = verify_review.locale(context, workspace.project)
    status = 0
    for change in stale:
        commit = str(change.get("commit") or "")
        line = git.first_line(str(change.get("message") or ""))
        run = review_commit(context, workspace, commit, locale=locale, again=True)
        verify_review.show_run(context, run, names, message=line)
        earlier = changes_api.decision_of(change)
        if earlier is not None:
            key = DECISION_KEYS.get(earlier)
            console.say("verify.earlier_decision", decision=context.text(key) if key else earlier)
        outcome = verify_decision.decide(
            context, workspace, [verify_decision.Reviewed(commit, line, run)]
        )
        status = status or outcome
    finish(context, workspace)
    return status


def stale_changes(workspace: Workspace, *, latest: bool) -> list[Mapping[str, object]]:
    pending = changes_api.changes(workspace.client, workspace.project_id, pending=True)
    stale = [change for change in reversed(pending) if changes_api.review_stale(change)]
    return stale[-1:] if latest else stale


def current_versions(document: Mapping[str, object]) -> dict[str, object]:
    design = changes_api.reference(document, "design") or {}
    return {
        "requirements": _number(changes_api.reference(document, "requirements")),
        "design": _number(design),
        "alternative": design.get("alternative_code") or "-",
    }


def recheck_line(context: CommandContext, change: Mapping[str, object]) -> str:
    reference = changes_api.review_reference(change)
    return context.text(
        "verify.recheck_line",
        commit=git.short(change.get("commit")),
        date=git.commit_date(str(change.get("committed_at") or "")),
        line=git.first_line(str(change.get("message") or "")),
        requirements=_number(reference, "requirements_version_number"),
        design=_number(reference, "design_version_number"),
        alternative=reference.get("alternative_code") or "-",
    )


def budget_error(context: CommandContext, workspace: Workspace, code: str) -> CliError:
    from orchestwin.cli.commands.init import Journey

    journey = Journey(
        context, workspace.client, workspace.project, script=None, until=None, idea=None
    )
    return journey.budget_error(code, BUDGET_OPERATION)


def decision_items(
    workspace: Workspace,
    commits: Sequence[git.Commit],
    known: Mapping[str, Mapping[str, object]],
    runs: Mapping[str, Mapping[str, object]],
) -> list[verify_decision.Reviewed]:
    items: list[verify_decision.Reviewed] = []
    for commit in commits:
        change = known.get(commit.hash)
        if change is None or changes_api.decision_of(change) is not None:
            continue
        if commit.hash not in runs and changes_api.verdict_of(change) is None:
            continue
        run = runs.get(commit.hash) or verify_review.latest_run(workspace, commit.hash)
        if run is None:
            continue
        items.append(verify_decision.Reviewed(commit.hash, git.first_line(commit.message), run))
    return items


def finish(context: CommandContext, workspace: Workspace) -> None:
    found = changes_api.development(workspace.client, workspace.project_id)
    if found is None:
        return
    context.console.write()
    status_command.show_alignment(context, found.summary)
    verify_decision.say_recheck(context, workspace, found.stale_reviews)


def _number(document: Mapping[str, object] | None, key: str = "version_number") -> object:
    value = None if document is None else document.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else "-"
