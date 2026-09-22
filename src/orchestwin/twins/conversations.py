import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.twins.user_twins import UserTwinField

MAX_QUESTION_CHARACTERS = 1000
MAX_REPLY_CHARACTERS = 2000
MAX_INSIGHT_CHARACTERS = 300
MAX_INSIGHT_GROUNDING = 4
MAX_INSIGHTS_PER_TURN = 6
MAX_TURNS_PER_CONVERSATION = 40
MAX_TWIN_NAME_CHARACTERS = 200
OBSERVATION_KEYS = frozenset(field.observation_key for field in UserTwinField)
EPISTEMIC_STATUS = "HYPOTHESIS"
HUMAN_VALIDATION = "REQUIRED"


class TwinInsightKind(StrEnum):
    NEED = "NEED"
    FRUSTRATION = "FRUSTRATION"
    PREFERENCE = "PREFERENCE"
    RISK = "RISK"
    OPEN_QUESTION = "OPEN_QUESTION"


def normalized_text(value, *, maximum):
    if not isinstance(value, str):
        raise ValueError("text is required")
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("text must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"text exceeds {maximum} characters")
    return normalized


def normalized_reply(value):
    if not isinstance(value, str):
        raise ValueError("reply is required")
    lines = [" ".join(line.split()) for line in value.strip().splitlines()]
    normalized = "\n".join(lines).strip()
    while "\n\n\n" in normalized:
        normalized = normalized.replace("\n\n\n", "\n\n")
    if not normalized:
        raise ValueError("reply must not be empty")
    if len(normalized) > MAX_REPLY_CHARACTERS:
        raise ValueError(f"reply exceeds {MAX_REPLY_CHARACTERS} characters")
    return normalized


def _require_uuid(value, label):
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _require_timestamp(value, label):
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")


def _canonical(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class TwinInsight:
    kind: TwinInsightKind
    text: str
    confidence: float
    grounded_on: tuple[str, ...]

    def __post_init__(self):
        if not isinstance(self.kind, TwinInsightKind):
            raise ValueError("insight kind must be a TwinInsightKind")
        if self.text != normalized_text(self.text, maximum=MAX_INSIGHT_CHARACTERS):
            raise ValueError("insight text must be normalized")
        if type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("insight confidence must be a float between 0 and 1")
        if (
            not isinstance(self.grounded_on, tuple)
            or len(self.grounded_on) > MAX_INSIGHT_GROUNDING
            or len(set(self.grounded_on)) != len(self.grounded_on)
            or any(key not in OBSERVATION_KEYS for key in self.grounded_on)
        ):
            raise ValueError("insight grounding must list distinct User Twin observation keys")

    def to_snapshot(self):
        return {
            "kind": self.kind.value,
            "text": self.text,
            "confidence": self.confidence,
            "grounded_on": list(self.grounded_on),
        }


@dataclass(frozen=True, slots=True)
class TwinConversationTurn:
    id: UUID
    conversation_id: UUID
    ordinal: int
    question: str
    reply: str
    insights: tuple[TwinInsight, ...]
    model_generation_id: UUID
    created_at: datetime

    def __post_init__(self):
        _require_uuid(self.id, "turn id")
        _require_uuid(self.conversation_id, "conversation id")
        _require_uuid(self.model_generation_id, "model generation id")
        if type(self.ordinal) is not int or not 1 <= self.ordinal <= MAX_TURNS_PER_CONVERSATION:
            raise ValueError(
                "turn ordinal must be a positive integer within the conversation limit"
            )
        if self.question != normalized_text(self.question, maximum=MAX_QUESTION_CHARACTERS):
            raise ValueError("question must be normalized")
        if self.reply != normalized_reply(self.reply):
            raise ValueError("reply must be normalized")
        if (
            not isinstance(self.insights, tuple)
            or len(self.insights) > MAX_INSIGHTS_PER_TURN
            or any(not isinstance(item, TwinInsight) for item in self.insights)
        ):
            raise ValueError("insights must be a bounded tuple of TwinInsight")
        _require_timestamp(self.created_at, "turn timestamp")

    def to_snapshot(self):
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "ordinal": self.ordinal,
            "question": self.question,
            "reply": self.reply,
            "insights": [insight.to_snapshot() for insight in self.insights],
            "model_generation_id": str(self.model_generation_id),
            "created_at": self.created_at.isoformat(),
            "epistemic_status": EPISTEMIC_STATUS,
            "human_validation": HUMAN_VALIDATION,
        }

    @property
    def content_hash(self):
        return hashlib.sha256(_canonical(self.to_snapshot()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TwinConversation:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    twin_id: UUID
    twin_version_id: UUID
    twin_version_number: int
    twin_content_hash: str
    twin_name: str
    created_at: datetime
    turns: tuple[TwinConversationTurn, ...]

    def __post_init__(self):
        for value, label in (
            (self.id, "conversation id"),
            (self.project_id, "project id"),
            (self.owner_user_id, "owner id"),
            (self.twin_id, "twin id"),
            (self.twin_version_id, "twin version id"),
        ):
            _require_uuid(value, label)
        if type(self.twin_version_number) is not int or self.twin_version_number < 1:
            raise ValueError("twin version number must be a positive integer")
        if not isinstance(self.twin_content_hash, str) or len(self.twin_content_hash) != 64:
            raise ValueError("twin content hash must be a SHA-256 digest")
        if self.twin_name != normalized_text(self.twin_name, maximum=MAX_TWIN_NAME_CHARACTERS):
            raise ValueError("twin name must be normalized")
        _require_timestamp(self.created_at, "conversation timestamp")
        if not isinstance(self.turns, tuple) or len(self.turns) > MAX_TURNS_PER_CONVERSATION:
            raise ValueError("turns must be a bounded tuple")
        for ordinal, turn in enumerate(self.turns, 1):
            if not isinstance(turn, TwinConversationTurn):
                raise ValueError("turns must contain TwinConversationTurn values")
            if turn.conversation_id != self.id or turn.ordinal != ordinal:
                raise ValueError("turns must belong to this conversation in consecutive order")

    def with_turn(self, turn):
        return replace(self, turns=(*self.turns, turn))

    def to_snapshot(self):
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "twin_id": str(self.twin_id),
            "twin_version_id": str(self.twin_version_id),
            "twin_version_number": self.twin_version_number,
            "twin_content_hash": self.twin_content_hash,
            "twin_name": self.twin_name,
            "created_at": self.created_at.isoformat(),
            "turns": [
                {**turn.to_snapshot(), "content_hash": turn.content_hash} for turn in self.turns
            ],
        }
