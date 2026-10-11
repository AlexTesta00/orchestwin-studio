from __future__ import annotations

import argparse
import re
import sys
from typing import Final

from orchestwin.cli.errors import USAGE_STATUS, CliError

PARSER_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}
CODE_SEPARATORS: Final = re.compile(r"[\s,;]+")


def nested_parser(
    actions: argparse._SubParsersAction,
    parser: argparse.ArgumentParser,
    name: str,
    *,
    help: str,
    description: str | None = None,
) -> argparse.ArgumentParser:
    child = actions.add_parser(
        name,
        help=help,
        description=description,
        formatter_class=parser.formatter_class,
        add_help=False,
        allow_abbrev=False,
        **PARSER_OPTIONS,
    )
    child.add_argument("-h", "--help", action="help", help="common.option_help")
    return child


def codes(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    return tuple(part for part in CODE_SEPARATORS.split(value) if part)


def bounded_text(value: str, limit: int, too_long: str) -> str:
    text = " ".join(value.split())
    if len(text) > limit:
        raise CliError(too_long, status=USAGE_STATUS, values={"limit": limit})
    return text
