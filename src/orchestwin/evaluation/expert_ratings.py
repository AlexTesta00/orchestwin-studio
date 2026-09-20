"""Raw blinded expert-rating contracts that preserve ratings and comments verbatim."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_MAX_IDENTIFIER_LENGTH: Final = 200
_MAX_RUBRIC_ITEM_LENGTH: Final = 500
_MAX_COMMENT_LENGTH: Final = 20_000


class ExpertPreference(StrEnum):
    """Public preference recorded while model identity remains blinded."""

    A = "A"
    B = "B"
    TIE = "TIE"


def _normalize(value: str, *, label: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if len(normalized) > maximum:
        raise ValueError(f"{label} exceeds maximum length")
    if normalized != value:
        raise ValueError(f"{label} must be normalized")
    return normalized


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExpertRubricScore:
    """One immutable Likert-style score for a public rubric item."""

    rubric_item: str
    score: int

    def __post_init__(self) -> None:
        _normalize(
            self.rubric_item,
            label="expert rubric item",
            maximum=_MAX_RUBRIC_ITEM_LENGTH,
        )
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError("expert rubric score must be an integer")
        if not 1 <= self.score <= 5:
            raise ValueError("expert rubric score must be between 1 and 5")

    @property
    def sort_key(self) -> str:
        return self.rubric_item.casefold()

    def to_snapshot(self) -> dict[str, object]:
        return {"rubric_item": self.rubric_item, "score": self.score}


@dataclass(frozen=True, slots=True)
class ExpertCandidateRating:
    """Complete rubric scores for one public candidate alias."""

    alias: str
    scores: tuple[ExpertRubricScore, ...]

    def __post_init__(self) -> None:
        if self.alias not in {"A", "B"}:
            raise ValueError("expert candidate alias must be A or B")
        if not self.scores:
            raise ValueError("expert candidate rating must contain rubric scores")
        if self.scores != tuple(sorted(self.scores, key=lambda item: item.sort_key)):
            raise ValueError("expert rubric scores must use canonical item order")
        names = tuple(item.rubric_item.casefold() for item in self.scores)
        if len(names) != len(set(names)):
            raise ValueError("expert rubric score items must be unique")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "alias": self.alias,
            "scores": [item.to_snapshot() for item in self.scores],
        }


@dataclass(frozen=True, slots=True)
class ExpertPairRating:
    """Raw blinded expert judgment; this is not target-user empirical evidence."""

    schema_version: int
    package_version: str
    package_content_hash: str
    pair_id: str
    reviewer_id: str
    candidate_a: ExpertCandidateRating
    candidate_b: ExpertCandidateRating
    preference: ExpertPreference
    comments: str
    submitted_at: datetime
    is_expert_judgment: bool
    is_target_user_evidence: bool
    real_user_behavior_validated: bool
    content_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported expert-rating schema version")
        _normalize(
            self.package_version,
            label="expert package version",
            maximum=_MAX_IDENTIFIER_LENGTH,
        )
        if _SHA256_PATTERN.fullmatch(self.package_content_hash) is None:
            raise ValueError("expert package hash must be a lowercase SHA-256 digest")
        _normalize(self.pair_id, label="expert pair ID", maximum=_MAX_IDENTIFIER_LENGTH)
        _normalize(
            self.reviewer_id,
            label="expert reviewer ID",
            maximum=_MAX_IDENTIFIER_LENGTH,
        )
        if self.candidate_a.alias != "A" or self.candidate_b.alias != "B":
            raise ValueError("expert pair ratings must preserve public aliases A and B")
        if len(self.comments) > _MAX_COMMENT_LENGTH:
            raise ValueError("expert comments exceed maximum length")
        if self.submitted_at.tzinfo is None:
            raise ValueError("expert rating timestamp must be timezone-aware")
        if not self.is_expert_judgment:
            raise ValueError("Sprint 12 ratings must remain explicitly expert judgment")
        if self.is_target_user_evidence:
            raise ValueError("expert ratings must not be labeled as target-user evidence")
        if self.real_user_behavior_validated:
            raise ValueError("expert ratings must not claim real-user behavior validation")
        if _SHA256_PATTERN.fullmatch(self.content_hash) is None:
            raise ValueError("expert rating content hash must be a lowercase SHA-256 digest")
        if self.content_hash != _hash(self.to_snapshot(include_hash=False)):
            raise ValueError("expert rating content hash is inconsistent")

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "package_version": self.package_version,
            "package_content_hash": self.package_content_hash,
            "pair_id": self.pair_id,
            "reviewer_id": self.reviewer_id,
            "candidate_a": self.candidate_a.to_snapshot(),
            "candidate_b": self.candidate_b.to_snapshot(),
            "preference": self.preference.value,
            "comments": self.comments,
            "submitted_at": self.submitted_at.isoformat(),
            "is_expert_judgment": self.is_expert_judgment,
            "is_target_user_evidence": self.is_target_user_evidence,
            "real_user_behavior_validated": self.real_user_behavior_validated,
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def create_expert_candidate_rating(
    alias: str,
    scores: tuple[ExpertRubricScore, ...],
) -> ExpertCandidateRating:
    """Create a canonically ordered public candidate rating."""
    return ExpertCandidateRating(
        alias=alias,
        scores=tuple(sorted(scores, key=lambda item: item.sort_key)),
    )


def create_expert_pair_rating(
    *,
    package_version: str,
    package_content_hash: str,
    pair_id: str,
    reviewer_id: str,
    candidate_a: ExpertCandidateRating,
    candidate_b: ExpertCandidateRating,
    preference: ExpertPreference,
    comments: str,
    submitted_at: datetime,
) -> ExpertPairRating:
    """Create one raw rating while keeping expert/user evidence categories separate."""
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "package_version": package_version,
        "package_content_hash": package_content_hash,
        "pair_id": pair_id,
        "reviewer_id": reviewer_id,
        "candidate_a": candidate_a.to_snapshot(),
        "candidate_b": candidate_b.to_snapshot(),
        "preference": preference.value,
        "comments": comments,
        "submitted_at": submitted_at.isoformat(),
        "is_expert_judgment": True,
        "is_target_user_evidence": False,
        "real_user_behavior_validated": False,
    }
    return ExpertPairRating(
        schema_version=1,
        package_version=package_version,
        package_content_hash=package_content_hash,
        pair_id=pair_id,
        reviewer_id=reviewer_id,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        preference=preference,
        comments=comments,
        submitted_at=submitted_at,
        is_expert_judgment=True,
        is_target_user_evidence=False,
        real_user_behavior_validated=False,
        content_hash=_hash(snapshot),
    )
