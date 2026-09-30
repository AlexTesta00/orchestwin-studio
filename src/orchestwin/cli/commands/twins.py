from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

from orchestwin.cli import folder as knowledge
from orchestwin.cli.api import twin_chat
from orchestwin.cli.api import twin_learning as learning_api
from orchestwin.cli.errors import SIGN_IN_STATUS, USAGE_STATUS, ApiFailure, CliError
from orchestwin.cli.flows import review, twin_conversation, twin_update
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
UPDATE: Final = "update"
LEARN: Final = "learn"
FORGET: Final = "forget"
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
UNSAFE_PARTS: Final = frozenset({"", ".", ".."})
UNSAFE_CHARACTERS: Final = ("\\", ":", "\0")


def configure(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", metavar="ACTION", help="twins.option_action")
    _action(actions, parser, LIST, help="twins.help_list")
    show = _action(actions, parser, SHOW, help="twins.help_show")
    show.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    ask = _action(actions, parser, ASK, help="twins.help_ask")
    ask.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    ask.add_argument("question", metavar="QUESTION", nargs="*", help="twins.option_question")
    _action(actions, parser, REVIEW, help="twins.help_review")
    update = _action(actions, parser, UPDATE, help="twins.help_update")
    update.add_argument("twin", metavar="TWIN", nargs="?", help="twins.option_update_twin")
    learn = _action(actions, parser, LEARN, help="twins.help_learn")
    learn.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    learn.add_argument("text", metavar="TEXT", nargs="*", help="twins.option_text")
    forget = _action(actions, parser, FORGET, help="twins.help_forget")
    forget.add_argument("twin", metavar="TWIN", help="twins.option_twin")
    forget.add_argument("code", metavar="CODE", help="twins.option_code")
    forget.add_argument("--reason", metavar="TEXT", help="twins.option_reason")


def run(context: CommandContext, arguments: argparse.Namespace) -> int:
    action = arguments.action or LIST
    if action == LEARN:
        statement = statement_of(arguments.text)
        return learn_observation(context, arguments.twin, statement)
    if action == FORGET:
        code = observation_code_of(arguments.code)
        reason = reason_of(arguments.reason)
        return forget_observation(context, arguments.twin, code, reason)
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
    if action == UPDATE:
        return update_twins(context, project, link, arguments.twin)
    twins, online, learning = _readable_twins(context, project, link)
    if action == SHOW:
        twin = _selected(context, link, twins, arguments.twin, online=online, learning=learning)
        if twin is None:
            return 1
        show_twin(context, twin, learning)
        return 0
    show_list(context, link, twins, online=online, learning=learning)
    return 0


def studio_twins(client: StudioClient, project_id: str) -> tuple[Twin, ...]:
    if not twin_chat.approved(twin_chat.readiness(client, project_id)):
        raise CliError("TWINS_NOT_APPROVED")
    document = twin_chat.current_snapshot(client, project_id)
    if document is None:
        raise CliError("TWINS_NOT_APPROVED")
    return twins_from(twin_chat.twin_versions(document))


def studio_view(
    context: CommandContext, client: StudioClient, link: ProjectLink
) -> tuple[tuple[Twin, ...], learning_api.Learning] | None:
    twins = studio_twins(client, link.project_id)
    document = learning_api.overview(client, link.project_id)
    if document is None:
        context.console.error("twins.update_unsupported")
        return None
    return twins, learning_api.learning_of(document)


def update_twins(
    context: CommandContext, project: ProjectFolder, link: ProjectLink, value: str | None
) -> int:
    client = context.client()
    view = studio_view(context, client, link)
    if view is None:
        return 1
    twins, learning = view
    chosen: Sequence[Twin] = twins
    if value is not None:
        twin = _selected(context, link, twins, value, online=True, learning=learning)
        if twin is None:
            return 1
        chosen = (twin,)
    subjects = [twin_update.Subject(twin, learning.entry(twin.twin_id) or {}) for twin in chosen]
    return twin_update.run_update(
        context, client, project, subjects, available=learning.update_available
    )


def learn_observation(context: CommandContext, value: str, statement: str) -> int:
    project = context.project()
    link = project.link()
    client = context.client()
    view = studio_view(context, client, link)
    if view is None:
        return 1
    twins, learning = view
    twin = _selected(context, link, twins, value, online=True, learning=learning)
    if twin is None:
        return 1
    before = learning_api.observation_codes(learning.entry(twin.twin_id))
    try:
        entry = learning_api.learn(client, link.project_id, twin.twin_id, statement)
    except ApiFailure as failure:
        raise about_twin(failure, twin) from None
    codes = learning_api.observation_codes(entry)
    added = [code for code in codes if code not in before] or codes[-1:]
    context.console.say(
        "twins.learn_done",
        name=twin.name,
        code=", ".join(added) or "-",
        label=learning_api.label_of(entry, twin.version_number),
    )
    twin_update.publish_folder(context, client, project)
    return 0


def forget_observation(context: CommandContext, value: str, code: str, reason: str | None) -> int:
    project = context.project()
    link = project.link()
    client = context.client()
    view = studio_view(context, client, link)
    if view is None:
        return 1
    twins, learning = view
    twin = _selected(context, link, twins, value, online=True, learning=learning)
    if twin is None:
        return 1
    try:
        entry = learning_api.retire(client, link.project_id, twin.twin_id, code, reason=reason)
    except ApiFailure as failure:
        raise about_twin(failure, twin, observation=code) from None
    number = learning_api.code_number(code)
    shown = next(
        (
            str(item["code"])
            for item in learning_api.retired_observations(entry)
            if learning_api.code_number(item.get("code")) == number
        ),
        code,
    )
    context.console.say(
        "twins.forget_done",
        name=twin.name,
        code=shown,
        label=learning_api.label_of(entry, twin.version_number),
    )
    twin_update.publish_folder(context, client, project)
    return 0


def statement_of(words: Sequence[str]) -> str:
    statement = " ".join(" ".join(words).split())
    if not statement:
        raise CliError("TWINS_TEXT_EMPTY", status=USAGE_STATUS)
    if len(statement) > learning_api.MAX_OBSERVATION_LENGTH:
        raise CliError(
            "TWINS_TEXT_TOO_LONG",
            status=USAGE_STATUS,
            values={"limit": learning_api.MAX_OBSERVATION_LENGTH},
        )
    return statement


def observation_code_of(value: str) -> str:
    code = learning_api.observation_code(value)
    if code is None:
        raise CliError(
            "TWINS_CODE_INVALID", status=USAGE_STATUS, values={"observation": value.strip()}
        )
    return code


def reason_of(value: str | None) -> str | None:
    if value is None:
        return None
    reason = " ".join(value.split())
    if len(reason) > learning_api.MAX_REASON_LENGTH:
        raise CliError(
            "TWINS_REASON_TOO_LONG",
            status=USAGE_STATUS,
            values={"limit": learning_api.MAX_REASON_LENGTH},
        )
    return reason or None


def about_twin(failure: ApiFailure, twin: Twin, **values: object) -> ApiFailure:
    return ApiFailure(
        failure.code,
        http_status=failure.http_status,
        detail=failure.detail,
        status=failure.status,
        values={
            **failure.values,
            "name": twin.name,
            "number": twin.number,
            "limit": learning_api.MAX_LEARNED_OBSERVATIONS,
            **values,
        },
    )


def show_list(
    context: CommandContext,
    link: ProjectLink,
    twins: Sequence[Twin],
    *,
    online: bool,
    learning: learning_api.Learning | None = None,
) -> None:
    console = context.console
    console.heading(context.text("twins.list_heading", project=link.project_name))
    if not twins:
        console.say("twins.none")
        return
    learned = learning is not None and learning.learned_anything()
    headers = [
        context.text("twins.column_number"),
        context.text("twins.column_name"),
        context.text("twins.column_role"),
        context.text("twins.column_wants"),
        context.text("twins.column_version"),
    ]
    if learned:
        headers.append(context.text("twins.column_learned"))
    rows: list[list[str]] = []
    for twin in twins:
        entry = _entry(learning, twin)
        row = [
            str(twin.number),
            twin.name,
            twin.role or "-",
            twin.wants or "-",
            learning_api.label_of(entry, twin.version_number),
        ]
        if learned:
            row.append(str(learning_api.learned_count(entry)))
        rows.append(row)
    console.table(headers, rows)
    console.write()
    for twin in twins:
        if learning_api.pending_update(_entry(learning, twin)) is not None:
            console.say("twins.hint_pending", name=twin.name, number=twin.number)
    console.say("twins.hint_show", number=twins[0].number)
    if online:
        console.say("twins.hint_ask", number=twins[0].number)


def show_twin(
    context: CommandContext, twin: Twin, learning: learning_api.Learning | None = None
) -> None:
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
    show_learning(context, twin, _entry(learning, twin))


def show_learning(context: CommandContext, twin: Twin, entry: Mapping[str, object] | None) -> None:
    if entry is None:
        return
    console = context.console
    console.write()
    label = learning_api.label_of(entry, twin.version_number)
    console.write(context.text("twins.section_learned", label=label))
    active = learning_api.active_observations(entry)
    retired = learning_api.retired_observations(entry)
    if active:
        console.items([learned_line(context, item) for item in active])
    elif retired:
        console.say("twins.learned_none_active")
    else:
        console.say("twins.learned_none")
    if retired:
        console.say("twins.learned_retired", count=len(retired))
    if learning_api.pending_update(entry) is not None:
        console.say("twins.learned_pending", number=twin.number)


def learned_line(context: CommandContext, observation: Mapping[str, object]) -> str:
    date = day_text(observation.get("approved_at"))
    source = observation.get("source")
    if source == learning_api.TWIN_CRITIQUE:
        origin = context.text("twins.learned_from_critiques", date=date)
    elif source == learning_api.OWNER:
        origin = context.text("twins.learned_from_owner", date=date)
    else:
        origin = context.text("twins.learned_on", date=date)
    code = observation.get("code")
    line = context.text(
        "twins.learned_observation",
        code=code if isinstance(code, str) and code else "-",
        statement=_text(observation.get("statement")),
        origin=origin,
    )
    contradiction = _text(observation.get("contradicts_profile"))
    if contradiction:
        return context.text("twins.learned_contradiction", line=line, text=contradiction)
    return line


def day_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "-"
    try:
        moment = datetime.fromisoformat(value.strip())
    except ValueError:
        return value.strip()[:10]
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%d")


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
    learning: learning_api.Learning | None = None,
) -> Twin | None:
    twin = select(context, twins, value)
    if twin is None:
        context.console.error("twins.no_match", value=value.strip())
        show_list(context, link, twins, online=online, learning=learning)
    return twin


def _readable_twins(
    context: CommandContext, project: ProjectFolder, link: ProjectLink
) -> tuple[tuple[Twin, ...], bool, learning_api.Learning | None]:
    client = context.client()
    try:
        twins = studio_twins(client, link.project_id)
        document = learning_api.overview(client, link.project_id)
    except CliError as error:
        reason = _offline_reason(error)
        local = None if reason is None else _local_twins(context, project, link)
        if reason is None or local is None:
            raise
        source, versions, learning = local
        context.console.say(OFFLINE_KEYS[reason], studio=client.studio.origin, source=source)
        return twins_from(versions), False, learning
    learning = None if document is None else learning_api.learning_of(document)
    return twins, True, learning


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
) -> tuple[str, list[Mapping[str, object]], learning_api.Learning | None] | None:
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
        return source, twin_chat.twin_versions(document), _folder_learning(folder)
    step = project.step(TWINS_STAGE)
    if step is None:
        return None
    path = f"{LOCAL_FOLDER}/{STEPS_FOLDER}/{TWINS_STAGE}.json"
    versions = twin_chat.twin_versions(_mapping(step.get("version")))
    return context.text("twins.source_step", path=path), versions, None


def _folder_learning(folder: Path) -> learning_api.Learning | None:
    manifest = read_json(folder / knowledge.MANIFEST_NAME)
    feedback = manifest.get("feedback") if isinstance(manifest, dict) else None
    relative = feedback.get("learned") if isinstance(feedback, dict) else None
    if not isinstance(relative, str) or any(mark in relative for mark in UNSAFE_CHARACTERS):
        return None
    parts = relative.split("/")
    if any(part in UNSAFE_PARTS for part in parts):
        return None
    document = read_json(folder.joinpath(*parts))
    if not isinstance(document, dict) or document.get("kind") != learning_api.TWIN_LEARNING_KIND:
        return None
    return learning_api.learning_of(document)


def _folder_version(folder: Path) -> int | None:
    try:
        found = knowledge.summary(folder)
    except CliError:
        return None
    return None if found is None else found.version_number


def _entry(learning: learning_api.Learning | None, twin: Twin) -> Mapping[str, object] | None:
    return None if learning is None else learning.entry(twin.twin_id)


def _mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: object) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""
