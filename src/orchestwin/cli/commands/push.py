from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from orchestwin.cli.flows import push as push_flow

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "push"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="push.option_dry_run")
    parser.add_argument("--stage", choices=push_flow.STAGES, help="push.option_stage")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    return push_flow.run(context, dry_run=arguments.dry_run, stage=arguments.stage)
