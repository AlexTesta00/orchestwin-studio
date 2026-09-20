"""Tests for pre-defined reproducible case-study metric formulas."""

from __future__ import annotations

import pytest

from orchestwin.evaluation.case_metrics import (
    CaseStudyMeasurement,
    aggregate_case_study_metrics,
)


def _measurement(case_id: str, *, tests_passed: int, repair_attempts: int) -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id=case_id,
        gates_completed=6,
        gates_total=6,
        artifacts_completed=8,
        artifacts_total=8,
        requirements_satisfied=5,
        requirements_total=5,
        criteria_satisfied=7,
        criteria_total=8,
        traceability_links_present=10,
        traceability_links_required=10,
        tests_passed=tests_passed,
        tests_total=10,
        repair_successes=repair_attempts,
        repair_attempts=repair_attempts,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=120.0,
        model_calls=12,
        input_tokens=1_000,
        output_tokens=500,
        estimated_cost_usd=0.25,
    )


def test_metric_snapshot_preserves_raw_formulas_and_a_deterministic_hash() -> None:
    measurement = _measurement("web-calculator", tests_passed=9, repair_attempts=0)

    first = measurement.metric_snapshot()
    second = measurement.metric_snapshot()

    assert first == second
    assert first["gate_completion_ratio"] == 1.0
    assert first["acceptance_criterion_satisfaction_ratio"] == 7 / 8
    assert first["test_pass_ratio"] == 0.9
    assert first["repair_success_ratio"] is None
    assert len(first["content_hash"]) == 64


def test_aggregate_metrics_use_available_ratios_without_fabricating_missing_repairs() -> None:
    result = aggregate_case_study_metrics(
        (
            _measurement("web-calculator", tests_passed=9, repair_attempts=0),
            _measurement("hotel-management-web", tests_passed=8, repair_attempts=2),
        )
    )

    assert result.case_count == 2
    assert result.mean_test_pass_ratio == pytest.approx(0.85)
    assert result.mean_repair_success_ratio == 1.0
    assert result.build_success_count == 2
    assert result.total_model_calls == 24
    assert result.total_estimated_cost_usd == pytest.approx(0.5)


def test_measurement_rejects_impossible_completed_counts() -> None:
    with pytest.raises(ValueError, match="test completed count"):
        CaseStudyMeasurement(
            case_id="invalid",
            gates_completed=1,
            gates_total=1,
            artifacts_completed=1,
            artifacts_total=1,
            requirements_satisfied=1,
            requirements_total=1,
            criteria_satisfied=1,
            criteria_total=1,
            traceability_links_present=1,
            traceability_links_required=1,
            tests_passed=2,
            tests_total=1,
            repair_successes=0,
            repair_attempts=0,
            build_succeeded=True,
            final_runtime_succeeded=True,
            elapsed_seconds=0.0,
            model_calls=0,
            input_tokens=0,
            output_tokens=0,
            estimated_cost_usd=0.0,
        )
