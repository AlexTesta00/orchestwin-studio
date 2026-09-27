from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    snapshot_content_hash,
    validate_display_code,
    validate_positive_integer,
    validate_sha256,
)

MAX_FINDING_NOTE_LENGTH: Final = 1000
_UUID: Final = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_FINDING_SOURCE: Final = re.compile(rf"run:({_UUID}):({_UUID}):(UTF-[0-9]{{3,6}})")


class FindingDecision(StrEnum):
    OWNER_CONFIRMED = "OWNER_CONFIRMED"
    OWNER_DISMISSED = "OWNER_DISMISSED"


def normalize_finding_note(note: str | None) -> str | None:
    return normalize_optional_text(
        note, label="finding validation note", maximum_length=MAX_FINDING_NOTE_LENGTH
    )


def _semantic_snapshot(
    *,
    evaluation_run_id: UUID,
    twin_id: UUID,
    finding_id: str,
    sequence_number: int,
    project_id: UUID,
    owner_user_id: UUID,
    decision: FindingDecision,
    note: str | None,
    decided_at: datetime,
) -> dict[str, object]:
    return {
        "evaluation_run_id": str(evaluation_run_id),
        "twin_id": str(twin_id),
        "finding_id": finding_id,
        "sequence_number": sequence_number,
        "project_id": str(project_id),
        "owner_user_id": str(owner_user_id),
        "decision": decision.value,
        "note": note,
        "decided_at": decided_at.isoformat(),
    }


@dataclass(frozen=True, slots=True)
class FindingValidation:
    evaluation_run_id: UUID
    twin_id: UUID
    finding_id: str
    sequence_number: int
    project_id: UUID
    owner_user_id: UUID
    decision: FindingDecision
    note: str | None
    decided_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.decision, FindingDecision):
            raise ValueError("finding decision must be a FindingDecision")
        validate_display_code(self.finding_id, prefix="UTF", label="finding ID")
        validate_positive_integer(self.sequence_number, label="finding validation sequence number")
        if normalize_finding_note(self.note) != self.note:
            raise ValueError("finding validation note must be normalized")
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            raise ValueError("finding validation timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="finding validation hash")
        if self.content_hash != snapshot_content_hash(self.semantic_snapshot()):
            raise ValueError("finding validation hash is inconsistent")

    @property
    def key(self) -> tuple[UUID, UUID, str]:
        return (self.evaluation_run_id, self.twin_id, self.finding_id)

    def semantic_snapshot(self) -> dict[str, object]:
        return _semantic_snapshot(
            evaluation_run_id=self.evaluation_run_id,
            twin_id=self.twin_id,
            finding_id=self.finding_id,
            sequence_number=self.sequence_number,
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            decision=self.decision,
            note=self.note,
            decided_at=self.decided_at,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {**self.semantic_snapshot(), "content_hash": self.content_hash}


def create_finding_validation(
    *,
    evaluation_run_id: UUID,
    twin_id: UUID,
    finding_id: str,
    sequence_number: int,
    project_id: UUID,
    owner_user_id: UUID,
    decision: FindingDecision,
    note: str | None,
    decided_at: datetime,
) -> FindingValidation:
    values = {
        "evaluation_run_id": evaluation_run_id,
        "twin_id": twin_id,
        "finding_id": finding_id,
        "sequence_number": sequence_number,
        "project_id": project_id,
        "owner_user_id": owner_user_id,
        "decision": FindingDecision(decision),
        "note": normalize_finding_note(note),
        "decided_at": decided_at,
    }
    return FindingValidation(
        **values, content_hash=snapshot_content_hash(_semantic_snapshot(**values))
    )


def finding_validation_from_snapshot(payload: Mapping[str, object]) -> FindingValidation:
    validation = FindingValidation(
        evaluation_run_id=UUID(str(payload["evaluation_run_id"])),
        twin_id=UUID(str(payload["twin_id"])),
        finding_id=str(payload["finding_id"]),
        sequence_number=int(payload["sequence_number"]),
        project_id=UUID(str(payload["project_id"])),
        owner_user_id=UUID(str(payload["owner_user_id"])),
        decision=FindingDecision(str(payload["decision"])),
        note=None if payload["note"] is None else str(payload["note"]),
        decided_at=datetime.fromisoformat(str(payload["decided_at"])),
        content_hash=str(payload["content_hash"]),
    )
    if validation.to_snapshot() != dict(payload):
        raise ValueError("finding validation snapshot is not canonical")
    return validation


def dismissed_finding_keys(
    validations: Iterable[FindingValidation],
) -> frozenset[tuple[UUID, UUID, str]]:
    latest: dict[tuple[UUID, UUID, str], FindingValidation] = {}
    for validation in validations:
        known = latest.get(validation.key)
        if known is None or validation.sequence_number > known.sequence_number:
            latest[validation.key] = validation
    return frozenset(
        key
        for key, validation in latest.items()
        if validation.decision is FindingDecision.OWNER_DISMISSED
    )


def finding_source_id(evaluation_run_id: UUID, twin_id: UUID, finding_id: str) -> str:
    return f"run:{evaluation_run_id}:{twin_id}:{finding_id}"


def finding_source_key(source_id: str) -> tuple[UUID, UUID, str] | None:
    match = _FINDING_SOURCE.fullmatch(source_id.strip())
    if match is None:
        return None
    return (UUID(match[1]), UUID(match[2]), match[3])


__all__ = [
    "MAX_FINDING_NOTE_LENGTH",
    "FindingDecision",
    "FindingValidation",
    "create_finding_validation",
    "dismissed_finding_keys",
    "finding_source_id",
    "finding_source_key",
    "finding_validation_from_snapshot",
    "normalize_finding_note",
]
