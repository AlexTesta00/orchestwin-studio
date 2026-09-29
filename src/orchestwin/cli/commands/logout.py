from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from orchestwin.cli.commands.login import studio_address
from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "logout"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--studio", metavar="ADDRESS", help="logout.option_studio")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    studio = studio_address(context, arguments.studio)
    session = context.sessions.read(studio)
    if session is None or not session.signed_in:
        if session is not None:
            context.sessions.forget(studio)
        context.console.say("logout.nobody", studio=studio.origin)
        return 0
    try:
        context.client(studio).sign_out()
    except CliError as error:
        if error.code != "STUDIO_UNREACHABLE":
            raise
        context.console.say("logout.offline", studio=studio.origin)
        return 0
    context.console.say("logout.done", studio=studio.origin)
    return 0
