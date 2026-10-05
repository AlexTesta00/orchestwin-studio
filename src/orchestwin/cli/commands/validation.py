from __future__ import annotations

import argparse
import json

from orchestwin.cli.api import validation
from orchestwin.cli.errors import SIGN_IN_STATUS, CliError
from orchestwin.cli.mcp.knowledge import FolderProblem, load
from orchestwin.cli.views.validation import show
from orchestwin.cli.views.workflow_inputs import show_records

NAME = "validation"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action", nargs="?", choices=("walkthrough",), help="validation.option_action"
    )
    parser.add_argument("scenario", nargs="?", help="validation.option_scenario")
    parser.add_argument("--alternative", help="validation.option_alternative")
    parser.add_argument("--document-hash", help="validation.option_document_hash")
    parser.add_argument("--all", action="store_true", help="validation.option_all")
    parser.add_argument("--json", action="store_true", help="validation.option_json")
    parser.add_argument("--offline", action="store_true", help="validation.option_offline")


def _local(project, arguments):
    from orchestwin.validation import ValidationError

    try:
        knowledge = load(project.knowledge)
        if arguments.action == "walkthrough":
            return knowledge.walkthrough(
                arguments.scenario,
                project_id=project.link().project_id,
                alternative_id=arguments.alternative,
                document_hash=arguments.document_hash,
            )
        return knowledge.validation(project_id=project.link().project_id)
    except FolderProblem as error:
        raise CliError(
            "FOLDER_NOT_VERIFIED",
            values={
                "code": error.code,
                "path": error.values.get("path", ""),
                "folder": str(project.knowledge),
            },
        ) from None
    except ValidationError as error:
        raise CliError(error.code, status=2) from None


def run(context, arguments):
    if (arguments.action == "walkthrough") != (arguments.scenario is not None):
        raise CliError("VALIDATION_INPUT_INVALID", status=2)
    if arguments.action is None and (arguments.alternative or arguments.document_hash):
        raise CliError("VALIDATION_INPUT_INVALID", status=2)
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    if arguments.offline:
        answer = _local(project, arguments)
        context.console.error("validation.offline", reason="--offline")
    else:
        try:
            client = context.client()
            identity = project.link().project_id
            answer = (
                validation.walkthrough(
                    client,
                    identity,
                    arguments.scenario,
                    alternative_id=arguments.alternative,
                    document_hash=arguments.document_hash,
                )
                if arguments.action == "walkthrough"
                else validation.overview(client, identity)
            )
        except CliError as error:
            if (
                error.code not in {"STUDIO_UNREACHABLE", "NOT_SIGNED_IN"}
                and error.status != SIGN_IN_STATUS
            ):
                raise
            answer = _local(project, arguments)
            context.console.error("validation.offline", reason=error.code)
    if arguments.json:
        context.console.write(json.dumps(answer, ensure_ascii=True, indent=2))
    else:
        show(context.console, answer, details=arguments.all)
        show_records(context.console, answer.get("workflow_inputs"))
    return 0
