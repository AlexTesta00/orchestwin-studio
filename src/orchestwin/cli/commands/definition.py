from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING

from orchestwin.cli.api import requirements
from orchestwin.cli.errors import SIGN_IN_STATUS, CliError
from orchestwin.cli.project import read_json
from orchestwin.cli.views.definition import show

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

NAME = "definition"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--all", action="store_true", help="definition.option_all")
    parser.add_argument("--json", action="store_true", help="definition.option_json")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
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
