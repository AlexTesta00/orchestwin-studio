"""Canonical comparison reports for validated live model-spike evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash
from orchestwin.training.benchmark_suite_files import (
    FROZEN_BENCHMARK_SUITE_CONTENT_HASH,
    FROZEN_BENCHMARK_SUITE_SHA256,
)
from orchestwin.training.benchmark_tasks import (
    BenchmarkMetricDirection,
    BenchmarkMetricId,
    EvaluatorBenchmarkSuite,
)
from orchestwin.training.model_candidate_matrix_files import (
    FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH,
    FROZEN_MODEL_CANDIDATE_MATRIX_SHA256,
    FrozenModelCandidateMatrix,
    FrozenModelCandidatePreflight,
)
from orchestwin.training.model_spike_requests import (
    MODEL_SPIKE_SELECTION_STATUS,
    ModelSpikeExecutionPlan,
)
from orchestwin.training.model_spike_results import (
    ValidatedBenchmarkMetric,
    ValidatedInferenceResourceSummary,
    ValidatedLanguageMetric,
    ValidatedModelSpikeBundle,
    ValidatedModelSpikeRun,
    ValidatedModelSpikeStatus,
)

MODEL_SPIKE_COMPARISON_REPORT_SCHEMA_VERSION: Final = 1
MODEL_SPIKE_COMPARISON_REPORT_ID: Final = "user-twin-evaluator-model-spike-comparison-v1"
MODEL_SPIKE_METHODOLOGICAL_NOTICE: Final = (
    "The benchmark evaluates structured protocol adherence on synthetic User Twin tasks. "
    "Its outputs are simulated feedback and design hypotheses, not empirical evidence of "
    "real-user behavior."
)
MODEL_SPIKE_PENDING_EVIDENCE: Final = (
    "ADAPTER_EXPORT_LOAD",
    "LICENSE_COMPATIBILITY_REVIEW",
    "QLORA_SMOKE_TRAINING",
    "SERVING_RUNTIME_VALIDATION",
)
_MAX_REPORT_BYTES: Final = 8_000_000


class ModelSpikeReportError(ValueError):
    """Raised when a comparison report cannot be built or trusted."""


class ModelSpikeThresholdStatus(StrEnum):
    """Observed state of one frozen benchmark threshold."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_OBSERVED = "NOT_OBSERVED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ModelSpikeSelectionReadiness(StrEnum):
    """Evidence readiness before the owner-controlled model-selection gate."""

    INFERENCE_INCOMPLETE = "INFERENCE_INCOMPLETE"
    BENCHMARK_REVIEW_REQUIRED = "BENCHMARK_REVIEW_REQUIRED"
    READY_FOR_LICENSE_AND_QLORA_REVIEW = "READY_FOR_LICENSE_AND_QLORA_REVIEW"


@dataclass(frozen=True, slots=True)
class ModelSpikeThresholdObservation:
    """One frozen metric threshold and its observed outcome."""

    metric_id: str
    direction: str
    threshold: float | None
    observed_value: float | None
    status: ModelSpikeThresholdStatus

    def __post_init__(self) -> None:
        if not self.metric_id or self.metric_id.strip() != self.metric_id:
            raise ModelSpikeReportError("comparison threshold metric ID must be normalized")
        if self.direction not in {
            BenchmarkMetricDirection.MAXIMIZE.value,
            BenchmarkMetricDirection.MINIMIZE.value,
        }:
            raise ModelSpikeReportError("comparison threshold direction is unsupported")
        for value, label in (
            (self.threshold, "comparison threshold"),
            (self.observed_value, "comparison threshold observation"),
        ):
            if value is not None and (isinstance(value, bool) or not isinstance(value, float)):
                raise ModelSpikeReportError(f"{label} must be a float or null")
        expected_status = _threshold_status(
            direction=self.direction,
            threshold=self.threshold,
            observed=self.observed_value,
        )
        if self.status is not expected_status:
            raise ModelSpikeReportError("comparison threshold status is inconsistent")

    @property
    def sort_key(self) -> str:
        return self.metric_id

    def to_snapshot(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id,
            "direction": self.direction,
            "threshold": self.threshold,
            "observed_value": self.observed_value,
            "status": self.status.value,
        }


@dataclass(frozen=True, slots=True)
class ModelSpikeCandidateComparison:
    """Comparable inference evidence for one candidate without a selection claim."""

    candidate_id: str
    family_id: str
    repository_id: str
    revision: str
    declared_parameter_count_millions: int
    declared_context_limit_tokens: int
    request_sha256: str
    source_evidence_content_hash: str
    source_evidence_file_sha256: str
    run_status: ValidatedModelSpikeStatus
    benchmark_complete: bool
    task_count: int
    successful_task_count: int
    schema_invalid_task_count: int
    benchmark_metrics: tuple[ValidatedBenchmarkMetric, ...]
    language_metrics: tuple[ValidatedLanguageMetric, ...]
    resource_summary: ValidatedInferenceResourceSummary | None
    threshold_observations: tuple[ModelSpikeThresholdObservation, ...]
    benchmark_thresholds_passed: bool
    license_review_status: str
    qlora_smoke_status: str
    adapter_export_load_status: str
    serving_validation_status: str
    selection_readiness: ModelSpikeSelectionReadiness
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.candidate_id, "comparison candidate ID"),
            (self.family_id, "comparison family ID"),
            (self.repository_id, "comparison repository ID"),
            (self.revision, "comparison revision"),
        ):
            if not value or value.strip() != value:
                raise ModelSpikeReportError(f"{label} must be normalized")
        for value, label in (
            (self.declared_parameter_count_millions, "comparison parameter count"),
            (self.declared_context_limit_tokens, "comparison context limit"),
            (self.task_count, "comparison task count"),
            (self.successful_task_count, "comparison successful task count"),
            (self.schema_invalid_task_count, "comparison schema-invalid task count"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ModelSpikeReportError(f"{label} must be a non-negative integer")
        if self.successful_task_count > self.task_count:
            raise ModelSpikeReportError("comparison successful task count exceeds total")
        if self.schema_invalid_task_count > self.task_count:
            raise ModelSpikeReportError("comparison schema-invalid task count exceeds total")
        for value, label in (
            (self.request_sha256, "comparison request digest"),
            (self.source_evidence_content_hash, "comparison source content hash"),
            (self.source_evidence_file_sha256, "comparison source file digest"),
            (self.content_hash, "comparison candidate content hash"),
        ):
            _validate_sha256(value, label=label)
        if self.benchmark_metrics != tuple(
            sorted(self.benchmark_metrics, key=lambda item: item.sort_key)
        ):
            raise ModelSpikeReportError("comparison benchmark metrics are not canonical")
        if self.language_metrics != tuple(
            sorted(self.language_metrics, key=lambda item: item.sort_key)
        ):
            raise ModelSpikeReportError("comparison language metrics are not canonical")
        if self.threshold_observations != tuple(
            sorted(self.threshold_observations, key=lambda item: item.sort_key)
        ):
            raise ModelSpikeReportError("comparison threshold observations are not canonical")
        if len({item.metric_id for item in self.threshold_observations}) != len(
            self.threshold_observations
        ):
            raise ModelSpikeReportError("comparison threshold observations must be unique")
        expected_threshold_state = _benchmark_thresholds_passed(
            self.threshold_observations,
            benchmark_complete=self.benchmark_complete,
        )
        if self.benchmark_thresholds_passed != expected_threshold_state:
            raise ModelSpikeReportError("comparison benchmark threshold state is inconsistent")
        for value, expected, label in (
            (self.license_review_status, "REVIEW_REQUIRED", "license review"),
            (self.qlora_smoke_status, "NOT_RUN", "QLoRA smoke"),
            (self.adapter_export_load_status, "NOT_RUN", "adapter export/load"),
            (self.serving_validation_status, "NOT_RUN", "serving validation"),
        ):
            if value != expected:
                raise ModelSpikeReportError(f"comparison {label} status is inconsistent")
        expected_readiness = _selection_readiness(
            run_status=self.run_status,
            benchmark_thresholds_passed=self.benchmark_thresholds_passed,
        )
        if self.selection_readiness is not expected_readiness:
            raise ModelSpikeReportError("comparison selection readiness is inconsistent")
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeReportError("comparison candidate content hash is inconsistent")

    @property
    def sort_key(self) -> str:
        return self.candidate_id

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "family_id": self.family_id,
            "repository_id": self.repository_id,
            "revision": self.revision,
            "declared_parameter_count_millions": self.declared_parameter_count_millions,
            "declared_context_limit_tokens": self.declared_context_limit_tokens,
            "request_sha256": self.request_sha256,
            "source_evidence_content_hash": self.source_evidence_content_hash,
            "source_evidence_file_sha256": self.source_evidence_file_sha256,
            "run_status": self.run_status.value,
            "benchmark_complete": self.benchmark_complete,
            "task_count": self.task_count,
            "successful_task_count": self.successful_task_count,
            "schema_invalid_task_count": self.schema_invalid_task_count,
            "benchmark_metrics": [item.to_snapshot() for item in self.benchmark_metrics],
            "language_metrics": [item.to_snapshot() for item in self.language_metrics],
            "resource_summary": (
                None if self.resource_summary is None else self.resource_summary.to_snapshot()
            ),
            "threshold_observations": [item.to_snapshot() for item in self.threshold_observations],
            "benchmark_thresholds_passed": self.benchmark_thresholds_passed,
            "license_review_status": self.license_review_status,
            "qlora_smoke_status": self.qlora_smoke_status,
            "adapter_export_load_status": self.adapter_export_load_status,
            "serving_validation_status": self.serving_validation_status,
            "selection_readiness": self.selection_readiness.value,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ModelSpikeComparisonReport:
    """Immutable comparison artifact that deliberately contains no winner or rank."""

    report_id: str
    created_at: datetime
    candidate_matrix_sha256: str
    candidate_matrix_content_hash: str
    benchmark_suite_sha256: str
    benchmark_suite_content_hash: str
    package_lock_sha256: str
    environment_sha256: str
    plan_content_hash: str
    plan_file_sha256: str
    validated_bundle_content_hash: str
    batch_content_hash: str
    batch_file_sha256: str
    selection_status: str
    methodological_notice: str
    pending_evidence: tuple[str, ...]
    candidates: tuple[ModelSpikeCandidateComparison, ...]
    all_live_benchmarks_complete: bool
    ready_for_owner_selection: bool
    content_hash: str
    schema_version: int = MODEL_SPIKE_COMPARISON_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_SPIKE_COMPARISON_REPORT_SCHEMA_VERSION:
            raise ModelSpikeReportError("unsupported comparison report schema")
        if self.report_id != MODEL_SPIKE_COMPARISON_REPORT_ID:
            raise ModelSpikeReportError("unexpected comparison report identity")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ModelSpikeReportError("comparison report timestamp must be timezone-aware")
        for value, label in (
            (self.candidate_matrix_sha256, "comparison matrix file digest"),
            (self.candidate_matrix_content_hash, "comparison matrix content hash"),
            (self.benchmark_suite_sha256, "comparison benchmark file digest"),
            (self.benchmark_suite_content_hash, "comparison benchmark content hash"),
            (self.package_lock_sha256, "comparison package lock digest"),
            (self.environment_sha256, "comparison environment digest"),
            (self.plan_content_hash, "comparison plan content hash"),
            (self.plan_file_sha256, "comparison plan file digest"),
            (self.validated_bundle_content_hash, "comparison validated bundle hash"),
            (self.batch_content_hash, "comparison batch content hash"),
            (self.batch_file_sha256, "comparison batch file digest"),
            (self.content_hash, "comparison report content hash"),
        ):
            _validate_sha256(value, label=label)
        if self.candidate_matrix_sha256 != FROZEN_MODEL_CANDIDATE_MATRIX_SHA256:
            raise ModelSpikeReportError("comparison matrix file identity changed")
        if self.candidate_matrix_content_hash != FROZEN_MODEL_CANDIDATE_MATRIX_CONTENT_HASH:
            raise ModelSpikeReportError("comparison matrix content identity changed")
        if self.benchmark_suite_sha256 != FROZEN_BENCHMARK_SUITE_SHA256:
            raise ModelSpikeReportError("comparison benchmark file identity changed")
        if self.benchmark_suite_content_hash != FROZEN_BENCHMARK_SUITE_CONTENT_HASH:
            raise ModelSpikeReportError("comparison benchmark content identity changed")
        if self.selection_status != MODEL_SPIKE_SELECTION_STATUS:
            raise ModelSpikeReportError("comparison report cannot preselect a model")
        if self.methodological_notice != MODEL_SPIKE_METHODOLOGICAL_NOTICE:
            raise ModelSpikeReportError("comparison methodological notice changed")
        if self.pending_evidence != MODEL_SPIKE_PENDING_EVIDENCE:
            raise ModelSpikeReportError("comparison pending evidence set changed")
        if self.candidates != tuple(sorted(self.candidates, key=lambda item: item.sort_key)):
            raise ModelSpikeReportError("comparison candidates are not canonical")
        if not self.candidates or len({item.candidate_id for item in self.candidates}) != len(
            self.candidates
        ):
            raise ModelSpikeReportError("comparison report requires unique candidates")
        expected_complete = all(item.benchmark_complete for item in self.candidates)
        if self.all_live_benchmarks_complete != expected_complete:
            raise ModelSpikeReportError("comparison benchmark completion is inconsistent")
        if self.ready_for_owner_selection:
            raise ModelSpikeReportError(
                "owner selection is forbidden before pending evidence exists"
            )
        if self.content_hash != snapshot_content_hash(self._semantic_snapshot()):
            raise ModelSpikeReportError("comparison report content hash is inconsistent")

    def _semantic_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "report_id": self.report_id,
            "created_at": self.created_at.isoformat(),
            "candidate_matrix_sha256": self.candidate_matrix_sha256,
            "candidate_matrix_content_hash": self.candidate_matrix_content_hash,
            "benchmark_suite_sha256": self.benchmark_suite_sha256,
            "benchmark_suite_content_hash": self.benchmark_suite_content_hash,
            "package_lock_sha256": self.package_lock_sha256,
            "environment_sha256": self.environment_sha256,
            "plan_content_hash": self.plan_content_hash,
            "plan_file_sha256": self.plan_file_sha256,
            "validated_bundle_content_hash": self.validated_bundle_content_hash,
            "batch_content_hash": self.batch_content_hash,
            "batch_file_sha256": self.batch_file_sha256,
            "selection_status": self.selection_status,
            "methodological_notice": self.methodological_notice,
            "pending_evidence": list(self.pending_evidence),
            "candidates": [item.to_snapshot() for item in self.candidates],
            "all_live_benchmarks_complete": self.all_live_benchmarks_complete,
            "ready_for_owner_selection": self.ready_for_owner_selection,
        }

    def to_snapshot(self) -> dict[str, object]:
        return {**self._semantic_snapshot(), "content_hash": self.content_hash}


def create_model_spike_comparison_report(
    *,
    plan: ModelSpikeExecutionPlan,
    plan_file_sha256: str,
    bundle: ValidatedModelSpikeBundle,
    matrix: FrozenModelCandidateMatrix,
    suite: EvaluatorBenchmarkSuite,
    created_at: datetime,
) -> ModelSpikeComparisonReport:
    """Compare validated live evidence without ranking or selecting a model."""
    if bundle.plan_content_hash != plan.content_hash:
        raise ModelSpikeReportError("validated bundle references a different plan")
    if bundle.plan_file_sha256 != plan_file_sha256:
        raise ModelSpikeReportError("validated bundle plan file digest differs")
    if plan.candidate_matrix_content_hash != matrix.content_hash:
        raise ModelSpikeReportError("comparison plan and candidate matrix differ")
    if plan.benchmark_suite_content_hash != suite.content_hash:
        raise ModelSpikeReportError("comparison plan and benchmark suite differ")
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise ModelSpikeReportError("comparison report timestamp must be timezone-aware")

    plan_ids = {item.candidate_id for item in plan.requests}
    matrix_ids = {item.candidate_id for item in matrix.candidates}
    run_ids = {item.candidate_id for item in bundle.runs}
    if plan_ids != matrix_ids or run_ids != matrix_ids:
        raise ModelSpikeReportError("comparison evidence must cover the frozen candidate matrix")

    runs = {item.candidate_id: item for item in bundle.runs}
    comparisons = tuple(
        sorted(
            (
                _candidate_comparison(
                    candidate=candidate,
                    plan=plan,
                    run=runs[candidate.candidate_id],
                    suite=suite,
                )
                for candidate in matrix.candidates
            ),
            key=lambda item: item.sort_key,
        )
    )
    semantic = {
        "schema_version": MODEL_SPIKE_COMPARISON_REPORT_SCHEMA_VERSION,
        "report_id": MODEL_SPIKE_COMPARISON_REPORT_ID,
        "created_at": created_at.isoformat(),
        "candidate_matrix_sha256": plan.candidate_matrix_sha256,
        "candidate_matrix_content_hash": plan.candidate_matrix_content_hash,
        "benchmark_suite_sha256": plan.benchmark_suite_sha256,
        "benchmark_suite_content_hash": plan.benchmark_suite_content_hash,
        "package_lock_sha256": plan.package_lock_sha256,
        "environment_sha256": plan.environment_sha256,
        "plan_content_hash": plan.content_hash,
        "plan_file_sha256": plan_file_sha256,
        "validated_bundle_content_hash": bundle.content_hash,
        "batch_content_hash": bundle.batch_content_hash,
        "batch_file_sha256": bundle.batch_file_sha256,
        "selection_status": MODEL_SPIKE_SELECTION_STATUS,
        "methodological_notice": MODEL_SPIKE_METHODOLOGICAL_NOTICE,
        "pending_evidence": list(MODEL_SPIKE_PENDING_EVIDENCE),
        "candidates": [item.to_snapshot() for item in comparisons],
        "all_live_benchmarks_complete": all(item.benchmark_complete for item in comparisons),
        "ready_for_owner_selection": False,
    }
    return ModelSpikeComparisonReport(
        report_id=MODEL_SPIKE_COMPARISON_REPORT_ID,
        created_at=created_at,
        candidate_matrix_sha256=plan.candidate_matrix_sha256,
        candidate_matrix_content_hash=plan.candidate_matrix_content_hash,
        benchmark_suite_sha256=plan.benchmark_suite_sha256,
        benchmark_suite_content_hash=plan.benchmark_suite_content_hash,
        package_lock_sha256=plan.package_lock_sha256,
        environment_sha256=plan.environment_sha256,
        plan_content_hash=plan.content_hash,
        plan_file_sha256=plan_file_sha256,
        validated_bundle_content_hash=bundle.content_hash,
        batch_content_hash=bundle.batch_content_hash,
        batch_file_sha256=bundle.batch_file_sha256,
        selection_status=MODEL_SPIKE_SELECTION_STATUS,
        methodological_notice=MODEL_SPIKE_METHODOLOGICAL_NOTICE,
        pending_evidence=MODEL_SPIKE_PENDING_EVIDENCE,
        candidates=comparisons,
        all_live_benchmarks_complete=bool(semantic["all_live_benchmarks_complete"]),
        ready_for_owner_selection=False,
        content_hash=snapshot_content_hash(semantic),
    )


def write_model_spike_comparison_report(
    path: Path,
    report: ModelSpikeComparisonReport,
) -> None:
    """Write one canonical immutable report artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(canonical_json(report.to_snapshot()), encoding="utf-8")
        temporary.replace(path)
    except OSError as error:
        temporary.unlink(missing_ok=True)
        raise ModelSpikeReportError("cannot write model-spike comparison report") from error


def load_model_spike_comparison_report(path: Path) -> ModelSpikeComparisonReport:
    """Load and reconstruct one canonical comparison report."""
    payload = _read_canonical_json(path)
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "report_id",
            "created_at",
            "candidate_matrix_sha256",
            "candidate_matrix_content_hash",
            "benchmark_suite_sha256",
            "benchmark_suite_content_hash",
            "package_lock_sha256",
            "environment_sha256",
            "plan_content_hash",
            "plan_file_sha256",
            "validated_bundle_content_hash",
            "batch_content_hash",
            "batch_file_sha256",
            "selection_status",
            "methodological_notice",
            "pending_evidence",
            "candidates",
            "all_live_benchmarks_complete",
            "ready_for_owner_selection",
            "content_hash",
        },
        label="model-spike comparison report",
    )
    candidate_values = payload.get("candidates")
    if not isinstance(candidate_values, list):
        raise ModelSpikeReportError("comparison candidates must be an array")
    try:
        created_at = datetime.fromisoformat(_required_string(payload, "created_at"))
    except ValueError as error:
        raise ModelSpikeReportError("comparison timestamp must use ISO-8601") from error
    report = ModelSpikeComparisonReport(
        schema_version=_required_integer(payload, "schema_version"),
        report_id=_required_string(payload, "report_id"),
        created_at=created_at,
        candidate_matrix_sha256=_required_string(payload, "candidate_matrix_sha256"),
        candidate_matrix_content_hash=_required_string(payload, "candidate_matrix_content_hash"),
        benchmark_suite_sha256=_required_string(payload, "benchmark_suite_sha256"),
        benchmark_suite_content_hash=_required_string(payload, "benchmark_suite_content_hash"),
        package_lock_sha256=_required_string(payload, "package_lock_sha256"),
        environment_sha256=_required_string(payload, "environment_sha256"),
        plan_content_hash=_required_string(payload, "plan_content_hash"),
        plan_file_sha256=_required_string(payload, "plan_file_sha256"),
        validated_bundle_content_hash=_required_string(payload, "validated_bundle_content_hash"),
        batch_content_hash=_required_string(payload, "batch_content_hash"),
        batch_file_sha256=_required_string(payload, "batch_file_sha256"),
        selection_status=_required_string(payload, "selection_status"),
        methodological_notice=_required_string(payload, "methodological_notice"),
        pending_evidence=_string_tuple(payload, "pending_evidence"),
        candidates=tuple(_parse_candidate(item) for item in candidate_values),
        all_live_benchmarks_complete=_required_boolean(payload, "all_live_benchmarks_complete"),
        ready_for_owner_selection=_required_boolean(payload, "ready_for_owner_selection"),
        content_hash=_required_string(payload, "content_hash"),
    )
    if report.to_snapshot() != payload:
        raise ModelSpikeReportError("comparison report is not a canonical snapshot")
    return report


def _candidate_comparison(
    *,
    candidate: FrozenModelCandidatePreflight,
    plan: ModelSpikeExecutionPlan,
    run: ValidatedModelSpikeRun,
    suite: EvaluatorBenchmarkSuite,
) -> ModelSpikeCandidateComparison:
    request = plan.request(candidate.candidate_id)
    observations = _threshold_observations(run=run, suite=suite)
    thresholds_passed = _benchmark_thresholds_passed(
        observations,
        benchmark_complete=run.benchmark_complete,
    )
    readiness = _selection_readiness(
        run_status=run.status,
        benchmark_thresholds_passed=thresholds_passed,
    )
    semantic = {
        "candidate_id": candidate.candidate_id,
        "family_id": candidate.family_id,
        "repository_id": candidate.repository_id,
        "revision": candidate.revision,
        "declared_parameter_count_millions": candidate.declared_parameter_count_millions,
        "declared_context_limit_tokens": candidate.declared_context_limit_tokens,
        "request_sha256": request.request_sha256,
        "source_evidence_content_hash": request.source_evidence_content_hash,
        "source_evidence_file_sha256": request.source_evidence_file_sha256,
        "run_status": run.status.value,
        "benchmark_complete": run.benchmark_complete,
        "task_count": run.task_count,
        "successful_task_count": run.successful_task_count,
        "schema_invalid_task_count": run.schema_invalid_task_count,
        "benchmark_metrics": [item.to_snapshot() for item in run.benchmark_metrics],
        "language_metrics": [item.to_snapshot() for item in run.language_metrics],
        "resource_summary": (
            None if run.resource_summary is None else run.resource_summary.to_snapshot()
        ),
        "threshold_observations": [item.to_snapshot() for item in observations],
        "benchmark_thresholds_passed": thresholds_passed,
        "license_review_status": "REVIEW_REQUIRED",
        "qlora_smoke_status": "NOT_RUN",
        "adapter_export_load_status": "NOT_RUN",
        "serving_validation_status": "NOT_RUN",
        "selection_readiness": readiness.value,
    }
    return ModelSpikeCandidateComparison(
        candidate_id=candidate.candidate_id,
        family_id=candidate.family_id,
        repository_id=candidate.repository_id,
        revision=candidate.revision,
        declared_parameter_count_millions=candidate.declared_parameter_count_millions,
        declared_context_limit_tokens=candidate.declared_context_limit_tokens,
        request_sha256=request.request_sha256,
        source_evidence_content_hash=request.source_evidence_content_hash,
        source_evidence_file_sha256=request.source_evidence_file_sha256,
        run_status=run.status,
        benchmark_complete=run.benchmark_complete,
        task_count=run.task_count,
        successful_task_count=run.successful_task_count,
        schema_invalid_task_count=run.schema_invalid_task_count,
        benchmark_metrics=run.benchmark_metrics,
        language_metrics=run.language_metrics,
        resource_summary=run.resource_summary,
        threshold_observations=observations,
        benchmark_thresholds_passed=thresholds_passed,
        license_review_status="REVIEW_REQUIRED",
        qlora_smoke_status="NOT_RUN",
        adapter_export_load_status="NOT_RUN",
        serving_validation_status="NOT_RUN",
        selection_readiness=readiness,
        content_hash=snapshot_content_hash(semantic),
    )


def _threshold_observations(
    *,
    run: ValidatedModelSpikeRun,
    suite: EvaluatorBenchmarkSuite,
) -> tuple[ModelSpikeThresholdObservation, ...]:
    observed = {item.metric_id: item.value for item in run.benchmark_metrics}
    observations = [
        ModelSpikeThresholdObservation(
            metric_id=definition.metric_id.value,
            direction=definition.direction.value,
            threshold=definition.threshold,
            observed_value=observed.get(definition.metric_id.value),
            status=_threshold_status(
                direction=definition.direction.value,
                threshold=definition.threshold,
                observed=observed.get(definition.metric_id.value),
            ),
        )
        for definition in suite.metrics
    ]
    return tuple(sorted(observations, key=lambda item: item.sort_key))


def _threshold_status(
    *,
    direction: str,
    threshold: float | None,
    observed: float | None,
) -> ModelSpikeThresholdStatus:
    if threshold is None:
        return ModelSpikeThresholdStatus.NOT_APPLICABLE
    if observed is None:
        return ModelSpikeThresholdStatus.NOT_OBSERVED
    if direction == BenchmarkMetricDirection.MAXIMIZE.value:
        passed = observed >= threshold
    elif direction == BenchmarkMetricDirection.MINIMIZE.value:
        passed = observed <= threshold
    else:
        raise ModelSpikeReportError("comparison threshold direction is unsupported")
    return ModelSpikeThresholdStatus.PASSED if passed else ModelSpikeThresholdStatus.FAILED


def _benchmark_thresholds_passed(
    observations: tuple[ModelSpikeThresholdObservation, ...],
    *,
    benchmark_complete: bool,
) -> bool:
    if not benchmark_complete:
        return False
    applicable = tuple(
        item
        for item in observations
        if item.threshold is not None
        and item.metric_id != BenchmarkMetricId.ADAPTER_EXPORT_LOAD.value
    )
    return bool(applicable) and all(
        item.status is ModelSpikeThresholdStatus.PASSED for item in applicable
    )


def _selection_readiness(
    *,
    run_status: ValidatedModelSpikeStatus,
    benchmark_thresholds_passed: bool,
) -> ModelSpikeSelectionReadiness:
    if run_status is not ValidatedModelSpikeStatus.BENCHMARK_COMPLETED:
        return ModelSpikeSelectionReadiness.INFERENCE_INCOMPLETE
    if not benchmark_thresholds_passed:
        return ModelSpikeSelectionReadiness.BENCHMARK_REVIEW_REQUIRED
    return ModelSpikeSelectionReadiness.READY_FOR_LICENSE_AND_QLORA_REVIEW


def _parse_candidate(value: object) -> ModelSpikeCandidateComparison:
    payload = _mapping(value, label="comparison candidate")
    benchmark_values = _required_list(payload, "benchmark_metrics")
    language_values = _required_list(payload, "language_metrics")
    threshold_values = _required_list(payload, "threshold_observations")
    resource_value = payload.get("resource_summary")
    resource = None if resource_value is None else _parse_resource(resource_value)
    return ModelSpikeCandidateComparison(
        candidate_id=_required_string(payload, "candidate_id"),
        family_id=_required_string(payload, "family_id"),
        repository_id=_required_string(payload, "repository_id"),
        revision=_required_string(payload, "revision"),
        declared_parameter_count_millions=_required_integer(
            payload, "declared_parameter_count_millions"
        ),
        declared_context_limit_tokens=_required_integer(payload, "declared_context_limit_tokens"),
        request_sha256=_required_string(payload, "request_sha256"),
        source_evidence_content_hash=_required_string(payload, "source_evidence_content_hash"),
        source_evidence_file_sha256=_required_string(payload, "source_evidence_file_sha256"),
        run_status=ValidatedModelSpikeStatus(_required_string(payload, "run_status")),
        benchmark_complete=_required_boolean(payload, "benchmark_complete"),
        task_count=_required_integer(payload, "task_count"),
        successful_task_count=_required_integer(payload, "successful_task_count"),
        schema_invalid_task_count=_required_integer(payload, "schema_invalid_task_count"),
        benchmark_metrics=tuple(_parse_metric(item) for item in benchmark_values),
        language_metrics=tuple(_parse_language_metric(item) for item in language_values),
        resource_summary=resource,
        threshold_observations=tuple(_parse_threshold(item) for item in threshold_values),
        benchmark_thresholds_passed=_required_boolean(payload, "benchmark_thresholds_passed"),
        license_review_status=_required_string(payload, "license_review_status"),
        qlora_smoke_status=_required_string(payload, "qlora_smoke_status"),
        adapter_export_load_status=_required_string(payload, "adapter_export_load_status"),
        serving_validation_status=_required_string(payload, "serving_validation_status"),
        selection_readiness=ModelSpikeSelectionReadiness(
            _required_string(payload, "selection_readiness")
        ),
        content_hash=_required_string(payload, "content_hash"),
    )


def _parse_metric(value: object) -> ValidatedBenchmarkMetric:
    payload = _mapping(value, label="comparison benchmark metric")
    raw_value = _optional_number(payload, "value")
    return ValidatedBenchmarkMetric(
        metric_id=_required_string(payload, "metric_id"),
        value=raw_value,
        sample_count=_required_integer(payload, "sample_count"),
    )


def _parse_language_metric(value: object) -> ValidatedLanguageMetric:
    payload = _mapping(value, label="comparison language metric")
    return ValidatedLanguageMetric(
        language=_required_string(payload, "language"),
        metric_id=_required_string(payload, "metric_id"),
        value=_optional_number(payload, "value"),
        sample_count=_required_integer(payload, "sample_count"),
    )


def _parse_threshold(value: object) -> ModelSpikeThresholdObservation:
    payload = _mapping(value, label="comparison threshold observation")
    return ModelSpikeThresholdObservation(
        metric_id=_required_string(payload, "metric_id"),
        direction=_required_string(payload, "direction"),
        threshold=_optional_number(payload, "threshold"),
        observed_value=_optional_number(payload, "observed_value"),
        status=ModelSpikeThresholdStatus(_required_string(payload, "status")),
    )


def _parse_resource(value: object) -> ValidatedInferenceResourceSummary:
    payload = _mapping(value, label="comparison resource summary")
    peak = payload.get("peak_gpu_memory_mb")
    if peak is not None and (isinstance(peak, bool) or not isinstance(peak, int)):
        raise ModelSpikeReportError("comparison peak GPU memory must be an integer or null")
    return ValidatedInferenceResourceSummary(
        candidate_id=_required_string(payload, "candidate_id"),
        measurement_count=_required_integer(payload, "measurement_count"),
        successful_count=_required_integer(payload, "successful_count"),
        mean_latency_milliseconds=_optional_number(payload, "mean_latency_milliseconds"),
        peak_gpu_memory_mb=peak,
        complete=_required_boolean(payload, "complete"),
    )


def _read_canonical_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ModelSpikeReportError("comparison report must be a regular file")
    raw = path.read_bytes()
    if len(raw) > _MAX_REPORT_BYTES:
        raise ModelSpikeReportError("comparison report exceeds the size limit")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSpikeReportError("comparison report must be UTF-8 JSON") from error
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        raise ModelSpikeReportError("comparison report must contain a JSON object")
    if raw != canonical_json(payload).encode("utf-8"):
        raise ModelSpikeReportError("comparison report must use canonical JSON")
    return payload


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ModelSpikeReportError(f"{label} must be an object")
    return value


def _required_list(payload: Mapping[str, object], key: str) -> list[object]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ModelSpikeReportError(f"{key} must be an array")
    return value


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ModelSpikeReportError(f"{key} must be a normalized string")
    return value


def _required_integer(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ModelSpikeReportError(f"{key} must be an integer")
    return value


def _required_boolean(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ModelSpikeReportError(f"{key} must be boolean")
    return value


def _optional_number(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ModelSpikeReportError(f"{key} must be numeric or null")
    return float(value)


def _string_tuple(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item and item.strip() == item for item in value
    ):
        raise ModelSpikeReportError(f"{key} must contain normalized strings")
    return tuple(value)


def _require_exact_keys(
    payload: Mapping[str, object],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(payload) != expected:
        raise ModelSpikeReportError(f"{label} fields do not match schema version 1")


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ModelSpikeReportError(f"{label} must use lowercase SHA-256")
