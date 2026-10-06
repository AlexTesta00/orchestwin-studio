from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import changes as changes_api
from orchestwin.cli.api import tasks as tasks_api
from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.client import ensure_access
from orchestwin.cli.errors import SIGN_IN_STATUS, USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import changes as git
from orchestwin.cli.flows import task_selection
from orchestwin.cli.flows.publish import publish_and_pull
from orchestwin.cli.flows.test_report import moment_text
from orchestwin.cli.project import json_default, read_json

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.task_selection import Candidate
    from orchestwin.cli.project import ProjectFolder

NAME = "tasks"
NESTED_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}
ADD: Final = "add"
DONE: Final = "done"
DROP: Final = "drop"
REOPEN: Final = "reopen"
FROM_TEST: Final = "from-test"
FROM_COMMIT: Final = "from-commit"
TARGETS: Final[Mapping[str, str]] = {
    DONE: tasks_api.DONE,
    DROP: tasks_api.DROPPED,
    REOPEN: tasks_api.OPEN,
}
CHANGED_KEYS: Final[Mapping[str, str]] = {
    DONE: "tasks.changed_done",
    DROP: "tasks.changed_dropped",
    REOPEN: "tasks.changed_reopened",
}
STATUS_KEYS: Final[Mapping[str, str]] = {
    tasks_api.OPEN: "tasks.status_open",
    tasks_api.DONE: "tasks.status_done",
    tasks_api.DROPPED: "tasks.status_dropped",
}
UNREACHABLE: Final = "unreachable"
NOT_SIGNED_IN: Final = "not_signed_in"
SESSION_EXPIRED: Final = "session_expired"
MISSING: Final = "missing"
OFFLINE_KEYS: Final[Mapping[str, str]] = {
    UNREACHABLE: "tasks.offline_unreachable",
    NOT_SIGNED_IN: "tasks.offline_not_signed_in",
    SESSION_EXPIRED: "tasks.offline_session_expired",
    MISSING: "tasks.offline_missing",
}
MISSING_ROUTE: Final = frozenset({404, 405})
SERVER_ERROR: Final = 500
CODE_SEPARATORS: Final = re.compile(r"[\s,;]+")
COMMIT_PATTERN: Final = re.compile(r"[0-9a-fA-F]{7,64}")
STATE_DOCUMENT: Final = ("state", "state.json")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="tasks.option_all")
    parser.add_argument("--json", action="store_true", help="tasks.option_json")
    actions = parser.add_subparsers(dest="action", metavar="ACTION", help="tasks.option_action")
    added = _action(actions, parser, ADD, help="tasks.help_add")
    added.add_argument("text", metavar="TEXT", nargs="+", help="tasks.option_text")
    done = _action(actions, parser, DONE, help="tasks.help_done")
    done.add_argument("codes", metavar="CODE", nargs="+", help="tasks.option_codes")
    done.add_argument("--note", metavar="TEXT", help="tasks.option_note")
    dropped = _action(actions, parser, DROP, help="tasks.help_drop")
    dropped.add_argument("codes", metavar="CODE", nargs="+", help="tasks.option_codes")
    dropped.add_argument("--note", metavar="TEXT", help="tasks.option_note")
    reopened = _action(actions, parser, REOPEN, help="tasks.help_reopen")
    reopened.add_argument("codes", metavar="CODE", nargs="+", help="tasks.option_codes")
    tested = _action(actions, parser, FROM_TEST, help="tasks.help_from_test")
    tested.add_argument("--run", metavar="RUN_ID", help="tasks.option_run")
    committed = _action(actions, parser, FROM_COMMIT, help="tasks.help_from_commit")
    committed.add_argument("commit", metavar="COMMIT", nargs="?", help="tasks.option_commit")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action
    if action == ADD:
        text = text_of(arguments.text)
        return add(context, context.project(), text)
    if action in TARGETS:
        codes = codes_of(arguments.codes)
        note = note_of(getattr(arguments, "note", None))
        return change(context, context.project(), action, codes, note)
    if action == FROM_TEST:
        run_id = run_of(arguments.run)
        return from_test(context, context.project(), run_id)
    if action == FROM_COMMIT:
        commit = commit_of(arguments.commit)
        return from_commit(context, context.project(), commit)
    return show_tasks(context, context.project(), every=arguments.all, as_json=arguments.json)


def show_tasks(
    context: CommandContext, project: ProjectFolder, *, every: bool, as_json: bool
) -> int:
    console = context.console
    link = project.link()
    client = context.client()
    reason: str | None = None
    try:
        ensure_access(context, client)
        items = tasks_api.tasks(client, link.project_id, every=every)
    except CliError as error:
        reason = offline_reason(error)
        local = None if reason is None else local_tasks(project)
        if reason is None or local is None:
            raise
        items = local if every else tasks_api.open_tasks(local)
    values = {"studio": client.studio.origin, "path": f"{link.knowledge_folder}/"}
    if as_json:
        if reason is not None:
            console.error(OFFLINE_KEYS[reason], **values)
        document = {"tasks": [dict(item) for item in items]}
        console.write(json.dumps(document, indent=2, ensure_ascii=True, default=json_default))
        return 0
    key = "tasks.heading_all" if every else "tasks.heading_open"
    console.heading(context.text(key, name=link.project_name))
    if reason is not None:
        console.say(OFFLINE_KEYS[reason], **values)
    if not items:
        console.say("tasks.none_all" if every else "tasks.none")
        return 0
    console.table(
        [
            context.text("tasks.column_code"),
            context.text("tasks.column_status"),
            context.text("tasks.column_text"),
            context.text("tasks.column_origin"),
        ],
        [task_row(context, task) for task in items],
    )
    if any(tasks_api.is_open(task) for task in items):
        console.write()
        console.say("tasks.hint")
    return 0


def add(context: CommandContext, project: ProjectFolder, text: str) -> int:
    link = project.link()
    client = context.client()
    _, document = tasks_api.create(client, link.project_id, [tasks_api.owner_item(text)])
    for task in tasks_api.created_tasks(document):
        context.console.say(
            "tasks.added", task=tasks_api.task_code(task), text=tasks_api.task_text(task)
        )
    publish(context, client, project)
    return 0


def change(
    context: CommandContext,
    project: ProjectFolder,
    action: str,
    codes: Sequence[str],
    note: str | None,
) -> int:
    console = context.console
    link = project.link()
    client = context.client()
    changed: list[Mapping[str, object]] = []
    failed: list[tuple[str, ApiFailure]] = []
    for code in codes:
        try:
            document = tasks_api.set_status(
                client, link.project_id, code, TARGETS[action], note=note
            )
        except ApiFailure as failure:
            if failure.status == SIGN_IN_STATUS:
                raise
            failed.append((code, failure))
            continue
        changed.append(tasks_api.changed_task(document) or {"code": code})
    if changed:
        console.say(CHANGED_KEYS[action], count=len(changed))
        console.items([task_line(task) for task in changed])
    for code, failure in failed:
        if failure.code == tasks_api.CODE_TASK_NOT_FOUND:
            console.error("tasks.not_found", task=code)
        else:
            console.error("tasks.not_changed", task=code, code=failure.code)
    if changed:
        publish(context, client, project)
    return 1 if failed else 0


def from_test(context: CommandContext, project: ProjectFolder, run_id: str | None) -> int:
    console = context.console
    link = project.link()
    client = context.client()
    if run_id is None:
        found = latest_review(client, link.project_id)
        if found is None:
            console.say("tasks.test_none_reviewed")
            return 0
    else:
        found = named_review(client, link.project_id, run_id)
        if found is None:
            console.say("tasks.test_not_reviewed", run=run_id)
            return 0
    console.heading(context.text("tasks.test_heading", date=moment_text(found.get("finished_at"))))
    return offer(
        context,
        client,
        project,
        lambda tasks: task_selection.candidates_of_run(found, tasks),
        run=str(found.get("id") or ""),
    )


def from_commit(context: CommandContext, project: ProjectFolder, value: str | None) -> int:
    console = context.console
    link = project.link()
    client = context.client()
    if value is None:
        change_document = newest_reviewed(client, link.project_id)
        if change_document is None:
            console.say("tasks.commit_none_reviewed")
            return 0
    else:
        change_document = changes_api.change(client, link.project_id, value)
        if change_document is None:
            raise CliError(tasks_api.CODE_CHANGE_NOT_FOUND, values={"commit": value})
    commit = str(change_document.get("commit") or value or "")
    runs = changes_api.reviews(client, link.project_id, commit)
    if not runs:
        console.say("tasks.commit_not_reviewed", commit=git.short(commit))
        return 0
    run = runs[0]
    line = git.first_line(str(change_document.get("message") or ""))
    console.heading(context.text("tasks.commit_heading", commit=git.short(commit), line=line))
    return offer(
        context,
        client,
        project,
        lambda tasks: task_selection.candidates_of_review(commit, run, tasks),
        commit=git.short(commit),
    )


def offer(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    candidates_of: Callable[[Sequence[Mapping[str, object]]], tuple[Candidate, ...]],
    **values: object,
) -> int:
    console = context.console
    link = project.link()
    if not candidates_of(()):
        console.say("tasks.no_findings")
        return 0
    candidates = candidates_of(tasks_api.tasks(client, link.project_id))
    chosen = task_selection.choose(context, candidates, question_key="tasks.choose_question")
    if not chosen:
        if any(item.offered for item in candidates):
            console.say("tasks.created_none")
        return 0
    items = [tasks_api.finding_item(item.source) for item in chosen if item.source is not None]
    count, created = tasks_api.create_all(client, link.project_id, items, **values)
    console.say("tasks.created", count=count)
    console.items([task_line(task) for task in created])
    console.say("tasks.created_next")
    publish(context, client, project)
    return 0


def latest_review(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    overview = tests_api.overview(client, project_id)
    review = tests_api.latest_review(overview)
    if review is not None:
        return {
            "id": review["run_id"],
            "finished_at": review.get("finished_at"),
            "critiques": review.get("critiques"),
        }
    latest = tests_api.latest_run(overview)
    if latest is not None and tests_api.critiques_of(latest):
        return {
            "id": latest.get("id"),
            "finished_at": latest.get("finished_at"),
            "critiques": latest.get("critiques"),
        }
    return None


def named_review(client: StudioClient, project_id: str, run_id: str) -> Mapping[str, object] | None:
    run = tests_api.run_of(client, project_id, run_id)
    if run is None:
        raise CliError(tasks_api.TEST_RUN_NOT_FOUND, values={"run": run_id})
    reviews = tests_api.reviews(client, project_id, run_id)
    if not reviews:
        return None
    return {
        "id": run_id,
        "finished_at": run.get("finished_at"),
        "critiques": reviews[0].get("critiques"),
    }


def newest_reviewed(client: StudioClient, project_id: str) -> Mapping[str, object] | None:
    for item in changes_api.changes(client, project_id, pending=True):
        if isinstance(item.get("review"), Mapping):
            return item
    return None


def publish(context: CommandContext, client: StudioClient, project: ProjectFolder) -> None:
    console = context.console
    label = f"{project.link().knowledge_folder}/"
    try:
        found = publish_and_pull(context, client, project)
    except CliError as error:
        inner = error.values.get("code")
        code = inner if isinstance(inner, str) and inner else error.code
        console.say("tasks.folder_not_updated", code=code)
        return
    console.say("tasks.folder_updated", path=label, version=found.version_number)


def task_row(context: CommandContext, task: Mapping[str, object]) -> list[str]:
    key = STATUS_KEYS.get(tasks_api.task_status(task))
    return [
        tasks_api.task_code(task),
        context.text(key) if key else "-",
        tasks_api.task_text(task) or "-",
        tasks_api.origin_text(context, task),
    ]


def task_line(task: Mapping[str, object]) -> str:
    text = tasks_api.task_text(task)
    code = tasks_api.task_code(task)
    return f"{code}: {text}" if text else code


def local_tasks(project: ProjectFolder) -> list[Mapping[str, object]] | None:
    document = read_json(project.knowledge.joinpath(*STATE_DOCUMENT))
    items = document.get("tasks") if isinstance(document, Mapping) else None
    if not isinstance(items, list):
        return None
    return tasks_api.mappings(items)


def offline_reason(error: CliError) -> str | None:
    if error.code == "STUDIO_UNREACHABLE":
        return UNREACHABLE
    if error.code == "NOT_SIGNED_IN":
        return NOT_SIGNED_IN
    if error.status == SIGN_IN_STATUS:
        return SESSION_EXPIRED
    if isinstance(error, ApiFailure) and (
        error.http_status in MISSING_ROUTE or error.http_status >= SERVER_ERROR
    ):
        return MISSING
    return None


def text_of(words: Sequence[str]) -> str:
    text = " ".join(" ".join(words).split())
    if not text:
        raise CliError("TASKS_TEXT_EMPTY", status=USAGE_STATUS)
    if len(text) > tasks_api.MAX_TASK_LENGTH:
        raise CliError(
            "TASKS_TEXT_TOO_LONG", status=USAGE_STATUS, values={"limit": tasks_api.MAX_TASK_LENGTH}
        )
    return text


def codes_of(values: Sequence[str]) -> list[str]:
    found: list[str] = []
    for value in values:
        for part in CODE_SEPARATORS.split(value):
            if not part:
                continue
            if not tasks_api.valid_code(part):
                raise CliError("TASKS_CODE_INVALID", status=USAGE_STATUS, values={"value": part})
            code = tasks_api.normal_code(part)
            if code not in found:
                found.append(code)
    if not found:
        raise CliError("TASKS_CODE_INVALID", status=USAGE_STATUS, values={"value": "-"})
    return found


def note_of(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if len(text) > tasks_api.MAX_TASK_NOTE_LENGTH:
        raise CliError(
            "TASKS_NOTE_TOO_LONG",
            status=USAGE_STATUS,
            values={"limit": tasks_api.MAX_TASK_NOTE_LENGTH},
        )
    return text or None


def run_of(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    try:
        return str(uuid.UUID(text))
    except ValueError:
        raise CliError(
            "TASKS_RUN_INVALID", status=USAGE_STATUS, values={"value": text or "-"}
        ) from None


def commit_of(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if COMMIT_PATTERN.fullmatch(text) is None:
        raise CliError("TASKS_COMMIT_INVALID", status=USAGE_STATUS, values={"value": text or "-"})
    return text.lower()


def _action(
    actions: argparse._SubParsersAction,
    parser: argparse.ArgumentParser,
    name: str,
    *,
    help: str,
) -> argparse.ArgumentParser:
    child = actions.add_parser(
        name,
        help=help,
        formatter_class=parser.formatter_class,
        add_help=False,
        allow_abbrev=False,
        **NESTED_OPTIONS,
    )
    child.add_argument("-h", "--help", action="help", help="common.option_help")
    return child
