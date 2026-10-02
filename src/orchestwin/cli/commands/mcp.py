from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from orchestwin.cli.mcp import configs, server

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "mcp"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--spend", action="store_true", help="mcp.option_spend")
    parser.add_argument(
        "--config", choices=configs.EDITORS, metavar="EDITOR", help="mcp.option_config"
    )


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project()
    if arguments.config is not None:
        return configs.show(context, project, arguments.config, spend=arguments.spend)
    return server.serve(context, project, spend=arguments.spend)
