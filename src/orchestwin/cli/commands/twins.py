from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import twin_chat
from orchestwin.cli.errors import SIGN_IN_STATUS, CliError
from orchestwin.cli.flows import review, twin_conversation
from orchestwin.cli.flows.twin_selection import (
    OBSERVATION_PREFIX,
    Twin,
    folded,
    observation_values,
    select,
    twins_from,
)
from orchestwin.cli.project import LOCAL_FOLDER, STEPS_FOLDER, read_json

if TYPE_CHECKING:
    from pathlib import Path

    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.project import ProjectFolder, ProjectLink

NAME = "twins"
NESTED_OPTIONS: Final[dict[str, object]] = {"color": False} if sys.version_info >= (3, 14) else {}
LIST: Final = "list"
SHOW: Final = "show"
ASK: Final = "ask"
REVIEW: Final = "review"
TWINS_STAGE: Final = "twins"
UNREACHABLE: Final = "unreachable"
NOT_SIGNED_IN: Final = "not_signed_in"
SESSION_EXPIRED: Final = "session_expired"
OFFLINE_KEYS: Final[Mapping[str, str]] = {
    UNREACHABLE: "twins.offline_unreachable",
    NOT_SIGNED_IN: "twins.offline_not_signed_in",
    SESSION_EXPIRED: "twins.offline_session_expired",
}
SECTIONS: Final = (
    ("twins.section_goals", ("goals",)),
    ("twins.section_obstacles", ("frustrations", "pain_points")),
    ("twins.section_context", ("context_of_use",)),
)
FIELDS: Final = (
    "role",
    "age_range",
    "expertise",
    "goals",
    "recurring_tasks",
    "context_of_use",
    "information_needs",
    "decision_criteria",
    "preferred_vocabulary",
    "frustrations",
    "pain_points",
    "trust_concerns",
    "accessibility_needs",
    "operational_constraints",
    "technical_literacy",
    "risk_sensitivity",
    "assumptions",
)
EPISTEMIC_STATUSES: Final = (
    "MODEL_INFERRED",
    "UNSUPPORTED_ASSUMPTION",
    "USER_PROVIDED",
    "HUMAN_VALIDATED",
    "EMPIRICALLY_SUPPORTED",
)
SOURCE_KINDS: Final = (
    "PROJECT_BRIEF",
    "OWNER_INPUT",
    "EMPIRICAL_RESEARCH",
    "HUMAN_REVIEW",
    "MODEL_OUTPUT",
    "SYSTEM_ARTIFACT",
)
ABSTAINED_VALUE: Final = "ABSTAINED"
REVIEW_REQUIRED: Final = "REQUIRED"


def configure(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", metavar="ACTION", help="twins.option_action")
    _action(actions, parser, LIST, help="twins.help_list")
    show = _action(actions, parser, SHOW, help="twins.help_show")
    show.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    ask = _action(actions, parser, ASK, help="twins.help_ask")
    ask.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    ask.add_argument("question", metavar="QUESTION", nargs="*", help="twins.option_question")
    _action(actions, parser, REVIEW, help="twins.help_review")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action or LIST
    project = context.project()
    if action == REVIEW:
        return review.run_review(context, context.client(), project)
    link = project.link()
    if action == ASK:
        client = context.client()
        twins = studio_twins(client, link.project_id)
        twin = _selected(context, link, twins, arguments.twin, online=True)
        if twin is None:
            return 1
        question = " ".join(arguments.question).strip()
        if question:
            return twin_conversation.ask_once(context, client, link.project_id, twin, question)
        return twin_conversation.converse(context, client, link.project_id, twin)
    twins, online = _readable_twins(context, project, link)
    if action == SHOW:
        twin = _selected(context, link, twins, arguments.twin, online=online)
        if twin is None:
            return 1
        show_twin(context, twin)
        return 0
    show_list(context, link, twins, online=online)
    return 0


def studio_twins(client: StudioClient, project_id: str) -> tuple[Twin, ...]:
    if not twin_chat.approved(twin_chat.readiness(client, project_id)):
        raise CliError("TWINS_NOT_APPROVED")
    document = twin_chat.current_snapshot(client, project_id)
    if document is None:
        raise CliError("TWINS_NOT_APPROVED")
    return twins_from(twin_chat.twin_versions(document))


def show_list(
    context: CommandContext, link: ProjectLink, twins: Sequence[Twin], *, online: bool
) -> None:
    console = context.console
    console.heading(context.text("twins.list_heading", project=link.project_name))
    if not twins:
        console.say("twins.none")
        return
    console.table(
        [
            context.text("twins.column_number"),
            context.text("twins.column_name"),
            context.text("twins.column_role"),
            context.text("twins.column_wants"),
        ],
        [[str(twin.number), twin.name, twin.role or "-", twin.wants or "-"] for twin in twins],
    )
    console.write()
    console.say("twins.hint_show", number=twins[0].number)
    if online:
        console.say("twins.hint_ask", number=twins[0].number)


def show_twin(context: CommandContext, twin: Twin) -> None:
    console = context.console
    console.heading(twin.name)
    role = twin.role
    if role is not None and folded(role) != folded(twin.name):
        console.say("twins.role", role=role)
    for key, fields in SECTIONS:
        values = [value for field in fields for value in twin.values(field)]
        if values:
            console.write()
            console.write(context.text(key))
            console.items(values)
    if twin.observations:
        console.write()
        console.write(context.text("twins.section_observations"))
        console.items([observation_line(context, item) for item in twin.observations])


def observation_line(context: CommandContext, observation: Mapping[str, object]) -> str:
    line = context.text(
        "twins.observation",
        label=field_label(context, observation.get("observation_key")),
        value=value_text(context, observation),
        origin=origin_text(context, observation),
    )
    rationale = observation.get("rationale")
    if isinstance(rationale, str) and rationale.strip():
        return context.text("twins.observation_why", line=line, rationale=rationale.strip())
    return line


def field_label(context: CommandContext, key: object) -> str:
    text = key if isinstance(key, str) else ""
    field = text.removeprefix(OBSERVATION_PREFIX).rsplit(".", 1)[-1].strip()
    if field in FIELDS:
        return context.text(f"twins.field_{field}")
    words = " ".join(field.replace("_", " ").replace("-", " ").split())
    return words[:1].upper() + words[1:] if words else "-"


def value_text(context: CommandContext, observation: Mapping[str, object]) -> str:
    values = observation_values(observation)
    if values:
        return "; ".join(values)
    value = observation.get("value")
    kind = value.get("kind") if isinstance(value, Mapping) else None
    reason = value.get("reason") if isinstance(value, Mapping) else None
    shown = context.text("twins.abstained" if kind == ABSTAINED_VALUE else "twins.not_known")
    if isinstance(reason, str) and reason.strip():
        return context.text("twins.value_reason", value=shown, reason=reason.strip())
    return shown


def origin_text(context: CommandContext, observation: Mapping[str, object]) -> str:
    raw = observation.get("epistemic_status")
    status = (
        context.text(f"twins.status_{raw.lower()}")
        if raw in EPISTEMIC_STATUSES
        else str(raw or "-")
    )
    if observation.get("human_validation") == REVIEW_REQUIRED:
        status = context.text("twins.needs_review", status=status)
    references = observation.get("provenance")
    sources: list[str] = []
    for reference in references if isinstance(references, list | tuple) else ():
        kind = reference.get("source_kind") if isinstance(reference, Mapping) else None
        if not isinstance(kind, str) or not kind:
            continue
        label = context.text(f"twins.source_kind_{kind.lower()}") if kind in SOURCE_KINDS else kind
        if label not in sources:
            sources.append(label)
    if not sources:
        return status
    return context.text("twins.origin_sources", status=status, sources=", ".join(sources))


def _action(
    actions: argparse._SubParsersAction,
    parser: argparse.ArgumentParser,
    name: str,
    *,
    help: str,
) -> argparse.ArgumentParser:
    child = actions.add_parser(
        name,
        help=help,
        formatter_class=parser.formatter_class,
        add_help=False,
        allow_abbrev=False,
        **NESTED_OPTIONS,
    )
    child.add_argument("-h", "--help", action="help", help="common.option_help")
    return child


def _selected(
    context: CommandContext,
    link: ProjectLink,
    twins: Sequence[Twin],
    value: str,
    *,
    online: bool,
) -> Twin | None:
    twin = select(context, twins, value)
    if twin is None:
        context.console.error("twins.no_match", value=value.strip())
        show_list(context, link, twins, online=online)
    return twin


def _readable_twins(
    context: CommandContext, project: ProjectFolder, link: ProjectLink
) -> tuple[tuple[Twin, ...], bool]:
    client = context.client()
    try:
        twins = studio_twins(client, link.project_id)
    except CliError as error:
        reason = _offline_reason(error)
        local = None if reason is None else _local_twins(context, project, link)
        if reason is None or local is None:
            raise
        source, versions = local
        context.console.say(OFFLINE_KEYS[reason], studio=client.studio.origin, source=source)
        return twins_from(versions), False
    return twins, True


def _offline_reason(error: CliError) -> str | None:
    if error.code == "STUDIO_UNREACHABLE":
        return UNREACHABLE
    if error.code == "NOT_SIGNED_IN":
        return NOT_SIGNED_IN
    if error.status == SIGN_IN_STATUS:
        return SESSION_EXPIRED
    return None


def _local_twins(
    context: CommandContext, project: ProjectFolder, link: ProjectLink
) -> tuple[str, list[Mapping[str, object]]] | None:
    from orchestwin.knowledge.layout import stage_document

    folder = project.knowledge
    document = read_json(folder / stage_document(TWINS_STAGE))
    if isinstance(document, dict) and isinstance(document.get("snapshot"), dict):
        version = _folder_version(folder)
        path = f"{link.knowledge_folder}/"
        source = (
            context.text("twins.source_folder_plain", path=path)
            if version is None
            else context.text("twins.source_folder", path=path, version=version)
        )
        return source, twin_chat.twin_versions(document)
    step = project.step(TWINS_STAGE)
    if step is None:
        return None
    path = f"{LOCAL_FOLDER}/{STEPS_FOLDER}/{TWINS_STAGE}.json"
    versions = twin_chat.twin_versions(_mapping(step.get("version")))
    return context.text("twins.source_step", path=path), versions


def _folder_version(folder: Path) -> int | None:
    try:
        found = knowledge.summary(folder)
    except CliError:
        return None
    return None if found is None else found.version_number


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None
