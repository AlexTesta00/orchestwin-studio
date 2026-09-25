from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.projects.brief_dialogue import (
    ESSENTIAL_FIELDS,
    MAX_DIALOGUE_QUESTIONS,
    BriefDialogue,
    BriefDialogueStatus,
    BriefDialogueTurn,
    DialogueAnswer,
    DialogueAnswerKind,
)
from orchestwin.projects.briefs import BriefField, create_project_brief

NOW = datetime(2026, 9, 25, 9, 0, tzinfo=UTC)
DIALOGUE_ID = UUID(int=1)


def dialogue(**overrides):
    values = {
        "id": DIALOGUE_ID,
        "project_id": UUID(int=2),
        "owner_user_id": UUID(int=3),
        "source_brief_version_number": 1,
        "statement": "Una lista ospiti per il workshop.\nServe ai volontari.",
        "status": BriefDialogueStatus.OPEN,
        "created_at": NOW,
    }
    values.update(overrides)
    return BriefDialogue(**values)


def turn(ordinal, field=BriefField.PROBLEM, answer=None, **overrides):
    values = {
        "id": UUID(int=100 + ordinal),
        "dialogue_id": DIALOGUE_ID,
        "ordinal": ordinal,
        "field": field,
        "question": f"Domanda {ordinal}?",
        "model_generation_id": UUID(int=200 + ordinal),
        "asked_at": NOW + timedelta(minutes=ordinal),
        "answer": answer,
        "answered_at": None if answer is None else NOW + timedelta(minutes=ordinal, seconds=30),
    }
    values.update(overrides)
    return BriefDialogueTurn(**values)


def test_text_answers_keep_paragraphs_and_reject_empty_or_long_values():
    answer = DialogueAnswer.text_answer("  Prima riga  \n\n\n seconda   riga ")
    assert answer.kind is DialogueAnswerKind.TEXT
    assert answer.text == "Prima riga\n\nseconda riga"
    assert answer.to_snapshot() == {"kind": "TEXT", "text": answer.text, "items": None}
    for value in ("   ", "x" * 2001, None):
        with pytest.raises(ValueError):
            DialogueAnswer.text_answer(value)


def test_item_answers_drop_blank_items_and_bound_the_list():
    answer = DialogueAnswer.item_list([" a ", "", "b   c"])
    assert answer.items == ("a", "b c")
    assert answer.to_snapshot() == {"kind": "ITEM_LIST", "text": None, "items": ["a", "b c"]}
    for values in ([], ["  "], ["x"] * 21, "abc", [1], ["y" * 501]):
        with pytest.raises(ValueError):
            DialogueAnswer.item_list(values)


@pytest.mark.parametrize(
    "values",
    [
        {"kind": DialogueAnswerKind.TEXT, "text": "ok", "items": ("a",)},
        {"kind": DialogueAnswerKind.TEXT, "text": " ok"},
        {"kind": DialogueAnswerKind.ITEM_LIST, "items": ("a",), "text": "ok"},
        {"kind": DialogueAnswerKind.ITEM_LIST, "items": ["a"]},
        {"kind": DialogueAnswerKind.UNKNOWN, "text": "ok"},
        {"kind": "TEXT", "text": "ok"},
    ],
)
def test_inconsistent_answers_are_rejected(values):
    with pytest.raises(ValueError):
        DialogueAnswer(**values)
    assert DialogueAnswer.unknown().to_snapshot() == {
        "kind": "UNKNOWN",
        "text": None,
        "items": None,
    }


def test_turn_answer_kind_follows_the_field():
    listed = turn(1, field=BriefField.GOALS, answer=DialogueAnswer.item_list(["a"]))
    assert listed.expected_answer_kind is DialogueAnswerKind.ITEM_LIST
    assert listed.to_snapshot()["answer_type"] == "ITEM_LIST"
    assert turn(1, field=BriefField.GOALS, answer=DialogueAnswer.unknown()).answered
    with pytest.raises(ValueError):
        turn(1, field=BriefField.GOALS, answer=DialogueAnswer.text_answer("a"))
    follow_up = turn(1, field=None, answer=DialogueAnswer.text_answer("a"))
    assert follow_up.expected_answer_kind is DialogueAnswerKind.TEXT
    assert follow_up.to_snapshot()["field"] is None
    with pytest.raises(ValueError):
        turn(1, field=None, answer=DialogueAnswer.item_list(["a"]))
    with pytest.raises(ValueError):
        turn(1, field=BriefField.NAME, answer=DialogueAnswer.item_list(["a"]))


@pytest.mark.parametrize(
    "overrides",
    [
        {"answer": DialogueAnswer.text_answer("a"), "answered_at": None},
        {"answer": DialogueAnswer.text_answer("a"), "answered_at": NOW},
        {"answer": None, "answered_at": NOW + timedelta(hours=1)},
        {"ordinal": 0},
        {"ordinal": MAX_DIALOGUE_QUESTIONS + 1},
        {"question": " Domanda? "},
        {"question": "x" * 501},
        {"field": "problem"},
        {"asked_at": NOW.replace(tzinfo=None)},
    ],
)
def test_turn_invariants_reject_inconsistent_values(overrides):
    with pytest.raises(ValueError):
        turn(**{"ordinal": 1, **overrides})


def test_open_fields_follow_the_brief_and_the_asked_fields():
    brief = create_project_brief(
        name="Lista ospiti", description="Una pagina", unknown_fields=[BriefField.BUDGET]
    )
    state = dialogue(turns=(turn(1, field=BriefField.PROBLEM),))
    open_fields = state.open_fields(brief)
    assert open_fields == tuple(
        field
        for field in BriefField
        if field
        not in {BriefField.NAME, BriefField.DESCRIPTION, BriefField.BUDGET, BriefField.PROBLEM}
    )
    assert state.open_essential_fields(brief) == (
        BriefField.GOALS,
        BriefField.TARGET_USERS,
        BriefField.FUNCTIONAL_REQUIREMENTS,
    )
    assert ESSENTIAL_FIELDS[0] is BriefField.DESCRIPTION
    assert dialogue().open_essential_fields(create_project_brief()) == ESSENTIAL_FIELDS


def test_questions_and_answers_advance_the_dialogue():
    state = dialogue().with_question(turn(1))
    assert state.pending_turn is not None and state.question_count == 1
    assert state.questions_remaining == MAX_DIALOGUE_QUESTIONS - 1
    with pytest.raises(ValueError):
        state.with_question(turn(2, field=None))
    with pytest.raises(ValueError):
        state.as_ready()
    answered = state.with_answer(DialogueAnswer.unknown(), answered_at=NOW + timedelta(hours=1))
    assert answered.pending_turn is None
    assert answered.unknown_fields == frozenset({BriefField.PROBLEM})
    assert answered.asked_fields == frozenset({BriefField.PROBLEM})
    with pytest.raises(ValueError):
        answered.with_answer(DialogueAnswer.text_answer("x"), answered_at=NOW)
    with pytest.raises(ValueError):
        answered.with_question(turn(2, field=BriefField.PROBLEM))
    with pytest.raises(ValueError):
        answered.with_question(turn(3, field=None))
    follow_up = answered.with_question(turn(2, field=None))
    replied = follow_up.with_answer(
        DialogueAnswer.text_answer("Serve solo ai volontari."), answered_at=NOW + timedelta(hours=2)
    )
    assert replied.unknown_fields == frozenset({BriefField.PROBLEM})
    assert len(replied.answered_turns) == 2
    ready = replied.as_ready()
    assert ready.status is BriefDialogueStatus.READY
    with pytest.raises(ValueError):
        ready.with_question(turn(3))
    with pytest.raises(ValueError):
        ready.with_answer(DialogueAnswer.unknown(), answered_at=NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": BriefDialogueStatus.READY, "turns": (turn(1),)},
        {"completed_at": NOW},
        {"status": BriefDialogueStatus.SYNTHESIZED, "completed_at": NOW},
        {
            "status": BriefDialogueStatus.SYNTHESIZED,
            "completed_at": NOW,
            "resulting_brief_version_number": 1,
            "synthesis_generation_id": UUID(int=9),
        },
        {
            "status": BriefDialogueStatus.SYNTHESIZED,
            "completed_at": NOW - timedelta(seconds=1),
            "resulting_brief_version_number": 2,
            "synthesis_generation_id": UUID(int=9),
        },
        {"status": BriefDialogueStatus.CLOSED},
        {
            "status": BriefDialogueStatus.CLOSED,
            "completed_at": NOW,
            "synthesis_generation_id": UUID(int=9),
        },
        {"turns": (turn(2),)},
        {"turns": (turn(1), turn(2, field=None))},
        {
            "turns": (
                turn(1, answer=DialogueAnswer.unknown()),
                turn(2, field=BriefField.PROBLEM, answer=DialogueAnswer.unknown()),
            )
        },
        {"turns": [turn(1)]},
        {"statement": " spazi "},
        {"statement": "x" * 2001},
        {"source_brief_version_number": 0},
        {"status": "OPEN"},
        {"created_at": NOW.replace(tzinfo=None)},
    ],
)
def test_dialogue_invariants_reject_inconsistent_states(overrides):
    with pytest.raises(ValueError):
        dialogue(**overrides)


def test_follow_up_count_and_repeated_text_detection():
    state = dialogue(
        turns=(
            turn(1, answer=DialogueAnswer.text_answer("Carta e penna.")),
            turn(2, field=None, answer=DialogueAnswer.text_answer("Sì, uno solo.")),
            turn(3, field=None, answer=DialogueAnswer.unknown()),
        )
    )
    assert state.follow_up_count == 2
    assert state.repeats_earlier_text("  domanda 1? ")
    assert state.repeats_earlier_text("SÌ, UNO SOLO.")
    assert not state.repeats_earlier_text("Domanda 4?")
    assert dialogue().follow_up_count == 0


def test_synthesis_and_closing_transitions():
    ready = dialogue(turns=(turn(1, answer=DialogueAnswer.unknown()),)).as_ready()
    synthesized = ready.as_synthesized(
        resulting_brief_version_number=2,
        synthesis_generation_id=UUID(int=9),
        completed_at=NOW + timedelta(hours=1),
    )
    assert synthesized.status is BriefDialogueStatus.SYNTHESIZED
    assert synthesized.resulting_brief_version_number == 2
    pending = dialogue(turns=(turn(1),))
    early = pending.as_synthesized(
        resulting_brief_version_number=2,
        synthesis_generation_id=UUID(int=9),
        completed_at=NOW + timedelta(hours=1),
    )
    assert early.pending_turn is not None and early.status is BriefDialogueStatus.SYNTHESIZED
    closed = pending.as_closed(completed_at=NOW + timedelta(hours=1))
    assert closed.status is BriefDialogueStatus.CLOSED
    with pytest.raises(ValueError):
        closed.as_synthesized(
            resulting_brief_version_number=2,
            synthesis_generation_id=UUID(int=9),
            completed_at=NOW + timedelta(hours=2),
        )
    with pytest.raises(ValueError):
        synthesized.as_closed(completed_at=NOW + timedelta(hours=2))
    with pytest.raises(ValueError):
        replace(closed, status=BriefDialogueStatus.OPEN)


def test_snapshot_exposes_limits_essential_fields_and_turns():
    state = dialogue(turns=(turn(1, answer=DialogueAnswer.text_answer("Carta e penna.")),))
    snapshot = state.to_snapshot()
    assert snapshot["question_limit"] == MAX_DIALOGUE_QUESTIONS
    assert snapshot["essential_fields"] == [field.value for field in ESSENTIAL_FIELDS]
    assert snapshot["asked_fields"] == ["problem"]
    assert snapshot["status"] == "OPEN"
    assert snapshot["statement"] == state.statement
    assert snapshot["resulting_brief_version_number"] is None
    assert snapshot["synthesis_generation_id"] is None
    assert snapshot["completed_at"] is None
    recorded = snapshot["turns"][0]
    assert recorded["field"] == "problem"
    assert recorded["answer_type"] == "TEXT"
    assert recorded["answer"] == {"kind": "TEXT", "text": "Carta e penna.", "items": None}
    assert recorded["answered_at"] == (NOW + timedelta(minutes=1, seconds=30)).isoformat()
    assert recorded["model_generation_id"] == str(UUID(int=201))
