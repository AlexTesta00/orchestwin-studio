"""A planning check must reject drift and never manufacture study readiness."""

import json
from pathlib import Path

import pytest

from orchestwin.evaluation.thesis_plan import verify_thesis_evaluation_plan

ROOT = Path(__file__).resolve().parents[4]
PLAN = ROOT / "experiments/case-studies/thesis-evaluation-plan-20260920.json"


def copied_inputs(tmp_path):
    plan = json.loads(PLAN.read_bytes())
    for item in plan["pinned_files"]:
        target = tmp_path / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / item["path"]).read_bytes())
    copied_plan = tmp_path / "plan.json"
    copied_plan.write_text(json.dumps(plan), encoding="utf-8")
    return plan, copied_plan


def test_repository_plan_is_coherent_but_never_claims_participants_or_execution():
    receipt = verify_thesis_evaluation_plan(ROOT, PLAN)
    assert receipt["pinned_files_verified"] == 15
    assert receipt["planned_expert_rating_count"] == 120
    assert receipt["planned_reviewer_counts"] == {"E1": 30, "E2": 30, "E3": 30, "E4": 30}
    assert receipt["is_observed_result"] is False
    assert receipt["human_participation_verified"] is False
    assert receipt["formal_execution_readiness_assessed"] is False


def test_changed_frozen_case_bytes_are_rejected_before_case_selection(tmp_path):
    plan, path = copied_inputs(tmp_path)
    case_path = tmp_path / plan["formal_cases"][0]["definition_path"]
    case_path.write_bytes(case_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="pinned thesis input changed"):
        verify_thesis_evaluation_plan(tmp_path, path)


@pytest.mark.parametrize(
    "mutation", ["escape", "duplicate", "result_claim", "rubric", "reviewers", "metric"]
)
def test_unbound_or_misleading_planning_changes_fail_closed(tmp_path, mutation):
    plan, path = copied_inputs(tmp_path)
    if mutation == "escape":
        plan["pinned_files"][0]["path"] = "../outside.json"
    elif mutation == "duplicate":
        plan["pinned_files"].append(plan["pinned_files"][0])
    elif mutation == "result_claim":
        plan["is_observed_result"] = True
    elif mutation == "rubric":
        plan["expert_review"]["rubric_items"] = ["Invented overall score"]
    elif mutation == "reviewers":
        plan["expert_review"]["ratings_per_reviewer"] = 15
    else:
        plan["metric_collection"]["required_raw_fields"] = []
    path.write_text(json.dumps(plan), encoding="utf-8")
    with pytest.raises(ValueError):
        verify_thesis_evaluation_plan(tmp_path, path)
