from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import packages
from orchestwin.cli.errors import NOT_VERIFIED_STATUS, SIGN_IN_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import package_import
from orchestwin.cli.flows import publish as publish_flow
from orchestwin.cli.flows.package_import import (
    LocalFolder,
    confirm_replacement,
    local_folder,
    swap_problem,
)
from orchestwin.cli.project import KNOWLEDGE_FOLDER

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder, ProjectLink

NAME = "package"
NESTED_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}
PUBLISH: Final = "publish"
PULL: Final = "pull"
VERIFY: Final = "verify"
HISTORY: Final = "history"
IMPORT: Final = "import"
SHORT_HASH: Final = 12
UNREACHABLE: Final = "unreachable"
NOT_SIGNED_IN: Final = "not_signed_in"
SESSION_EXPIRED: Final = "session_expired"
PROJECT_MISSING: Final = "project_missing"
STUDIO_KEYS: Final[Mapping[str, str]] = {
    UNREACHABLE: "package.studio_unreachable",
    NOT_SIGNED_IN: "package.studio_not_signed_in",
    SESSION_EXPIRED: "package.studio_session_expired",
    PROJECT_MISSING: "package.studio_project_missing",
}
VERIFY_KEYS: Final[Mapping[str, str]] = {
    "FOLDER_MISSING": "package.verify_missing",
    "FOLDER_TAMPERED": "package.verify_tampered",
    "FOLDER_DOCUMENT_MISSING": "package.verify_missing_file",
    "FOLDER_DOCUMENT_INVALID": "package.verify_invalid",
    "FOLDER_SCHEMA_UNSUPPORTED": "package.verify_schema",
}
VERSION_MISSING: Final = "KNOWLEDGE_PACKAGE_NOT_FOUND"


def configure(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", metavar="ACTION", help="package.option_action")
    _action(actions, parser, PUBLISH, help="package.help_publish")
    pull = _action(actions, parser, PULL, help="package.help_pull")
    pull.add_argument("--version", metavar="N", type=int, help="package.option_version")
    _action(actions, parser, VERIFY, help="package.help_verify")
    _action(actions, parser, HISTORY, help="package.help_history")
    imported = _action(actions, parser, IMPORT, help="package.help_import")
    imported.add_argument("path", metavar="PATH", help="package.option_path")
    imported.add_argument("--name", metavar="NAME", help="package.option_name")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action
    if action == VERIFY:
        return verify(context)
    if action == IMPORT:
        return package_import.run_import(context, arguments.path, arguments.name)
    project = context.project()
    if action == PUBLISH:
        return publish(context, project)
    if action == PULL:
        return pull(context, project, arguments.version)
    if action == HISTORY:
        return history(context, project)
    return state(context, project)


def state(context: CommandContext, project: ProjectFolder) -> int:
    console = context.console
    link = project.link()
    label = folder_label(link)
    console.heading(context.text("package.heading", project=link.project_name))
    local = local_folder(project.knowledge)
    _local_line(context, local, label)
    client = context.client()
    latest, reason = _studio_latest(client, link.project_id)
    if reason is not None:
        console.say(STUDIO_KEYS[reason], studio=client.studio.origin)
    elif latest is None:
        console.say("package.studio_none")
    else:
        console.say(
            "package.studio_latest",
            version=version_number(latest),
            date=moment_text(latest.get("created_at")),
        )
    advice = _advice(local, latest, reason)
    if advice is not None:
        console.write()
        console.say(advice, version=None if latest is None else version_number(latest))
    return 0


def publish(context: CommandContext, project: ProjectFolder) -> int:
    console = context.console
    link = project.link()
    label = folder_label(link)
    client = context.client()
    local = local_folder(project.knowledge)
    with console.progress(context.text("common.folder_publishing")):
        publication = packages.publish(client, link.project_id)
    version = publication["version"]
    number = version_number(version)
    reused = publication.get("reused") is True
    if reused and _matches(local, number, version.get("content_hash")):
        console.say("package.up_to_date", version=number, path=label)
        return 0
    if not confirm_replacement(context, local, label):
        console.say("package.kept_published", version=number, path=label)
        return 1
    try:
        found = publish_flow.pull(context, client, project, number)
    except CliError as error:
        raise swap_problem(error) from None
    console.say(
        "package.unchanged_downloaded" if reused else "package.published",
        version=found.version_number,
        path=label,
        files=found.file_count,
    )
    return 0


def pull(context: CommandContext, project: ProjectFolder, version: int | None) -> int:
    console = context.console
    link = project.link()
    label = folder_label(link)
    client = context.client()
    latest = packages.latest(client, link.project_id)
    if latest is None:
        raise CliError("FOLDER_NOT_PUBLISHED")
    newest = version_number(latest)
    number = newest if version is None else version
    missing = CliError("PACKAGE_VERSION_NOT_FOUND", values={"version": number, "latest": newest})
    if not 1 <= number <= newest:
        raise missing
    if not confirm_replacement(context, local_folder(project.knowledge), label):
        console.say("package.kept", path=label)
        return 1
    try:
        found = publish_flow.pull(context, client, project, number)
    except ApiFailure as failure:
        if failure.code == VERSION_MISSING:
            raise missing from None
        raise
    except CliError as error:
        raise swap_problem(error) from None
    console.say("package.pulled", version=found.version_number, path=label, files=found.file_count)
    return 0


def verify(context: CommandContext) -> int:
    project = context.project(required=False)
    if project is None:
        folder = context.directory / KNOWLEDGE_FOLDER
        if not folder.exists():
            raise CliError("PROJECT_NOT_LINKED")
        label = f"{KNOWLEDGE_FOLDER}/"
    else:
        folder = project.knowledge
        label = folder_label(project.link())
    try:
        verified = knowledge.verify(folder)
    except CliError as error:
        if error.code != "FOLDER_NOT_VERIFIED":
            raise
        context.console.error(
            verify_key(error),
            path=label,
            file=str(error.values.get("path", "")),
            code=str(error.values.get("code", "")),
        )
        return NOT_VERIFIED_STATUS
    context.console.say(
        "package.verified",
        path=label,
        version=verified.package_version,
        project=verified.project_name,
        files=len(verified.files),
        hash=verified.content_hash[:SHORT_HASH],
    )
    return 0


def history(context: CommandContext, project: ProjectFolder) -> int:
    console = context.console
    link = project.link()
    client = context.client()
    versions = packages.history(client, link.project_id)
    console.heading(context.text("package.history_heading", project=link.project_name))
    if not versions:
        console.say("package.history_none")
        return 0
    here = _local_summary(project)
    rows: list[list[str]] = []
    for item in versions:
        number = version_number(item)
        content_hash = item.get("content_hash")
        shown = str(number)
        if here is not None and (here.version_number, here.content_hash) == (
            number,
            content_hash,
        ):
            shown = context.text("package.history_here", version=number)
        rows.append(
            [
                shown,
                moment_text(item.get("created_at")),
                str(content_hash or "-")[:SHORT_HASH],
                str(item.get("file_count") or "-"),
            ]
        )
    console.table(
        [
            context.text("package.column_version"),
            context.text("package.column_date"),
            context.text("package.column_hash"),
            context.text("package.column_files"),
        ],
        rows,
    )
    return 0


def verify_key(error: CliError) -> str:
    if error.values.get("reason") == knowledge.LINE_ENDINGS:
        return "package.verify_line_endings"
    return VERIFY_KEYS.get(str(error.values.get("code")), "package.verify_generic")


def folder_label(link: ProjectLink) -> str:
    return f"{link.knowledge_folder}/"


def version_number(document: Mapping[str, object]) -> int:
    number = document.get("version_number")
    if not isinstance(number, int) or isinstance(number, bool):
        raise ApiFailure("API_FAILURE", http_status=200)
    return number


def moment_text(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "-"
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return value
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


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


def _local_line(context: CommandContext, local: LocalFolder, label: str) -> None:
    console = context.console
    if not local.exists:
        console.say("package.local_missing", path=label)
        return
    problem = local.problem
    found = local.summary
    if found is None:
        values = {} if problem is None else problem.values
        console.say(
            "package.local_unreadable",
            path=label,
            file=str(values.get("path", "")),
            code=str(values.get("code", "")),
        )
        return
    if problem is None:
        console.say(
            "package.local_ok",
            path=label,
            version=found.version_number,
            date=moment_text(found.created_at),
        )
        return
    key = (
        "package.local_line_endings"
        if problem.values.get("reason") == knowledge.LINE_ENDINGS
        else "package.local_problem"
    )
    console.say(
        key,
        path=label,
        version=found.version_number,
        file=str(problem.values.get("path", "")),
        code=str(problem.values.get("code", "")),
    )


def _studio_latest(
    client: StudioClient, project_id: str
) -> tuple[Mapping[str, object] | None, str | None]:
    try:
        return packages.latest(client, project_id), None
    except CliError as error:
        reason = _offline_reason(error)
        if reason is None:
            raise
        return None, reason


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


def _advice(
    local: LocalFolder, latest: Mapping[str, object] | None, reason: str | None
) -> str | None:
    if local.exists and local.problem is not None:
        if local.problem.values.get("reason") == knowledge.LINE_ENDINGS:
            return "package.advice_line_endings"
        return "package.advice_restore"
    if reason is not None:
        return None
    if latest is None:
        return "package.advice_newer" if local.exists else "package.advice_publish_first"
    if local.summary is None:
        return "package.advice_download"
    newest = version_number(latest)
    if local.summary.version_number < newest:
        return "package.advice_older"
    if local.summary.version_number > newest:
        return "package.advice_newer"
    if local.summary.content_hash != latest.get("content_hash"):
        return "package.advice_different"
    return "package.advice_up_to_date"


def _matches(local: LocalFolder, number: int, content_hash: object) -> bool:
    return (
        local.verified
        and local.summary is not None
        and local.summary.version_number == number
        and local.summary.content_hash == content_hash
    )


def _local_summary(project: ProjectFolder) -> knowledge.FolderSummary | None:
    try:
        return knowledge.summary(project.knowledge)
    except CliError:
        return None
