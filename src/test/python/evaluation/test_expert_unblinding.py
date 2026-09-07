"""Tests for post-collection expert-rating identity decoding."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from orchestwin.evaluation.expert_blinding import ModelVariant, create_blinded_pair
from orchestwin.evaluation.expert_package import build_expert_review_package
from orchestwin.evaluation.expert_rating_validation import validate_expert_ratings
from orchestwin.evaluation.expert_ratings import (
    ExpertPreference,
    ExpertRubricScore,
    create_expert_candidate_rating,
    create_expert_pair_rating,
)
from orchestwin.evaluation.expert_unblinding import decode_expert_ratings_after_collection

RUBRIC = ("Code quality",)
NOW = datetime(2026, 9, 7, 16, 20, tzinfo=UTC)


def _package_ratings_and_keys():
    pair_and_keys = tuple(
        create_blinded_pair(
            pair_id=f"PAIR-{index:03d}",
            case_id="web-calculator",
            base_output_id=f"base-{index}",
            base_payload={"summary": "base"},
            adapter_output_id=f"adapter-{index}",
            adapter_payload={"summary": "adapter"},
            randomization_seed="s12-unblinding",
        )
        for index in range(1, 7)
    )
    pairs = tuple(item[0] for item in pair_and_keys)
    keys = tuple(item[1] for item in pair_and_keys)
    package = build_expert_review_package(
        package_version="expert-package-v1",
        pairs=pairs,
        rubric_items=RUBRIC,
    )
    ratings = []
    for assignment in package.assignments:
        for reviewer_id in assignment.reviewer_ids:
            ratings.append(
                create_expert_pair_rating(
                    package_version=package.package_version,
                    package_content_hash=package.content_hash,
                    pair_id=assignment.pair_id,
                    reviewer_id=reviewer_id,
                    candidate_a=create_expert_candidate_rating(
                        "A",
                        (ExpertRubricScore("Code quality", 2),),
                    ),
                    candidate_b=create_expert_candidate_rating(
                        "B",
                        (ExpertRubricScore("Code quality", 5),),
                    ),
                    preference=ExpertPreference.B,
                    comments=f"raw comment {assignment.pair_id}/{reviewer_id}",
                    submitted_at=NOW,
                )
            )
    return package, tuple(ratings), keys


def test_unblinding_requires_completed_collection_and_preserves_comments() -> None:
    package, ratings, keys = _package_ratings_and_keys()
    validation = validate_expert_ratings(package, ratings, require_complete=True)

    decoded = decode_expert_ratings_after_collection(
        ratings,
        keys,
        validation=validation,
    )

    assert len(decoded) == 12
    first_key = next(key for key in keys if key.pair_id == decoded[0].pair_id)
    expected_base = 2 if first_key.candidate_a_variant is ModelVariant.BASE else 5
    assert decoded[0].base_scores[0].score == expected_base
    assert decoded[0].comments.startswith("raw comment")
    assert decoded[0].is_target_user_evidence is False
    assert decoded[0].real_user_behavior_validated is False


def test_unblinding_rejects_incomplete_validation_summary() -> None:
    package, ratings, keys = _package_ratings_and_keys()
    validation = validate_expert_ratings(package, ratings[:-1], require_complete=False)

    with pytest.raises(ValueError, match="before collection is complete"):
        decode_expert_ratings_after_collection(
            ratings[:-1],
            keys,
            validation=validation,
        )


def test_unblinding_rejects_missing_identity_key() -> None:
    package, ratings, keys = _package_ratings_and_keys()
    validation = validate_expert_ratings(package, ratings, require_complete=True)

    with pytest.raises(ValueError, match="does not exactly match"):
        decode_expert_ratings_after_collection(
            ratings,
            keys[:-1],
            validation=validation,
        )
