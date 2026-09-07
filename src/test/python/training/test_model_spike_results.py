"""Tests for strict immutable live model-spike result-bundle validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from model_spike_test_support import run_fake_model_spike_bundle

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.model_spike_results import (
    ModelSpikeResultError,
    ValidatedModelSpikeStatus,
    load_validated_model_spike_bundle,
)


def test_loader_validates_complete_batch_results_and_referenced_artifacts(
    tmp_path: Path,
) -> None:
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)

    bundle = load_validated_model_spike_bundle(
        plan_path=plan_path,
        batch_result_path=batch_path,
    )

    assert bundle.validation_complete is True
    assert bundle.all_benchmarks_complete is True
    assert len(bundle.runs) == 3
    assert all(run.status is ValidatedModelSpikeStatus.BENCHMARK_COMPLETED for run in bundle.runs)
    assert all(run.task_count == 1 for run in bundle.runs)
    assert all(run.schema_invalid_task_count == 0 for run in bundle.runs)
    assert all(run.resource_summary is not None for run in bundle.runs)
    assert all(
        run.resource_summary is not None and run.resource_summary.peak_gpu_memory_mb == 1000
        for run in bundle.runs
    )
    assert all(
        {metric.language for metric in run.language_metrics} == {"en"} for run in bundle.runs
    )
    assert all(
        next(
            metric.value
            for metric in run.language_metrics
            if metric.metric_id == "schema_valid_rate"
        )
        == 1.0
        for run in bundle.runs
    )


def test_loader_detects_tampered_task_artifact(tmp_path: Path) -> None:
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    first_run = json.loads(batch_path.read_text())["processes"][0]
    result_path = batch_path.parent / first_run["result_reference"]
    raw_path = result_path.parent / "raw" / "bench-en-001-r01.txt"
    raw_path.write_text("tampered")

    with pytest.raises(ModelSpikeResultError, match="task artifact digest changed"):
        load_validated_model_spike_bundle(
            plan_path=plan_path,
            batch_result_path=batch_path,
        )


def test_loader_detects_cross_candidate_result_substitution(tmp_path: Path) -> None:
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    batch = json.loads(batch_path.read_text())
    first = batch["processes"][0]
    result_path = batch_path.parent / first["result_reference"]
    result = json.loads(result_path.read_text())
    result["candidate_id"] = "model-candidate-substituted"
    result_without_hash = dict(result)
    result_without_hash.pop("result_sha256")
    result["result_sha256"] = snapshot_content_hash(result_without_hash)
    result_path.write_text(canonical_json(result))
    first["result_file_sha256"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    process_path = result_path.parent / "process.json"
    process = json.loads(process_path.read_text())
    process["result_file_sha256"] = first["result_file_sha256"]
    process_without_hash = dict(process)
    process_without_hash.pop("content_hash")
    process["content_hash"] = snapshot_content_hash(process_without_hash)
    process_path.write_text(canonical_json(process))
    batch["processes"][0] = process
    batch_without_hash = dict(batch)
    batch_without_hash.pop("content_hash")
    batch["content_hash"] = snapshot_content_hash(batch_without_hash)
    batch_path.write_text(canonical_json(batch))

    with pytest.raises(ModelSpikeResultError, match="candidate differs"):
        load_validated_model_spike_bundle(
            plan_path=plan_path,
            batch_result_path=batch_path,
        )


def test_loader_rejects_noncanonical_batch_json(tmp_path: Path) -> None:
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    payload = json.loads(batch_path.read_text())
    batch_path.write_text(json.dumps(payload, indent=2))

    with pytest.raises(ModelSpikeResultError, match="canonical JSON"):
        load_validated_model_spike_bundle(
            plan_path=plan_path,
            batch_result_path=batch_path,
        )
