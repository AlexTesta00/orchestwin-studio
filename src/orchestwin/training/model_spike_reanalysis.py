"""Read-only, versioned remeasurement of archived model-spike outputs.

The v1 validator and reports are not changed. This overlay separates structural
and task-rule observations and retains the old measurements alongside them.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_measurement_v2 import (
    MeasurementV2Error,
    measure_evaluator_output_v2,
    measurement_policy_snapshot,
    strict_json_loads,
    summarize_measurements_v2,
)
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmark_tasks import EvaluatorBenchmarkTask
from orchestwin.training.benchmarking import evaluator_benchmark_output_schema
from orchestwin.training.model_candidate_matrix_files import load_frozen_model_candidate_matrix
from orchestwin.training.model_spike_requests import load_model_spike_execution_plan
from orchestwin.training.model_spike_results import load_validated_model_spike_bundle

_MAX_FILE_BYTES = 128_000_000
_MAX_TREE_BYTES = 256_000_000
_MAX_FILES = 4096
_SUCCESS_TASK_STATUSES = {"SCHEMA_VALID", "SCHEMA_INVALID", "INVALID_JSON", "SUCCEEDED"}


def _regular_path(path: Path) -> Path:
    path = Path(os.path.abspath(path))
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise MeasurementV2Error(f"symbolic links are not accepted: {component.name}")
    if not path.is_file() or path.stat().st_size > _MAX_FILE_BYTES:
        raise MeasurementV2Error(f"expected a bounded regular file: {path.name}")
    return path


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular_path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_file(path: Path) -> dict[str, object]:
    try:
        value = strict_json_loads(_regular_path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        raise MeasurementV2Error(f"invalid JSON evidence: {path.name}") from error
    if not isinstance(value, dict):
        raise MeasurementV2Error(f"evidence must contain a JSON object: {path.name}")
    return value


def _reference(root: Path, relative: object) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise MeasurementV2Error("artifact reference must be a relative POSIX path")
    pure = PurePosixPath(relative)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in relative.split("/")):
        raise MeasurementV2Error("unsafe artifact reference")
    return _regular_path(root.joinpath(*pure.parts))


def _input_inventory(plan_path: Path, batch_path: Path) -> list[dict[str, object]]:
    inventory = []
    total = 0
    for label, root in (("plan", plan_path.parent), ("batch", batch_path.parent)):
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if path.is_symlink():
                raise MeasurementV2Error("symbolic links are not accepted in input trees")
            if path.is_dir():
                continue
            regular = _regular_path(path)
            size = regular.stat().st_size
            total += size
            if total > _MAX_TREE_BYTES or len(inventory) >= _MAX_FILES:
                raise MeasurementV2Error("input evidence exceeds the inspection limits")
            inventory.append(
                {
                    "path": f"{label}/{path.relative_to(root).as_posix()}",
                    "size_bytes": size,
                    "sha256": _file_digest(regular),
                }
            )
    return inventory


def _schema_in_prompt(
    prompt: Mapping[str, object],
    *,
    task: EvaluatorBenchmarkTask,
    repetition: int,
) -> dict[str, object]:
    for key, expected in (
        ("task_id", task.task_id),
        ("task_content_hash", task.content_hash),
        ("repetition", repetition),
    ):
        if prompt.get(key) != expected:
            raise MeasurementV2Error(f"prompt {key} differs from the frozen task")
    messages = prompt.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise MeasurementV2Error("prompt must contain the archived system and user messages")
    if not all(isinstance(message, dict) for message in messages):
        raise MeasurementV2Error("archived messages must be objects")
    if messages[0].get("role") != "system" or messages[1].get("role") != "user":
        raise MeasurementV2Error("unexpected prompt roles")
    try:
        user = strict_json_loads(messages[1]["content"])
    except (KeyError, TypeError, ValueError, RecursionError) as error:
        raise MeasurementV2Error("invalid archived user message") from error
    if not isinstance(user, dict) or user.get("task_id") != task.task_id:
        raise MeasurementV2Error("archived user message references a different task")
    if user.get("allowed_evidence_refs") != list(task.expected.allowed_evidence_refs):
        raise MeasurementV2Error("archived evidence references differ from the frozen task")
    schema = user.get("output_schema")
    expected = evaluator_benchmark_output_schema()
    if not isinstance(schema, dict) or schema != json.loads(expected.canonical_schema_json):
        raise MeasurementV2Error("archived prompt does not contain the frozen output schema")
    if prompt.get("output_schema_sha256") != expected.content_hash:
        raise MeasurementV2Error("archived schema identity is inconsistent")
    return schema


def _task_record(
    task: EvaluatorBenchmarkTask,
    repetition: int,
    observation: dict[str, object] | None,
    root: Path,
) -> dict[str, object]:
    record: dict[str, object] = {
        "task_id": task.task_id,
        "task_content_hash": task.content_hash,
        "language": task.language.value,
        "repetition": repetition,
        "generation_succeeded": None,
        "finish_reason": None,
        "legacy_task_status": None,
        "legacy_score_v1": None,
        "prompt_reference": None,
        "prompt_sha256": None,
        "raw_output_reference": None,
        "raw_output_sha256": None,
        "resource_measurement": None,
        "failure_kind": None,
        "failure_message": None,
    }
    schema = json.loads(evaluator_benchmark_output_schema().canonical_schema_json)
    raw = None
    if observation is not None:
        for key, expected in (
            ("task_id", task.task_id),
            ("task_content_hash", task.content_hash),
            ("language", task.language.value),
            ("repetition", repetition),
        ):
            if observation.get(key) != expected:
                raise MeasurementV2Error(f"observation {key} differs from the frozen task")
        resource = observation.get("resource_measurement")
        if not isinstance(resource, dict) or resource.get("status") not in {"SUCCEEDED", "FAILED"}:
            raise MeasurementV2Error("missing or unknown generation resource status")
        success = resource["status"] == "SUCCEEDED"
        status = observation.get("status")
        if (success and status not in _SUCCESS_TASK_STATUSES) or (
            not success and status != "FAILED"
        ):
            raise MeasurementV2Error("task and generation resource status disagree")
        for key, expected in (("task_id", task.task_id), ("repetition", repetition)):
            if resource.get(key) != expected:
                raise MeasurementV2Error("resource observation references a different task")
        record.update(
            {
                "generation_succeeded": success,
                "legacy_task_status": status,
                "legacy_score_v1": observation.get("score"),
            }
        )
        for key in (
            "finish_reason",
            "prompt_reference",
            "prompt_sha256",
            "raw_output_reference",
            "raw_output_sha256",
            "resource_measurement",
            "failure_kind",
            "failure_message",
        ):
            record[key] = observation.get(key)
        prompt = _json_file(_reference(root, record["prompt_reference"]))
        schema = _schema_in_prompt(prompt, task=task, repetition=repetition)
        if success:
            raw_path = _reference(root, record["raw_output_reference"])
            if _file_digest(raw_path) != record["raw_output_sha256"]:
                raise MeasurementV2Error("raw output digest changed")
            raw = raw_path.read_bytes().decode("utf-8")
        elif record["raw_output_reference"] is not None:
            raise MeasurementV2Error(
                "failed generation cannot silently include a successful output"
            )
    record["measurement"] = measure_evaluator_output_v2(
        task=task,
        raw_output=raw,
        output_schema=schema,
    ).to_snapshot()
    return record


def reanalyze_model_spike_v2(
    *,
    repository_root: Path,
    plan_path: Path,
    batch_result_path: Path,
    created_at: datetime,
) -> dict[str, object]:
    """Create a deterministic derived report using only archived files and frozen labels."""
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise MeasurementV2Error("created-at must be timezone-aware")
    plan_path = _regular_path(plan_path)
    batch_result_path = _regular_path(batch_result_path)
    before = _input_inventory(plan_path, batch_result_path)
    plan = load_model_spike_execution_plan(plan_path)
    bundle_v1 = load_validated_model_spike_bundle(
        plan_path=plan_path,
        batch_result_path=batch_result_path,
    )
    batch = _json_file(batch_result_path)
    suite = load_frozen_evaluator_benchmark_suite(repository_root)
    matrix = load_frozen_model_candidate_matrix(repository_root)
    if plan.benchmark_suite_content_hash != suite.content_hash:
        raise MeasurementV2Error("execution plan references a different benchmark suite")
    if plan.candidate_matrix_content_hash != matrix.content_hash:
        raise MeasurementV2Error("execution plan references a different candidate matrix")
    processes = {item["candidate_id"]: item for item in batch["processes"]}
    candidates = []
    for reference in plan.requests:
        candidate = matrix.candidate(reference.candidate_id)
        request = _json_file(_reference(plan_path.parent, reference.request_reference))
        repetitions = request["generation"]["repetitions"]
        if isinstance(repetitions, bool) or not isinstance(repetitions, int):
            raise MeasurementV2Error("invalid number of repetitions")
        if not 1 <= repetitions <= 5:
            raise MeasurementV2Error("invalid number of repetitions")
        if (
            request["model_repository"] != candidate.repository_id
            or request["model_revision"] != candidate.revision
        ):
            raise MeasurementV2Error("request model identity differs from frozen candidate")
        process = processes.get(candidate.candidate_id)
        result = {}
        result_root = batch_result_path.parent
        if process is not None and process.get("result_reference") is not None:
            result_path = _reference(batch_result_path.parent, process["result_reference"])
            result = _json_file(result_path)
            result_root = result_path.parent
        observations = {}
        for item in result.get("tasks", []):
            key = (item["task_id"], item["repetition"])
            if key in observations:
                raise MeasurementV2Error("duplicate task observation")
            observations[key] = item
        expected_keys = {
            (task.task_id, number) for task in suite.tasks for number in range(1, repetitions + 1)
        }
        if not set(observations).issubset(expected_keys):
            raise MeasurementV2Error("observation not present in the frozen task/repetition set")
        if result.get("status") == "COMPLETED" and set(observations) != expected_keys:
            raise MeasurementV2Error("complete result is missing expected observations")
        records = [
            _task_record(task, number, observations.get((task.task_id, number)), result_root)
            for task in suite.tasks
            for number in range(1, repetitions + 1)
        ]
        legacy_run = next(
            (run for run in bundle_v1.runs if run.candidate_id == candidate.candidate_id),
            None,
        )
        candidates.append(
            {
                "candidate_id": candidate.candidate_id,
                "model_repository": candidate.repository_id,
                "requested_revision": candidate.revision,
                "runtime_identity": result.get("model_identity"),
                "observed_identity": result.get("observed_identity"),
                "process_status": None if process is None else process["status"],
                "runner_status": result.get("status"),
                "failure_kind": result.get("failure_kind"),
                "failure_message": result.get("failure_message"),
                "request_sha256": reference.request_sha256,
                "legacy_v1": {
                    "successful_task_count_as_originally_computed": (
                        None if legacy_run is None else legacy_run.successful_task_count
                    ),
                    "benchmark_metrics": result.get("benchmark_metrics", []),
                    "resource_summary": result.get("resource_summary"),
                    "notice": (
                        "Legacy counters and censored scores preserved, "
                        "not used as v2 semantic measurements."
                    ),
                },
                "summary": summarize_measurements_v2(records),
                "by_language": {
                    language: summarize_measurements_v2(
                        [item for item in records if item["language"] == language]
                    )
                    for language in ("en", "it")
                },
                "tasks": records,
            }
        )
    if before != _input_inventory(plan_path, batch_result_path):
        raise MeasurementV2Error("input evidence changed while being analyzed")
    policy = measurement_policy_snapshot()
    report: dict[str, object] = {
        "schema_version": 2,
        "report_id": "user-twin-evaluator-model-spike-reanalysis-v2",
        "created_at": created_at.isoformat(),
        "policy": policy,
        "policy_content_hash": snapshot_content_hash(policy),
        "implementation_sha256": {
            name: _file_digest(Path(__file__).parent / name)
            for name in ("benchmark_measurement_v2.py", "model_spike_reanalysis.py")
        },
        "input_inventory": before,
        "input_inventory_content_hash": snapshot_content_hash({"files": before}),
        "source_plan_content_hash": plan.content_hash,
        "source_batch_content_hash": batch["content_hash"],
        "legacy_validated_bundle_content_hash": bundle_v1.content_hash,
        "benchmark_suite_content_hash": suite.content_hash,
        "candidate_matrix_content_hash": matrix.content_hash,
        "package_lock_sha256": plan.package_lock_sha256,
        "environment_sha256": plan.environment_sha256,
        "candidates": candidates,
        "selection_status": "NO_MODEL_SELECTED",
        "ready_for_owner_selection": False,
        "post_hoc": True,
        "live_inference_executed": False,
        "original_reports_replaced": False,
        "methodological_notice": (
            "Post-hoc measurement correction on unchanged synthetic benchmark responses. "
            "Conditional semantic observations require schema-valid output and report coverage. "
            "No ranking, fresh inference, QLoRA feasibility or real-user validity is inferred."
        ),
    }
    report["content_hash"] = snapshot_content_hash(report)
    return report


def write_reanalysis_report_v2(
    *,
    path: Path,
    report: Mapping[str, object],
    protected_roots: tuple[Path, ...],
) -> None:
    """Publish once, outside source trees; never overwrite or edit an original artifact."""
    destination = Path(os.path.abspath(path))
    for component in (*reversed(destination.parents), destination):
        if component.is_symlink():
            raise MeasurementV2Error("output path must not contain symbolic links")
    for root in protected_roots:
        root = root.resolve()
        if destination == root or root in destination.parents:
            raise MeasurementV2Error("derived report must be outside the protected input trees")
    value = dict(report)
    observed = value.pop("content_hash", None)
    if observed != snapshot_content_hash(value):
        raise MeasurementV2Error("report content hash is inconsistent")
    if destination.exists():
        raise MeasurementV2Error("output already exists; refusing to overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as target:
            target.write(canonical_json(dict(report)).encode("utf-8"))
        # Link publishes atomically with no replacement on Linux and Windows/NTFS.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
