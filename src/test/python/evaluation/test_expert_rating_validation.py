"""Tests for blinded expert rating assignment integrity."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from orchestwin.evaluation.expert_blinding import create_blinded_pair
from orchestwin.evaluation.expert_package import build_expert_review_package
from orchestwin.evaluation.expert_rating_validation import validate_expert_ratings
from orchestwin.evaluation.expert_ratings import (
    ExpertPreference,
    ExpertRubricScore,
    create_expert_candidate_rating,
    create_expert_pair_rating,
)

RUBRIC = ("Architecture coherence", "Code quality")
NOW = datetime(2026, 9, 7, 16, 10, tzinfo=UTC)


def _package():
    pairs = tuple(
        create_blinded_pair(
            pair_id=f"PAIR-{index:03d}",
            case_id="web-calculator",
            base_output_id=f"base-{index}",
            base_payload={"summary": f"base {index}"},
            adapter_output_id=f"adapter-{index}",
            adapter_payload={"summary": f"adapter {index}"},
            randomization_seed="s12-rating-validation",
        )[0]
        for index in range(1, 7)
    )
    return build_expert_review_package(
        package_version="expert-package-v1",
        pairs=pairs,
        rubric_items=RUBRIC,
    )


def _candidate(alias: str, value: int):
    return create_expert_candidate_rating(
        alias,
        tuple(ExpertRubricScore(item, value) for item in RUBRIC),
    )


def _all_ratings(package):
    ratings = []
    for assignment in package.assignments:
        for reviewer_id in assignment.reviewer_ids:
            ratings.append(
                create_expert_pair_rating(
                    package_version=package.package_version,
                    package_content_hash=package.content_hash,
                    pair_id=assignment.pair_id,
                    reviewer_id=reviewer_id,
                    candidate_a=_candidate("A", 3),
                    candidate_b=_candidate("B", 4),
                    preference=ExpertPreference.B,
                    comments="",
                    submitted_at=NOW,
                )
            )
    return tuple(ratings)


def test_complete_rating_collection_matches_every_public_assignment() -> None:
    package = _package()
    ratings = _all_ratings(package)

    summary = validate_expert_ratings(package, ratings, require_complete=True)

    assert summary.complete is True
    assert summary.rating_count == 12
    assert summary.pair_count == 6
    assert summary.reviewer_counts == (("E1", 3), ("E2", 3), ("E3", 3), ("E4", 3))
    assert summary.is_target_user_evidence is False
    assert summary.real_user_behavior_validated is False


def test_incomplete_collection_cannot_be_marked_complete() -> None:
    package = _package()
    ratings = _all_ratings(package)[:-1]

    with pytest.raises(ValueError, match="collection is incomplete"):
        validate_expert_ratings(package, ratings, require_complete=True)


def test_unassigned_reviewer_is_rejected() -> None:
    package = _package()
    first = package.assignments[0]
    assigned = set(first.reviewer_ids)
    reviewer = next(item for item in ("E1", "E2", "E3", "E4") if item not in assigned)
    rating = create_expert_pair_rating(
        package_version=package.package_version,
        package_content_hash=package.content_hash,
        pair_id=first.pair_id,
        reviewer_id=reviewer,
        candidate_a=_candidate("A", 3),
        candidate_b=_candidate("B", 4),
        preference=ExpertPreference.B,
        comments="",
        submitted_at=NOW,
    )

    with pytest.raises(ValueError, match="not assigned"):
        validate_expert_ratings(package, (rating,), require_complete=False)
