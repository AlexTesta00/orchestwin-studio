"""Strict validation of immutable live model-spike process and result bundles."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Final

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_SHA256,
)
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
)
from orchestwin.training.model_spike_requests import (
    ModelSpikeExecutionPlan,
    load_model_spike_execution_plan,
    request_payload_sha256,
    sha256_file,
)

MODEL_SPIKE_VALIDATED_BUNDLE_SCHEMA_VERSION: Final = 1
_MAX_JSON_BYTES: Final = 16_000_000
_MAX_REFERENCED_ARTIFACT_BYTES: Final = 4_000_000
_SHA256_PATTERN: Final = re.compile(r"[0-9a-f]{64}")
_LANGUAGE_IDS: Final = {"en", "it"}
_SCORE_METRIC_IDS: Final = (
    "abstention_accuracy",
    "context_reference_recall",
    "criterion_agreement",
    "evidence_reference_precision",
    "latency_milliseconds",
    "role_adherence",
    "schema_valid_rate",
    "severity_agreement",
    "unsupported_claim_rate",
)


class ModelSpikeResultError(ValueError):
    """Raised when a process, result, or referenced artifact cannot be trusted."""


class ValidatedModelSpikeStatus(StrEnum):
    """Validated result maturity without masking process or benchmark failures."""

    BENCHMARK_COMPLETED = "BENCHMARK_COMPLETED"
    BENCHMARK_PARTIAL = "BENCHMARK_PARTIAL"
    RUNNER_FAILED = "RUNNER_FAILED"
    RESULT_MISSING = "RESULT_MISSING"
    PROCESS_TIMED_OUT = "PROCESS_TIMED_OUT"


@dataclass(frozen=True, slots=True)
class ValidatedBenchmarkMetric:
    """One aggregate metric copied only after result identity validation."""

    metric_id: str
    value: float | None
    sample_count: int

    def __post_init__(self) -> None:
        if not self.metric_id or self.metric_id.strip() != self.metric_id:
            raise ModelSpikeResultError("validated metric ID must be normalized")
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, float)
        ):
            raise ModelSpikeResultError("validated metric value must be a float or null")
        if isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ModelSpikeResultError("validated metric sample count must not be negative")
        if (self.value is None) != (self.sample_count == 0):
            raise ModelSpikeResultError("validated metric value and sample count are inconsistent")

    @property
    def sort_key(self) -> str:
        return self.metric_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True, slots=True)
class ValidatedLanguageMetric:
    """One observed metric aggregated for one benchmark language."""

    language: str
    metric_id: str
    value: float | None
    sample_count: int

    def __post_init__(self) -> None:
        if self.language not in _LANGUAGE_IDS:
            raise ModelSpikeResultError("validated language metric uses an unsupported language")
        if not self.metric_id or self.metric_id.strip() != self.metric_id:
            raise ModelSpikeResultError("validated language metric ID must be normalized")
        if self.value is not None and (
            isinstance(self.value, bool) or not isinstance(self.value, float)
        ):
            raise ModelSpikeResultError("validated language metric value must be a float or null")
        if isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ModelSpikeResultError(
                "validated language metric sample count must not be negative"
            )
        if (self.value is None) != (self.sample_count == 0):
            raise ModelSpikeResultError(
                "validated language metric value and sample count are inconsistent"
            )

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.language, self.metric_id)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "language": self.language,
            "metric_id": self.metric_id,
            "value": self.value,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True, slots=True)
class ValidatedInferenceResourceSummary:
    """Typed inference resource aggregate copied from a validated runner result."""

    candidate_id: str
    measurement_count: int
    successful_count: int
    mean_latency_milliseconds: float | None
    peak_gpu_memory_mb: int | None
    complete: bool

    def __post_init__(self) -> None:
        if not self.candidate_id or self.candidate_id.strip() != self.candidate_id:
            raise ModelSpikeResultError("validated resource candidate ID must be normalized")
        if (
            isinstance(self.measurement_count, bool)
            or self.measurement_count < 0
            or isinstance(self.successful_count, bool)
            or not 0 <= self.successful_count <= self.measurement_count
        ):
            raise ModelSpikeResultError("validated inference resource counts are inconsistent")
        has_success = self.successful_count > 0
        if has_success != (self.mean_latency_milliseconds is not None):
            raise ModelSpikeResultError(
                "validated mean latency must exist exactly when measurements succeeded"
            )
        if has_success != (self.peak_gpu_memory_mb is not None):
            raise ModelSpikeResultError(
                "validated peak GPU memory must exist exactly when measurements succeeded"
            )
        if self.mean_latency_milliseconds is not None and (
            isinstance(self.mean_latency_milliseconds, bool)
            or not isinstance(self.mean_latency_milliseconds, float)
            or self.mean_latency_milliseconds < 0
        ):
            raise ModelSpikeResultError("validated mean latency must be non-negative")
        if self.peak_gpu_memory_mb is not None and (
            isinstance(self.peak_gpu_memory_mb, bool)
            or not isinstance(self.peak_gpu_memory_mb, int)
            or self.peak_gpu_memory_mb < 0
        ):
            raise ModelSpikeResultError("validated peak GPU memory must be non-negative")
        expected_complete = (
            self.measurement_count > 0 and self.successful_count == self.measurement_count
        )
        if self.complete != expected_complete:
            raise ModelSpikeResultError("validated inference resource completeness is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "measurement_count": self.measurement_count,
            "successful_count": self.successful_count,
            "mean_latency_milliseconds": self.mean_latency_milliseconds,
            "peak_gpu_memory_mb": self.peak_gpu_memory_mb,
            "complete": self.complete,
        }


@dataclass(frozen=True, slots=True)
class ValidatedModelSpikeRun:
    """One process and runner result after all available hashes and references were checked."""

    candidate_id: str
    request_sha256: str
    process_status: str
    process_exit_code: int | None
    status: ValidatedModelSpikeStatus
    result_file_sha256: str | None
    result_content_hash: str | None
    runner_status: str | None
    network_authorized: bool
    benchmark_complete: bool
    task_count: int
    successful_task_count: int
    schema_invalid_task_count: int
    benchmark_metrics: tuple[ValidatedBenchmarkMetric, ...]
    language_metrics: tuple[ValidatedLanguageMetric, ...]
    resource_summary: ValidatedInferenceResourceSummary | None
    failure_kind: str | None
    failure_message: str | None
    content_hash: str

    def __post_init__(self) -> None:
        _validate_sha256(self.request_sha256, label="validated request digest")
        if (self.result_file_sha256 is None) != (self.result_content_hash is None):
            raise ModelSpikeResultError("validated result digests must appear together")
        if self.result_file_sha256 is not None:
            _validate_sha256(self.result_file_sha256, label="validated result file digest")
            _validate_sha256(self.result_content_hash or "", label="validated result content hash")
        for value, label in (
            (self.task_count, "validated task count"),
            (self.successful_task_count, "validated successful task count"),
            (self.schema_invalid_task_count, "validated schema-invalid task count"),
        ):
            if isinstance(value, bool) or value < 0:
                raise ModelSpikeResultError(f"{label} must not be negative")
        if self.successful_task_count > self.task_count:
            raise ModelSpikeResultError("successful task count exceeds validated task count")
        if self.schema_invalid_task_count > self.task_count:
            raise ModelSpikeResultError("schema-invalid task count exceeds validated task count")
        if self.benchmark_metrics != tuple(
            sorted(self.benchmark_metrics, key=lambda item: item.sort_key)
        ):
            raise ModelSpikeResultError("validated benchmark metrics must use canonical order")
        if len({item.metric_id for item in self.benchmark_metrics}) != len(self.benchmark_metrics):
            raise ModelSpikeResultError("validated benchmark metrics must be unique")
        if self.language_metrics != tuple(
            sorted(self.language_metrics, key=lambda item: item.sort_key)
        ):
            raise ModelSpikeResultError("validated language metrics must use canonical order")
        if len({item.sort_key for item in self.language_metrics}) != len(self.language_metrics):
            raise ModelSpikeResultError("validated language metrics must be unique")
        if self.status is ValidatedModelSpikeStatus.BENCHMARK_COMPLETED and (
            not self.benchmark_complete or self.runner_status != "COMPLETED"
        ):
            raise ModelSpikeResultError("completed benchmark status is inconsistent")
        if (
            self.status
            in {
                ValidatedModelSpikeStatus.RESULT_MISSING,
                ValidatedModelSpikeStatus.PROCESS_TIMED_OUT,
            }
            and self.result_file_sha256 is not None
        ):
            raise ModelSpikeResultError("missing or timed-out result cannot carry result digests")
        _validate_sha256(self.content_hash, label="validated model-spike run hash")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeResultError("validated model-spike run hash is inconsistent")

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "request_sha256": self.request_sha256,
            "process_status": self.process_status,
            "process_exit_code": self.process_exit_code,
            "status": self.status.value,
            "result_file_sha256": self.result_file_sha256,
            "result_content_hash": self.result_content_hash,
            "runner_status": self.runner_status,
            "network_authorized": self.network_authorized,
            "benchmark_complete": self.benchmark_complete,
            "task_count": self.task_count,
            "successful_task_count": self.successful_task_count,
            "schema_invalid_task_count": self.schema_invalid_task_count,
            "benchmark_metrics": [item.to_snapshot() for item in self.benchmark_metrics],
            "language_metrics": [item.to_snapshot() for item in self.language_metrics],
            "resource_summary": (
                None if self.resource_summary is None else self.resource_summary.to_snapshot()
            ),
            "failure_kind": self.failure_kind,
            "failure_message": self.failure_message,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ValidatedModelSpikeBundle:
    """Validated projection over one plan and one observed batch-result artifact."""

    plan_content_hash: str
    plan_file_sha256: str
    batch_content_hash: str
    batch_file_sha256: str
    runs: tuple[ValidatedModelSpikeRun, ...]
    validation_complete: bool
    all_benchmarks_complete: bool
    content_hash: str
    schema_version: int = MODEL_SPIKE_VALIDATED_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SPIKE_VALIDATED_BUNDLE_SCHEMA_VERSION:
            raise ModelSpikeResultError("unsupported validated model-spike bundle schema")
        for value, label in (
            (self.plan_content_hash, "validated bundle plan content hash"),
            (self.plan_file_sha256, "validated bundle plan file digest"),
            (self.batch_content_hash, "validated bundle batch content hash"),
            (self.batch_file_sha256, "validated bundle batch file digest"),
            (self.content_hash, "validated bundle content hash"),
        ):
            _validate_sha256(value, label=label)
        if self.runs != tuple(sorted(self.runs, key=lambda item: item.sort_key)):
            raise ModelSpikeResultError("validated model-spike runs must use canonical order")
        if not self.runs or len({item.candidate_id for item in self.runs}) != len(self.runs):
            raise ModelSpikeResultError("validated model-spike bundle requires unique runs")
        expected_validation = all(
            item.status
            not in {
                ValidatedModelSpikeStatus.RESULT_MISSING,
                ValidatedModelSpikeStatus.PROCESS_TIMED_OUT,
            }
            for item in self.runs
        )
        if self.validation_complete != expected_validation:
            raise ModelSpikeResultError("validated bundle completeness is inconsistent")
        expected_benchmarks = all(
            item.status is ValidatedModelSpikeStatus.BENCHMARK_COMPLETED for item in self.runs
        )
        if self.all_benchmarks_complete != expected_benchmarks:
            raise ModelSpikeResultError("validated benchmark completion is inconsistent")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeResultError("validated model-spike bundle hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "plan_content_hash": self.plan_content_hash,
            "plan_file_sha256": self.plan_file_sha256,
            "batch_content_hash": self.batch_content_hash,
            "batch_file_sha256": self.batch_file_sha256,
            "runs": [item.to_snapshot() for item in self.runs],
            "validation_complete": self.validation_complete,
            "all_benchmarks_complete": self.all_benchmarks_complete,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


def load_validated_model_spike_bundle(
    *,
    plan_path: Path,
    batch_result_path: Path,
) -> ValidatedModelSpikeBundle:
    """Validate batch, process, request, result, and referenced task artifacts."""
    plan = load_model_spike_execution_plan(plan_path)
    batch = _read_canonical_json(
        batch_result_path,
        label="model-spike batch result",
        maximum_bytes=_MAX_JSON_BYTES,
    )
    _validate_content_hash(batch, label="model-spike batch")
    if batch.get("plan_content_hash") != plan.content_hash:
        raise ModelSpikeResultError("batch result references a different execution plan")
    if batch.get("plan_file_sha256") != sha256_file(plan_path):
        raise ModelSpikeResultError("batch result plan file digest changed")
    selected = _string_tuple(batch, "selected_candidate_ids")
    raw_processes = batch.get("processes")
    if not isinstance(raw_processes, list):
        raise ModelSpikeResultError("batch processes must be an array")
    if len(raw_processes) != len(selected):
        raise ModelSpikeResultError("batch process count differs from selected candidates")
    network_authorized = _required_boolean(batch, "network_authorized")
    batch_root = batch_result_path.resolve().parent
    plan_root = plan_path.resolve().parent
    runs = tuple(
        sorted(
            (
                _validate_process_and_result(
                    process=_mapping(raw_process, label="batch process"),
                    candidate_id=candidate_id,
                    plan=plan,
                    plan_root=plan_root,
                    batch_root=batch_root,
                    network_authorized=network_authorized,
                )
                for candidate_id, raw_process in zip(selected, raw_processes, strict=True)
            ),
            key=lambda item: item.sort_key,
        )
    )
    semantic = {
        "schema_version": MODEL_SPIKE_VALIDATED_BUNDLE_SCHEMA_VERSION,
        "plan_content_hash": plan.content_hash,
        "plan_file_sha256": sha256_file(plan_path),
        "batch_content_hash": _required_string(batch, "content_hash"),
        "batch_file_sha256": sha256_file(batch_result_path),
        "runs": [item.to_snapshot() for item in runs],
        "validation_complete": all(
            item.status
            not in {
                ValidatedModelSpikeStatus.RESULT_MISSING,
                ValidatedModelSpikeStatus.PROCESS_TIMED_OUT,
            }
            for item in runs
        ),
        "all_benchmarks_complete": all(
            item.status is ValidatedModelSpikeStatus.BENCHMARK_COMPLETED for item in runs
        ),
    }
    return ValidatedModelSpikeBundle(
        plan_content_hash=plan.content_hash,
        plan_file_sha256=sha256_file(plan_path),
        batch_content_hash=str(semantic["batch_content_hash"]),
        batch_file_sha256=str(semantic["batch_file_sha256"]),
        runs=runs,
        validation_complete=bool(semantic["validation_complete"]),
        all_benchmarks_complete=bool(semantic["all_benchmarks_complete"]),
        content_hash=snapshot_content_hash(semantic),
    )


def write_validated_model_spike_bundle(
    path: Path,
    bundle: ValidatedModelSpikeBundle,
) -> None:
    """Write a canonical derived validation artifact without mutating raw evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(canonical_json(bundle.to_snapshot()), encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ModelSpikeResultError("cannot write validated model-spike bundle") from error


def _validate_process_and_result(
    *,
    process: Mapping[str, object],
    candidate_id: str,
    plan: ModelSpikeExecutionPlan,
    plan_root: Path,
    batch_root: Path,
    network_authorized: bool,
) -> ValidatedModelSpikeRun:
    _validate_content_hash(process, label="model-spike process")
    if _required_string(process, "candidate_id") != candidate_id:
        raise ModelSpikeResultError("batch process candidate order changed")
    reference = plan.request(candidate_id)
    request_sha256 = _required_string(process, "request_sha256")
    if request_sha256 != reference.request_sha256:
        raise ModelSpikeResultError("batch process request digest differs from plan")
    request_path = _resolve_artifact(
        plan_root,
        reference.request_reference,
        maximum_bytes=2_000_000,
    )
    request_payload = _read_canonical_json(
        request_path,
        label="model-spike request",
        maximum_bytes=2_000_000,
    )
    if request_payload_sha256(request_payload) != request_sha256:
        raise ModelSpikeResultError("model-spike request content digest changed")
    if request_payload.get("request_sha256") != request_sha256:
        raise ModelSpikeResultError("model-spike request identity changed")
    for reference_key, digest_key in (
        ("stdout_reference", "stdout_sha256"),
        ("stderr_reference", "stderr_sha256"),
    ):
        artifact = _resolve_artifact(
            batch_root,
            _required_string(process, reference_key),
            maximum_bytes=32_000_000,
        )
        if _sha256(artifact) != _required_string(process, digest_key):
            raise ModelSpikeResultError(f"{reference_key} digest changed")
    if _required_boolean(process, "network_authorized") != network_authorized:
        raise ModelSpikeResultError("process network evidence differs from batch")

    process_status = _required_string(process, "status")
    exit_code_value = process.get("exit_code")
    if exit_code_value is not None and (
        isinstance(exit_code_value, bool) or not isinstance(exit_code_value, int)
    ):
        raise ModelSpikeResultError("process exit code must be an integer or null")
    result_reference = process.get("result_reference")
    result_file_sha256 = process.get("result_file_sha256")
    if result_reference is None:
        status = (
            ValidatedModelSpikeStatus.PROCESS_TIMED_OUT
            if process_status == "TIMED_OUT"
            else ValidatedModelSpikeStatus.RESULT_MISSING
        )
        return _validated_run(
            candidate_id=candidate_id,
            request_sha256=request_sha256,
            process_status=process_status,
            process_exit_code=exit_code_value,
            status=status,
            result_file_sha256=None,
            result_content_hash=None,
            runner_status=None,
            network_authorized=network_authorized,
            benchmark_complete=False,
            task_count=0,
            successful_task_count=0,
            schema_invalid_task_count=0,
            benchmark_metrics=(),
            language_metrics=(),
            resource_summary=None,
            failure_kind=process_status,
            failure_message="No runner result artifact was produced.",
        )
    if not isinstance(result_reference, str) or not isinstance(result_file_sha256, str):
        raise ModelSpikeResultError("process result reference and digest are invalid")
    result_path = _resolve_artifact(batch_root, result_reference, maximum_bytes=_MAX_JSON_BYTES)
    if _sha256(result_path) != result_file_sha256:
        raise ModelSpikeResultError("runner result file digest changed")
    result = _read_canonical_json(
        result_path,
        label="model-spike runner result",
        maximum_bytes=_MAX_JSON_BYTES,
    )
    result_content_hash = _required_string(result, "result_sha256")
    _validate_result_hash(result)
    if result.get("request_sha256") != request_sha256:
        raise ModelSpikeResultError("runner result references a different request")
    if _required_boolean(result, "network_authorized") != network_authorized:
        raise ModelSpikeResultError("runner and process network evidence differ")
    runner_status = _required_string(result, "status")
    result_candidate = result.get("candidate_id")
    if result_candidate is not None and result_candidate != candidate_id:
        raise ModelSpikeResultError("runner result candidate differs from batch process")
    if result_candidate is None:
        return _validated_run(
            candidate_id=candidate_id,
            request_sha256=request_sha256,
            process_status=process_status,
            process_exit_code=exit_code_value,
            status=ValidatedModelSpikeStatus.RUNNER_FAILED,
            result_file_sha256=result_file_sha256,
            result_content_hash=result_content_hash,
            runner_status=runner_status,
            network_authorized=network_authorized,
            benchmark_complete=False,
            task_count=0,
            successful_task_count=0,
            schema_invalid_task_count=0,
            benchmark_metrics=(),
            language_metrics=(),
            resource_summary=None,
            failure_kind=_optional_string(result, "failure_kind"),
            failure_message=_optional_string(result, "failure_message"),
        )
    _validate_success_result_identities(result, plan=plan)
    tasks = result.get("tasks")
    if not isinstance(tasks, list):
        raise ModelSpikeResultError("runner result tasks must be an array")
    _validate_task_artifacts(tasks, result_root=result_path.parent)
    metrics = _parse_metrics(result.get("benchmark_metrics"))
    language_metrics = _parse_language_metrics(tasks)
    benchmark = _mapping(result.get("benchmark"), label="runner benchmark")
    benchmark_complete = _required_boolean(benchmark, "complete")
    successful_tasks = sum(
        1 for item in tasks if _mapping(item, label="runner task").get("status") == "SUCCEEDED"
    )
    schema_invalid = sum(
        1
        for item in tasks
        if _mapping(_mapping(item, label="runner task").get("score"), label="task score").get(
            "schema_valid_rate"
        )
        == 0.0
    )
    status = (
        ValidatedModelSpikeStatus.BENCHMARK_COMPLETED
        if runner_status == "COMPLETED" and benchmark_complete
        else ValidatedModelSpikeStatus.BENCHMARK_PARTIAL
    )
    resource = _parse_resource_summary(
        result.get("resource_summary"),
        candidate_id=candidate_id,
    )
    return _validated_run(
        candidate_id=candidate_id,
        request_sha256=request_sha256,
        process_status=process_status,
        process_exit_code=exit_code_value,
        status=status,
        result_file_sha256=result_file_sha256,
        result_content_hash=result_content_hash,
        runner_status=runner_status,
        network_authorized=network_authorized,
        benchmark_complete=benchmark_complete,
        task_count=len(tasks),
        successful_task_count=successful_tasks,
        schema_invalid_task_count=schema_invalid,
        benchmark_metrics=metrics,
        language_metrics=language_metrics,
        resource_summary=resource,
        failure_kind=_optional_string(result, "failure_kind"),
        failure_message=_optional_string(result, "failure_message"),
    )


def _validated_run(**values: object) -> ValidatedModelSpikeRun:
    semantic = {
        "candidate_id": values["candidate_id"],
        "request_sha256": values["request_sha256"],
        "process_status": values["process_status"],
        "process_exit_code": values["process_exit_code"],
        "status": values["status"].value,
        "result_file_sha256": values["result_file_sha256"],
        "result_content_hash": values["result_content_hash"],
        "runner_status": values["runner_status"],
        "network_authorized": values["network_authorized"],
        "benchmark_complete": values["benchmark_complete"],
        "task_count": values["task_count"],
        "successful_task_count": values["successful_task_count"],
        "schema_invalid_task_count": values["schema_invalid_task_count"],
        "benchmark_metrics": [item.to_snapshot() for item in values["benchmark_metrics"]],
        "language_metrics": [item.to_snapshot() for item in values["language_metrics"]],
        "resource_summary": (
            None if values["resource_summary"] is None else values["resource_summary"].to_snapshot()
        ),
        "failure_kind": values["failure_kind"],
        "failure_message": values["failure_message"],
    }
    return ValidatedModelSpikeRun(**values, content_hash=snapshot_content_hash(semantic))


def _validate_success_result_identities(
    result: Mapping[str, object],
    *,
    plan: ModelSpikeExecutionPlan,
) -> None:
    matrix = _mapping(result.get("candidate_matrix"), label="runner candidate matrix")
    if matrix.get("matrix_sha256") != FROZEN_MODEL_CANDIDATE_MATRIX_SHA256:
        raise ModelSpikeResultError("runner candidate matrix file identity changed")
    if matrix.get("matrix_content_hash") != FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH:
        raise ModelSpikeResultError("runner candidate matrix content identity changed")
    benchmark = _mapping(result.get("benchmark"), label="runner benchmark")
    if benchmark.get("suite_sha256") != FROZEN_BENCHMARK_SUITE_SHA256:
        raise ModelSpikeResultError("runner benchmark file identity changed")
    if benchmark.get("suite_content_hash") != FROZEN_BENCHMARK_SUITE_CONTENT_HASH:
        raise ModelSpikeResultError("runner benchmark content identity changed")
    environment = _mapping(result.get("environment"), label="runner environment")
    if environment.get("environment_sha256") != plan.environment_sha256:
        raise ModelSpikeResultError("runner environment digest differs from plan")
    if environment.get("package_lock_sha256") != plan.package_lock_sha256:
        raise ModelSpikeResultError("runner package lock digest differs from plan")


def _validate_task_artifacts(tasks: list[object], *, result_root: Path) -> None:
    identities: set[tuple[str, int]] = set()
    for raw_task in tasks:
        task = _mapping(raw_task, label="runner task")
        _validate_content_hash(task, label="runner task")
        task_id = _required_string(task, "task_id")
        repetition = _required_integer(task, "repetition")
        identity = (task_id, repetition)
        if identity in identities:
            raise ModelSpikeResultError("runner task identities must be unique")
        identities.add(identity)
        for reference_key, digest_key in (
            ("prompt_reference", "prompt_sha256"),
            ("raw_output_reference", "raw_output_sha256"),
            ("structured_output_reference", "structured_output_sha256"),
        ):
            reference = task.get(reference_key)
            digest = task.get(digest_key)
            if reference is None:
                if digest is not None:
                    raise ModelSpikeResultError("task artifact digest exists without reference")
                continue
            if not isinstance(reference, str) or not isinstance(digest, str):
                raise ModelSpikeResultError("task artifact reference and digest are invalid")
            artifact = _resolve_artifact(
                result_root,
                reference,
                maximum_bytes=_MAX_REFERENCED_ARTIFACT_BYTES,
            )
            if _sha256(artifact) != digest:
                raise ModelSpikeResultError(f"runner task artifact digest changed: {reference_key}")


def _parse_metrics(value: object) -> tuple[ValidatedBenchmarkMetric, ...]:
    if not isinstance(value, list):
        raise ModelSpikeResultError("runner benchmark metrics must be an array")
    metrics = []
    for raw in value:
        metric = _mapping(raw, label="runner benchmark metric")
        raw_value = metric.get("value")
        if raw_value is not None and (
            isinstance(raw_value, bool) or not isinstance(raw_value, (int, float))
        ):
            raise ModelSpikeResultError("runner metric value must be numeric or null")
        metrics.append(
            ValidatedBenchmarkMetric(
                metric_id=_required_string(metric, "metric_id"),
                value=None if raw_value is None else float(raw_value),
                sample_count=_required_integer(metric, "sample_count"),
            )
        )
    return tuple(sorted(metrics, key=lambda item: item.sort_key))


def _parse_resource_summary(
    value: object,
    *,
    candidate_id: str,
) -> ValidatedInferenceResourceSummary | None:
    if value is None:
        return None
    payload = _mapping(value, label="runner resource summary")
    expected_keys = {
        "candidate_id",
        "measurement_count",
        "successful_count",
        "mean_latency_milliseconds",
        "peak_gpu_memory_mb",
        "complete",
    }
    if set(payload) != expected_keys:
        raise ModelSpikeResultError("runner resource summary fields do not match schema")
    observed_candidate = _required_string(payload, "candidate_id")
    if observed_candidate != candidate_id:
        raise ModelSpikeResultError("runner resource summary candidate differs from process")
    latency_value = payload.get("mean_latency_milliseconds")
    if latency_value is not None and (
        isinstance(latency_value, bool) or not isinstance(latency_value, (int, float))
    ):
        raise ModelSpikeResultError("runner mean latency must be numeric or null")
    peak_value = payload.get("peak_gpu_memory_mb")
    if peak_value is not None and (isinstance(peak_value, bool) or not isinstance(peak_value, int)):
        raise ModelSpikeResultError("runner peak GPU memory must be an integer or null")
    return ValidatedInferenceResourceSummary(
        candidate_id=observed_candidate,
        measurement_count=_required_integer(payload, "measurement_count"),
        successful_count=_required_integer(payload, "successful_count"),
        mean_latency_milliseconds=(None if latency_value is None else float(latency_value)),
        peak_gpu_memory_mb=peak_value,
        complete=_required_boolean(payload, "complete"),
    )


def _parse_language_metrics(tasks: list[object]) -> tuple[ValidatedLanguageMetric, ...]:
    values: dict[tuple[str, str], list[float]] = {}
    for raw_task in tasks:
        task = _mapping(raw_task, label="runner task")
        language = _required_string(task, "language")
        if language not in _LANGUAGE_IDS:
            raise ModelSpikeResultError("runner task language is unsupported")
        score = _mapping(task.get("score"), label="runner task score")
        for metric_id in _SCORE_METRIC_IDS:
            raw_value = score.get(metric_id)
            if raw_value is None:
                continue
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
                raise ModelSpikeResultError(
                    f"runner task score {metric_id} must be numeric or null"
                )
            values.setdefault((language, metric_id), []).append(float(raw_value))

    metrics = [
        ValidatedLanguageMetric(
            language=language,
            metric_id=metric_id,
            value=round(sum(observed) / len(observed), 6),
            sample_count=len(observed),
        )
        for (language, metric_id), observed in values.items()
    ]
    return tuple(sorted(metrics, key=lambda item: item.sort_key))


def _validate_result_hash(result: Mapping[str, object]) -> None:
    observed = _required_string(result, "result_sha256")
    _validate_sha256(observed, label="runner result content hash")
    without_hash = dict(result)
    without_hash.pop("result_sha256", None)
    if observed != snapshot_content_hash(without_hash):
        raise ModelSpikeResultError("runner result content hash is inconsistent")


def _validate_content_hash(payload: Mapping[str, object], *, label: str) -> None:
    observed = _required_string(payload, "content_hash")
    _validate_sha256(observed, label=f"{label} content hash")
    without_hash = dict(payload)
    without_hash.pop("content_hash", None)
    if observed != snapshot_content_hash(without_hash):
        raise ModelSpikeResultError(f"{label} content hash is inconsistent")


def _read_canonical_json(path: Path, *, label: str, maximum_bytes: int) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeResultError(f"{label} must be a regular file")
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise ModelSpikeResultError(f"{label} exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeResultError(f"{label} must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSpikeResultError(f"{label} must contain a JSON object")
    if raw != canonical_json(payload).encode("utf-8"):
        raise ModelSpikeResultError(f"{label} must use canonical JSON")
    return payload


def _resolve_artifact(root: Path, reference: str, *, maximum_bytes: int) -> Path:
    _validate_relative_path(reference, label="model-spike artifact reference")
    resolved_root = root.resolve()
    path = resolved_root.joinpath(*PurePosixPath(reference).parts).resolve()
    if resolved_root not in path.parents:
        raise ModelSpikeResultError("model-spike artifact reference escapes its root")
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeResultError("model-spike artifact reference must be a regular file")
    if path.stat().st_size > maximum_bytes:
        raise ModelSpikeResultError("model-spike referenced artifact exceeds size limit")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelSpikeResultError(f"{label} must be an object")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSpikeResultError(f"{key} must be a normalized string")
    return value


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSpikeResultError(f"{key} must be a normalized string or null")
    return value


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelSpikeResultError(f"{key} must be an integer")
    return value


def _required_boolean(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ModelSpikeResultError(f"{key} must be boolean")
    return value


def _string_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and item.strip() == item for item in value
    ):
        raise ModelSpikeResultError(f"{key} must contain normalized strings")
    return tuple(value)


def _validate_relative_path(value: str, *, label: str) -> None:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ModelSpikeResultError(f"{label} must be a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ModelSpikeResultError(f"{label} must be traversal-free")


def _validate_sha256(value: str, *, label: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ModelSpikeResultError(f"{label} must use lowercase SHA-256")
