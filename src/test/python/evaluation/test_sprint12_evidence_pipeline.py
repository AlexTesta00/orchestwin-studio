"""Cross-cutting tests for the frozen Sprint 12 evidence pipeline."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.pipeline_validation import verify_sprint12_evidence_pipeline

REPO_ROOT = Path(__file__).resolve().parents[4]


def test_sprint12_pipeline_freezes_case_and_expert_evidence_boundaries() -> None:
    summary = verify_sprint12_evidence_pipeline(REPO_ROOT)

    assert summary.formal_case_ids == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert summary.case_run_contract_version == 1
    assert summary.expert_pair_count == 60
    assert summary.expert_rating_count == 120
    assert summary.reviewer_count == 4
    assert summary.ratings_per_reviewer == 30
    assert summary.mobile_platforms_in_scope is False
    assert summary.frozen_training_feedback_allowed is False
    assert summary.expert_judgment_is_target_user_evidence is False
    assert summary.real_user_behavior_validated is False
    assert summary.empirical_user_evidence_created is False
