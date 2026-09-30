import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.models.proposal_generation import ProposalGenerationError
from orchestwin.models.twin_chat import (
    HISTORY_TURNS,
    INSTRUCTION,
    LEARNED_CHAT_INSTRUCTION,
    TwinChatOutput,
    answer_as_twin,
    bind_insights,
    chat_instruction,
    twin_chat_context,
)
from orchestwin.models.twin_update import LEARNED_INSTRUCTION
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


LEARNED = [
    {
        "code": "OBS-001",
        "statement": "Il gruppo registra gli ospiti mentre parla al telefono.",
        "source": "TWIN_CRITIQUE",
    },
    {"code": "OBS-003", "statement": "Il gruppo lavora anche di notte.", "source": "OWNER"},
]


def test_without_learned_observations_the_chat_sends_the_context_and_instruction_of_today():
    twin = twin_version()
    context = twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=brief(),
        turns=history(2),
        question="Come registri un ospite?",
        learned=[],
    )
    assert context == twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=brief(),
        turns=history(2),
        question="Come registri un ospite?",
    )
    assert context["user_twin"] == {
        "twin_id": str(twin.twin_id),
        "version_number": twin.version_number,
        "content_hash": twin.content_hash,
        "profile": twin.profile.to_snapshot(),
    }
    assert chat_instruction(context) is INSTRUCTION
    assert chat_instruction({}) is INSTRUCTION


def test_the_learned_observations_join_the_twin_and_the_instruction_says_how_to_use_them():
    twin = twin_version()
    context = twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=None,
        turns=(),
        question="Come registri un ospite?",
        learned=LEARNED,
    )
    assert list(context["user_twin"]) == [
        "twin_id",
        "version_number",
        "content_hash",
        "profile",
        "learned",
    ]
    assert context["user_twin"]["learned"] == LEARNED
    assert chat_instruction(context) == f"{INSTRUCTION} {LEARNED_CHAT_INSTRUCTION}"
    assert LEARNED_CHAT_INSTRUCTION == (
        "user_twin.learned lists what your user group learned during the development of the "
        "application, each observation approved by the owner of the project: use it as you use "
        "the profile, and where a learned observation and the profile disagree the learned "
        "observation prevails; grounded_on still lists only keys of profile observations."
    )
    assert LEARNED_CHAT_INSTRUCTION != LEARNED_INSTRUCTION
    assert " ".join(LEARNED_CHAT_INSTRUCTION.split()) == LEARNED_CHAT_INSTRUCTION


def test_the_answer_with_learned_observations_sends_them_and_the_longer_instruction(tmp_path):
    generator, transport = audited_generator(tmp_path, OUTPUT)
    twin = twin_version()
    context = twin_chat_context(
        project_id=twin.project_id,
        twin_version=twin,
        brief=None,
        turns=(),
        question="Come registri un ospite?",
        learned=LEARNED,
    )
    asyncio.run(answer_as_twin(generator, context=context))
    payload = transport.calls[0]["payload"]
    assert payload["messages"][0]["content"].endswith(f"{INSTRUCTION} {LEARNED_CHAT_INSTRUCTION}")
    sent = json.loads(payload["messages"][1]["content"])["context"]
    assert sent["user_twin"]["learned"] == LEARNED
    folder = tmp_path / "plain"
    folder.mkdir()
    plain, plain_transport = audited_generator(folder, OUTPUT)
    asyncio.run(
        answer_as_twin(
            plain,
            context=twin_chat_context(
                project_id=twin.project_id,
                twin_version=twin,
                brief=None,
                turns=(),
                question="Come registri un ospite?",
            ),
        )
    )
    system = plain_transport.calls[0]["payload"]["messages"][0]["content"]
    assert system.endswith(INSTRUCTION)
    assert "user_twin.learned" not in system
    assert (
        "learned"
        not in json.loads(plain_transport.calls[0]["payload"]["messages"][1]["content"])["context"][
            "user_twin"
        ]
    )


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
