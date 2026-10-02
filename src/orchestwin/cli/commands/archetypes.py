from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli.api import modeling
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import USAGE_STATUS, CliError

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext

NAME = "archetypes"
FIELDS = ("name", "description", "role", "context")


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="archetypes.option_json")
    actions = parser.add_subparsers(dest="action", metavar="ACTION")
    for action in ("add", "edit", "remove"):
        nested = actions.add_parser(action, help=f"archetypes.help_{action}")
        nested.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS, help="archetypes.option_json"
        )
        if action != "add":
            nested.add_argument("archetype", help="archetypes.option_archetype")
        if action != "remove":
            for field in FIELDS:
                nested.add_argument(
                    f"--{field}",
                    required=action == "add" and field != "context",
                    help=f"archetypes.option_{field}",
                )
            goals = nested.add_mutually_exclusive_group()
            goals.add_argument("--goal", action="append", help="archetypes.option_goal")
            goals.add_argument(
                "--clear-goals", action="store_true", help="archetypes.option_clear_goals"
            )


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project_id = context.project().link().project_id
    client = context.client()
    roster = modeling.archetypes(client, project_id)
    action = arguments.action
    if action is None:
        document = roster
    elif action == "add":
        document = modeling.create_archetype(client, project_id, body_of(arguments))
    else:
        current = select(roster, arguments.archetype)
        if action == "remove":
            document = modeling.archive_archetype(
                client, project_id, str(current["persona_id"]), int(current["version_number"])
            )
        else:
            body = body_of(arguments, current)
            body["based_on_version_number"] = current["version_number"]
            document = modeling.edit_archetype(client, project_id, str(current["persona_id"]), body)
    if arguments.json:
        context.console.write(json.dumps(document, ensure_ascii=False, indent=2))
    elif action is None:
        show(context, roster)
    else:
        context.console.say("archetypes.changed")
    return 0


def body_of(
    arguments: argparse.Namespace, current: Mapping[str, object] | None = None
) -> dict[str, object]:
    current = current or {}
    body = {
        field: getattr(arguments, field, None)
        if getattr(arguments, field, None) is not None
        else current.get(field)
        for field in FIELDS
    }
    body["context"] = body["context"] or None
    goals = getattr(arguments, "goal", None)
    body["goals"] = (
        []
        if getattr(arguments, "clear_goals", False)
        else (list(current.get("goals") or ()) if goals is None else goals)
    )
    if any(
        not isinstance(body[field], str) or not str(body[field]).strip()
        for field in ("name", "description", "role")
    ):
        raise CliError("ARCHETYPE_INPUT_INVALID", status=USAGE_STATUS)
    return body


def select(roster: list[Mapping[str, object]], value: str) -> Mapping[str, object]:
    exact = [
        item
        for index, item in enumerate(roster, 1)
        if value in {str(item.get("persona_id")), str(index)}
        or value.casefold() == str(item.get("name", "")).casefold()
    ]
    if len(exact) != 1:
        raise CliError("ARCHETYPE_NOT_FOUND")
    return exact[0]


def show(context: CommandContext, roster: list[Mapping[str, object]]) -> None:
    context.console.heading(context.text("archetypes.heading"))
    context.console.table(
        [
            context.text(f"archetypes.column_{field}")
            for field in ("number", "name", "description", "version")
        ],
        [
            [
                str(index),
                str(item.get("name") or "-"),
                str(item.get("description") or "-"),
                str(item.get("version_number") or "-"),
            ]
            for index, item in enumerate(roster, 1)
        ],
    )


def manage(context: CommandContext, client: StudioClient, project_id: str) -> None:
    roster = modeling.archetypes(client, project_id)
    show(context, roster)
    action = context.console.choose(
        "archetypes.manage",
        [
            Choice("done", context.text("archetypes.done")),
            *(
                Choice(item, context.text(f"archetypes.help_{item}"))
                for item in ("add", "edit", "remove")
            ),
        ],
    ).key
    if action == "done":
        return
    current = None if action == "add" else select(roster, context.console.ask("archetypes.select"))
    if action == "remove":
        modeling.archive_archetype(
            client, project_id, str(current["persona_id"]), int(current["version_number"])
        )
        return
    values = {
        field: context.console.ask(
            f"archetypes.ask_{field}", default=str((current or {}).get(field) or "")
        )
        for field in FIELDS
    }
    goals = context.console.ask(
        "archetypes.ask_goals", default="; ".join((current or {}).get("goals") or ())
    )
    arguments = argparse.Namespace(
        **values, goal=[item.strip() for item in goals.split(";") if item.strip()]
    )
    body = body_of(arguments, current)
    if current is None:
        modeling.create_archetype(client, project_id, body)
    else:
        body["based_on_version_number"] = current["version_number"]
        modeling.edit_archetype(client, project_id, str(current["persona_id"]), body)
