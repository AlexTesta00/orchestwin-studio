from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from orchestwin.twins.epistemics import EvidenceSourceKind, ObservationValue, ObservationValueKind
from orchestwin.twins.user_twins import UserTwinField

MAX_EVIDENCE_CHARACTERS = 24_000
MAX_EVIDENCE_BYTES = 32_768
MAX_PROJECT_EVIDENCE_BYTES = 1_048_576
MAX_PROJECT_EVIDENCE_VERSIONS = 50


class EvidenceStatus(StrEnum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EvidenceEffect(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    ADDS = "ADDS"


class ResearchEvidenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def normalize_evidence_text(text: str) -> str:
    if not isinstance(text, str) or "\x00" in text:
        raise ResearchEvidenceError("EVIDENCE_INVALID_TEXT")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if any(ord(character) < 32 and character not in "\n\t" for character in normalized):
        raise ResearchEvidenceError("EVIDENCE_INVALID_TEXT")
    try:
        size = len(normalized.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ResearchEvidenceError("EVIDENCE_INVALID_TEXT") from error
    if not normalized.strip():
        raise ResearchEvidenceError("EVIDENCE_INVALID_TEXT")
    if len(normalized) > MAX_EVIDENCE_CHARACTERS or size > MAX_EVIDENCE_BYTES:
        raise ResearchEvidenceError("EVIDENCE_LIMIT")
    return normalized


def evidence_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest(value: str) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True, slots=True)
class EvidenceCitation:
    source_id: UUID
    source_version: int
    content_hash: str
    quote: str
    start: int
    end: int
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, UUID) or not _digest(self.content_hash):
            raise ValueError("invalid evidence citation reference")
        if not isinstance(self.quote, str) or not 1 <= len(self.quote) <= 1000:
            raise ValueError("invalid evidence quote")
        for number in (self.source_version, self.start_line, self.end_line):
            if isinstance(number, bool) or not isinstance(number, int) or number < 1:
                raise ValueError("invalid evidence citation version or line")
        if (
            isinstance(self.start, bool)
            or not isinstance(self.start, int)
            or self.start < 0
            or isinstance(self.end, bool)
            or not isinstance(self.end, int)
            or self.end != self.start + len(self.quote)
            or self.end_line < self.start_line
        ):
            raise ValueError("invalid evidence citation interval")

    def verify(self, text: str) -> bool:
        return (
            evidence_content_hash(text) == self.content_hash
            and text[self.start : self.end] == self.quote
            and text.count("\n", 0, self.start) + 1 == self.start_line
            and text.count("\n", 0, self.end - 1) + 1 == self.end_line
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, object]) -> EvidenceCitation:
        return cls(
            source_id=UUID(str(payload["source_id"])),
            source_version=payload["source_version"],
            content_hash=payload["content_hash"],
            quote=payload["quote"],
            start=payload["start"],
            end=payload["end"],
            start_line=payload["start_line"],
            end_line=payload["end_line"],
        )


@dataclass(frozen=True, slots=True)
class EvidenceChange:
    effect: EvidenceEffect
    field: UserTwinField
    value: ObservationValue
    citation: EvidenceCitation

    def __post_init__(self) -> None:
        if not isinstance(self.effect, EvidenceEffect) or not isinstance(self.field, UserTwinField):
            raise ValueError("invalid evidence effect or field")
        if self.value.kind not in (ObservationValueKind.TEXT, ObservationValueKind.ITEMS):
            raise ValueError("an evidence change requires a substantive value")
        if not isinstance(self.citation, EvidenceCitation):
            raise ValueError("an evidence change requires a verified citation")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "effect": self.effect.value,
            "field": self.field.value,
            "value": self.value.to_snapshot(),
            "citation": self.citation.to_snapshot(),
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, object]) -> EvidenceChange:
        value = payload["value"]
        return cls(
            effect=EvidenceEffect(str(payload["effect"])),
            field=UserTwinField(str(payload["field"])),
            value=ObservationValue(
                kind=ObservationValueKind(str(value["kind"])),
                text=value.get("text"),
                items=tuple(value.get("items", ())),
            ),
            citation=EvidenceCitation.from_snapshot(payload["citation"]),
        )


@dataclass(frozen=True, slots=True)
class EvidenceUpdateSource:
    source_id: UUID
    source_version: int
    content_hash: str
    rejected_changes: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, UUID) or not _digest(self.content_hash):
            raise ValueError("invalid evidence update source")
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (self.source_version, self.rejected_changes)
            )
            or self.source_version < 1
            or not 0 <= self.rejected_changes <= 6
        ):
            raise ValueError("invalid evidence update counters")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "source_id": str(self.source_id),
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "rejected_changes": self.rejected_changes,
        }

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, object]) -> EvidenceUpdateSource:
        return cls(
            source_id=UUID(str(payload["source_id"])),
            source_version=payload["source_version"],
            content_hash=payload["content_hash"],
            rejected_changes=payload.get("rejected_changes", 0),
        )


@dataclass(frozen=True, slots=True)
class EvidenceVersion:
    id: UUID
    code: str
    version: int
    title: str
    source_kind: EvidenceSourceKind
    source_ref: str
    context: str
    method: str
    collected_at: str | None
    limitations: str
    empirical: bool
    content_hash: str
    character_count: int
    byte_count: int
    created_at: datetime
    status: EvidenceStatus = EvidenceStatus.ACTIVE
    retired_at: datetime | None = None
    retired_reason: str | None = None
    text_available: bool = True
    imported_from: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID) or re.fullmatch(r"EVD-[0-9]{3,6}", self.code) is None:
            raise ValueError("invalid evidence identity")
        if self.version < 1 or not _digest(self.content_hash):
            raise ValueError("invalid evidence version")
        if self.created_at.utcoffset() is None:
            raise ValueError("evidence creation time must be aware")
        if (self.source_kind is EvidenceSourceKind.EMPIRICAL_RESEARCH) != self.empirical:
            raise ValueError("empirical nature must match the declared source kind")
        if self.empirical and (not self.method.strip() or not self.limitations.strip()):
            raise ValueError("empirical evidence requires method and limitations")
        if self.status is EvidenceStatus.RETIRED and self.retired_at is None:
            raise ValueError("retired evidence requires its retirement time")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "version": self.version,
            "title": self.title,
            "source_kind": self.source_kind.value,
            "source_ref": self.source_ref,
            "context": self.context,
            "method": self.method,
            "collected_at": self.collected_at,
            "limitations": self.limitations,
            "empirical": self.empirical,
            "content_hash": self.content_hash,
            "character_count": self.character_count,
            "byte_count": self.byte_count,
            "created_at": self.created_at.astimezone(UTC).isoformat(),
            "status": self.status.value,
            "retired_at": None
            if self.retired_at is None
            else self.retired_at.astimezone(UTC).isoformat(),
            "retired_reason": self.retired_reason,
            "text_available": self.text_available,
            **(
                {"imported_from": dict(self.imported_from)}
                if self.imported_from is not None
                else {}
            ),
        }
