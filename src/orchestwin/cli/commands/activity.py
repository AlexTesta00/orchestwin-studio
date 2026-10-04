from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import activity as activity_api
from orchestwin.cli.errors import USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.project import write_atomically
from orchestwin.cli.views.activity import csv_text, mappings, show

if TYPE_CHECKING:
    from datetime import datetime

    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

NAME = "activity"
START: Final = "start"
STOP: Final = "stop"
SOURCE: Final = "UT"
NOT_ACTIVE: Final = "ACTIVITY_SESSION_NOT_ACTIVE"
UNRECORDED: Final = frozenset({"login", "logout", NAME})
MAX_BATCH_EVENTS: Final = 50
MAX_DURATION_MS: Final = 86_400_000


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", nargs="?", choices=(START, STOP), help="activity.option_action")
    parser.add_argument("code", nargs="?", metavar="CODE", help="activity.option_code")
    parser.add_argument("--json", action="store_true", help="activity.option_json")
    parser.add_argument("--csv", metavar="FILE", help="activity.option_csv")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action
    shown = arguments.json or arguments.csv is not None
    if (
        (action == START) != (arguments.code is not None)
        or (action is not None and shown)
        or (arguments.json and arguments.csv is not None)
    ):
        raise CliError("ACTIVITY_OPTIONS_INVALID", status=USAGE_STATUS)
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    client = context.client()
    project_id = project.link().project_id
    if action == START:
        session = activity_api.start(client, project_id, arguments.code)
        project.save_activity_session(str(session["code"]), str(session["started_at"]))
        context.console.say("activity.started", code=session["code"])
        return 0
    if action == STOP:
        return stop(context, client, project)
    document = activity_api.overview(client, project_id)
    if arguments.json:
        context.console.write(json.dumps(document, ensure_ascii=True, indent=2))
    elif arguments.csv is not None:
        events = mappings(document.get("events"))
        path = context.directory / arguments.csv
        try:
            write_atomically(path, csv_text(events).encode("utf-8"))
        except OSError:
            raise CliError("ACTIVITY_CSV_NOT_WRITTEN", values={"path": str(path)}) from None
        context.console.say("activity.csv_written", count=len(events), path=str(path))
    else:
        show(context, document)
    return 0


def stop(context: CommandContext, client: StudioClient, project: ProjectFolder) -> int:
    project_id = project.link().project_id
    saved = project.activity_session()
    code = activity_api.active_code(client, project_id) if saved is None else saved["session_code"]
    if code is None:
        raise CliError("ACTIVITY_SESSION_NOT_ACTIVE")
    try:
        activity_api.end(client, project_id, str(code))
    except ApiFailure as failure:
        if failure.code == NOT_ACTIVE:
            project.forget_activity_session()
        raise
    project.forget_activity_session()
    context.console.say("activity.stopped", code=code)
    return 0


def record_command(
    context: CommandContext, name: str, started_at: datetime, seconds: float, status: int
) -> None:
    if name in UNRECORDED:
        return
    project = context.project(required=False)
    saved = None if project is None else project.activity_session()
    if project is None or saved is None:
        return
    body = journal(
        str(saved["session_code"]),
        name,
        started_at,
        context.environment.now(),
        seconds,
        status,
        context.generation_waits,
    )
    try:
        activity_api.record(context.client(), project.link().project_id, body)
    except ApiFailure as failure:
        if failure.code == NOT_ACTIVE:
            project.forget_activity_session()


def journal(
    session_code: str,
    name: str,
    started_at: datetime,
    finished_at: datetime,
    seconds: float,
    status: int,
    waits: Sequence[tuple[datetime, float, int | None]],
) -> dict[str, object]:
    events: list[dict[str, object]] = [
        {"kind": "COMMAND_STARTED", "target": name, "client_at": started_at.isoformat()}
    ]
    events.extend(
        {
            "kind": "GENERATION_WAITED",
            "target": name,
            "client_at": at.isoformat(),
            "duration_ms": milliseconds(waited),
            "status": None if code is None else str(code),
        }
        for at, waited, code in waits[: MAX_BATCH_EVENTS - 2]
    )
    events.append(
        {
            "kind": "COMMAND_FINISHED",
            "target": name,
            "client_at": finished_at.isoformat(),
            "duration_ms": milliseconds(seconds),
            "status": str(status),
        }
    )
    return {"session_code": session_code, "source": SOURCE, "events": events}


def milliseconds(seconds: float) -> int:
    return min(max(round(seconds * 1000), 0), MAX_DURATION_MS)
