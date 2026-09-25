from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.briefs import LIST_FIELDS, BriefField, ProjectBrief

MAX_STATEMENT_CHARACTERS: Final = 2000
MAX_QUESTION_CHARACTERS: Final = 500
MAX_ANSWER_CHARACTERS: Final = 2000
MAX_ANSWER_ITEM_CHARACTERS: Final = 500
MAX_ANSWER_ITEMS: Final = 20
MAX_DIALOGUE_QUESTIONS: Final = 20
MAX_FOLLOW_UP_QUESTIONS: Final = 3
ESSENTIAL_FIELDS: Final = (
    BriefField.DESCRIPTION,
    BriefField.PROBLEM,
    BriefField.GOALS,
    BriefField.TARGET_USERS,
    BriefField.FUNCTIONAL_REQUIREMENTS,
)
STANDARD_FIELDS: Final = tuple(BriefField)


class BriefDialogueStatus(StrEnum):
    OPEN = "OPEN"
    READY = "READY"
    SYNTHESIZED = "SYNTHESIZED"
    CLOSED = "CLOSED"


class DialogueAnswerKind(StrEnum):
    TEXT = "TEXT"
    ITEM_LIST = "ITEM_LIST"
    UNKNOWN = "UNKNOWN"


ACTIVE_STATUSES: Final = frozenset({BriefDialogueStatus.OPEN, BriefDialogueStatus.READY})


def normalized_text(value, *, maximum):
    if not isinstance(value, str):
        raise ValueError("text is required")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("text must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"text exceeds {maximum} characters")
    return normalized


def normalized_block(value, *, maximum):
    if not isinstance(value, str):
        raise ValueError("text is required")
    lines = [" ".join(line.split()) for line in value.strip().splitlines()]
    normalized = "\n".join(lines).strip()
    while "\n\n\n" in normalized:
        normalized = normalized.replace("\n\n\n", "\n\n")
    if not normalized:
        raise ValueError("text must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"text exceeds {maximum} characters")
    return normalized


def normalized_items(values):
    if isinstance(values, str) or not isinstance(values, list | tuple):
        raise ValueError("items must be a sequence of strings")
    items = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("items must be a sequence of strings")
        normalized = " ".join(value.split())
        if not normalized:
            continue
        if len(normalized) > MAX_ANSWER_ITEM_CHARACTERS:
            raise ValueError(f"item exceeds {MAX_ANSWER_ITEM_CHARACTERS} characters")
        items.append(normalized)
    if not items:
        raise ValueError("items must not be empty")
    if len(items) > MAX_ANSWER_ITEMS:
        raise ValueError(f"items exceed {MAX_ANSWER_ITEMS} entries")
    return tuple(items)


def _require_uuid(value, label):
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _require_timestamp(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class DialogueAnswer:
    kind: DialogueAnswerKind
    text: str | None = None
    items: tuple[str, ...] | None = None

    def __post_init__(self):
        if not isinstance(self.kind, DialogueAnswerKind):
            raise ValueError("answer kind must be a DialogueAnswerKind")
        if self.kind is DialogueAnswerKind.TEXT:
            if self.items is not None or self.text != normalized_block(
                self.text, maximum=MAX_ANSWER_CHARACTERS
            ):
                raise ValueError("a text answer requires normalized text only")
        elif self.kind is DialogueAnswerKind.ITEM_LIST:
            if (
                self.text is not None
                or not isinstance(self.items, tuple)
                or self.items != normalized_items(self.items)
            ):
                raise ValueError("an item-list answer requires normalized items only")
        elif self.text is not None or self.items is not None:
            raise ValueError("an unknown answer carries no value")

    @classmethod
    def text_answer(cls, value):
        return cls(
            kind=DialogueAnswerKind.TEXT,
            text=normalized_block(value, maximum=MAX_ANSWER_CHARACTERS),
        )

    @classmethod
    def item_list(cls, values):
        return cls(kind=DialogueAnswerKind.ITEM_LIST, items=normalized_items(values))

    @classmethod
    def unknown(cls):
        return cls(kind=DialogueAnswerKind.UNKNOWN)

    def to_snapshot(self):
        return {
            "kind": self.kind.value,
            "text": self.text,
            "items": None if self.items is None else list(self.items),
        }


def answer_kind_for(field):
    return DialogueAnswerKind.ITEM_LIST if field in LIST_FIELDS else DialogueAnswerKind.TEXT


@dataclass(frozen=True, slots=True)
class BriefDialogueTurn:
    id: UUID
    dialogue_id: UUID
    ordinal: int
    field: BriefField | None
    question: str
    model_generation_id: UUID
    asked_at: datetime
    answer: DialogueAnswer | None = None
    answered_at: datetime | None = None

    def __post_init__(self):
        _require_uuid(self.id, "turn id")
        _require_uuid(self.dialogue_id, "dialogue id")
        _require_uuid(self.model_generation_id, "model generation id")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_DIALOGUE_QUESTIONS:
            raise ValueError("turn ordinal must be a positive integer within the question limit")
        if self.field is not None and not isinstance(self.field, BriefField):
            raise ValueError("turn field must be a BriefField or None")
        if self.question != normalized_text(self.question, maximum=MAX_QUESTION_CHARACTERS):
            raise ValueError("question must be normalized")
        _require_timestamp(self.asked_at, "asked_at")
        if self.answer is None:
            if self.answered_at is not None:
                raise ValueError("an unanswered turn has no answer time")
            return
        if not isinstance(self.answer, DialogueAnswer):
            raise ValueError("answer must be a DialogueAnswer")
        if self.answered_at is None:
            raise ValueError("an answered turn requires an answer time")
        _require_timestamp(self.answered_at, "answered_at")
        if self.answered_at < self.asked_at:
            raise ValueError("a turn cannot be answered before it is asked")
        if (
            self.answer.kind is not DialogueAnswerKind.UNKNOWN
            and self.answer.kind is not self.expected_answer_kind
        ):
            raise ValueError("answer kind does not match the question")

    @property
    def expected_answer_kind(self):
        return answer_kind_for(self.field)

    @property
    def answered(self):
        return self.answer is not None

    def with_answer(self, answer, *, answered_at):
        if self.answer is not None:
            raise ValueError("the turn is already answered")
        return replace(self, answer=answer, answered_at=answered_at)

    def to_snapshot(self):
        return {
            "id": str(self.id),
            "dialogue_id": str(self.dialogue_id),
            "ordinal": self.ordinal,
            "field": None if self.field is None else self.field.value,
            "answer_type": self.expected_answer_kind.value,
            "question": self.question,
            "model_generation_id": str(self.model_generation_id),
            "asked_at": self.asked_at.isoformat(),
            "answer": None if self.answer is None else self.answer.to_snapshot(),
            "answered_at": None if self.answered_at is None else self.answered_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class BriefDialogue:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    source_brief_version_number: int
    statement: str
    status: BriefDialogueStatus
    created_at: datetime
    turns: tuple[BriefDialogueTurn, ...] = ()
    resulting_brief_version_number: int | None = None
    synthesis_generation_id: UUID | None = None
    completed_at: datetime | None = None

    def __post_init__(self):
        for value, label in (
            (self.id, "dialogue id"),
            (self.project_id, "project id"),
            (self.owner_user_id, "owner id"),
        ):
            _require_uuid(value, label)
        if (
            type(self.source_brief_version_number) is not int
            or self.source_brief_version_number < 1
        ):
            raise ValueError("source brief version number must be a positive integer")
        if self.statement != normalized_block(self.statement, maximum=MAX_STATEMENT_CHARACTERS):
            raise ValueError("statement must be normalized")
        if not isinstance(self.status, BriefDialogueStatus):
            raise ValueError("status must be a BriefDialogueStatus")
        _require_timestamp(self.created_at, "created_at")
        if not isinstance(self.turns, tuple) or len(self.turns) > MAX_DIALOGUE_QUESTIONS:
            raise ValueError("turns must be a bounded tuple")
        for ordinal, turn in enumerate(self.turns, 1):
            if not isinstance(turn, BriefDialogueTurn):
                raise ValueError("turns must contain BriefDialogueTurn values")
            if turn.dialogue_id != self.id or turn.ordinal != ordinal:
                raise ValueError("turns must belong to this dialogue in consecutive order")
            if ordinal < len(self.turns) and not turn.answered:
                raise ValueError("only the last turn can await an answer")
        asked = [turn.field for turn in self.turns if turn.field is not None]
        if len(asked) != len(set(asked)):
            raise ValueError("each brief field can be asked at most once")
        if self.status in ACTIVE_STATUSES:
            if (
                self.resulting_brief_version_number is not None
                or self.synthesis_generation_id is not None
                or self.completed_at is not None
            ):
                raise ValueError("an active dialogue carries no completion data")
            if self.status is BriefDialogueStatus.READY and self.pending_turn is not None:
                raise ValueError("a ready dialogue has no pending question")
            return
        _require_timestamp(self.completed_at, "completed_at")
        if self.completed_at < self.created_at:
            raise ValueError("a dialogue cannot complete before its creation")
        if self.status is BriefDialogueStatus.SYNTHESIZED:
            if (
                type(self.resulting_brief_version_number) is not int
                or self.resulting_brief_version_number <= self.source_brief_version_number
            ):
                raise ValueError("a synthesized dialogue requires a later brief version")
            _require_uuid(self.synthesis_generation_id, "synthesis generation id")
            return
        if (
            self.resulting_brief_version_number is not None
            or self.synthesis_generation_id is not None
        ):
            raise ValueError("a closed dialogue carries no synthesis data")

    @property
    def pending_turn(self):
        if self.turns and not self.turns[-1].answered:
            return self.turns[-1]
        return None

    @property
    def answered_turns(self):
        return tuple(turn for turn in self.turns if turn.answered)

    @property
    def asked_fields(self):
        return frozenset(turn.field for turn in self.turns if turn.field is not None)

    @property
    def unknown_fields(self):
        return frozenset(
            turn.field
            for turn in self.answered_turns
            if turn.field is not None and turn.answer.kind is DialogueAnswerKind.UNKNOWN
        )

    @property
    def follow_up_count(self):
        return sum(1 for turn in self.turns if turn.field is None)

    @property
    def question_count(self):
        return len(self.turns)

    def repeats_earlier_text(self, text):
        candidate = normalized_text(text, maximum=MAX_ANSWER_CHARACTERS).casefold()
        earlier = [turn.question.casefold() for turn in self.turns]
        earlier.extend(
            " ".join(turn.answer.text.split()).casefold()
            for turn in self.answered_turns
            if turn.answer.text is not None
        )
        return candidate in earlier

    @property
    def questions_remaining(self):
        return MAX_DIALOGUE_QUESTIONS - len(self.turns)

    def open_fields(self, brief: ProjectBrief):
        missing = brief.missing_fields
        asked = self.asked_fields
        return tuple(field for field in STANDARD_FIELDS if field in missing and field not in asked)

    def open_essential_fields(self, brief: ProjectBrief):
        open_fields = self.open_fields(brief)
        return tuple(field for field in ESSENTIAL_FIELDS if field in open_fields)

    def with_question(self, turn: BriefDialogueTurn):
        if self.status is not BriefDialogueStatus.OPEN:
            raise ValueError("only an open dialogue accepts a question")
        if self.pending_turn is not None:
            raise ValueError("the current question is still unanswered")
        if turn.ordinal != len(self.turns) + 1:
            raise ValueError("question ordinal must continue the dialogue")
        if turn.field is not None and turn.field in self.asked_fields:
            raise ValueError("the field was already asked")
        return replace(self, turns=(*self.turns, turn))

    def with_answer(self, answer: DialogueAnswer, *, answered_at):
        if self.status is not BriefDialogueStatus.OPEN:
            raise ValueError("only an open dialogue accepts an answer")
        pending = self.pending_turn
        if pending is None:
            raise ValueError("no question awaits an answer")
        answered = pending.with_answer(answer, answered_at=answered_at)
        return replace(self, turns=(*self.turns[:-1], answered))

    def as_ready(self):
        if self.status is not BriefDialogueStatus.OPEN or self.pending_turn is not None:
            raise ValueError("only an open dialogue without a pending question becomes ready")
        return replace(self, status=BriefDialogueStatus.READY)

    def as_synthesized(
        self, *, resulting_brief_version_number, synthesis_generation_id, completed_at
    ):
        if self.status not in ACTIVE_STATUSES:
            raise ValueError("only an active dialogue can be synthesized")
        return replace(
            self,
            status=BriefDialogueStatus.SYNTHESIZED,
            resulting_brief_version_number=resulting_brief_version_number,
            synthesis_generation_id=synthesis_generation_id,
            completed_at=completed_at,
        )

    def as_closed(self, *, completed_at):
        if self.status not in ACTIVE_STATUSES:
            raise ValueError("only an active dialogue can be closed")
        return replace(self, status=BriefDialogueStatus.CLOSED, completed_at=completed_at)

    def to_snapshot(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "source_brief_version_number": self.source_brief_version_number,
            "statement": self.statement,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "question_limit": MAX_DIALOGUE_QUESTIONS,
            "essential_fields": [field.value for field in ESSENTIAL_FIELDS],
            "asked_fields": sorted(field.value for field in self.asked_fields),
            "turns": [turn.to_snapshot() for turn in self.turns],
            "resulting_brief_version_number": self.resulting_brief_version_number,
            "synthesis_generation_id": None
            if self.synthesis_generation_id is None
            else str(self.synthesis_generation_id),
            "completed_at": None if self.completed_at is None else self.completed_at.isoformat(),
        }
