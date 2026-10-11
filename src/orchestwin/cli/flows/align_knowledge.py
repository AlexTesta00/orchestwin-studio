from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs, jobs
from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import alignment as alignment_api
from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import verify_review
from orchestwin.cli.flows.design_state import bullets, wrapped
from orchestwin.cli.project import LATEST_NAME, read_json, write_json

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.verify_review import Titles, Workspace
    from orchestwin.cli.project import ProjectFolder

ALIGN_FOLDER: Final = "align"
SCHEMA_VERSION: Final = 1
EXCERPT_LINES: Final = 8
LIMIT_SECONDS: Final = 1800.0
SECTION_KEYS: Final[Mapping[str, str]] = {
    alignment_api.REQUIREMENTS: "align.section_requirements",
    alignment_api.DESIGN: "align.section_design",
    alignment_api.TESTS: "align.section_tests",
}
SUBJECT_KEYS: Final = (
    ("requirements", "align.subjects_requirements"),
    ("screens", "align.subjects_screens"),
    ("criteria", "align.subjects_criteria"),
)
SINCE: Final = "align.start_since"
AFTER_RUN: Final = "align.start_run"
AFTER_VERIFY: Final = "align.start_verify"
EVERYTHING: Final = "align.start_all"


@dataclass(frozen=True, slots=True)
class Start:
    commit: str | None
    key: str


def starting_point(
    context: CommandContext,
    workspace: Workspace,
    value: str | None,
    latest: Mapping[str, object] | None,
) -> Start:
    if value is not None:
        found = git.resolve(context, workspace.root, value)
        if found is None:
            raise CliError("ALIGN_SINCE_UNKNOWN", status=USAGE_STATUS, values={"commit": value})
        return Start(found, SINCE)
    last = None if latest is None else latest.get("to_commit")
    if isinstance(last, str) and last:
        return Start(last, AFTER_RUN)
    point = changes_api.aligned(workspace.alignment)
    commit = None if point is None else point.get("commit")
    if isinstance(commit, str) and commit:
        return Start(commit, AFTER_VERIFY)
    return Start(None, EVERYTHING)


def say_start(context: CommandContext, start: Start) -> None:
    context.console.say(start.key, commit=git.short(start.commit), limit=git.DEFAULT_LIMIT)


def align_folder(project: ProjectFolder) -> Path:
    return project.local / ALIGN_FOLDER


def run_file(project: ProjectFolder, run_id: str) -> Path:
    return align_folder(project) / f"{run_id}.json"


def latest_file(project: ProjectFolder) -> Path:
    return align_folder(project) / LATEST_NAME


def write_run(project: ProjectFolder, run: Mapping[str, object]) -> Path:
    return write_json(run_file(project, str(run.get("id"))), dict(run))


def latest_document(
    run: Mapping[str, object], *, waiting: int, finished_at: str
) -> dict[str, object]:
    proposals = alignment_api.proposals_of(run)
    statuses = [alignment_api.status_of(item) for item in proposals]
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.get("id"),
        "finished_at": finished_at,
        "from_commit": run.get("from_commit"),
        "to_commit": run.get("to_commit"),
        "proposals": len(proposals),
        "waiting": waiting,
        "applied": statuses.count(alignment_api.APPLIED),
        "skipped": statuses.count(alignment_api.SKIPPED),
    }


def write_latest(
    project: ProjectFolder, run: Mapping[str, object], *, waiting: int, finished_at: str
) -> Path:
    document = latest_document(run, waiting=waiting, finished_at=finished_at)
    return write_json(latest_file(project), document)


def read_latest(project: ProjectFolder) -> Mapping[str, object] | None:
    document = read_json(latest_file(project))
    if (
        not isinstance(document, Mapping)
        or document.get("schema_version") != SCHEMA_VERSION
        or not isinstance(document.get("run_id"), str)
        or not document.get("run_id")
    ):
        return None
    return document


def read_run(project: ProjectFolder, run_id: str) -> Mapping[str, object] | None:
    if not run_id or any(character in run_id for character in '/\\:*?"<>|\0'):
        return None
    document = read_json(run_file(project, run_id))
    return document if isinstance(document, Mapping) and document.get("id") == run_id else None


def folder_version(project: ProjectFolder) -> int | None:
    try:
        found = knowledge.summary(project.knowledge)
    except CliError:
        return None
    return None if found is None else found.version_number


def commit_lines(commits: Sequence[git.Commit]) -> dict[str, str]:
    return {commit.hash: git.first_line(commit.message) for commit in commits}


def known_lines(workspace: Workspace) -> dict[str, str]:
    return {
        commit: git.first_line(str(change.get("message") or ""))
        for commit, change in verify_review.known_changes(workspace).items()
    }


def list_commits(context: CommandContext, commits: Sequence[git.Commit]) -> None:
    console = context.console
    console.say("align.commits", count=len(commits))
    console.items([verify_review.commit_line(context, commit) for commit in commits])


def dry_run(context: CommandContext, workspace: Workspace, commits: Sequence[git.Commit]) -> None:
    context.console.say("align.dry_run", count=len(commits))
    costs.say_estimate(
        context,
        workspace.client,
        [alignment_api.OPERATION],
        subscription_key="align.dry_run_subscription",
        estimate_key="align.dry_run_estimate",
    )


def start_run(
    context: CommandContext,
    workspace: Workspace,
    commits: Sequence[git.Commit],
    since: str | None,
    *,
    locale: str,
) -> Mapping[str, object]:
    context.console.say("align.reading")
    costs.confirm_spending(context, workspace.client, [alignment_api.OPERATION])
    result = jobs.generate(
        context,
        workspace.client,
        workspace.project_id,
        alignment_api.runs_path(workspace.project_id),
        alignment_api.run_body(locale, [commit.hash for commit in commits], since),
        label=context.text("align.run_label"),
        limit_seconds=LIMIT_SECONDS,
    )
    if result.status_code < 400:
        return jobs.answer_member(result, "run")
    raise refusal(context, workspace, result.status_code, result.body, alignment_api.OPERATION)


def refusal(
    context: CommandContext, workspace: Workspace, status: int, body: object, operation: str
) -> CliError:
    failure = verify_review.failure_of(status, body)
    return costs.budget_or_failure(
        context, workspace.client, workspace.project_id, failure, operation
    )


def show_run(
    context: CommandContext,
    run: Mapping[str, object],
    names: Titles,
    lines: Mapping[str, str],
) -> None:
    console = context.console
    commits = alignment_api.texts(run.get("commits"))
    console.write()
    console.heading(
        context.text(
            "align.run_heading", count=len(commits), commit=git.short(run.get("to_commit"))
        )
    )
    summary = alignment_api.text_of(run, "summary")
    if summary:
        wrapped(context, summary)
    show_proposals(context, alignment_api.proposals_of(run), names, lines)


def show_proposals(
    context: CommandContext,
    proposals: Sequence[Mapping[str, object]],
    names: Titles,
    lines: Mapping[str, str],
) -> None:
    console = context.console
    if not proposals:
        console.say("align.no_proposals")
        return
    for section in alignment_api.SECTIONS:
        items = [item for item in proposals if alignment_api.section_of(item) == section]
        if not items:
            continue
        console.write()
        console.heading(context.text(SECTION_KEYS[section]))
        for item in items:
            show_proposal(context, item, names, lines)


def show_proposal(
    context: CommandContext,
    proposal: Mapping[str, object],
    names: Titles,
    lines: Mapping[str, str],
) -> None:
    console = context.console
    console.write()
    wrapped(
        context,
        context.text(
            "align.proposal",
            code=alignment_api.code_of(proposal),
            title=alignment_api.text_of(proposal, "title"),
        ),
        hang="  ",
    )
    request = alignment_api.text_of(proposal, "request")
    if request:
        wrapped(context, request, indent="  ")
    rationale = alignment_api.text_of(proposal, "rationale")
    if rationale:
        wrapped(context, context.text("align.rationale", text=rationale), indent="  ")
    show_origin(context, alignment_api.origin_of(proposal), lines)
    show_subjects(context, alignment_api.subjects_of(proposal), names)
    wrapped(context, context.text("align.hypothesis"), indent="  ")


def show_origin(
    context: CommandContext, origin: Mapping[str, object], lines: Mapping[str, str]
) -> None:
    console = context.console
    commits = alignment_api.texts(origin.get("commits"))
    if commits:
        items = "; ".join(commit_label(commit, lines) for commit in commits)
        wrapped(context, context.text("align.origin_commits", items=items), indent="  ")
    files = alignment_api.texts(origin.get("files"))
    if files:
        wrapped(context, context.text("align.origin_files", files=", ".join(files)), indent="  ")
    excerpt = origin.get("excerpt")
    rows = excerpt.splitlines() if isinstance(excerpt, str) else []
    rows = [row for row in rows if row.strip()]
    if not rows:
        return
    console.write(f"  {context.text('align.excerpt')}")
    for row in rows[:EXCERPT_LINES]:
        console.write(f"    {row.rstrip()}")
    if len(rows) > EXCERPT_LINES:
        console.write(f"    {context.text('align.excerpt_more', count=len(rows) - EXCERPT_LINES)}")


def show_subjects(context: CommandContext, subjects: Mapping[str, object], names: Titles) -> None:
    titles = {"requirements": names.requirements, "screens": names.screens, "criteria": {}}
    for field, key in SUBJECT_KEYS:
        codes = alignment_api.texts(subjects.get(field))
        if not codes:
            continue
        items = "; ".join(verify_review.named(context, code, titles[field]) for code in codes)
        wrapped(context, context.text(key, items=items), indent="  ")


def commit_label(commit: str, lines: Mapping[str, str]) -> str:
    line = next((text for hash_value, text in lines.items() if same_commit(hash_value, commit)), "")
    return f"{git.short(commit)} {line}".rstrip()


def same_commit(first: str, second: str) -> bool:
    return bool(first and second) and (first.startswith(second) or second.startswith(first))


def show_changes(context: CommandContext, changes: Sequence[str]) -> None:
    if not changes:
        return
    context.console.say("align.design_changes")
    bullets(context, list(changes), indent="  ")
