from __future__ import annotations

import argparse
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import brief
from orchestwin.cli.api import projects as project_api
from orchestwin.cli.client import ensure_access
from orchestwin.cli.console import ATTEMPTS, Choice
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.flows import answers as answers_file
from orchestwin.cli.flows.journey import STAGES, Journey, ask_idea
from orchestwin.cli.flows.journey import code_of as code_of
from orchestwin.cli.project import LINK_FILE, ProjectFolder, ProjectLink

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.answers import Answers

NAME = "init"
DESIGN_ONLY: Final = "DESIGN_ONLY"
DESIGN_AND_CODE: Final = "DESIGN_AND_CODE"
MODE_OPTIONS: Final = {"design": DESIGN_ONLY, "design-code": DESIGN_AND_CODE}
MODE_KEYS: Final = {
    DESIGN_ONLY: "init.mode_design_only",
    DESIGN_AND_CODE: "init.mode_design_and_code",
}
STAGE_INDEX: Final = {"BRIEF": 0, "TEAM": 1, "USER_TWINS": 2, "REQUIREMENTS": 3}
STAGE_OPERATIONS: Final = (
    ("BRIEF_DIALOGUE",),
    ("TEAM_PROPOSAL",),
    ("PERSONA_PROPOSAL", "USER_TWIN_GENERATION"),
    ("REQUIREMENTS_PROPOSAL",),
)
CHANGE_OPERATION: Final = "REQUIREMENTS_CHANGE"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", metavar="NAME", help="init.option_name")
    parser.add_argument("--idea", metavar="TEXT", help="init.option_idea")
    parser.add_argument("--mode", choices=tuple(MODE_OPTIONS), help="init.option_mode")
    parser.add_argument("--project", metavar="ID", help="init.option_project")
    parser.add_argument("--answers", metavar="FILE", help="init.option_answers")
    parser.add_argument("--until", choices=STAGES, help="init.option_until")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    script = _script(context, arguments.answers)
    name = _name_option(arguments.name)
    idea = _idea_option(arguments.idea)
    project_id = _project_option(arguments.project)
    mode = MODE_OPTIONS[arguments.mode] if arguments.mode else None
    until = arguments.until
    folder = context.project(required=False)
    if folder is None and project_id is None and script is not None:
        if name is None and script.name is None:
            raise script.missing("name")
        if idea is None and script.idea is None:
            raise script.missing("idea")
    client = context.client()
    require_sign_in(context, client)
    if folder is not None:
        journey = resume(context, client, folder, project_id, mode, script, until, idea)
    elif project_id is not None:
        journey = attach(context, client, project_id, mode, script, until, idea)
    else:
        journey = create(context, client, name, idea, mode, script, until)
    return journey.run()


def require_sign_in(context: CommandContext, client: StudioClient) -> None:
    ensure_access(context, client)


def create(
    context: CommandContext,
    client: StudioClient,
    name: str | None,
    idea: str | None,
    mode: str | None,
    script: Answers | None,
    until: str | None,
) -> Journey:
    console = context.console
    client.get("/auth/me")
    console.say("init.welcome")
    console.say("init.path")
    chosen = _mode(context, mode, script)
    statement = idea or (script.idea if script is not None else None) or ask_idea(context)
    title = name or (script.name if script is not None else None) or ask_name(context)
    spend(context, client, operations(0, until, script), script)
    created = project_api.create_project(client, title)
    shown = created.get("display_name")
    link = ProjectLink(
        studio=client.studio.origin,
        api_prefix=client.studio.api_prefix,
        project_id=str(created["id"]),
        project_name=shown if isinstance(shown, str) and shown else title,
        mode=chosen,
        language=context.language,
        created_at=context.now_text(),
    )
    folder = ProjectFolder.create(context.directory, link)
    console.say("init.created", name=link.project_name, path=str(folder.local / LINK_FILE))
    return Journey(context, client, folder, script=script, until=until, idea=statement)


def attach(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    mode: str | None,
    script: Answers | None,
    until: str | None,
    idea: str | None,
) -> Journey:
    found = project_api.get_project(client, project_id)
    shown = found.get("display_name")
    title = shown if isinstance(shown, str) and shown else project_id
    context.console.say("init.attaching", name=title)
    chosen = _mode(context, mode, script)
    link = ProjectLink(
        studio=client.studio.origin,
        api_prefix=client.studio.api_prefix,
        project_id=str(found.get("id") or project_id),
        project_name=title,
        mode=chosen,
        language=None,
        created_at=context.now_text(),
    )
    folder = ProjectFolder.create(context.directory, link)
    context.console.say("init.linked", name=title, path=str(folder.local / LINK_FILE))
    position(context, client, found, until, script)
    return Journey(context, client, folder, script=script, until=until, idea=idea)


def resume(
    context: CommandContext,
    client: StudioClient,
    folder: ProjectFolder,
    project_id: str | None,
    mode: str | None,
    script: Answers | None,
    until: str | None,
    idea: str | None,
) -> Journey:
    link = folder.link()
    if project_id is not None and project_id != link.project_id:
        raise CliError("PROJECT_ALREADY_LINKED", values={"root": str(folder.root)})
    found = project_api.get_project(client, link.project_id)
    wanted = mode or (script.mode if script is not None else None)
    if wanted is not None and wanted != link.mode:
        folder.update_link(mode=wanted)
        context.console.say("init.mode_updated", mode=context.text(MODE_KEYS[wanted]))
        if wanted == DESIGN_AND_CODE:
            context.console.say("init.mode_code_note")
    position(context, client, found, until, script)
    return Journey(context, client, folder, script=script, until=until, idea=idea)


def position(
    context: CommandContext,
    client: StudioClient,
    found: Mapping[str, object],
    until: str | None,
    script: Answers | None,
) -> None:
    shown = found.get("display_name")
    name = shown if isinstance(shown, str) else ""
    index = STAGE_INDEX.get(str(found.get("current_stage")))
    if index is None:
        context.console.say("init.resume_done", name=name)
        return
    context.console.say(
        "init.resume",
        name=name,
        number=index + 1,
        total=len(STAGES),
        step=context.text(f"common.stage_{STAGES[index]}"),
    )
    needed = operations(index, until, script)
    if needed:
        spend(context, client, needed, script)


def spend(
    context: CommandContext,
    client: StudioClient,
    needed: Sequence[str],
    script: Answers | None,
) -> None:
    try:
        costs.confirm_spending(context, client, needed, ask=script is None)
    except CliError as error:
        if error.code == "SPENDING_REFUSED" and script is not None:
            raise CliError("SPENDING_REFUSED", values={"reason": "answers"}) from None
        raise


def operations(start: int, until: str | None, script: Answers | None) -> list[str]:
    last = STAGES.index(until) if until else len(STAGES) - 1
    found: list[str] = []
    for index in range(start, last + 1):
        found.extend(STAGE_OPERATIONS[index])
    if script is not None and start <= len(STAGES) - 1 <= last:
        found.extend([CHANGE_OPERATION] * len(script.changes))
    return found


def ask_mode(context: CommandContext) -> str:
    options = [
        Choice("design", context.text("init.mode_design_only")),
        Choice("design-code", context.text("init.mode_design_and_code")),
    ]
    return MODE_OPTIONS[context.console.choose("init.mode_question", options, default="1").key]


def ask_name(context: CommandContext) -> str:
    console = context.console
    folder = " ".join(context.directory.name.split())
    default = folder if 0 < len(folder) <= brief.MAX_NAME else None
    for _ in range(ATTEMPTS):
        name = " ".join(console.ask("init.name", default=default).split())
        if 0 < len(name) <= brief.MAX_NAME:
            return name
        console.say("init.name_too_long", limit=brief.MAX_NAME)
    raise CliError("ANSWER_NOT_VALID")


def _mode(context: CommandContext, mode: str | None, script: Answers | None) -> str:
    if mode is not None:
        chosen = mode
    elif script is not None:
        chosen = script.mode or DESIGN_ONLY
    else:
        chosen = ask_mode(context)
    if chosen == DESIGN_AND_CODE:
        context.console.say("init.mode_code_note")
    return chosen


def _script(context: CommandContext, value: str | None) -> Answers | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = context.environment.working_directory / path
    return answers_file.load(path)


def _name_option(value: str | None) -> str | None:
    if value is None:
        return None
    name = " ".join(value.split())
    if not 0 < len(name) <= brief.MAX_NAME:
        raise CliError("NAME_INVALID", status=USAGE_STATUS, values={"limit": brief.MAX_NAME})
    return name


def _idea_option(value: str | None) -> str | None:
    if value is None:
        return None
    idea = value.strip()
    if not 0 < len(idea) <= brief.MAX_STATEMENT:
        raise CliError("IDEA_INVALID", status=USAGE_STATUS, values={"limit": brief.MAX_STATEMENT})
    return idea


def _project_option(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return str(uuid.UUID(value.strip()))
    except ValueError:
        raise CliError("PROJECT_ID_INVALID", status=USAGE_STATUS, values={"value": value}) from None
