from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Final

from orchestwin.cli import costs
from orchestwin.cli.api import twin_chat
from orchestwin.cli.errors import SPENDING_STATUS, ApiFailure, CliError

if TYPE_CHECKING:
    from orchestwin.cli.client import StudioClient
    from orchestwin.cli.context import CommandContext
    from orchestwin.cli.flows.twin_selection import Twin

OPERATION: Final = "TWIN_CHAT"
HISTORY_TURNS: Final = 3
EXIT_WORDS: Final = frozenset({"/esci", "/quit"})
MODEL_STAGES: Final = frozenset({"MODEL_PROPOSAL", "MODEL_RUNTIME", "MODEL_PROPOSAL_EVIDENCE"})
CONVERSATION_CHANGED: Final = "TWIN_CONVERSATION_CHANGED"
INPUT_CLOSED: Final = "INPUT_CLOSED"


def ask_once(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    twin: Twin,
    question: str,
) -> int:
    text = normalized_question(question)
    if len(text) > twin_chat.QUESTION_LIMIT:
        raise CliError("TWIN_QUESTION_TOO_LONG", values={"limit": twin_chat.QUESTION_LIMIT})
    existing = twin_chat.turns(
        twin_chat.conversation(client, project_id, twin.twin_id), twin.version_id
    )
    context.console.say("twins.simulated")
    costs.confirm_spending(context, client, [OPERATION])
    try:
        recorded = twin_chat.ask(
            client, project_id, twin.twin_id, text, expected_turn_count=len(existing)
        )
    except ApiFailure as failure:
        if model_failure(failure):
            raise CliError(
                "TWIN_ANSWER_FAILED", values={"name": twin.name, "code": failure.code}
            ) from None
        raise
    show_answer(context, twin, twin_chat.turns(recorded))
    return 0


def converse(
    context: CommandContext,
    client: StudioClient,
    project_id: str,
    twin: Twin,
) -> int:
    console = context.console
    found = twin_chat.conversation(client, project_id, twin.twin_id)
    turns = twin_chat.turns(found, twin.version_id)
    if not turns and twin_chat.turns(found):
        console.say("twins.twin_changed", name=twin.name)
    show_history(context, twin, turns)
    console.say("twins.simulated")
    console.say("twins.conversation_hint")
    estimated = False
    while True:
        if not estimated:
            costs.confirm_spending(context, client, [OPERATION])
            estimated = True
        try:
            question = console.ask("twins.you")
        except CliError as error:
            if error.code != INPUT_CLOSED:
                raise
            break
        text = normalized_question(question)
        if text.casefold() in EXIT_WORDS:
            break
        if len(text) > twin_chat.QUESTION_LIMIT:
            console.say("twins.question_too_long", limit=twin_chat.QUESTION_LIMIT)
            continue
        try:
            recorded = twin_chat.ask(
                client, project_id, twin.twin_id, text, expected_turn_count=len(turns)
            )
        except ApiFailure as failure:
            if model_failure(failure):
                console.error("twins.answer_failed", name=twin.name, code=failure.code)
                estimated = False
                continue
            if failure.code != CONVERSATION_CHANGED:
                raise
            turns = twin_chat.turns(
                twin_chat.conversation(client, project_id, twin.twin_id), twin.version_id
            )
            console.error("twins.conversation_changed", name=twin.name)
            continue
        turns = twin_chat.turns(recorded)
        show_answer(context, twin, turns)
        console.write()
    console.say("twins.conversation_end")
    return 0


def normalized_question(question: str) -> str:
    return " ".join(question.split())


def model_failure(failure: ApiFailure) -> bool:
    if failure.status == SPENDING_STATUS:
        return False
    detail = failure.detail
    return isinstance(detail, Mapping) and detail.get("stage") in MODEL_STAGES


def show_history(
    context: CommandContext, twin: Twin, turns: Sequence[Mapping[str, object]]
) -> None:
    shown = list(turns)[-HISTORY_TURNS:]
    if not shown:
        return
    console = context.console
    console.say("twins.previous_turns", name=twin.name, count=len(shown))
    for turn in shown:
        console.write(f"{context.text('twins.you')} {twin_chat.turn_question(turn)}")
        console.say("twins.answer_by", name=twin.name)
        console.write(twin_chat.turn_reply(turn))
    console.write()


def show_answer(context: CommandContext, twin: Twin, turns: Sequence[Mapping[str, object]]) -> None:
    if not turns:
        return
    context.console.say("twins.answer_by", name=twin.name)
    context.console.write(twin_chat.turn_reply(turns[-1]))
