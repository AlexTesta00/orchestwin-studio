from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Final

from orchestwin.cli.client import LOCAL_ACCESS, SESSION_ACCESS, ensure_access
from orchestwin.cli.commands.login import studio_address
from orchestwin.cli.errors import CliError

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "logout"
WITHOUT_SESSION: Final = frozenset({"NOT_SIGNED_IN", "STUDIO_UNREACHABLE"})


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--studio", metavar="ADDRESS", help="logout.option_studio")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    studio = studio_address(context, arguments.studio)
    client = context.client(studio)
    try:
        access = ensure_access(context, client)
    except CliError as error:
        if error.code not in WITHOUT_SESSION:
            raise
        access = None
    if access != SESSION_ACCESS:
        if context.sessions.read(studio) is not None:
            context.sessions.forget(studio)
        if access == LOCAL_ACCESS:
            context.console.say("logout.local_mode", studio=studio.origin)
        else:
            context.console.say("logout.nobody", studio=studio.origin)
        return 0
    try:
        client.sign_out()
    except CliError as error:
        if error.code != "STUDIO_UNREACHABLE":
            raise
        context.console.say("logout.offline", studio=studio.origin)
        return 0
    context.console.say("logout.done", studio=studio.origin)
    return 0
