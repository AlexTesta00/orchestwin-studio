"""Tests for the 60-pair, two-ratings-per-pair blinded expert package."""

from __future__ import annotations

import json
from collections import Counter

from orchestwin.evaluation.expert_blinding import create_blinded_pair
from orchestwin.evaluation.expert_package import build_expert_review_package

_RUBRIC = (
    "groundedness",
    "unsupported_claims",
    "role_adherence",
    "actionability",
    "severity_appropriateness",
    "uncertainty_and_abstention_quality",
    "pairwise_preference",
)


def _pairs() -> tuple:
    pairs = []
    for index in range(60):
        pair, _ = create_blinded_pair(
            pair_id=f"PAIR-{index + 1:03d}",
            case_id=f"held-out-{index + 1:03d}",
            base_output_id=f"OUT-X-{index + 1:03d}",
            base_payload={"summary": f"Candidate X finding {index + 1}"},
            adapter_output_id=f"OUT-Y-{index + 1:03d}",
            adapter_payload={"summary": f"Candidate Y finding {index + 1}"},
            randomization_seed="s12-frozen-seed",
        )
        pairs.append(pair)
    return tuple(pairs)


def test_sixty_pairs_receive_two_balanced_ratings_across_four_reviewers() -> None:
    package = build_expert_review_package(
        package_version="s12-expert-v1",
        pairs=_pairs(),
        rubric_items=_RUBRIC,
    )

    assert len(package.pairs) == 60
    assert len(package.assignments) == 60
    assert all(len(assignment.reviewer_ids) == 2 for assignment in package.assignments)
    loads = Counter(
        reviewer for assignment in package.assignments for reviewer in assignment.reviewer_ids
    )
    assert loads == {"E1": 30, "E2": 30, "E3": 30, "E4": 30}


def test_public_expert_package_contains_no_model_identity_mapping() -> None:
    package = build_expert_review_package(
        package_version="s12-expert-v1",
        pairs=_pairs(),
        rubric_items=_RUBRIC,
    )

    public_json = json.dumps(package.to_snapshot(), sort_keys=True).lower()
    assert '"candidate_a_variant"' not in public_json
    assert '"candidate_b_variant"' not in public_json
    assert '"model_variant"' not in public_json
    assert "blindingkey" not in public_json
    assert len(package.content_hash) == 64
