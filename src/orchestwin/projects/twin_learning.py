from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.knowledge.state import (
    MAX_BASIS_LENGTH,
    MAX_LEARNED_OBSERVATIONS,
    MAX_OBSERVATION_LENGTH,
    MAX_TASK_NOTE_LENGTH,
    MAX_UPDATE_CHANGES,
    MAX_UPDATE_COMMENT_LENGTH,
    MAX_UPDATE_OBSERVATIONS,
    MAX_UPDATE_TESTS,
    OBSERVATION_CODE_PREFIX,
)
from orchestwin.projects.code_changes import (
    LOCALE_PATTERN,
    MAX_LOCALE_LENGTH,
    MAX_TWIN_NAME_LENGTH,
    normalized_line,
)
from orchestwin.projects.research_evidence import EvidenceChange, EvidenceUpdateSource

OBSERVATION_CODE_PATTERN: Final = rf"^{OBSERVATION_CODE_PREFIX}-[0-9]{{3,6}}$"
REQUIREMENT_CODE_PATTERN: Final = r"^REQ-[0-9]{3,6}$"
SCREEN_CODE_PATTERN: Final = r"^SCR-[0-9]{3,6}$"
MAX_OBSERVATION_NUMBER: Final = 999_999
MAX_LEARNING_REASON_LENGTH: Final = MAX_TASK_NOTE_LENGTH
_OBSERVATION_CODE: Final = re.compile(OBSERVATION_CODE_PATTERN)
_REQUIREMENT_CODE: Final = re.compile(REQUIREMENT_CODE_PATTERN)
_SCREEN_CODE: Final = re.compile(SCREEN_CODE_PATTERN)
_LOCALE: Final = re.compile(LOCALE_PATTERN)


class LearningSource(StrEnum):
    TWIN_CRITIQUE = "TWIN_CRITIQUE"
    OWNER = "OWNER"


class UpdateStatus(StrEnum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EMPTY = "EMPTY"


class UpdateDecisionKind(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


def _aware(value: object, label: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _moment(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO timestamp")
    moment = datetime.fromisoformat(value)
    _aware(moment, label)
    return moment


def _uuid(value: object, label: str) -> None:
    if not isinstance(value, UUID):
        raise ValueError(f"{label} must be a UUID")


def _count(value: object, label: str, *, minimum: int = 0, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} must be at most {maximum}")


def _normalized(value: object, *, label: str, maximum: int) -> None:
    if normalized_line(value, label=label, maximum=maximum) != value:
        raise ValueError(f"{label} must be normalized")


def _optional_normalized(value: object, *, label: str, maximum: int) -> None:
    if value is not None:
        _normalized(value, label=label, maximum=maximum)


def _optional_code(value: object, pattern: re.Pattern[str], label: str) -> None:
    if value is not None and (not isinstance(value, str) or pattern.fullmatch(value) is None):
        raise ValueError(f"{label} holds an invalid code")


def _about(about: object) -> Mapping[str, object]:
    if not isinstance(about, Mapping):
        raise ValueError("the subject of an observation must be an object")
    return about


def observation_code(number: int) -> str:
    _count(number, "observation number", minimum=1, maximum=MAX_OBSERVATION_NUMBER)
    return f"{OBSERVATION_CODE_PREFIX}-{number:03d}"


def observation_number(code: object) -> int:
    if not isinstance(code, str) or _OBSERVATION_CODE.fullmatch(code) is None:
        raise ValueError(f"observation code must use the {OBSERVATION_CODE_PREFIX}-NNN format")
    number = int(code.split("-", 1)[1])
    if observation_code(number) != code:
        raise ValueError("observation code must write its number with at least three digits")
    return number


def requested_observation_number(value: object) -> int | None:
    if not isinstance(value, str) or _OBSERVATION_CODE.fullmatch(value.upper()) is None:
        return None
    number = int(value.split("-", 1)[1])
    return number if 1 <= number <= MAX_OBSERVATION_NUMBER else None


def normalize_statement(value: object) -> str:
    return normalized_line(value, label="observation statement", maximum=MAX_OBSERVATION_LENGTH)


def normalize_learning_reason(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("reason must be a text")
    if not value.strip():
        return None
    return normalized_line(value, label="reason", maximum=MAX_LEARNING_REASON_LENGTH)


def statement_key(value: str) -> str:
    return " ".join(value.split()).casefold()


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    statement: str
    basis: str | None = None
    requirement: str | None = None
    screen: str | None = None
    contradicts_profile: str | None = None

    def __post_init__(self) -> None:
        _normalized(self.statement, label="observation statement", maximum=MAX_OBSERVATION_LENGTH)
        _optional_normalized(self.basis, label="observation basis", maximum=MAX_BASIS_LENGTH)
        _optional_code(self.requirement, _REQUIREMENT_CODE, "observation requirement")
        _optional_code(self.screen, _SCREEN_CODE, "observation screen")
        _optional_normalized(
            self.contradicts_profile, label="profile contradiction", maximum=MAX_BASIS_LENGTH
        )


@dataclass(frozen=True, slots=True)
class RetiredObservation:
    number: int
    statement: str
    retired_in_version: int
    retired_at: datetime
    reason: str | None = None

    def __post_init__(self) -> None:
        observation_code(self.number)
        _normalized(self.statement, label="observation statement", maximum=MAX_OBSERVATION_LENGTH)
        _count(self.retired_in_version, "retirement version", minimum=2)
        _aware(self.retired_at, "retirement time")
        if normalize_learning_reason(self.reason) != self.reason:
            raise ValueError("retirement reason must be normalized")

    @property
    def code(self) -> str:
        return observation_code(self.number)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "statement": self.statement,
            "retired_in_version": self.retired_in_version,
            "retired_at": _timestamp(self.retired_at),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class LearnedObservation:
    twin_id: UUID
    number: int
    statement: str
    source: LearningSource
    added_in_version: int
    approved_at: datetime
    basis: str | None = None
    requirement: str | None = None
    screen: str | None = None
    contradicts_profile: str | None = None
    update_id: UUID | None = None
    retired_in_version: int | None = None
    retired_at: datetime | None = None
    retire_reason: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.twin_id, "observation twin ID")
        observation_code(self.number)
        _normalized(self.statement, label="observation statement", maximum=MAX_OBSERVATION_LENGTH)
        if not isinstance(self.source, LearningSource):
            raise ValueError("observation source must be a LearningSource")
        _count(self.added_in_version, "observation version", minimum=1)
        _aware(self.approved_at, "observation approval time")
        _optional_normalized(self.basis, label="observation basis", maximum=MAX_BASIS_LENGTH)
        _optional_code(self.requirement, _REQUIREMENT_CODE, "observation requirement")
        _optional_code(self.screen, _SCREEN_CODE, "observation screen")
        _optional_normalized(
            self.contradicts_profile, label="profile contradiction", maximum=MAX_BASIS_LENGTH
        )
        if self.update_id is not None:
            _uuid(self.update_id, "observation update ID")
        written = self.source is LearningSource.OWNER
        if written != (self.update_id is None):
            raise ValueError(
                "an observation comes from an update exactly when a critique taught it"
            )
        if written != (self.basis is None):
            raise ValueError("an observation has a basis exactly when a critique taught it")
        if (self.retired_in_version is None) != (self.retired_at is None):
            raise ValueError("a retired observation has its retirement version and time")
        if self.retired_in_version is not None:
            _count(self.retired_in_version, "retirement version", minimum=self.added_in_version + 1)
            _aware(self.retired_at, "retirement time")
        if self.retire_reason is not None and self.retired_at is None:
            raise ValueError("only a retired observation has a retirement reason")
        if normalize_learning_reason(self.retire_reason) != self.retire_reason:
            raise ValueError("retirement reason must be normalized")

    @property
    def code(self) -> str:
        return observation_code(self.number)

    @property
    def active(self) -> bool:
        return self.retired_at is None

    def retire(
        self, *, version: int, retired_at: datetime, reason: str | None = None
    ) -> LearnedObservation:
        if not self.active:
            raise ValueError("the observation is already retired")
        return replace(
            self, retired_in_version=version, retired_at=retired_at, retire_reason=reason
        )

    def retirement(self) -> RetiredObservation:
        if self.active:
            raise ValueError("the observation is not retired")
        return RetiredObservation(
            number=self.number,
            statement=self.statement,
            retired_in_version=self.retired_in_version,
            retired_at=self.retired_at,
            reason=self.retire_reason,
        )

    def learned_view(self) -> dict[str, object]:
        return {"code": self.code, "statement": self.statement, "source": self.source.value}

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "statement": self.statement,
            "basis": self.basis,
            "source": self.source.value,
            "about": {"requirement": self.requirement, "screen": self.screen},
            "contradicts_profile": self.contradicts_profile,
            "added_in_version": self.added_in_version,
            "approved_at": _timestamp(self.approved_at),
            "update_id": None if self.update_id is None else str(self.update_id),
        }


def development_version(records: Iterable[LearnedObservation]) -> int:
    return max(
        (max(item.added_in_version, item.retired_in_version or 0) for item in records),
        default=0,
    )


def learned_view(records: Iterable[LearnedObservation]) -> list[dict[str, object]]:
    active = sorted((item for item in records if item.active), key=lambda item: item.number)
    return [item.learned_view() for item in active]


def learned_observations(
    drafts: Sequence[ObservationDraft],
    *,
    twin_id: UUID,
    first_number: int,
    version: int,
    approved_at: datetime,
    source: LearningSource,
    update_id: UUID | None = None,
) -> tuple[LearnedObservation, ...]:
    return tuple(
        LearnedObservation(
            twin_id=twin_id,
            number=first_number + offset,
            statement=draft.statement,
            source=source,
            added_in_version=version,
            approved_at=approved_at,
            basis=draft.basis,
            requirement=draft.requirement,
            screen=draft.screen,
            contradicts_profile=draft.contradicts_profile,
            update_id=update_id,
        )
        for offset, draft in enumerate(drafts)
    )


@dataclass(frozen=True, slots=True)
class TwinLearning:
    twin_id: UUID
    twin_name: str
    profile_version_number: int
    development_version_number: int = 0
    observations: tuple[LearnedObservation, ...] = ()
    retired: tuple[RetiredObservation, ...] = ()

    def __post_init__(self) -> None:
        _uuid(self.twin_id, "twin ID")
        _normalized(self.twin_name, label="twin name", maximum=MAX_TWIN_NAME_LENGTH)
        _count(self.profile_version_number, "profile version number", minimum=1)
        _count(self.development_version_number, "development version number")
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, LearnedObservation) and item.active and item.twin_id == self.twin_id
            for item in self.observations
        ):
            raise ValueError("learned observations must be active observations of this twin")
        if len(self.observations) > MAX_LEARNED_OBSERVATIONS:
            raise ValueError(
                f"a twin holds at most {MAX_LEARNED_OBSERVATIONS} learned observations"
            )
        numbers = [item.number for item in self.observations]
        if numbers != sorted(set(numbers)):
            raise ValueError("learned observations are listed oldest first, each once")
        if not isinstance(self.retired, tuple) or not all(
            isinstance(item, RetiredObservation) for item in self.retired
        ):
            raise ValueError("retired observations must be a tuple of RetiredObservation")
        order = [(item.retired_in_version, item.number) for item in self.retired]
        if order != sorted(order):
            raise ValueError("retired observations are listed in the order they were retired")
        every = numbers + [item.number for item in self.retired]
        if len(set(every)) != len(every):
            raise ValueError("an observation is either active or retired, once")
        expected = max(
            (
                *(item.added_in_version for item in self.observations),
                *(item.retired_in_version for item in self.retired),
            ),
            default=0,
        )
        if self.development_version_number != expected:
            raise ValueError(
                "the development version grows with every approved update, "
                "observation of the owner and retirement"
            )

    @property
    def label(self) -> str:
        return f"{self.profile_version_number}.{self.development_version_number}"

    def learned_view(self) -> list[dict[str, object]]:
        return [item.learned_view() for item in self.observations]

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "twin_name": self.twin_name,
            "profile_version_number": self.profile_version_number,
            "development_version_number": self.development_version_number,
            "label": self.label,
            "observations": [item.to_snapshot() for item in self.observations],
            "retired": [item.to_snapshot() for item in self.retired],
        }


def build_twin_learning(
    *,
    twin_id: UUID,
    twin_name: str,
    profile_version_number: int,
    records: Iterable[LearnedObservation] = (),
) -> TwinLearning:
    owned = [item for item in records if item.twin_id == twin_id]
    active = sorted((item for item in owned if item.active), key=lambda item: item.number)
    retired = sorted(
        (item for item in owned if not item.active),
        key=lambda item: (item.retired_in_version, item.number),
    )
    return TwinLearning(
        twin_id=twin_id,
        twin_name=normalized_line(twin_name, label="twin name", maximum=MAX_TWIN_NAME_LENGTH),
        profile_version_number=profile_version_number,
        development_version_number=development_version(owned),
        observations=tuple(active),
        retired=tuple(item.retirement() for item in retired),
    )


@dataclass(frozen=True, slots=True)
class ProposedObservation:
    index: int
    statement: str
    basis: str
    requirement: str | None = None
    screen: str | None = None
    contradicts_profile: str | None = None
    evidence: EvidenceChange | None = None

    def __post_init__(self) -> None:
        _count(self.index, "proposed observation index", maximum=MAX_UPDATE_OBSERVATIONS - 1)
        _normalized(self.statement, label="observation statement", maximum=MAX_OBSERVATION_LENGTH)
        _normalized(self.basis, label="observation basis", maximum=MAX_BASIS_LENGTH)
        _optional_code(self.requirement, _REQUIREMENT_CODE, "observation requirement")
        _optional_code(self.screen, _SCREEN_CODE, "observation screen")
        _optional_normalized(
            self.contradicts_profile, label="profile contradiction", maximum=MAX_BASIS_LENGTH
        )
        if self.evidence is not None and not isinstance(self.evidence, EvidenceChange):
            raise ValueError("an evidence observation requires a typed change")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "index": self.index,
            "statement": self.statement,
            "basis": self.basis,
            "about": {"requirement": self.requirement, "screen": self.screen},
            "contradicts_profile": self.contradicts_profile,
            **({"evidence": self.evidence.to_snapshot()} if self.evidence is not None else {}),
        }


@dataclass(frozen=True, slots=True)
class KeptObservation:
    index: int
    statement: str | None = None

    def __post_init__(self) -> None:
        _count(self.index, "kept observation index")
        _optional_normalized(
            self.statement, label="observation statement", maximum=MAX_OBSERVATION_LENGTH
        )


@dataclass(frozen=True, slots=True)
class UpdateDecision:
    decided_at: datetime
    kept: tuple[int, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        _aware(self.decided_at, "decision time")
        if not isinstance(self.kept, tuple):
            raise ValueError("kept observations must be a tuple of indexes")
        for index in self.kept:
            _count(index, "kept observation index")
        if len(set(self.kept)) != len(self.kept):
            raise ValueError("a decision keeps each observation once")
        if normalize_learning_reason(self.reason) != self.reason:
            raise ValueError("decision reason must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "decided_at": _timestamp(self.decided_at),
            "kept": list(self.kept),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class TwinUpdate:
    id: UUID
    twin_id: UUID
    twin_name: str
    created_at: datetime
    locale: str
    status: UpdateStatus
    base_profile_version: int
    base_development_version: int
    comment: str
    observations: tuple[ProposedObservation, ...] = ()
    material_changes: int = 0
    material_tests: int = 0
    decision: UpdateDecision | None = None
    generation_ids: tuple[UUID, ...] = ()
    cost_microusd: int = 0
    evidence: EvidenceUpdateSource | None = None

    def __post_init__(self) -> None:
        _uuid(self.id, "update ID")
        _uuid(self.twin_id, "update twin ID")
        _normalized(self.twin_name, label="update twin name", maximum=MAX_TWIN_NAME_LENGTH)
        _aware(self.created_at, "update time")
        if (
            not isinstance(self.locale, str)
            or len(self.locale) > MAX_LOCALE_LENGTH
            or _LOCALE.fullmatch(self.locale) is None
        ):
            raise ValueError("update locale must be a language tag such as it-IT")
        if not isinstance(self.status, UpdateStatus):
            raise ValueError("update status must be an UpdateStatus")
        _count(self.base_profile_version, "base profile version", minimum=1)
        _count(self.base_development_version, "base development version")
        _normalized(self.comment, label="update comment", maximum=MAX_UPDATE_COMMENT_LENGTH)
        if not isinstance(self.observations, tuple) or not all(
            isinstance(item, ProposedObservation) for item in self.observations
        ):
            raise ValueError("proposed observations must be a tuple of ProposedObservation")
        if len(self.observations) > MAX_UPDATE_OBSERVATIONS:
            raise ValueError(f"an update proposes at most {MAX_UPDATE_OBSERVATIONS} observations")
        if [item.index for item in self.observations] != list(range(len(self.observations))):
            raise ValueError("proposed observations are numbered from 0 in their order")
        keys = [statement_key(item.statement) for item in self.observations]
        if len(set(keys)) != len(keys):
            raise ValueError("an update proposes each observation once")
        if (self.status is UpdateStatus.EMPTY) != (not self.observations):
            raise ValueError("an update is empty exactly when it proposes no observation")
        _count(self.material_changes, "changes of the material", maximum=MAX_UPDATE_CHANGES)
        _count(self.material_tests, "test runs of the material", maximum=MAX_UPDATE_TESTS)
        if self.material_changes + self.material_tests < 1 and self.evidence is None:
            raise ValueError("an update is generated from some material")
        decided = self.status in (UpdateStatus.APPROVED, UpdateStatus.REJECTED)
        if decided != (self.decision is not None):
            raise ValueError("an update carries its decision exactly when it is decided")
        if self.decision is not None:
            if not isinstance(self.decision, UpdateDecision):
                raise ValueError("update decision must be an UpdateDecision")
            if (self.status is UpdateStatus.APPROVED) != bool(self.decision.kept):
                raise ValueError("an approved update keeps some observations, a rejected one none")
            if any(index >= len(self.observations) for index in self.decision.kept):
                raise ValueError("a decision keeps only observations of the proposal")
        if not isinstance(self.generation_ids, tuple) or not all(
            isinstance(item, UUID) for item in self.generation_ids
        ):
            raise ValueError("generation IDs must be a tuple of UUID")
        if len(set(self.generation_ids)) != len(self.generation_ids):
            raise ValueError("generation IDs must not repeat")
        _count(self.cost_microusd, "update cost")
        if self.evidence is not None:
            if not isinstance(self.evidence, EvidenceUpdateSource):
                raise ValueError("an evidence update requires a typed source")
            if len(self.observations) + self.evidence.rejected_changes > MAX_UPDATE_OBSERVATIONS:
                raise ValueError("accepted and rejected evidence changes exceed the proposal limit")
            if any(
                item.evidence is None
                or item.evidence.citation.source_id != self.evidence.source_id
                or item.evidence.citation.source_version != self.evidence.source_version
                or item.evidence.citation.content_hash != self.evidence.content_hash
                for item in self.observations
            ):
                raise ValueError("evidence changes must cite the update source version")

    @property
    def pending(self) -> bool:
        return self.status is UpdateStatus.PROPOSED

    def decided(
        self,
        decision: UpdateDecisionKind,
        *,
        kept: Iterable[int] = (),
        reason: str | None = None,
        decided_at: datetime,
    ) -> TwinUpdate:
        if not self.pending:
            raise ValueError("only a proposed update is decided")
        if not isinstance(decision, UpdateDecisionKind):
            raise ValueError("decision must be an UpdateDecisionKind")
        status = (
            UpdateStatus.APPROVED
            if decision is UpdateDecisionKind.APPROVE
            else UpdateStatus.REJECTED
        )
        return replace(
            self,
            status=status,
            decision=UpdateDecision(decided_at=decided_at, kept=tuple(sorted(kept)), reason=reason),
        )

    def kept_drafts(self, kept: Iterable[KeptObservation]) -> tuple[ObservationDraft, ...]:
        proposals = {item.index: item for item in self.observations}
        drafts = []
        for item in sorted(kept, key=lambda value: value.index):
            proposal = proposals.get(item.index)
            if proposal is None:
                raise ValueError("the proposal has no observation at this index")
            drafts.append(
                ObservationDraft(
                    statement=proposal.statement if item.statement is None else item.statement,
                    basis=proposal.basis,
                    requirement=proposal.requirement,
                    screen=proposal.screen,
                    contradicts_profile=proposal.contradicts_profile,
                )
            )
        return tuple(drafts)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "twin_id": str(self.twin_id),
            "twin_name": self.twin_name,
            "created_at": _timestamp(self.created_at),
            "locale": self.locale,
            "status": self.status.value,
            "base": {
                "profile_version_number": self.base_profile_version,
                "development_version_number": self.base_development_version,
            },
            "comment": self.comment,
            "observations": [item.to_snapshot() for item in self.observations],
            "material": {"changes": self.material_changes, "tests": self.material_tests},
            "decision": None if self.decision is None else self.decision.to_snapshot(),
            "cost_microusd": self.cost_microusd,
            **({"evidence": self.evidence.to_snapshot()} if self.evidence is not None else {}),
        }


def learned_observation_from_snapshot(
    payload: Mapping[str, object], *, twin_id: UUID
) -> LearnedObservation:
    about = _about(payload["about"])
    update_id = payload["update_id"]
    return LearnedObservation(
        twin_id=twin_id,
        number=observation_number(payload["code"]),
        statement=payload["statement"],
        source=LearningSource(str(payload["source"])),
        added_in_version=payload["added_in_version"],
        approved_at=_moment(payload["approved_at"], "observation approval time"),
        basis=payload["basis"],
        requirement=about["requirement"],
        screen=about["screen"],
        contradicts_profile=payload["contradicts_profile"],
        update_id=None if update_id is None else UUID(str(update_id)),
    )


def retired_observation_from_snapshot(payload: Mapping[str, object]) -> RetiredObservation:
    return RetiredObservation(
        number=observation_number(payload["code"]),
        statement=payload["statement"],
        retired_in_version=payload["retired_in_version"],
        retired_at=_moment(payload["retired_at"], "retirement time"),
        reason=payload["reason"],
    )


def twin_learning_from_snapshot(payload: Mapping[str, object]) -> TwinLearning:
    twin_id = UUID(str(payload["twin_id"]))
    learning = TwinLearning(
        twin_id=twin_id,
        twin_name=payload["twin_name"],
        profile_version_number=payload["profile_version_number"],
        development_version_number=payload["development_version_number"],
        observations=tuple(
            learned_observation_from_snapshot(item, twin_id=twin_id)
            for item in payload["observations"]
        ),
        retired=tuple(retired_observation_from_snapshot(item) for item in payload["retired"]),
    )
    if payload["label"] != learning.label:
        raise ValueError("the label of a twin is its profile version and its development version")
    return learning


def proposed_observation_from_snapshot(payload: Mapping[str, object]) -> ProposedObservation:
    about = _about(payload["about"])
    return ProposedObservation(
        index=payload["index"],
        statement=payload["statement"],
        basis=payload["basis"],
        requirement=about["requirement"],
        screen=about["screen"],
        contradicts_profile=payload["contradicts_profile"],
        evidence=None
        if payload.get("evidence") is None
        else EvidenceChange.from_snapshot(payload["evidence"]),
    )


def update_decision_from_snapshot(payload: Mapping[str, object]) -> UpdateDecision:
    return UpdateDecision(
        decided_at=_moment(payload["decided_at"], "decision time"),
        kept=tuple(payload["kept"]),
        reason=payload["reason"],
    )


def twin_update_from_snapshot(payload: Mapping[str, object]) -> TwinUpdate:
    base = payload["base"]
    material = payload["material"]
    decision = payload["decision"]
    if not isinstance(base, Mapping) or not isinstance(material, Mapping):
        raise ValueError("the base and the material of an update must be objects")
    return TwinUpdate(
        id=UUID(str(payload["id"])),
        twin_id=UUID(str(payload["twin_id"])),
        twin_name=payload["twin_name"],
        created_at=_moment(payload["created_at"], "update time"),
        locale=payload["locale"],
        status=UpdateStatus(str(payload["status"])),
        base_profile_version=base["profile_version_number"],
        base_development_version=base["development_version_number"],
        comment=payload["comment"],
        observations=tuple(
            proposed_observation_from_snapshot(item) for item in payload["observations"]
        ),
        material_changes=material["changes"],
        material_tests=material["tests"],
        decision=None if decision is None else update_decision_from_snapshot(decision),
        cost_microusd=payload["cost_microusd"],
        evidence=None
        if payload.get("evidence") is None
        else EvidenceUpdateSource.from_snapshot(payload["evidence"]),
    )


__all__ = [
    "MAX_LEARNING_REASON_LENGTH",
    "MAX_OBSERVATION_NUMBER",
    "OBSERVATION_CODE_PATTERN",
    "REQUIREMENT_CODE_PATTERN",
    "SCREEN_CODE_PATTERN",
    "KeptObservation",
    "LearnedObservation",
    "LearningSource",
    "ObservationDraft",
    "ProposedObservation",
    "RetiredObservation",
    "TwinLearning",
    "TwinUpdate",
    "UpdateDecision",
    "UpdateDecisionKind",
    "UpdateStatus",
    "build_twin_learning",
    "development_version",
    "learned_observation_from_snapshot",
    "learned_observations",
    "learned_view",
    "normalize_learning_reason",
    "normalize_statement",
    "observation_code",
    "observation_number",
    "proposed_observation_from_snapshot",
    "requested_observation_number",
    "retired_observation_from_snapshot",
    "statement_key",
    "twin_learning_from_snapshot",
    "twin_update_from_snapshot",
    "update_decision_from_snapshot",
]
