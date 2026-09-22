import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.twins.conversations import (
    MAX_INSIGHTS_PER_TURN,
    TwinConversation,
    TwinConversationTurn,
    TwinInsight,
    TwinInsightKind,
    normalized_reply,
    normalized_text,
)

NOW = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def insight(**overrides):
    return TwinInsight(
        **{
            "kind": TwinInsightKind.NEED,
            "text": "Registrazione in pochi secondi.",
            "confidence": 0.7,
            "grounded_on": ("user_twin.recurring_tasks",),
            **overrides,
        }
    )


def turn(conversation_id, ordinal=1, **overrides):
    return TwinConversationTurn(
        **{
            "id": uuid4(),
            "conversation_id": conversation_id,
            "ordinal": ordinal,
            "question": "Quanto tempo hai per registrare un ospite?",
            "reply": "Pochissimo.\n\nServe un solo campo.",
            "insights": (insight(),),
            "model_generation_id": uuid4(),
            "created_at": NOW,
            **overrides,
        }
    )


def conversation(turns=(), **overrides):
    identifier = overrides.pop("id", uuid4())
    return TwinConversation(
        **{
            "id": identifier,
            "project_id": uuid4(),
            "owner_user_id": uuid4(),
            "twin_id": uuid4(),
            "twin_version_id": uuid4(),
            "twin_version_number": 1,
            "twin_content_hash": "a" * 64,
            "twin_name": "Marta Rinaldi",
            "created_at": NOW,
            "turns": turns,
            **overrides,
        }
    )


def test_text_normalization_collapses_whitespace_and_keeps_reply_paragraphs():
    assert (
        normalized_text("  Come   registri\tun ospite? ", maximum=100) == "Come registri un ospite?"
    )
    assert normalized_reply(" Pochissimo.  \n\n\n\nServe   un campo.\n") == (
        "Pochissimo.\n\nServe un campo."
    )
    with pytest.raises(ValueError):
        normalized_text("   ", maximum=10)
    with pytest.raises(ValueError):
        normalized_text("x" * 11, maximum=10)
    with pytest.raises(ValueError):
        normalized_reply("\n \n")


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "NEED"},
        {"text": " spazi doppi  "},
        {"text": ""},
        {"confidence": 1.5},
        {"confidence": 1},
        {"grounded_on": ["user_twin.goals"]},
        {"grounded_on": ("user_twin.unknown",)},
        {"grounded_on": ("user_twin.goals", "user_twin.goals")},
        {
            "grounded_on": tuple(
                f"user_twin.{f}"
                for f in ("goals", "role", "expertise", "frustrations", "assumptions")
            )
        },
    ],
)
def test_invalid_insights_are_rejected(overrides):
    with pytest.raises(ValueError):
        insight(**overrides)


def test_turn_snapshot_labels_the_answer_as_a_hypothesis_with_a_stable_hash():
    identifier = uuid4()
    first = turn(identifier)
    snapshot = first.to_snapshot()
    assert snapshot["epistemic_status"] == "HYPOTHESIS"
    assert snapshot["human_validation"] == "REQUIRED"
    assert snapshot["insights"][0] == {
        "kind": "NEED",
        "text": "Registrazione in pochi secondi.",
        "confidence": 0.7,
        "grounded_on": ["user_twin.recurring_tasks"],
    }
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert first.content_hash == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert (
        turn(
            identifier, id=first.id, model_generation_id=first.model_generation_id, reply="Altro."
        ).content_hash
        != first.content_hash
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"ordinal": 0},
        {"ordinal": True},
        {"question": "  spazi  "},
        {"reply": "Riga.\n\n\n\nAltra."},
        {"insights": [insight()]},
        {"insights": tuple(insight() for _ in range(MAX_INSIGHTS_PER_TURN + 1))},
        {"created_at": datetime(2026, 9, 22, 10, 0)},
    ],
)
def test_invalid_turns_are_rejected(overrides):
    with pytest.raises(ValueError):
        turn(uuid4(), **overrides)


def test_conversation_keeps_consecutive_turns_of_its_own():
    identifier = uuid4()
    first = turn(identifier)
    second = turn(identifier, ordinal=2)
    recorded = conversation(id=identifier).with_turn(first).with_turn(second)
    assert [item.ordinal for item in recorded.turns] == [1, 2]
    snapshot = recorded.to_snapshot()
    assert snapshot["turns"][1]["content_hash"] == second.content_hash
    assert snapshot["twin_name"] == "Marta Rinaldi"
    with pytest.raises(ValueError):
        conversation(id=identifier, turns=(second,))
    with pytest.raises(ValueError):
        conversation(turns=(first,))
    with pytest.raises(ValueError):
        conversation(twin_name="  Marta ")
    with pytest.raises(ValueError):
        conversation(twin_content_hash="abc")
