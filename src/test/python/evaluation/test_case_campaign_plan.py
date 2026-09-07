"""Tests for generic Sprint 12 formal case campaign planning."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_campaign import (
    CaseCampaignPhase,
    build_formal_case_campaign_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_COMMIT = "1" * 40


def test_campaign_plan_routes_distinct_cases_through_generic_profiles() -> None:
    plan = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)

    assert tuple(case.case_id for case in plan.cases) == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert tuple(case.execution_profile for case in plan.cases) == (
        "WEB_STATIC",
        "WEB_VUE_NODE",
        "WEB_VUE_NODE",
    )
    assert plan.phases == tuple(CaseCampaignPhase)
    assert plan.actual_files_only is True
    assert plan.observed_measurements_only is True
    assert plan.owner_gates_must_not_be_bypassed is True
    assert plan.real_user_behavior_validated is False
    assert plan.empirical_user_evidence_created is False


def test_campaign_plan_is_deterministic_for_same_frozen_inputs() -> None:
    first = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)
    second = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)

    assert first == second
    assert first.content_hash == second.content_hash
    assert all(case.definition_path.startswith("experiments/case-studies/") for case in first.cases)
