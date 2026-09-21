"""Tests for raw blinded expert rating contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.evaluation.expert_ratings import (
    ExpertPreference,
    ExpertRubricScore,
    create_expert_candidate_rating,
    create_expert_pair_rating,
)

NOW = datetime(2026, 9, 7, 16, 0, tzinfo=UTC)


def _candidate(alias: str, offset: int = 0):
    return create_expert_candidate_rating(
        alias,
        (
            ExpertRubricScore("Architecture coherence", 4 + offset),
            ExpertRubricScore("Code quality", 3 + offset),
        ),
    )


def _rating():
    return create_expert_pair_rating(
        package_version="expert-package-v1",
        package_content_hash="a" * 64,
        pair_id="PAIR-001",
        reviewer_id="E1",
        candidate_a=_candidate("A"),
        candidate_b=_candidate("B", 1),
        preference=ExpertPreference.B,
        comments="Keep this comment exactly as entered.  Two spaces remain.",
        submitted_at=NOW,
    )


def test_raw_expert_rating_preserves_scores_comments_and_evidence_type() -> None:
    rating = _rating()

    assert rating.candidate_a.scores[0].rubric_item == "Architecture coherence"
    assert rating.candidate_b.scores[1].score == 4
    assert rating.comments.endswith("Two spaces remain.")
    assert "  " in rating.comments
    assert rating.is_expert_judgment is True
    assert rating.is_target_user_evidence is False
    assert rating.real_user_behavior_validated is False


def test_raw_expert_rating_rejects_out_of_range_scores() -> None:
    with pytest.raises(ValueError, match="between 1 and 5"):
        ExpertRubricScore("Code quality", 6)


def test_raw_expert_rating_rejects_target_user_or_behavior_claims() -> None:
    rating = _rating()

    with pytest.raises(ValueError, match="target-user evidence"):
        replace(rating, is_target_user_evidence=True, content_hash="0" * 64)
    with pytest.raises(ValueError, match="real-user behavior"):
        replace(rating, real_user_behavior_validated=True, content_hash="0" * 64)
