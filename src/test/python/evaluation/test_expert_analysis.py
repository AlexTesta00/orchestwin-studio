"""Tests for descriptive-only expert rating aggregation."""

from __future__ import annotations

from orchestwin.evaluation.expert_analysis import (
    EXPERT_EVIDENCE_DISCLAIMER,
    aggregate_decoded_expert_ratings,
)
from orchestwin.evaluation.expert_blinding import ModelVariant
from orchestwin.evaluation.expert_ratings import ExpertRubricScore
from orchestwin.evaluation.expert_unblinding import DecodedExpertPairRating


def _decoded(pair_id: str, reviewer_id: str, base: int, adapter: int, preference):
    return DecodedExpertPairRating(
        pair_id=pair_id,
        reviewer_id=reviewer_id,
        base_scores=(
            ExpertRubricScore("Architecture coherence", base),
            ExpertRubricScore("Code quality", base),
        ),
        adapter_scores=(
            ExpertRubricScore("Architecture coherence", adapter),
            ExpertRubricScore("Code quality", adapter),
        ),
        preferred_variant=preference,
        comments="raw expert comment",
        is_expert_judgment=True,
        is_target_user_evidence=False,
        real_user_behavior_validated=False,
    )


def test_expert_analysis_reports_only_paired_descriptive_results() -> None:
    ratings = (
        _decoded("PAIR-001", "E1", 3, 5, ModelVariant.ADAPTER),
        _decoded("PAIR-001", "E2", 4, 4, None),
        _decoded("PAIR-002", "E3", 5, 4, ModelVariant.BASE),
    )

    summary = aggregate_decoded_expert_ratings(ratings)

    assert summary.rating_count == 3
    assert summary.pair_count == 2
    assert summary.base_preference_count == 1
    assert summary.adapter_preference_count == 1
    assert summary.tie_count == 1
    assert summary.overall_base_mean == 4.0
    assert summary.overall_adapter_mean == 13 / 3
    assert summary.overall_mean_delta_adapter_minus_base == 1 / 3
    assert summary.disclaimer == EXPERT_EVIDENCE_DISCLAIMER
    assert summary.is_target_user_evidence is False
    assert summary.real_user_behavior_validated is False


def test_expert_analysis_rejects_mismatched_rubrics() -> None:
    first = _decoded("PAIR-001", "E1", 3, 4, ModelVariant.ADAPTER)
    mismatched = DecodedExpertPairRating(
        pair_id="PAIR-002",
        reviewer_id="E2",
        base_scores=(ExpertRubricScore("Usability", 3),),
        adapter_scores=(ExpertRubricScore("Usability", 4),),
        preferred_variant=ModelVariant.ADAPTER,
        comments="",
        is_expert_judgment=True,
        is_target_user_evidence=False,
        real_user_behavior_validated=False,
    )

    try:
        aggregate_decoded_expert_ratings((first, mismatched))
    except ValueError as error:
        assert "same ordered rubric" in str(error)
    else:
        raise AssertionError("mismatched rubrics must be rejected")
