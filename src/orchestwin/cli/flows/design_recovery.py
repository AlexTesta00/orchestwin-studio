from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import design as design_api
from orchestwin.cli.api import sections as sections_api

if TYPE_CHECKING:
    from orchestwin.cli.api.sections import Section, Sections
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.design_state import DesignState
    from orchestwin.cli.project import ProjectFolder

REGENERATE: Final = "regenerate"
UPDATE: Final = "update_sections"
BLOCKED: Final = "blocked"
READY: Final = frozenset({sections_api.FINE, sections_api.UPDATE_AVAILABLE})
UPSTREAM: Final = sections_api.SECTION_KEYS[: sections_api.SECTION_KEYS.index(sections_api.DESIGN)]


@dataclass(frozen=True, slots=True)
class Recovery:
    sections: Sections | None
    action: str | None = None
    blocked: Section | None = None


def regeneration_block(found: Sections | None, state: DesignState) -> Section | None:
    if state.pending_change is not None:
        return sections_api.Section(
            sections_api.DESIGN, sections_api.TO_UPDATE, blocked=sections_api.REVISION_PENDING
        )
    if found is None:
        return None
    for section in found.sections:
        if sections_api.block_of(section.blocked) == sections_api.REVISION_PENDING:
            return section
    for key in UPSTREAM:
        section = found.section(key)
        if section is None or section.state not in READY:
            if section is None:
                return sections_api.Section(
                    key, sections_api.NOT_STARTED, blocked=sections_api.UPSTREAM_NOT_READY
                )
            return replace(section, blocked=section.blocked or sections_api.UPSTREAM_NOT_READY)
    return None


def assess(found: Sections | None, state: DesignState) -> Recovery:
    design = None if found is None else found.section(sections_api.DESIGN)
    if design is None or not design.behind:
        return Recovery(found)
    blocker = regeneration_block(found, state)
    if (
        blocker is not None
        and sections_api.block_of(blocker.blocked) == sections_api.REVISION_PENDING
    ):
        return Recovery(found, BLOCKED, blocker)
    block = sections_api.block_of(design.blocked)
    if (
        design.blocked is None
        and found.alignment.available
        and sections_api.DESIGN in found.alignment.sections
    ):
        return Recovery(found, UPDATE)
    if block in (sections_api.REQUIREMENT_NO_LONGER_AVAILABLE, sections_api.PREPARE_AGAIN):
        if blocker is None:
            return Recovery(found, REGENERATE, design)
        return Recovery(found, BLOCKED, blocker)
    return Recovery(found, BLOCKED, blocker or design)


def read(client: StudioClient, project: ProjectFolder, state: DesignState) -> Recovery:
    found = (
        sections_api.sections(client, project.link().project_id)
        if state.version is not None
        else None
    )
    recovery = assess(found, state)
    if recovery.action is not None and (pending := pending_revision(client, state)) is not None:
        return Recovery(found, BLOCKED, pending)
    return recovery


def pending_revision(client: StudioClient, state: DesignState) -> Section | None:
    if any(
        item.get("status") == "PROPOSED" for item in design_api.revisions(client, state.project_id)
    ):
        return sections_api.Section(
            sections_api.DESIGN, sections_api.TO_UPDATE, blocked=sections_api.REVISION_PENDING
        )
    return None


def explain(context: CommandContext, recovery: Recovery, *, error: bool = False) -> None:
    from orchestwin.cli.commands import sections as sections_command

    write = context.console.error if error else context.console.say
    if recovery.action == UPDATE:
        write("design.behind")
    elif recovery.action == REGENERATE:
        section = recovery.blocked
        if section is not None and section.blocked == sections_api.REQUIREMENT_NO_LONGER_AVAILABLE:
            write("design.recovery_requirement_removed", codes=", ".join(section.codes) or "-")
        else:
            write("design.recovery_prepare_again")
    elif recovery.blocked is not None:
        section = recovery.blocked
        block = sections_api.block_of(section.blocked)
        if block == sections_api.REVISION_PENDING:
            write("design.recovery_revision_pending")
            return
        command = sections_command.solver(recovery.sections, section.key, block)
        detail = sections_command.blocked_text(
            context, section.stage, block, section.blocked, section.codes, command
        )
        write("design.recovery_blocked", blocked=detail)
