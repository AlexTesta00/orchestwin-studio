"""Tests for no-selection comparison reports over validated live model-spike evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from model_spike_test_support import run_fake_model_spike_bundle

from orchestwin.training.benchmark_suite_files import (
    load_frozen_evaluator_benchmark_suite,
)
from orchestwin.training.model_candidate_matrix_files import (
    load_frozen_model_candidate_matrix,
)
from orchestwin.training.model_spike_reports import (
    MODEL_SPIKE_METHODOLOGICAL_NOTICE,
    MODEL_SPIKE_PENDING_EVIDENCE,
    ModelSpikeReportError,
    ModelSpikeSelectionReadiness,
    ModelSpikeThresholdStatus,
    create_model_spike_comparison_report,
    load_model_spike_comparison_report,
    write_model_spike_comparison_report,
)
from orchestwin.training.model_spike_requests import (
    load_model_spike_execution_plan,
    sha256_file,
)
from orchestwin.training.model_spike_results import (
    load_validated_model_spike_bundle,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 4, 15, 30, tzinfo=UTC)


def _report(tmp_path: Path):
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    plan = load_model_spike_execution_plan(plan_path)
    bundle = load_validated_model_spike_bundle(
        plan_path=plan_path,
        batch_result_path=batch_path,
    )
    return create_model_spike_comparison_report(
        plan=plan,
        plan_file_sha256=sha256_file(plan_path),
        bundle=bundle,
        matrix=load_frozen_model_candidate_matrix(REPOSITORY_ROOT),
        suite=load_frozen_evaluator_benchmark_suite(REPOSITORY_ROOT),
        created_at=NOW,
    )


def test_report_compares_every_frozen_candidate_without_selecting_one(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)

    assert report.selection_status == "NO_MODEL_SELECTED"
    assert report.ready_for_owner_selection is False
    assert report.pending_evidence == MODEL_SPIKE_PENDING_EVIDENCE
    assert report.methodological_notice == MODEL_SPIKE_METHODOLOGICAL_NOTICE
    assert len(report.candidates) == 3
    assert {item.candidate_id for item in report.candidates} == {
        "model-candidate-granite-3-3-2b-instruct",
        "model-candidate-qwen3-4b-instruct-2507",
        "model-candidate-smollm3-3b",
    }
    assert all(item.license_review_status == "REVIEW_REQUIRED" for item in report.candidates)
    assert all(item.qlora_smoke_status == "NOT_RUN" for item in report.candidates)
    assert all(item.adapter_export_load_status == "NOT_RUN" for item in report.candidates)
    assert all(item.serving_validation_status == "NOT_RUN" for item in report.candidates)


def test_report_preserves_overall_language_and_resource_measurements(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)

    for candidate in report.candidates:
        assert candidate.task_count == 1
        assert candidate.successful_task_count == 1
        assert candidate.schema_invalid_task_count == 0
        assert {item.language for item in candidate.language_metrics} == {"en"}
        schema_metric = next(
            item for item in candidate.benchmark_metrics if item.metric_id == "schema_valid_rate"
        )
        assert schema_metric.value == 1.0
        assert candidate.resource_summary is not None
        assert candidate.resource_summary.peak_gpu_memory_mb == 1000
        assert candidate.resource_summary.mean_latency_milliseconds == 10.0


def test_report_marks_adapter_threshold_pending_and_never_claims_selection_readiness(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)

    for candidate in report.candidates:
        adapter = next(
            item
            for item in candidate.threshold_observations
            if item.metric_id == "adapter_export_load"
        )
        assert adapter.status is ModelSpikeThresholdStatus.NOT_OBSERVED
        assert candidate.benchmark_thresholds_passed is False
        assert (
            candidate.selection_readiness is ModelSpikeSelectionReadiness.BENCHMARK_REVIEW_REQUIRED
        )


def test_report_round_trips_canonical_json_and_rejects_noncanonical_bytes(
    tmp_path: Path,
) -> None:
    report = _report(tmp_path)
    output = tmp_path / "comparison.json"

    write_model_spike_comparison_report(output, report)
    loaded = load_model_spike_comparison_report(output)

    assert loaded == report
    output.write_text(output.read_text() + "\n", encoding="utf-8")
    with pytest.raises(ModelSpikeReportError, match="canonical JSON"):
        load_model_spike_comparison_report(output)


def test_report_rejects_mismatched_plan_file_identity(tmp_path: Path) -> None:
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    plan = load_model_spike_execution_plan(plan_path)
    bundle = load_validated_model_spike_bundle(
        plan_path=plan_path,
        batch_result_path=batch_path,
    )

    with pytest.raises(ModelSpikeReportError, match="plan file digest differs"):
        create_model_spike_comparison_report(
            plan=plan,
            plan_file_sha256="0" * 64,
            bundle=bundle,
            matrix=load_frozen_model_candidate_matrix(REPOSITORY_ROOT),
            suite=load_frozen_evaluator_benchmark_suite(REPOSITORY_ROOT),
            created_at=NOW,
        )
