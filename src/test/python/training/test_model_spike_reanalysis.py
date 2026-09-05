"""File-backed regressions for versioned, offline and non-destructive reanalysis."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from model_spike_test_support import run_fake_model_spike_bundle

from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import MeasurementV2Error
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmarking import (
    create_benchmark_generation_request,
    evaluator_benchmark_output_schema,
)
from orchestwin.training.model_spike_reanalysis import (
    reanalyze_model_spike_v2,
    write_reanalysis_report_v2,
)

ROOT = Path(__file__).resolve().parents[4]
CREATED_AT = datetime(2026, 9, 5, tzinfo=UTC)


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, payload, *, hash_field=None):
    if hash_field is not None:
        payload.pop(hash_field, None)
        payload[hash_field] = snapshot_content_hash(payload)
    path.write_bytes(canonical_json(payload).encode("utf-8"))


def update_result(batch_path, index, result, result_path):
    write_json(result_path, result, hash_field="result_sha256")
    batch = json.loads(batch_path.read_bytes())
    process = batch["processes"][index]
    process.update(result_file_sha256=digest_file(result_path), status="FAILED", exit_code=27)
    write_json(result_path.parent / "process.json", process, hash_field="content_hash")
    batch["all_succeeded"] = False
    write_json(batch_path, batch, hash_field="content_hash")


def fixture(tmp_path):
    """Represent one real task per candidate, with the other eleven not observed."""
    plan_path, batch_path = run_fake_model_spike_bundle(tmp_path)
    task = load_frozen_evaluator_benchmark_suite(ROOT).tasks[0]
    schema = evaluator_benchmark_output_schema()
    batch = json.loads(batch_path.read_bytes())
    for index, process in enumerate(batch["processes"]):
        request = json.loads((plan_path.parent / process["request_reference"]).read_bytes())
        result_path = batch_path.parent / process["result_reference"]
        result = json.loads(result_path.read_bytes())
        observation = result["tasks"][0]
        identity = ModelRuntimeIdentity(
            provider_id="fake",
            runtime_id="test",
            base_model_repository=request["model_repository"],
            base_model_revision=request["model_revision"],
            tokenizer_revision=request["tokenizer_revision"],
            configuration_sha256="a" * 64,
        )
        generation_request = create_benchmark_generation_request(
            run_id=UUID(request["run_id"]),
            task=task,
            model_identity=identity,
        )
        user = {
            "task_id": task.task_id,
            "allowed_evidence_refs": list(task.expected.allowed_evidence_refs),
            "input": json.loads(generation_request.input_payload_json),
            "output_schema": json.loads(schema.canonical_schema_json),
        }
        prompt = {
            "task_id": task.task_id,
            "task_content_hash": task.content_hash,
            "repetition": 1,
            "output_schema_sha256": schema.content_hash,
            "messages": [
                {"role": "system", "content": generation_request.system_instruction},
                {"role": "user", "content": canonical_json(user)},
            ],
        }
        payload = {
            "overall_summary": "Synthetic evaluator feedback.",
            "abstained": False,
            "evidence_gaps": [],
            "findings": [
                {
                    "finding_id": "F-1",
                    "summary": "Issue",
                    "rationale": "Supplied evidence.",
                    "criterion": "accessibility",
                    "severity": "major",
                    "epistemic_status": "MODEL_INFERRED",
                    "evidence_refs": [task.evidence[0].reference_id],
                    "recommended_action": "Validate with a person.",
                    "requires_human_validation": True,
                }
            ],
        }
        prompt_path = result_path.parent / observation["prompt_reference"]
        write_json(prompt_path, prompt)
        raw_path = result_path.parent / observation["raw_output_reference"]
        raw_path.write_bytes(canonical_json(payload).encode())
        structured = result_path.parent / observation["structured_output_reference"]
        write_json(structured, payload)
        observation.update(
            status="SCHEMA_VALID",
            task_content_hash=task.content_hash,
            prompt_sha256=digest_file(prompt_path),
            raw_output_sha256=digest_file(raw_path),
            structured_output_sha256=digest_file(structured),
        )
        observation.pop("content_hash")
        observation["content_hash"] = snapshot_content_hash(observation)
        result["status"] = "PARTIAL"
        result["benchmark"].update(
            task_count=12,
            expected_measurement_count=12,
            observed_measurement_count=1,
            complete=False,
        )
        result["model_identity"] = identity.to_snapshot()
        update_result(batch_path, index, result, result_path)
    return plan_path, batch_path


def analyze(plan, batch):
    return reanalyze_model_spike_v2(
        repository_root=ROOT,
        plan_path=plan,
        batch_result_path=batch,
        created_at=CREATED_AT,
    )


def tree_hashes(tmp_path):
    return {
        path.relative_to(tmp_path).as_posix(): digest_file(path)
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


def test_reanalysis_counts_generation_and_preserves_v1_metrics_and_all_input_bytes(tmp_path):
    plan, batch = fixture(tmp_path)
    before = tree_hashes(tmp_path)
    first = analyze(plan, batch)
    second = analyze(plan, batch)
    assert first == second
    assert tree_hashes(tmp_path) == before
    assert first["schema_version"] == 2
    assert first["post_hoc"] is True
    assert first["live_inference_executed"] is False
    assert first["original_reports_replaced"] is False
    assert first["ready_for_owner_selection"] is False
    for candidate in first["candidates"]:
        assert candidate["summary"]["successful_generation_count"] == 1
        assert candidate["summary"]["unobserved_generation_count"] == 11
        assert candidate["summary"]["json_schema_valid_count"] == 1
        assert candidate["legacy_v1"]["successful_task_count_as_originally_computed"] == 0
        assert candidate["by_language"]["en"]["successful_generation_count"] == 1
        assert candidate["by_language"]["it"]["successful_generation_count"] == 0
        metric = candidate["by_language"]["it"]["semantic_metrics"][
            "unsupported_finding_heuristic_rate"
        ]
        assert metric["value"] is None


def test_raw_file_tampering_is_rejected(tmp_path):
    plan, batch = fixture(tmp_path)
    raw = next(batch.parent.glob("runs/*/raw/*.txt"))
    raw.write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="digest changed"):
        analyze(plan, batch)


@pytest.mark.parametrize("field", ["task_content_hash", "language", "repetition"])
def test_rehashed_but_wrong_task_identity_is_rejected(tmp_path, field):
    plan, batch = fixture(tmp_path)
    result_path = next(batch.parent.glob("runs/*/result.json"))
    result = json.loads(result_path.read_bytes())
    result["tasks"][0][field] = 99 if field == "repetition" else "incorrect"
    task = result["tasks"][0]
    task.pop("content_hash")
    task["content_hash"] = snapshot_content_hash(task)
    index = next(
        i
        for i, item in enumerate(json.loads(batch.read_bytes())["processes"])
        if batch.parent / item["result_reference"] == result_path
    )
    update_result(batch, index, result, result_path)
    with pytest.raises(ValueError):
        analyze(plan, batch)


def test_wrong_resource_status_is_not_counted_as_success(tmp_path):
    plan, batch = fixture(tmp_path)
    result_path = next(batch.parent.glob("runs/*/result.json"))
    result = json.loads(result_path.read_bytes())
    observation = result["tasks"][0]
    observation["resource_measurement"]["status"] = "FAILED"
    observation.pop("content_hash")
    observation["content_hash"] = snapshot_content_hash(observation)
    index = next(
        i
        for i, item in enumerate(json.loads(batch.read_bytes())["processes"])
        if batch.parent / item["result_reference"] == result_path
    )
    update_result(batch, index, result, result_path)
    with pytest.raises(MeasurementV2Error, match="status disagree"):
        analyze(plan, batch)


def test_complete_result_with_unobserved_tasks_is_rejected(tmp_path):
    plan, batch = fixture(tmp_path)
    result_path = next(batch.parent.glob("runs/*/result.json"))
    result = json.loads(result_path.read_bytes())
    result["status"] = "COMPLETED"
    index = next(
        i
        for i, item in enumerate(json.loads(batch.read_bytes())["processes"])
        if batch.parent / item["result_reference"] == result_path
    )
    update_result(batch, index, result, result_path)
    with pytest.raises(MeasurementV2Error, match="missing expected observations"):
        analyze(plan, batch)


def test_symlink_input_is_rejected_before_following_it(tmp_path):
    plan, batch = fixture(tmp_path)
    target = plan.parent / "link.json"
    try:
        target.symlink_to(plan)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    with pytest.raises(MeasurementV2Error, match="symbolic links"):
        analyze(plan, batch)


def test_report_cannot_overwrite_or_write_into_input_tree(tmp_path):
    plan, batch = fixture(tmp_path)
    report = analyze(plan, batch)
    protected = (plan.parent, batch.parent)
    with pytest.raises(MeasurementV2Error, match="protected input"):
        write_reanalysis_report_v2(
            path=batch.parent / "new.json",
            report=report,
            protected_roots=protected,
        )
    target = tmp_path / "analysis-v2.json"
    write_reanalysis_report_v2(path=target, report=report, protected_roots=protected)
    original_bytes = target.read_bytes()
    with pytest.raises(MeasurementV2Error, match="overwrite"):
        write_reanalysis_report_v2(path=target, report=report, protected_roots=protected)
    assert target.read_bytes() == original_bytes
    assert json.loads(original_bytes) == report


def test_cli_runs_with_only_stdlib_and_no_site_packages(tmp_path):
    plan, batch = fixture(tmp_path)
    target = tmp_path / "cli-analysis.json"
    cli = ROOT / "environments/training/reanalyze_model_spike.py"
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            str(cli),
            "--plan",
            str(plan),
            "--batch-result",
            str(batch),
            "--created-at",
            CREATED_AT.isoformat(),
            "--output",
            str(target),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "offline_model_spike_reanalysis_v2: PASSED" in completed.stdout
    assert json.loads(target.read_bytes()) == analyze(plan, batch)


def test_cli_help_does_not_need_dependencies_or_write_files(tmp_path):
    cli = ROOT / "environments/training/reanalyze_model_spike.py"
    completed = subprocess.run(
        [sys.executable, "-I", "-S", str(cli), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0
    assert not list(tmp_path.iterdir())


def test_naive_timestamp_is_rejected(tmp_path):
    plan, batch = fixture(tmp_path)
    with pytest.raises(MeasurementV2Error, match="timezone-aware"):
        reanalyze_model_spike_v2(
            repository_root=ROOT,
            plan_path=plan,
            batch_result_path=batch,
            created_at=datetime(2026, 9, 5),
        )
