from __future__ import annotations

import argparse
import json
from typing import TYPE_CHECKING

from orchestwin.cli.api import why
from orchestwin.cli.errors import CliError, signed_out_reason
from orchestwin.cli.mcp.knowledge import FolderProblem, load
from orchestwin.cli.views.why import show

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

NAME = "why"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("code", help="why.option_code")
    parser.add_argument("--all", action="store_true", help="why.option_all")
    parser.add_argument("--json", action="store_true", help="why.option_json")
    parser.add_argument("--offline", action="store_true", help="why.option_offline")


def local_answer(project, code):
    from orchestwin.why import WhyError, explain_why

    try:
        knowledge = load(project.knowledge)
        document = knowledge.why(project_id=project.link().project_id)
        answer = explain_why(document, code)
        answer["limits"] = sorted({*answer["limits"], *knowledge.why_limits()})
        return answer
    except FolderProblem as error:
        raise CliError(
            "FOLDER_NOT_VERIFIED",
            values={
                "code": error.code,
                "path": error.values.get("path", ""),
                "folder": str(project.knowledge),
            },
        ) from None
    except WhyError as error:
        raise CliError(
            error.code, status=2, values={"candidates": list(error.candidates)}
        ) from None


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    try:
        return run_answer(context, arguments)
    except CliError as error:
        if not arguments.json or not error.code.startswith("WHY_CODE_"):
            raise
        context.environment.stderr.write(
            json.dumps(
                {"error": {"code": error.code, "candidates": error.values.get("candidates", [])}},
                ensure_ascii=True,
            )
            + "\n"
        )
        context.environment.stderr.flush()
        return error.status


def run_answer(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.linked_project()
    if arguments.offline:
        answer = local_answer(project, arguments.code)
        context.console.error("why.offline", reason="--offline")
    else:
        try:
            answer = why.explain(context.client(), project.link().project_id, arguments.code)
        except CliError as error:
            if signed_out_reason(error) is None:
                raise
            answer = local_answer(project, arguments.code)
            context.console.error("why.offline", reason=error.code)
    if arguments.json:
        context.console.write(json.dumps(answer, ensure_ascii=True, indent=2))
    else:
        show(context.console, answer, details=arguments.all)
    return 0
