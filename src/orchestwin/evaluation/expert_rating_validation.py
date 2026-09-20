"""Integrity validation for blinded expert ratings before identity decoding."""

from __future__ import annotations

from dataclasses import dataclass

from orchestwin.evaluation.expert_package import ExpertReviewPackage
from orchestwin.evaluation.expert_ratings import ExpertPairRating


@dataclass(frozen=True, slots=True)
class ExpertRatingValidationSummary:
    """Assignment and completeness summary with no base/adapter identity information."""

    package_version: str
    package_content_hash: str
    rating_count: int
    pair_count: int
    reviewer_counts: tuple[tuple[str, int], ...]
    complete: bool
    is_expert_judgment: bool
    is_target_user_evidence: bool
    real_user_behavior_validated: bool

    def to_snapshot(self) -> dict[str, object]:
        return {
            "package_version": self.package_version,
            "package_content_hash": self.package_content_hash,
            "rating_count": self.rating_count,
            "pair_count": self.pair_count,
            "reviewer_counts": [
                {"reviewer_id": reviewer_id, "rating_count": count}
                for reviewer_id, count in self.reviewer_counts
            ],
            "complete": self.complete,
            "is_expert_judgment": self.is_expert_judgment,
            "is_target_user_evidence": self.is_target_user_evidence,
            "real_user_behavior_validated": self.real_user_behavior_validated,
        }


def validate_expert_ratings(
    package: ExpertReviewPackage,
    ratings: tuple[ExpertPairRating, ...],
    *,
    require_complete: bool,
) -> ExpertRatingValidationSummary:
    """Validate pair assignments and rubric completeness without using the identity key."""
    pair_by_id = {pair.pair_id: pair for pair in package.pairs}
    assignment_by_id = {assignment.pair_id: assignment for assignment in package.assignments}
    expected_reviews = {
        (assignment.pair_id, reviewer_id)
        for assignment in package.assignments
        for reviewer_id in assignment.reviewer_ids
    }
    observed_reviews: set[tuple[str, str]] = set()
    reviewer_counts: dict[str, int] = {}
    rubric_items = set(package.rubric_items)

    for rating in ratings:
        if rating.package_version != package.package_version:
            raise ValueError("expert rating package version does not match review package")
        if rating.package_content_hash != package.content_hash:
            raise ValueError("expert rating package hash does not match review package")
        if rating.pair_id not in pair_by_id:
            raise ValueError(f"expert rating references unknown pair: {rating.pair_id}")
        assignment = assignment_by_id[rating.pair_id]
        if rating.reviewer_id not in assignment.reviewer_ids:
            raise ValueError("expert rating reviewer is not assigned to the referenced pair")
        identity = (rating.pair_id, rating.reviewer_id)
        if identity in observed_reviews:
            raise ValueError("duplicate expert rating for the same pair and reviewer")
        observed_reviews.add(identity)
        reviewer_counts[rating.reviewer_id] = reviewer_counts.get(rating.reviewer_id, 0) + 1
        for candidate in (rating.candidate_a, rating.candidate_b):
            observed_items = {score.rubric_item for score in candidate.scores}
            if observed_items != rubric_items:
                raise ValueError("expert rating rubric items do not match the frozen package")

    complete = observed_reviews == expected_reviews
    if require_complete and not complete:
        missing = expected_reviews - observed_reviews
        extra = observed_reviews - expected_reviews
        raise ValueError(
            "expert rating collection is incomplete or inconsistent: "
            f"missing={len(missing)}, extra={len(extra)}"
        )
    return ExpertRatingValidationSummary(
        package_version=package.package_version,
        package_content_hash=package.content_hash,
        rating_count=len(ratings),
        pair_count=len({rating.pair_id for rating in ratings}),
        reviewer_counts=tuple(sorted(reviewer_counts.items())),
        complete=complete,
        is_expert_judgment=True,
        is_target_user_evidence=False,
        real_user_behavior_validated=False,
    )
