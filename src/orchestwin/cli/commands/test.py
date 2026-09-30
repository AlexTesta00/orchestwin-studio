from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import tests as tests_api
from orchestwin.cli.console import Console
from orchestwin.cli.context import CommandContext
from orchestwin.cli.errors import USAGE_STATUS, CliError
from orchestwin.cli.flows import previews, test_run
from orchestwin.cli.flows.test_settings import BROWSER_CHOICES
from orchestwin.cli.project import json_default

if TYPE_CHECKING:
    from orchestwin.cli.flows.test_run import TestOutcome

NAME = "test"
DEFAULT_MAX_USD: Final = 2.0
LATEST_PLAN: Final = "latest"
NEW_PLAN: Final = "new"
PLAN_CHOICES: Final = (LATEST_PLAN, NEW_PLAN)
CODE_SEPARATORS: Final = re.compile(r"[\s,;]+")


def configure(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--url", metavar="ADDRESS", help="test.option_url")
    source.add_argument("--static", metavar="FOLDER", help="test.option_static")
    parser.add_argument("--browser", choices=BROWSER_CHOICES, help="test.option_browser")
    parser.add_argument("--criteria", metavar="CODES", help="test.option_criteria")
    parser.add_argument(
        "--plan", choices=PLAN_CHOICES, default=LATEST_PLAN, help="test.option_plan"
    )
    parser.add_argument("--no-review", action="store_true", help="test.option_no_review")
    parser.add_argument(
        "--max-usd",
        type=float,
        default=DEFAULT_MAX_USD,
        metavar="USD",
        help="test.option_max_usd",
    )
    parser.add_argument("--open", action="store_true", help="test.option_open")
    parser.add_argument("--json", action="store_true", help="test.option_json")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    cap = float(arguments.max_usd)
    if not math.isfinite(cap) or cap < 0:
        raise CliError("TEST_MAX_USD_INVALID", status=USAGE_STATUS)
    request = test_run.TestRequest(
        application=application(arguments),
        browsers=() if arguments.browser is None else (str(arguments.browser),),
        criteria=codes(arguments.criteria),
        new_plan=arguments.plan == NEW_PLAN,
        review=not arguments.no_review,
        max_usd=cap,
    )
    working = diagnostic_context(context) if arguments.json else context
    outcome = test_run.execute(working, request)
    if arguments.open:
        previews.open_page(working, outcome.report)
    if arguments.json:
        print_run(context, outcome)
    if tests_api.failing(outcome.run):
        working.console.write()
        working.console.say("test.failed_summary")
        return 1
    return 0


def application(arguments: argparse.Namespace) -> dict[str, str] | None:
    if arguments.url is not None:
        return {"kind": tests_api.URL, "address": str(arguments.url)}
    if arguments.static is not None:
        return {"kind": tests_api.STATIC, "address": str(arguments.static)}
    return None


def codes(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part for part in CODE_SEPARATORS.split(value) if part)


def diagnostic_context(context: CommandContext) -> CommandContext:
    environment = replace(context.environment, stdout=context.environment.stderr)
    console = Console(environment, language=context.language, color=context.console.color)
    return CommandContext(
        environment,
        console,
        language=context.language,
        assume_yes=context.assume_yes,
        debug=context.debug,
        directory=context.directory,
        sessions=context.sessions,
    )


def print_run(context: CommandContext, outcome: TestOutcome) -> None:
    text = json.dumps(dict(outcome.run), indent=2, ensure_ascii=True, default=json_default)
    context.console.write(text)
