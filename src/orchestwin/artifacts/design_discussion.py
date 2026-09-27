from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.twins.conversations import OBSERVATION_KEYS
from orchestwin.twins.limits import MAX_USER_TWINS

MAX_DISCUSSION_ROUNDS: Final = 4
MAX_DISCUSSION_TWINS: Final = MAX_USER_TWINS
MAX_STATEMENT_LENGTH: Final = 1000
MAX_STATEMENT_PROPOSALS: Final = 3
MAX_STATEMENT_GROUNDING: Final = 4
MAX_REACTION_REASON_LENGTH: Final = 700
MAX_PROPOSAL_LENGTH: Final = 600
MAX_OWNER_NOTE_LENGTH: Final = 1000
MAX_OWNER_ANSWER_LENGTH: Final = 800
MAX_AGREEMENTS: Final = 5
MAX_AGREEMENT_LENGTH: Final = 500
MAX_CONFLICTS: Final = 4
MAX_CONFLICT_TOPIC_LENGTH: Final = 500
MAX_POSITION_LENGTH: Final = 600
MAX_SYNTHESIS_PROPOSALS: Final = 5
MAX_QUESTIONS_FOR_OWNER: Final = 4
MAX_QUESTION_LENGTH: Final = 600
MAX_TWIN_NAME_LENGTH: Final = 200
MAX_LOCALE_LENGTH: Final = 20
PROPOSAL_CODE_PREFIX: Final = "PRP"
LOCALE_PATTERN: Final = r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,3}$"
_LOCALE: Final = re.compile(LOCALE_PATTERN)


class DiscussionStatus(StrEnum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"


class DiscussionStance(StrEnum):
    SUPPORT = "SUPPORT"
    CONCERN = "CONCERN"
    OBJECTION = "OBJECTION"


class DiscussionProposalTarget(StrEnum):
    BRIEF = "BRIEF"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"


class ReactionVerdict(StrEnum):
    AGREE = "AGREE"
    PARTLY = "PARTLY"
    DISAGREE = "DISAGREE"


def normalize_owner_note(note: str | None) -> str | None:
    return normalize_optional_text(
        note, label="discussion owner note", maximum_length=MAX_OWNER_NOTE_LENGTH
    )


def validate_locale(locale: str) -> None:
    if (
        not isinstance(locale, str)
        or len(locale) > MAX_LOCALE_LENGTH
        or _LOCALE.fullmatch(locale) is None
    ):
        raise ValueError("discussion locale must be a language tag")


def proposal_code(ordinal: int) -> str:
    return f"{PROPOSAL_CODE_PREFIX}-{ordinal:03d}"


def _require_uuid(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _require_timestamp(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware datetime")


def _require_text(value: object, *, label: str, maximum: int) -> None:
    if not isinstance(value, str) or (
        normalize_required_text(value, label=label, maximum_length=maximum) != value
    ):
        raise ValueError(f"{label} must be normalized text")


def _require_items(values: object, *, label: str, maximum_items: int, maximum: int) -> None:
    if not isinstance(values, tuple) or len(values) > maximum_items:
        raise ValueError(f"{label} must be a tuple of at most {maximum_items} items")
    if any(not isinstance(item, str) for item in values) or (
        normalize_text_items(values, label=label, maximum_item_length=maximum, require_items=False)
        != values
    ):
        raise ValueError(f"{label} must be distinct normalized text")


def _require_twin_ids(values: object, *, label: str, minimum: int) -> None:
    if (
        not isinstance(values, tuple)
        or not minimum <= len(values) <= MAX_DISCUSSION_TWINS
        or any(not isinstance(item, UUID) for item in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError(f"{label} must name {minimum} to {MAX_DISCUSSION_TWINS} distinct twins")


@dataclass(frozen=True, slots=True)
class TwinReaction:
    twin_id: UUID
    verdict: ReactionVerdict
    reason: str

    def __post_init__(self) -> None:
        _require_uuid(self.twin_id, "reaction twin ID")
        if not isinstance(self.verdict, ReactionVerdict):
            raise ValueError("reaction verdict must be a ReactionVerdict")
        _require_text(self.reason, label="reaction reason", maximum=MAX_REACTION_REASON_LENGTH)

    def to_snapshot(self) -> dict[str, object]:
        return {"twin_id": str(self.twin_id), "verdict": self.verdict.value, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class TwinStatement:
    twin_id: UUID
    twin_version: int
    twin_name: str
    stance: DiscussionStance
    statement: str
    replies_to: tuple[UUID, ...]
    proposals: tuple[str, ...]
    grounded_on: tuple[str, ...]
    confidence: float
    model_generation_id: UUID
    reactions: tuple[TwinReaction, ...] = ()
    owner_answer: str | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.twin_id, "statement twin ID")
        validate_positive_integer(self.twin_version, label="statement twin version")
        _require_text(self.twin_name, label="statement twin name", maximum=MAX_TWIN_NAME_LENGTH)
        if not isinstance(self.stance, DiscussionStance):
            raise ValueError("statement stance must be a DiscussionStance")
        _require_text(self.statement, label="twin statement", maximum=MAX_STATEMENT_LENGTH)
        _require_twin_ids(self.replies_to, label="statement replies", minimum=0)
        if self.twin_id in self.replies_to:
            raise ValueError("a twin cannot reply to itself")
        _require_items(
            self.proposals,
            label="statement proposal",
            maximum_items=MAX_STATEMENT_PROPOSALS,
            maximum=MAX_PROPOSAL_LENGTH,
        )
        if (
            not isinstance(self.grounded_on, tuple)
            or not 1 <= len(self.grounded_on) <= MAX_STATEMENT_GROUNDING
            or len(set(self.grounded_on)) != len(self.grounded_on)
            or any(key not in OBSERVATION_KEYS for key in self.grounded_on)
        ):
            raise ValueError("statement grounding must list distinct User Twin observation keys")
        if type(self.confidence) is not float or not 0.0 <= self.confidence <= 1.0:
            raise ValueError("statement confidence must be a float between 0 and 1")
        _require_uuid(self.model_generation_id, "statement model generation ID")
        if not isinstance(self.reactions, tuple) or any(
            not isinstance(item, TwinReaction) for item in self.reactions
        ):
            raise ValueError("statement reactions must be a tuple of TwinReaction")
        reacted = self.reacted_twins
        _require_twin_ids(reacted, label="statement reactions", minimum=0)
        if self.twin_id in reacted:
            raise ValueError("a twin cannot react to itself")
        if reacted and self.replies_to != reacted:
            raise ValueError("a statement replies to the twins it reacts to")
        if self.owner_answer is not None:
            _require_text(
                self.owner_answer, label="answer to the owner", maximum=MAX_OWNER_ANSWER_LENGTH
            )

    @property
    def reacted_twins(self) -> tuple[UUID, ...]:
        return tuple(item.twin_id for item in self.reactions)

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "twin_id": str(self.twin_id),
            "twin_version": self.twin_version,
            "twin_name": self.twin_name,
            "stance": self.stance.value,
            "statement": self.statement,
            "replies_to": [str(item) for item in self.replies_to],
            "proposals": list(self.proposals),
            "grounded_on": list(self.grounded_on),
            "confidence": self.confidence,
            "model_generation_id": str(self.model_generation_id),
        }
        if self.reactions:
            snapshot["reactions"] = [item.to_snapshot() for item in self.reactions]
        if self.owner_answer is not None:
            snapshot["answer_to_owner"] = self.owner_answer
        return snapshot

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class SynthesisConflict:
    topic: str
    positions: tuple[tuple[UUID, str], ...]

    def __post_init__(self) -> None:
        _require_text(self.topic, label="conflict topic", maximum=MAX_CONFLICT_TOPIC_LENGTH)
        if not isinstance(self.positions, tuple) or any(
            not isinstance(item, tuple) or len(item) != 2 for item in self.positions
        ):
            raise ValueError("conflict positions must be (twin ID, position) pairs")
        _require_twin_ids(self.twin_ids, label="conflict positions", minimum=2)
        for _, position in self.positions:
            _require_text(position, label="conflict position", maximum=MAX_POSITION_LENGTH)

    @property
    def twin_ids(self) -> tuple[UUID, ...]:
        return tuple(twin_id for twin_id, _ in self.positions)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "positions": [
                {"twin_id": str(twin_id), "position": position}
                for twin_id, position in self.positions
            ],
        }


@dataclass(frozen=True, slots=True)
class SynthesisProposal:
    code: str
    text: str
    target: DiscussionProposalTarget
    supported_by: tuple[UUID, ...]

    def __post_init__(self) -> None:
        validate_display_code(self.code, prefix=PROPOSAL_CODE_PREFIX, label="proposal code")
        _require_text(self.text, label="synthesis proposal", maximum=MAX_PROPOSAL_LENGTH)
        if not isinstance(self.target, DiscussionProposalTarget):
            raise ValueError("proposal target must be a DiscussionProposalTarget")
        _require_twin_ids(self.supported_by, label="proposal supporters", minimum=1)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "text": self.text,
            "target": self.target.value,
            "supported_by": [str(item) for item in self.supported_by],
        }


@dataclass(frozen=True, slots=True)
class DiscussionSynthesis:
    agreements: tuple[str, ...]
    conflicts: tuple[SynthesisConflict, ...]
    proposals: tuple[SynthesisProposal, ...]
    questions_for_owner: tuple[str, ...]
    model_generation_id: UUID

    def __post_init__(self) -> None:
        _require_items(
            self.agreements,
            label="synthesis agreement",
            maximum_items=MAX_AGREEMENTS,
            maximum=MAX_AGREEMENT_LENGTH,
        )
        if (
            not isinstance(self.conflicts, tuple)
            or len(self.conflicts) > MAX_CONFLICTS
            or any(not isinstance(item, SynthesisConflict) for item in self.conflicts)
        ):
            raise ValueError(f"synthesis conflicts must be at most {MAX_CONFLICTS}")
        if (
            not isinstance(self.proposals, tuple)
            or len(self.proposals) > MAX_SYNTHESIS_PROPOSALS
            or any(not isinstance(item, SynthesisProposal) for item in self.proposals)
        ):
            raise ValueError(f"synthesis proposals must be at most {MAX_SYNTHESIS_PROPOSALS}")
        if [item.code for item in self.proposals] != [
            proposal_code(ordinal) for ordinal in range(1, len(self.proposals) + 1)
        ]:
            raise ValueError("synthesis proposal codes must follow PRP-001 in order")
        if len({item.text for item in self.proposals}) != len(self.proposals):
            raise ValueError("synthesis proposals must be distinct")
        _require_items(
            self.questions_for_owner,
            label="question for the owner",
            maximum_items=MAX_QUESTIONS_FOR_OWNER,
            maximum=MAX_QUESTION_LENGTH,
        )
        _require_uuid(self.model_generation_id, "synthesis model generation ID")

    @property
    def twin_ids(self) -> frozenset[UUID]:
        return frozenset(
            (
                *(twin_id for item in self.conflicts for twin_id in item.twin_ids),
                *(twin_id for item in self.proposals for twin_id in item.supported_by),
            )
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "agreements": list(self.agreements),
            "conflicts": [item.to_snapshot() for item in self.conflicts],
            "proposals": [item.to_snapshot() for item in self.proposals],
            "questions_for_owner": list(self.questions_for_owner),
            "model_generation_id": str(self.model_generation_id),
        }


def _round_semantic_snapshot(
    *,
    ordinal: int,
    owner_note: str | None,
    statements: tuple[TwinStatement, ...],
    synthesis: DiscussionSynthesis,
    created_at: datetime,
) -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "owner_note": owner_note,
        "created_at": created_at.isoformat(),
        "statements": [item.to_snapshot() for item in statements],
        "synthesis": synthesis.to_snapshot(),
    }


@dataclass(frozen=True, slots=True)
class DiscussionRound:
    ordinal: int
    owner_note: str | None
    statements: tuple[TwinStatement, ...]
    synthesis: DiscussionSynthesis
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or not 1 <= self.ordinal <= MAX_DISCUSSION_ROUNDS
        ):
            raise ValueError(f"round ordinal must be between 1 and {MAX_DISCUSSION_ROUNDS}")
        if self.owner_note is not None and (
            not isinstance(self.owner_note, str)
            or normalize_owner_note(self.owner_note) != self.owner_note
        ):
            raise ValueError("round owner note must be normalized")
        if (
            not isinstance(self.statements, tuple)
            or not 1 <= len(self.statements) <= MAX_DISCUSSION_TWINS
            or any(not isinstance(item, TwinStatement) for item in self.statements)
        ):
            raise ValueError("a round needs one statement per twin")
        participants = self.participants
        if len(set(participants)) != len(participants):
            raise ValueError("a round holds one statement per twin")
        for statement in self.statements:
            if self.ordinal == 1 and statement.replies_to:
                raise ValueError("nobody can be answered in the first round")
            if not set(statement.replies_to) <= set(participants):
                raise ValueError("statements reply only to the participants of the round")
            if self.owner_note is None and statement.owner_answer is not None:
                raise ValueError("an answer to the owner requires the owner's note")
        if not isinstance(self.synthesis, DiscussionSynthesis):
            raise ValueError("a round needs its synthesis")
        if not self.synthesis.twin_ids <= set(participants):
            raise ValueError("the synthesis names only the participants of the round")
        generations = [item.model_generation_id for item in self.statements]
        generations.append(self.synthesis.model_generation_id)
        if len(set(generations)) != len(generations):
            raise ValueError("every statement and the synthesis come from distinct generations")
        _require_timestamp(self.created_at, "round timestamp")
        validate_sha256(self.content_hash, label="discussion round hash")
        if self.content_hash != snapshot_content_hash(self.semantic_snapshot()):
            raise ValueError("discussion round hash is inconsistent")

    @property
    def participants(self) -> tuple[UUID, ...]:
        return tuple(item.twin_id for item in self.statements)

    def semantic_snapshot(self) -> dict[str, object]:
        return _round_semantic_snapshot(
            ordinal=self.ordinal,
            owner_note=self.owner_note,
            statements=self.statements,
            synthesis=self.synthesis,
            created_at=self.created_at,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def create_discussion_round(
    *,
    ordinal: int,
    owner_note: str | None,
    statements: tuple[TwinStatement, ...],
    synthesis: DiscussionSynthesis,
    created_at: datetime,
) -> DiscussionRound:
    note = normalize_owner_note(owner_note)
    semantic = _round_semantic_snapshot(
        ordinal=ordinal,
        owner_note=note,
        statements=statements,
        synthesis=synthesis,
        created_at=created_at,
    )
    return DiscussionRound(
        ordinal=ordinal,
        owner_note=note,
        statements=statements,
        synthesis=synthesis,
        created_at=created_at,
        content_hash=snapshot_content_hash(semantic),
    )


@dataclass(frozen=True, slots=True)
class DesignDiscussion:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    design_version_id: UUID
    design_version_number: int
    design_content_hash: str
    alternative_id: UUID
    alternative_code: str
    locale: str
    status: DiscussionStatus
    rounds: tuple[DiscussionRound, ...]
    created_at: datetime
    decided_at: datetime | None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "discussion ID"),
            (self.project_id, "discussion project ID"),
            (self.owner_user_id, "discussion owner ID"),
            (self.design_version_id, "discussion design version ID"),
            (self.alternative_id, "discussion alternative ID"),
        ):
            _require_uuid(value, label)
        validate_positive_integer(self.design_version_number, label="discussion design version")
        validate_sha256(self.design_content_hash, label="discussion design hash")
        validate_display_code(self.alternative_code, prefix="DES", label="discussion alternative")
        validate_locale(self.locale)
        if not isinstance(self.status, DiscussionStatus):
            raise ValueError("discussion status must be a DiscussionStatus")
        if (
            not isinstance(self.rounds, tuple)
            or not 1 <= len(self.rounds) <= MAX_DISCUSSION_ROUNDS
            or any(not isinstance(item, DiscussionRound) for item in self.rounds)
        ):
            raise ValueError(f"a discussion holds 1 to {MAX_DISCUSSION_ROUNDS} rounds")
        if [item.ordinal for item in self.rounds] != list(range(1, len(self.rounds) + 1)):
            raise ValueError("discussion rounds must be numbered from 1 in order")
        speakers = {
            frozenset((item.twin_id, item.twin_version) for item in current.statements)
            for current in self.rounds
        }
        if len(speakers) != 1:
            raise ValueError("every round is held among the same twins")
        _require_timestamp(self.created_at, "discussion timestamp")
        moments = [self.created_at, *(item.created_at for item in self.rounds)]
        if any(later < earlier for earlier, later in pairwise(moments)):
            raise ValueError("discussion rounds must follow the discussion in time")
        if (self.status is DiscussionStatus.OPEN) != (self.decided_at is None):
            raise ValueError("only a decided discussion carries its decision time")
        if self.decided_at is not None:
            _require_timestamp(self.decided_at, "discussion decision timestamp")
            if self.decided_at < moments[-1]:
                raise ValueError("a discussion is decided after its last round")

    @property
    def participants(self) -> tuple[UUID, ...]:
        return self.rounds[0].participants

    def with_round(self, round_: DiscussionRound) -> DesignDiscussion:
        if self.status is not DiscussionStatus.OPEN:
            raise ValueError("only an open discussion accepts new rounds")
        return replace(self, rounds=(*self.rounds, round_))

    def decided(self, status: DiscussionStatus, at: datetime) -> DesignDiscussion:
        if self.status is not DiscussionStatus.OPEN:
            raise ValueError("the discussion has already been decided")
        if status is DiscussionStatus.OPEN:
            raise ValueError("a decision approves or closes the discussion")
        return replace(self, status=status, decided_at=at)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "design_version_id": str(self.design_version_id),
            "design_version_number": self.design_version_number,
            "design_content_hash": self.design_content_hash,
            "alternative_id": str(self.alternative_id),
            "alternative_code": self.alternative_code,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "decided_at": None if self.decided_at is None else self.decided_at.isoformat(),
            "max_rounds": MAX_DISCUSSION_ROUNDS,
            "rounds": [item.to_snapshot() for item in self.rounds],
        }


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp")
    return datetime.fromisoformat(value)


def _statement_from_snapshot(payload: Mapping[str, object]) -> TwinStatement:
    return TwinStatement(
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(payload["twin_version"]),
        twin_name=str(payload["twin_name"]),
        stance=DiscussionStance(str(payload["stance"])),
        statement=str(payload["statement"]),
        replies_to=tuple(UUID(str(item)) for item in payload["replies_to"]),
        proposals=tuple(str(item) for item in payload["proposals"]),
        grounded_on=tuple(str(item) for item in payload["grounded_on"]),
        confidence=float(payload["confidence"]),
        model_generation_id=UUID(str(payload["model_generation_id"])),
        reactions=tuple(
            TwinReaction(
                twin_id=UUID(str(reaction["twin_id"])),
                verdict=ReactionVerdict(str(reaction["verdict"])),
                reason=str(reaction["reason"]),
            )
            for reaction in (_mapping(item, "reaction") for item in payload.get("reactions", ()))
        ),
        owner_answer=None
        if payload.get("answer_to_owner") is None
        else str(payload["answer_to_owner"]),
    )


def _synthesis_from_snapshot(payload: Mapping[str, object]) -> DiscussionSynthesis:
    return DiscussionSynthesis(
        agreements=tuple(str(item) for item in payload["agreements"]),
        conflicts=tuple(
            SynthesisConflict(
                topic=str(conflict["topic"]),
                positions=tuple(
                    (UUID(str(position["twin_id"])), str(position["position"]))
                    for position in conflict["positions"]
                ),
            )
            for conflict in (_mapping(item, "conflict") for item in payload["conflicts"])
        ),
        proposals=tuple(
            SynthesisProposal(
                code=str(proposal["code"]),
                text=str(proposal["text"]),
                target=DiscussionProposalTarget(str(proposal["target"])),
                supported_by=tuple(UUID(str(item)) for item in proposal["supported_by"]),
            )
            for proposal in (_mapping(item, "proposal") for item in payload["proposals"])
        ),
        questions_for_owner=tuple(str(item) for item in payload["questions_for_owner"]),
        model_generation_id=UUID(str(payload["model_generation_id"])),
    )


def discussion_round_from_snapshot(payload: Mapping[str, object]) -> DiscussionRound:
    round_ = DiscussionRound(
        ordinal=int(payload["ordinal"]),
        owner_note=None if payload["owner_note"] is None else str(payload["owner_note"]),
        statements=tuple(
            _statement_from_snapshot(_mapping(item, "statement")) for item in payload["statements"]
        ),
        synthesis=_synthesis_from_snapshot(_mapping(payload["synthesis"], "synthesis")),
        created_at=_timestamp(payload["created_at"], "round created_at"),
        content_hash=str(payload["content_hash"]),
    )
    if round_.to_snapshot() != dict(payload):
        raise ValueError("discussion round snapshot is not canonical")
    return round_


def design_discussion_from_snapshot(
    payload: Mapping[str, object], *, locale: str
) -> DesignDiscussion:
    discussion = DesignDiscussion(
        id=UUID(str(payload["id"])),
        project_id=UUID(str(payload["project_id"])),
        owner_user_id=UUID(str(payload["owner_user_id"])),
        design_version_id=UUID(str(payload["design_version_id"])),
        design_version_number=int(payload["design_version_number"]),
        design_content_hash=str(payload["design_content_hash"]),
        alternative_id=UUID(str(payload["alternative_id"])),
        alternative_code=str(payload["alternative_code"]),
        locale=locale,
        status=DiscussionStatus(str(payload["status"])),
        rounds=tuple(
            discussion_round_from_snapshot(_mapping(item, "round")) for item in payload["rounds"]
        ),
        created_at=_timestamp(payload["created_at"], "discussion created_at"),
        decided_at=None
        if payload["decided_at"] is None
        else _timestamp(payload["decided_at"], "discussion decided_at"),
    )
    if discussion.to_snapshot() != dict(payload):
        raise ValueError("design discussion snapshot is not canonical")
    return discussion


__all__ = [
    "LOCALE_PATTERN",
    "MAX_AGREEMENTS",
    "MAX_AGREEMENT_LENGTH",
    "MAX_CONFLICTS",
    "MAX_CONFLICT_TOPIC_LENGTH",
    "MAX_DISCUSSION_ROUNDS",
    "MAX_DISCUSSION_TWINS",
    "MAX_LOCALE_LENGTH",
    "MAX_OWNER_ANSWER_LENGTH",
    "MAX_OWNER_NOTE_LENGTH",
    "MAX_POSITION_LENGTH",
    "MAX_PROPOSAL_LENGTH",
    "MAX_QUESTIONS_FOR_OWNER",
    "MAX_QUESTION_LENGTH",
    "MAX_REACTION_REASON_LENGTH",
    "MAX_STATEMENT_GROUNDING",
    "MAX_STATEMENT_LENGTH",
    "MAX_STATEMENT_PROPOSALS",
    "MAX_SYNTHESIS_PROPOSALS",
    "MAX_TWIN_NAME_LENGTH",
    "PROPOSAL_CODE_PREFIX",
    "DesignDiscussion",
    "DiscussionProposalTarget",
    "DiscussionRound",
    "DiscussionStance",
    "DiscussionStatus",
    "DiscussionSynthesis",
    "ReactionVerdict",
    "SynthesisConflict",
    "SynthesisProposal",
    "TwinReaction",
    "TwinStatement",
    "create_discussion_round",
    "design_discussion_from_snapshot",
    "discussion_round_from_snapshot",
    "normalize_owner_note",
    "proposal_code",
    "validate_locale",
]
