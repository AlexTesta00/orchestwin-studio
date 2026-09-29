from __future__ import annotations

import argparse
from typing import TYPE_CHECKING, Final

from orchestwin.cli.errors import SIGN_IN_STATUS, USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.session import DEFAULT_STUDIO, StudioAddress

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "login"
HEALTHY: Final = 200
REFUSED: Final = frozenset({401, 422})
TOO_MANY_ATTEMPTS: Final = 429


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--studio", metavar="ADDRESS", help="login.option_studio")
    parser.add_argument("--email", metavar="EMAIL", help="login.option_email")
    parser.add_argument("--password-stdin", action="store_true", help="login.option_password_stdin")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    studio = studio_address(context, arguments.studio)
    client = context.client(studio)
    health = client.health()
    if health.status != HEALTHY:
        raise CliError(
            "STUDIO_NOT_RECOGNIZED",
            values={"address": studio.origin, "http_status": health.status},
        )
    given = (arguments.email or "").strip()
    if arguments.password_stdin:
        password = context.console.read_line()
        email = given or _ask_email(context, studio)
    else:
        email = given or _ask_email(context, studio)
        password = context.console.secret("login.password")
    if not password:
        context.console.error("login.password_empty")
        return USAGE_STATUS
    try:
        user = client.sign_in(email, password)
    except ApiFailure as failure:
        if failure.http_status in REFUSED:
            context.console.error("login.refused")
            return SIGN_IN_STATUS
        if failure.http_status == TOO_MANY_ATTEMPTS:
            context.console.error("login.too_many_attempts")
            return SIGN_IN_STATUS
        raise
    shown = user.get("email")
    context.console.say(
        "login.done",
        email=shown if isinstance(shown, str) and shown else email,
        studio=studio.origin,
    )
    linked = _linked_studio(context)
    if linked is not None and linked != studio.origin:
        context.console.say("login.other_studio", linked=linked)
    return 0


def studio_address(context: CommandContext, option: str | None) -> StudioAddress:
    if option:
        return StudioAddress.parse(option)
    default = context.sessions.default_studio()
    return StudioAddress.parse(DEFAULT_STUDIO) if default is None else default


def _ask_email(context: CommandContext, studio: StudioAddress) -> str:
    session = context.sessions.read(studio)
    remembered = session.email if session is not None and session.email else None
    return context.console.ask("login.email", default=remembered)


def _linked_studio(context: CommandContext) -> str | None:
    project = context.project(required=False)
    if project is None:
        return None
    try:
        link = project.link()
    except CliError:
        return None
    try:
        return StudioAddress.parse(link.studio).origin
    except CliError:
        return link.studio
