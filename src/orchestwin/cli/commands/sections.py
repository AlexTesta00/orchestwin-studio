from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import projects as project_api
from orchestwin.cli.api import sections as sections_api
from orchestwin.cli.errors import (
    INTERRUPTED_STATUS,
    SIGN_IN_STATUS,
    UNREACHABLE_STATUS,
    USAGE_STATUS,
    CliError,
)
from orchestwin.cli.flows.publish import publish_and_pull
from orchestwin.cli.messages import known
from orchestwin.cli.views.workflow_inputs import show_records

if TYPE_CHECKING:
    from orchestwin.cli.api.sections import Gesture, Result, Section, Sections
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder

NAME = "sections"
NESTED_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}
UPDATE: Final = "update"
UNSUPPORTED: Final = "SECTIONS_UNSUPPORTED"
JSON_ALONE: Final = "SECTIONS_JSON_ALONE"
SEPARATOR: Final = ", "
ENDING_STATUSES: Final = frozenset({SIGN_IN_STATUS, UNREACHABLE_STATUS, INTERRUPTED_STATUS})
SOLVE_INIT: Final = "sections.solve_init"
SOLVE_DESIGN: Final = "sections.solve_design"
SOLVE_DESIGN_CHANGE: Final = "sections.solve_design_change"
SOLVE_WEB: Final = "sections.solve_web"


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="sections.option_json")
    actions = parser.add_subparsers(dest="action", metavar="ACTION", help="sections.option_action")
    child = actions.add_parser(
        UPDATE,
        help="sections.help_update",
        formatter_class=parser.formatter_class,
        add_help=False,
        allow_abbrev=False,
        **NESTED_OPTIONS,
    )
    child.add_argument("-h", "--help", action="help", help="common.option_help")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    if arguments.action == UPDATE and arguments.json:
        raise CliError(JSON_ALONE, status=USAGE_STATUS)
    project = context.project()
    if project is None:
        raise CliError("PROJECT_NOT_LINKED")
    client = context.client()
    found = current(client, project)
    if arguments.action == UPDATE:
        return update(context, client, project, found)
    records = found.document.get("workflow_inputs", found.document.get("workflow_records"))
    has_records = records is not None and (records["decisions"] or records["prototypes"])
    if arguments.json:
        document = {**found.document, "workflow_inputs": records} if has_records else found.document
        context.console.write(json.dumps(document, indent=2, ensure_ascii=True))
        return 0
    show(context, client, project, found)
    if has_records:
        show_records(context.console, records)
    return 0


def current(client: StudioClient, project: ProjectFolder) -> Sections:
    found = sections_api.sections(client, project.link().project_id)
    if found is None:
        raise CliError(UNSUPPORTED, values={"studio": client.studio.origin})
    return found


def show(
    context: CommandContext, client: StudioClient, project: ProjectFolder, found: Sections
) -> None:
    from orchestwin.cli.commands import status as status_command

    if found.first_pass_complete:
        table(context, found)
    else:
        status_command.steps_table(
            context, project_api.step_states(client, project.link().project_id)
        )
    lines = sentences(context, found)
    if lines:
        context.console.write()
    for line in lines:
        context.console.write(line)


def update(
    context: CommandContext, client: StudioClient, project: ProjectFolder, found: Sections
) -> int:
    console = context.console
    alignment = found.alignment
    if not alignment.sections:
        console.say("sections.nothing")
        return 0
    if not alignment.available:
        for line in blocked_lines(context, found):
            console.write(line)
        return 1
    archetypes_changed = any("ARCHETYPES_CHANGED" in section.reasons for section in found.sections)
    console.say(
        "sections.archetypes_behind" if archetypes_changed else "sections.behind",
        sections=names(context, alignment.sections),
    )
    if alignment.uncovered_codes:
        console.say("sections.uncovered", codes=joined(alignment.uncovered_codes))
    for line in blocked_lines(context, found):
        console.write(line)
    if not context.assume_yes and not console.confirm("sections.confirm", default=True):
        console.say("sections.cancelled")
        return 1
    gesture = sections_api.align(client, project.link().project_id)
    if gesture is None:
        raise CliError(UNSUPPORTED, values={"studio": client.studio.origin})
    return finish(context, client, project, gesture, expected=alignment.sections)


def finish(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    gesture: Gesture,
    *,
    expected: Sequence[str],
) -> int:
    console = context.console
    aligned = gesture.aligned
    if not aligned and not gesture.blocked:
        console.say("sections.nothing")
        return 0
    after = gesture.sections
    for result in gesture.results:
        if result.outcome == sections_api.SKIPPED and result.key not in expected:
            continue
        console.write(result_line(context, after, result))
    if aligned:
        console.say("sections.done", sections=names(context, [item.key for item in aligned]))
        for line in after_lines(context, after, aligned, covered=True):
            console.write(line)
        publish(context, client, project, after)
    return 1 if gesture.blocked else 0


def publish(
    context: CommandContext,
    client: StudioClient,
    project: ProjectFolder,
    after: Sections | None,
) -> None:
    console = context.console
    if after is not None and after.behind():
        console.say("sections.folder_waits")
        return
    label = f"{project.link().knowledge_folder}/"
    try:
        summary = publish_and_pull(context, client, project)
    except CliError as error:
        if error.status in ENDING_STATUSES:
            raise
        inner = error.values.get("code")
        code = inner if isinstance(inner, str) and inner else error.code
        console.say("sections.folder_not_updated", code=code)
        return
    console.say("sections.folder_updated", path=label, version=summary.version_number)


def table(context: CommandContext, found: Sections) -> None:
    context.console.table(
        [
            context.text("sections.column_section"),
            context.text("status.column_state"),
            context.text("status.column_version"),
        ],
        [
            [
                stage_name(context, section.stage),
                state_text(context, section.state),
                version_text(context, section.version_number),
            ]
            for section in found.sections
        ],
    )


def sentences(context: CommandContext, found: Sections) -> list[str]:
    lines: list[str] = []
    alignment = found.alignment
    told = team_line(context, found)
    if told is not None:
        lines.append(told)
    if alignment.sections and alignment.available:
        key = (
            "sections.archetypes_behind"
            if any(sections_api.ARCHETYPES_CHANGED in section.reasons for section in found.sections)
            else "sections.behind"
        )
        behind = context.text(key, sections=names(context, alignment.sections))
        lines.append(f"{behind} {context.text('sections.behind_command')}")
        if alignment.uncovered_codes:
            lines.append(
                context.text("sections.uncovered", codes=joined(alignment.uncovered_codes))
            )
    lines.extend(alignable_lines(context, found, upstream_told=told is not None))
    lines.extend(material_lines(context, found))
    package = found.section(sections_api.PACKAGE)
    if package is not None and package.behind and package.blocked is None and not found.behind():
        lines.append(context.text("sections.dossier_behind"))
    return lines


def blocked_lines(context: CommandContext, found: Sections) -> list[str]:
    told = team_line(context, found)
    lines = [] if told is None else [told]
    lines.extend(alignable_lines(context, found, upstream_told=told is not None))
    return lines


def team_line(context: CommandContext, found: Sections) -> str | None:
    team = found.section(sections_api.TEAM)
    if team is None or not team.behind or team.blocked is None:
        return None
    return section_line(context, found, team)


def alignable_lines(context: CommandContext, found: Sections, *, upstream_told: bool) -> list[str]:
    lines: list[str] = []
    told = upstream_told
    for section in found.behind(sections_api.ALIGNABLE):
        if section.key == sections_api.TEAM:
            continue
        if section.blocked is None:
            continue
        if section.blocked == sections_api.UPSTREAM_NOT_READY:
            if told:
                continue
            told = True
        lines.append(section_line(context, found, section))
    return lines


def material_lines(context: CommandContext, found: Sections) -> list[str]:
    lines: list[str] = []
    twins = found.section(sections_api.USER_TWINS)
    if (
        twins is not None
        and twins.state == sections_api.UPDATE_AVAILABLE
        and sections_api.TWINS_LEARNED in twins.reasons
    ):
        lines.append(context.text("sections.twins_learned"))
    design = found.section(sections_api.DESIGN)
    if design is None or design.state != sections_api.UPDATE_AVAILABLE:
        return lines
    if sections_api.REQUIREMENTS_NOT_COVERED in design.reasons and design.codes:
        lines.append(context.text("sections.not_covered", codes=joined(design.codes)))
    if sections_api.EVALUATION_MISSING in design.reasons:
        lines.append(context.text("sections.evaluation_missing"))
    return lines


def after_lines(
    context: CommandContext,
    after: Sections | None,
    aligned: Sequence[Result],
    *,
    covered: bool,
    evaluation: str = "sections.evaluation_after",
) -> list[str]:
    if after is None or sections_api.DESIGN not in {item.key for item in aligned}:
        return []
    design = after.section(sections_api.DESIGN)
    if design is None:
        return []
    lines: list[str] = []
    if not covered and sections_api.REQUIREMENTS_NOT_COVERED in design.reasons and design.codes:
        lines.append(context.text("sections.not_covered", codes=joined(design.codes)))
    if sections_api.EVALUATION_MISSING in design.reasons:
        lines.append(context.text(evaluation))
    return lines


def section_line(context: CommandContext, found: Sections, section: Section) -> str:
    block = sections_api.block_of(section.blocked)
    return blocked_text(
        context,
        section.stage,
        block,
        section.blocked,
        section.codes,
        solver(found, section.key, block),
    )


def result_line(context: CommandContext, after: Sections | None, result: Result) -> str:
    name = stage_name(context, result.stage)
    if result.outcome == sections_api.ALIGNED:
        return context.text(
            "sections.result_aligned",
            section=name,
            version="-" if result.version_number is None else result.version_number,
        )
    if result.outcome == sections_api.BLOCKED:
        block = sections_api.block_of(result.issue)
        return blocked_text(
            context,
            result.stage,
            block,
            result.issue,
            result.codes,
            solver(after, result.key, block),
        )
    return context.text("sections.result_skipped", section=name)


def blocked_text(
    context: CommandContext,
    stage: str,
    block: str | None,
    issue: str | None,
    codes: Sequence[str],
    command: str | None,
) -> str:
    sentence = context.text(
        "sections.blocked",
        section=stage_name(context, stage),
        reason=reason_text(context, block, issue, codes),
    )
    return sentence if command is None else f"{sentence} {context.text(command)}"


def reason_text(
    context: CommandContext, block: str | None, issue: str | None, codes: Sequence[str]
) -> str:
    key = None if block is None else f"sections.reason_{block.lower()}"
    if key is None or not known(key):
        return context.text("sections.reason_other", code=issue or "-")
    return context.text(key, codes=joined(codes) or "-")


def solver(found: Sections | None, key: str, block: str | None) -> str | None:
    if block == sections_api.PREPARE_TWINS:
        return SOLVE_INIT
    if block == sections_api.PREPARE_AGAIN:
        return SOLVE_INIT
    if block == sections_api.REQUIREMENT_NO_LONGER_AVAILABLE:
        return SOLVE_DESIGN_CHANGE
    if block in (sections_api.TWIN_SET_CHANGED, sections_api.TWIN_NO_LONGER_AVAILABLE):
        return SOLVE_WEB
    if block == sections_api.REVISION_PENDING:
        return SOLVE_DESIGN if key == sections_api.DESIGN else SOLVE_WEB
    if block == sections_api.UPSTREAM_NOT_READY and found is not None:
        return upstream_solver(found, key)
    return None


def upstream_solver(found: Sections, key: str) -> str | None:
    keys = sections_api.SECTION_KEYS
    above = keys[: keys.index(key)] if key in keys else keys
    for section in found.sections:
        if section.key not in above:
            continue
        if section.state == sections_api.IN_PROGRESS:
            return SOLVE_DESIGN if section.key == sections_api.DESIGN else SOLVE_INIT
        if (
            section.behind
            and section.blocked is not None
            and section.blocked != sections_api.UPSTREAM_NOT_READY
        ):
            return solver(found, section.key, section.blocked)
    return None


def names(context: CommandContext, keys: Iterable[str]) -> str:
    return SEPARATOR.join(
        stage_name(context, sections_api.STAGE_OF.get(key, key.lower())) for key in keys
    )


def stage_name(context: CommandContext, stage: str) -> str:
    key = f"common.stage_{stage}"
    return context.text(key) if known(key) else stage.upper()


def state_text(context: CommandContext, state: str) -> str:
    key = f"sections.state_{state.lower()}"
    return context.text(key) if state in sections_api.STATES and known(key) else state


def version_text(context: CommandContext, number: int | None) -> str:
    return "-" if number is None else context.text("sections.version", number=number)


def joined(codes: Iterable[str]) -> str:
    return SEPARATOR.join(codes)
