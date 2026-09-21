"""Tests for formal case execution preflight decisions."""

from __future__ import annotations

from pathlib import Path

from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_preflight import (
    CaseExecutionHostState,
    evaluate_case_execution_readiness,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_COMMIT = "2" * 40
BRANCH = "sprint/12-case-studies-expert-evaluation"


def test_preflight_accepts_clean_frozen_state_with_required_profiles() -> None:
    plan = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)
    host = CaseExecutionHostState(
        platform_commit=PLATFORM_COMMIT,
        branch=BRANCH,
        worktree_clean=True,
        available_execution_profiles=("WEB_STATIC", "WEB_VUE_NODE"),
    )

    readiness = evaluate_case_execution_readiness(plan, host, expected_branch=BRANCH)

    assert readiness.ready is True
    assert readiness.blockers == ()
    assert readiness.required_profiles == ("WEB_STATIC", "WEB_VUE_NODE")


def test_preflight_blocks_drift_dirty_tree_and_missing_profile() -> None:
    plan = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)
    host = CaseExecutionHostState(
        platform_commit="3" * 40,
        branch="develop",
        worktree_clean=False,
        available_execution_profiles=("WEB_STATIC",),
    )

    readiness = evaluate_case_execution_readiness(plan, host, expected_branch=BRANCH)

    assert readiness.ready is False
    assert readiness.blockers == (
        "platform commit differs from the frozen campaign plan",
        "formal case execution is on an unexpected Git branch",
        "formal case execution requires a clean working tree",
        "missing execution profiles: WEB_VUE_NODE",
    )
