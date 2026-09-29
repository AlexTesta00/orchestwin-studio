from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Final

from orchestwin.cli.api import brief
from orchestwin.cli.api.projects import approves
from orchestwin.cli.console import Choice
from orchestwin.cli.errors import CliError
from orchestwin.cli.flows.answers import ACCEPT_ALL

if TYPE_CHECKING:
    from orchestwin.cli.commands.init import Journey

STAGE: Final = "brief"
OPERATION: Final = "BRIEF_DIALOGUE"
DONE_WORDS: Final = frozenset({"/fine", "/done"})
QUIT_WORDS: Final = frozenset({"/esci", "/quit"})
SPECIAL_WORDS: Final = DONE_WORDS | QUIT_WORDS | {"?"}
DONE: Final = "DONE"
QUIT: Final = "QUIT"
ATTEMPTS: Final = 5
NOTHING_TO_ACCEPT: Final = "NOTHING_TO_ACCEPT"
MANUAL_FIELDS: Final = ("problem", "target_users", "goals", "functional_requirements")

Reply = dict[str, object] | str


@dataclass(frozen=True, slots=True)
class BriefState:
    approved: bool
    version: Mapping[str, object] | None
    gate: Mapping[str, object] | None

    @property
    def number(self) -> int | None:
        return _number(self.version)


def read(journey: Journey) -> BriefState:
    version = brief.current(journey.client, journey.project_id)
    gate = None if version is None else brief.gate(journey.client, journey.project_id)
    approved = version is not None and gate is not None and approves(gate, version)
    if approved and version is not None and gate is not None:
        journey.keep(STAGE, version, gate)
    return BriefState(approved=approved, version=version, gate=gate)


def run(journey: Journey, state: BriefState) -> bool:
    dialogue = brief.dialogue(journey.client, journey.project_id)
    if dialogue is not None and brief.status(dialogue) in brief.ACTIVE_STATUSES:
        version = converse(journey, dialogue)
    elif state.version is None or brief.missing(state.version):
        version = begin(journey, state.version)
    else:
        version = state.version
    if version is None:
        return False
    return review(journey, version)


def begin(journey: Journey, version: Mapping[str, object] | None) -> Mapping[str, object] | None:
    described = brief.content(version).get("description")
    statement = described if isinstance(described, str) and described else journey.statement()
    journey.say("init.dialogue_starting")
    status, state = journey.generate(
        lambda: brief.start(journey.client, journey.project_id, statement),
        operation=OPERATION,
        label=journey.text("init.dialogue_label"),
        passthrough=(brief.MODEL_NOT_CONFIGURED, brief.DIALOGUE_ACTIVE),
    )
    if status >= 400 and _code(state) == brief.MODEL_NOT_CONFIGURED:
        return manual(journey, version, statement)
    if status >= 400 or not isinstance(state, Mapping):
        return converse(journey, _fresh(journey))
    return converse(journey, state)


def converse(journey: Journey, state: Mapping[str, object]) -> Mapping[str, object] | None:
    explain(journey)
    offered = False
    while True:
        if brief.status(state) not in brief.ACTIVE_STATUSES:
            raise journey.changed("BRIEF_DIALOGUE_CHANGED")
        count = len(brief.turns(state))
        turn = brief.pending(state)
        essential = brief.open_essential(state, turn)
        if turn is None:
            if brief.status(state) == brief.READY:
                journey.say("init.dialogue_ready")
                return compose(journey, count)
            state = _advance(
                journey, partial(brief.ask_next, journey.client, journey.project_id, count)
            )
            continue
        if journey.script is not None:
            if not essential or count >= brief.question_limit(state):
                return compose(journey, count)
            _open_points(journey, essential)
            reply: Reply = journey.script.reply(turn)
            _show_scripted(journey, turn, reply)
        else:
            if not essential and not offered:
                offered = True
                if not _go_on(journey):
                    return compose(journey, count)
            _open_points(journey, essential)
            reply = ask(journey, turn)
            if reply == DONE:
                return compose(journey, count)
            if reply == QUIT:
                journey.say("init.dialogue_left")
                return None
        answer = reply if isinstance(reply, dict) else brief.unknown_answer()
        state = _advance(
            journey, partial(brief.answer, journey.client, journey.project_id, answer, count)
        )


def compose(journey: Journey, count: int) -> Mapping[str, object]:
    label = journey.text("init.compose_label")
    status, state = journey.generate(
        lambda: journey.waiting(
            label, lambda: brief.synthesize(journey.client, journey.project_id, count)
        ),
        operation=OPERATION,
        label=label,
        passthrough=(brief.SYNTHESIS_UNCHANGED,),
    )
    if status >= 400:
        brief.close(journey.client, journey.project_id, count)
        journey.say("init.compose_unchanged")
        found = brief.current(journey.client, journey.project_id)
    else:
        found = brief.composed(state) if isinstance(state, Mapping) else None
        found = found or brief.current(journey.client, journey.project_id)
    if found is None:
        raise journey.changed("BRIEF_NOT_FOUND")
    return found


def manual(
    journey: Journey, version: Mapping[str, object] | None, statement: str
) -> Mapping[str, object] | None:
    journey.say("init.dialogue_unavailable")
    current = brief.content(version)
    known_unknown = set(brief.unknown(version))
    changes: dict[str, object] = {}
    unknown: list[str] = []
    if not current.get("name"):
        changes["name"] = journey.project.link().project_name
    if not current.get("description"):
        changes["description"] = statement
    stopped = False
    for number, field in enumerate(MANUAL_FIELDS, start=1):
        if current.get(field) is not None or field in known_unknown:
            continue
        if stopped:
            unknown.append(field)
            continue
        if journey.script is not None:
            value = journey.script.value(field)
            if value is None:
                unknown.append(field)
            else:
                changes[field] = _shaped(field, value)
            continue
        turn = {
            "ordinal": number,
            "question": journey.text(f"init.question_{field}"),
            "answer_type": brief.ITEM_LIST if field in brief.LIST_FIELDS else brief.TEXT,
        }
        reply = ask(journey, turn)
        if reply == QUIT:
            journey.say("init.manual_left")
            return None
        if reply == DONE:
            stopped = True
            unknown.append(field)
        elif isinstance(reply, dict) and reply.get("kind") == brief.ITEM_LIST:
            changes[field] = list(reply.get("items") or [])
        elif isinstance(reply, dict) and reply.get("kind") == brief.TEXT:
            changes[field] = reply.get("text")
        else:
            unknown.append(field)
    for field in brief.FIELDS:
        if (
            field not in changes
            and field not in unknown
            and current.get(field) is None
            and field not in known_unknown
        ):
            unknown.append(field)
    body = brief.request_body(current, changes, unknown)
    status, document = brief.create(journey.client, journey.project_id, body)
    if status >= 400 or not isinstance(document, Mapping):
        raise journey.refused(status, document)
    journey.say("init.manual_saved", version=_number(document) or "-")
    return document


def review(journey: Journey, version: Mapping[str, object]) -> bool:
    version = proposals(journey, version)
    while True:
        show(journey, version)
        if journey.script is not None:
            action = "approve"
        else:
            action = journey.console.choose(
                "init.brief_choice",
                [
                    Choice("approve", journey.text("init.brief_approve")),
                    Choice("correct", journey.text("init.brief_correct")),
                    Choice("stop", journey.text("init.brief_stop")),
                ],
            ).key
        if action == "stop":
            journey.say("init.brief_left")
            return False
        if action == "correct":
            version = correct(journey, version)
            continue
        try:
            gate = journey.approve(
                lambda: brief.submit_gate(journey.client, journey.project_id),
                lambda: brief.decide_gate(journey.client, journey.project_id),
                step=STAGE,
            )
        except CliError as error:
            if error.code != "BRIEF_INCOMPLETE" or journey.script is not None:
                raise
            journey.say("init.brief_incomplete", fields=error.values.get("fields", ""))
            continue
        journey.conclude(STAGE, version, gate)
        return True


def proposals(journey: Journey, version: Mapping[str, object]) -> Mapping[str, object]:
    items = brief.proposed(brief.assumptions(journey.client, journey.project_id))
    if not items:
        return version
    journey.console.write()
    journey.say("init.proposals_intro", count=len(items))
    for number, item in enumerate(items, start=1):
        journey.console.write(
            f"  {number}. {_label(journey, item.get('field'))}: {item.get('statement')}"
        )
    if journey.script is not None:
        action = "all" if journey.script.proposals == ACCEPT_ALL else "none"
    else:
        action = journey.console.choose(
            "init.proposals_choice",
            [
                Choice("all", journey.text("init.proposals_all")),
                Choice("each", journey.text("init.proposals_each")),
                Choice("none", journey.text("init.proposals_none")),
            ],
        ).key
    accepted = rejected = 0
    if action == "all":
        status, document = brief.accept_all(journey.client, journey.project_id)
        if status >= 400 and _code(document) != NOTHING_TO_ACCEPT:
            raise journey.refused(status, document)
        found = document.get("accepted") if isinstance(document, Mapping) else None
        accepted = len(found) if isinstance(found, list) else 0
    else:
        for number, item in enumerate(items, start=1):
            take = action == "each" and journey.console.confirm(
                "init.proposal_accept",
                default=True,
                number=number,
                field=_label(journey, item.get("field")),
            )
            identifier = str(item.get("id"))
            if take:
                status, document = brief.accept(journey.client, journey.project_id, identifier)
            else:
                status, document = brief.reject(
                    journey.client,
                    journey.project_id,
                    identifier,
                    journey.text("init.proposal_reason"),
                )
            if status == 409:
                journey.say("init.proposal_skipped", number=number)
                continue
            if status >= 400:
                raise journey.refused(status, document)
            if take:
                accepted += 1
            else:
                rejected += 1
    current = brief.current(journey.client, journey.project_id) or version
    journey.say(
        "init.proposals_done",
        accepted=accepted,
        rejected=rejected,
        version=_number(current) or "-",
    )
    return current


def show(journey: Journey, version: Mapping[str, object]) -> None:
    content = brief.content(version)
    journey.console.write()
    journey.say("init.brief_heading", version=_number(version) or "-")
    for field in brief.FIELDS:
        value = content.get(field)
        if isinstance(value, list) and value:
            journey.console.write(f"  {_label(journey, field)}:")
            for item in value:
                journey.console.write(f"    - {item}")
        elif isinstance(value, str) and value:
            journey.console.write(f"  {_label(journey, field)}: {value}")
    unknown = [field for field in brief.FIELDS if field in brief.unknown(version)]
    if unknown:
        journey.say(
            "init.brief_open", fields=", ".join(_label(journey, field) for field in unknown)
        )


def correct(journey: Journey, version: Mapping[str, object]) -> Mapping[str, object]:
    content = brief.content(version)
    field = journey.console.choose(
        "init.correct_which",
        [Choice(field, _label(journey, field)) for field in brief.FIELDS],
    ).key
    label = _label(journey, field)
    listing = field in brief.LIST_FIELDS
    for _ in range(ATTEMPTS):
        if listing:
            journey.say("init.correct_list", field=label)
            values = _lines(journey)
            first = values[0] if len(values) == 1 else None
        else:
            first = journey.console.ask("init.correct_text", required=False, field=label)
            values = [first] if first else []
        if not values:
            journey.say("init.correct_cancelled")
            return version
        if first == "?":
            body = brief.request_body(content, unknown_fields=[field])
        else:
            problem = _problem(journey, field, values)
            if problem:
                continue
            value = values if listing else " ".join(values[0].split())
            body = brief.request_body(content, {field: value})
        status, document = brief.create(journey.client, journey.project_id, body)
        if status >= 400 or not isinstance(document, Mapping):
            raise journey.refused(status, document)
        if status == 201:
            journey.say("init.correct_saved", version=_number(document) or "-")
        else:
            journey.say("init.correct_same")
        return document
    raise CliError("ANSWER_NOT_VALID")


def explain(journey: Journey) -> None:
    if journey.script is not None or journey.explained:
        return
    journey.explained = True
    journey.console.write()
    journey.say("init.dialogue_intro")
    journey.say("init.dialogue_rule_unknown")
    journey.say("init.dialogue_rule_done")
    journey.say("init.dialogue_rule_quit")


def ask(journey: Journey, turn: Mapping[str, object]) -> Reply:
    journey.say(
        "init.dialogue_question",
        number=turn.get("ordinal") or "-",
        question=turn.get("question") or "",
    )
    listing = turn.get("answer_type") == brief.ITEM_LIST
    field = turn.get("field")
    for _ in range(ATTEMPTS):
        if listing:
            journey.say("init.dialogue_list_hint")
            values = _lines(journey)
        else:
            line = journey.console.ask("init.dialogue_answer", required=False)
            values = [line] if line else []
        word = values[0].casefold() if len(values) == 1 else ""
        if word in DONE_WORDS:
            return DONE
        if word in QUIT_WORDS:
            return QUIT
        if not values or word == "?":
            return brief.unknown_answer()
        if _problem(journey, field if isinstance(field, str) else "", values):
            continue
        if listing:
            return brief.list_answer(values)
        return brief.text_answer(values[0])
    raise CliError("ANSWER_NOT_VALID")


def _problem(journey: Journey, field: str, values: list[str]) -> bool:
    if field in brief.LIST_FIELDS or len(values) > 1:
        if len(values) > brief.MAX_ITEMS:
            journey.say("init.answer_too_many", limit=brief.MAX_ITEMS)
            return True
        if any(len(item) > brief.MAX_ITEM for item in values):
            journey.say("init.answer_too_long", limit=brief.MAX_ITEM)
            return True
        return False
    limit = brief.MAX_NAME if field == "name" else brief.MAX_ANSWER
    if len(values[0]) > limit:
        journey.say("init.answer_too_long", limit=limit)
        return True
    return False


def _lines(journey: Journey) -> list[str]:
    values: list[str] = []
    while True:
        try:
            line = journey.console.read_line().strip()
        except CliError as error:
            if error.code == "INPUT_CLOSED" and values:
                return values
            raise
        if not line:
            return values
        values.append(line)
        if len(values) == 1 and line.casefold() in SPECIAL_WORDS:
            return values


def _open_points(journey: Journey, essential: list[str]) -> None:
    if essential:
        journey.say("init.dialogue_open", count=len(essential))


def _go_on(journey: Journey) -> bool:
    journey.say("init.dialogue_essentials_done")
    choice = journey.console.choose(
        "init.dialogue_more",
        [
            Choice("more", journey.text("init.dialogue_more_yes")),
            Choice("compose", journey.text("init.dialogue_more_no")),
        ],
    )
    return choice.key == "more"


def _show_scripted(journey: Journey, turn: Mapping[str, object], reply: Reply) -> None:
    journey.say(
        "init.dialogue_question",
        number=turn.get("ordinal") or "-",
        question=turn.get("question") or "",
    )
    if not isinstance(reply, dict) or reply.get("kind") == brief.UNKNOWN:
        journey.say("init.dialogue_scripted_unknown")
        return
    items = reply.get("items")
    text = "; ".join(str(item) for item in items) if isinstance(items, list) else reply.get("text")
    journey.say("init.dialogue_scripted", answer=text)


def _advance(journey: Journey, send: Callable[[], tuple[int, object]]) -> Mapping[str, object]:
    _, state = journey.generate(
        send,
        operation=OPERATION,
        label=journey.text("init.dialogue_label"),
        again=lambda: (200, _fresh(journey)),
    )
    if not isinstance(state, Mapping):
        raise journey.changed("BRIEF_DIALOGUE_CHANGED")
    return state


def _fresh(journey: Journey) -> Mapping[str, object]:
    state = brief.dialogue(journey.client, journey.project_id)
    if state is None:
        raise journey.changed("BRIEF_DIALOGUE_NOT_FOUND")
    return state


def _shaped(field: str, value: str | tuple[str, ...]) -> object:
    if field in brief.LIST_FIELDS:
        return [value] if isinstance(value, str) else list(value)
    return value if isinstance(value, str) else "; ".join(value)


def _label(journey: Journey, field: object) -> str:
    return journey.text(f"init.field_{field}") if field in brief.FIELDS else str(field)


def _code(document: object) -> str | None:
    if not isinstance(document, Mapping):
        return None
    detail = document.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    status = document.get("status")
    return status if isinstance(status, str) else None


def _number(version: Mapping[str, object] | None) -> int | None:
    value = None if version is None else version.get("version_number")
    return value if isinstance(value, int) and not isinstance(value, bool) else None
