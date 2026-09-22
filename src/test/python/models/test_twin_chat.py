import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_chat import (
    HISTORY_TURNS,
    TwinChatOutput,
    answer_as_twin,
    bind_insights,
    twin_chat_context,
)
from orchestwin.projects.briefs import ProjectBrief
from orchestwin.twins.conversations import TwinConversationTurn, TwinInsightKind
from src.test.python.models.test_proposal_evidence import audited_generator
from src.test.python.twins.test_user_modeling_persistence import twin_version

OUTPUT = {
    "reply": "Pochissimo tempo: lo faccio con l'ospite davanti a me.",
    "insights": [
        {
            "kind": "NEED",
            "text": "Registrazione  in pochi secondi.",
            "confidence": 0.754,
            "grounded_on": [
                "user_twin.recurring_tasks",
                "user_twin.unknown_field",
                "user_twin.recurring_tasks",
            ],
        }
    ],
}


def brief():
    return ProjectBrief(
        name="Registro ospiti",
        problem="La reception perde tempo a registrare gli ospiti.",
        goals=("Registrare un ospite in dieci secondi",),
        definition_of_done=("I test automatici passano",),
    )


def history(count):
    conversation_id = uuid4()
    return tuple(
        TwinConversationTurn(
            id=uuid4(),
            conversation_id=conversation_id,
            ordinal=ordinal,
            question=f"Domanda {ordinal}",
            reply=f"Risposta {ordinal}",
            insights=(),
            model_generation_id=uuid4(),
            created_at=datetime(2026, 9, 22, 10, ordinal, tzinfo=UTC),
        )
        for ordinal in range(1, count + 1)
    )


def test_context_carries_profile_brief_bounded_history_and_question():
    twin = twin_version()
    turns = history(HISTORY_TURNS + 2)
    context = twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=brief(),
        turns=turns,
        question="Come registri un ospite?",
    )
    assert context["purpose"] == "TWIN_CHAT"
    assert context["user_twin"]["profile"] == twin.profile.to_snapshot()
    assert context["user_twin"]["content_hash"] == twin.content_hash
    assert context["project_brief"]["goals"] == ["Registrare un ospite in dieci secondi"]
    assert len(context["conversation"]) == HISTORY_TURNS
    assert context["conversation"][-1] == {
        "question": turns[-1].question,
        "reply": turns[-1].reply,
    }
    assert context["question"] == "Come registri un ospite?"
    assert (
        twin_chat_context(
            project_id=twin.project_id, twin_version=twin, brief=None, turns=(), question="Ciao?"
        )["project_brief"]
        is None
    )


def test_answer_uses_the_twin_chat_task_with_the_grounding_instruction(tmp_path):
    generator, transport = audited_generator(tmp_path, OUTPUT)
    twin = twin_version()
    context = twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=None,
        turns=(),
        question="Come registri un ospite?",
    )
    output = asyncio.run(answer_as_twin(generator, context=context))
    assert isinstance(output, TwinChatOutput)
    assert len(transport.calls) == 1
    payload = transport.calls[0]["payload"]
    assert payload["metadata"]["orchestwin_task_id"] == "proposal-twin-chat-v1"
    assert "never invent research" in payload["messages"][0]["content"]
    sent = json.loads(payload["messages"][1]["content"])["context"]
    assert sent["question"] == "Come registri un ospite?"
    assert sent["user_twin"]["profile"]["name"] == twin.profile.name
    insights = bind_insights(output)
    assert [item.kind for item in insights] == [TwinInsightKind.NEED]
    assert insights[0].text == "Registrazione in pochi secondi."
    assert insights[0].confidence == 0.75
    assert insights[0].grounded_on == ("user_twin.recurring_tasks",)


@pytest.mark.parametrize(
    "output",
    [
        {"reply": "", "insights": []},
        {
            "reply": "Ok.",
            "insights": [{"kind": "WISH", "text": "x", "confidence": 0.5, "grounded_on": []}],
        },
        {
            "reply": "Ok.",
            "insights": [{"kind": "NEED", "text": "x", "confidence": 2, "grounded_on": []}],
        },
        {"reply": "Ok.", "insights": [], "extra": True},
    ],
)
def test_invalid_answers_are_rejected_by_the_output_contract(tmp_path, output):
    generator, _ = audited_generator(tmp_path, output)
    twin = twin_version()
    context = twin_chat_context(
        project_id=twin.project_id, twin_version=twin, brief=None, turns=(), question="Ciao?"
    )
    with pytest.raises(ProposalGenerationError):
        asyncio.run(answer_as_twin(generator, context=context))
