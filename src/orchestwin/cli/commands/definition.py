from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli import costs
from orchestwin.cli.api import requirements
from orchestwin.cli.commands.init import Journey
from orchestwin.cli.errors import SIGN_IN_STATUS, CliError
from orchestwin.cli.flows import init_requirements
from orchestwin.cli.flows.publish import publish_and_pull
from orchestwin.cli.project import read_json
from orchestwin.cli.views.definition import show

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

NAME = "definition"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "action", nargs="?", choices=("journeys",), help="definition.option_journeys"
    )
    parser.add_argument(
        "--yes", action="store_true", default=argparse.SUPPRESS, help="common.option_yes"
    )
    parser.add_argument("--all", action="store_true", help="definition.option_all")
    parser.add_argument("--json", action="store_true", help="definition.option_json")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    if arguments.action == "journeys":
        if arguments.all or arguments.json:
            raise CliError("DEFINITION_JOURNEYS_OPTIONS", status=2)
        return request_journeys(context, project)
    try:
        version = requirements.current(context.client(), project.link().project_id)
    except CliError as error:
        if (
            error.code not in {"STUDIO_UNREACHABLE", "NOT_SIGNED_IN"}
            and error.status != SIGN_IN_STATUS
        ):
            raise
        local = local_version(project)
        if local is None:
            raise
        version, source = local
        context.console.error("definition.offline", source=source, reason=error.code)
    if version is None or not requirements.specification(version):
        raise CliError("REQUIREMENTS_SPECIFICATION_NOT_FOUND")
    if arguments.json:
        context.console.write(
            json.dumps(requirements.specification(version), ensure_ascii=True, indent=2)
        )
    else:
        show(context.console, version, details=arguments.all)
    return 0


def request_journeys(context: CommandContext, project: ProjectFolder) -> int:
    client = context.client()
    version = requirements.current(client, project.link().project_id)
    if version is None:
        raise CliError("REQUIREMENTS_SPECIFICATION_NOT_FOUND")
    if requirements.pending_revision(
        requirements.revisions(client, project.link().project_id), version
    ):
        raise CliError("REQUIREMENTS_REVISION_PENDING")
    journey = Journey(context, client, project, script=None, until="requirements", idea=None)
    costs.confirm_spending(context, client, [init_requirements.CHANGE_OPERATION])
    status, document = journey.job(
        requirements.change_path(journey.project_id),
        requirements.change_body(context.text("definition.journey_request"), include_journeys=True),
        operation=init_requirements.CHANGE_OPERATION,
        label=context.text("init.change_label"),
        passthrough=(requirements.UNCHANGED,),
    )
    if status >= 400:
        context.console.say("init.change_unchanged")
        return 0
    diff = document.get("diff") if isinstance(document, Mapping) else None
    if not isinstance(diff, Mapping):
        raise journey.refused(status, document)
    proposal = diff.get("proposed_specification")
    if isinstance(proposal, Mapping):
        show(context.console, {"specification": proposal}, details=True)
    updated = init_requirements.decide(journey, diff, version, assume_yes=context.assume_yes)
    if updated.get("id") == version.get("id"):
        return 0
    gate = journey.approve(
        lambda: requirements.submit_gate(client, journey.project_id),
        lambda: requirements.decide_gate(client, journey.project_id),
        step="requirements",
    )
    journey.conclude("requirements", updated, gate)
    folder = publish_and_pull(context, client, project)
    context.console.say("init.folder_updated", version=folder.version_number)
    return 0


def local_version(project: ProjectFolder) -> tuple[Mapping[str, object], str] | None:
    path = project.knowledge / "requirements" / "requirements.json"
    document = read_json(path)
    if isinstance(document, Mapping) and requirements.specification(document):
        return document, f"{project.link().knowledge_folder}/requirements/requirements.json"
    step = project.step("requirements")
    version = None if step is None else step.get("version")
    if isinstance(version, Mapping) and requirements.specification(version):
        return version, ".orchestwin/steps/requirements.json"
    return None
