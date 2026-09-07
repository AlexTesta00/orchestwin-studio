"""Balanced public expert-review package construction for the blinded ablation."""

from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass

from orchestwin.evaluation.expert_blinding import BlindedPair


@dataclass(frozen=True, slots=True)
class PairReviewAssignment:
    """Public assignment of one blinded pair to exactly two reviewer aliases."""

    pair_id: str
    reviewer_ids: tuple[str, str]

    def to_snapshot(self) -> dict[str, object]:
        return {"pair_id": self.pair_id, "reviewer_ids": list(self.reviewer_ids)}


@dataclass(frozen=True, slots=True)
class ExpertReviewPackage:
    """Identity-free review package; decoding keys are intentionally absent."""

    package_version: str
    pairs: tuple[BlindedPair, ...]
    assignments: tuple[PairReviewAssignment, ...]
    rubric_items: tuple[str, ...]
    content_hash: str

    def to_snapshot(self, *, include_hash: bool = True) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "package_version": self.package_version,
            "pairs": [pair.to_snapshot() for pair in self.pairs],
            "assignments": [assignment.to_snapshot() for assignment in self.assignments],
            "rubric_items": list(self.rubric_items),
        }
        if include_hash:
            snapshot["content_hash"] = self.content_hash
        return snapshot


def _hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def assign_blinded_pairs(
    pair_ids: tuple[str, ...],
    *,
    reviewer_ids: tuple[str, ...] = ("E1", "E2", "E3", "E4"),
) -> tuple[PairReviewAssignment, ...]:
    """Assign each pair to two reviewers using repeated pairwise combinations."""
    if len(reviewer_ids) < 2:
        raise ValueError("at least two reviewer aliases are required")
    combinations = tuple(itertools.combinations(reviewer_ids, 2))
    if len(pair_ids) % len(combinations) != 0:
        raise ValueError("pair count must be divisible by the number of reviewer-pair combinations")
    return tuple(
        PairReviewAssignment(pair_id=pair_id, reviewer_ids=combinations[index % len(combinations)])
        for index, pair_id in enumerate(pair_ids)
    )


def build_expert_review_package(
    *,
    package_version: str,
    pairs: tuple[BlindedPair, ...],
    rubric_items: tuple[str, ...],
    reviewer_ids: tuple[str, ...] = ("E1", "E2", "E3", "E4"),
) -> ExpertReviewPackage:
    """Build a deterministic public package without any variant-decoding material."""
    if not pairs:
        raise ValueError("expert package must contain at least one blinded pair")
    pair_ids = tuple(pair.pair_id for pair in pairs)
    if len(pair_ids) != len(set(pair_ids)):
        raise ValueError("blinded pair IDs must be unique")
    if not rubric_items or len(rubric_items) != len(set(rubric_items)):
        raise ValueError("rubric items must be non-empty and unique")
    assignments = assign_blinded_pairs(pair_ids, reviewer_ids=reviewer_ids)
    snapshot = {
        "package_version": package_version,
        "pairs": [pair.to_snapshot() for pair in pairs],
        "assignments": [assignment.to_snapshot() for assignment in assignments],
        "rubric_items": list(rubric_items),
    }
    return ExpertReviewPackage(
        package_version=package_version,
        pairs=pairs,
        assignments=assignments,
        rubric_items=rubric_items,
        content_hash=_hash(snapshot),
    )
