"""Deterministic metric formulas for reproducible formal case-study reporting."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from statistics import fmean


def _ratio(completed: int, total: int) -> float | None:
    if total == 0:
        return None
    return completed / total


def _validate_count_pair(*, completed: int, total: int, label: str) -> None:
    if completed < 0 or total < 0:
        raise ValueError(f"{label} counts must not be negative")
    if completed > total:
        raise ValueError(f"{label} completed count must not exceed total")


def _hash(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaseStudyMeasurement:
    """Raw case evidence counts from which all reported ratios are derived."""

    case_id: str
    gates_completed: int
    gates_total: int
    artifacts_completed: int
    artifacts_total: int
    requirements_satisfied: int
    requirements_total: int
    criteria_satisfied: int
    criteria_total: int
    traceability_links_present: int
    traceability_links_required: int
    tests_passed: int
    tests_total: int
    repair_successes: int
    repair_attempts: int
    build_succeeded: bool
    final_runtime_succeeded: bool
    elapsed_seconds: float
    model_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float

    def __post_init__(self) -> None:
        for completed, total, label in (
            (self.gates_completed, self.gates_total, "gate"),
            (self.artifacts_completed, self.artifacts_total, "artifact"),
            (self.requirements_satisfied, self.requirements_total, "requirement"),
            (self.criteria_satisfied, self.criteria_total, "acceptance criterion"),
            (
                self.traceability_links_present,
                self.traceability_links_required,
                "traceability",
            ),
            (self.tests_passed, self.tests_total, "test"),
            (self.repair_successes, self.repair_attempts, "repair"),
        ):
            _validate_count_pair(completed=completed, total=total, label=label)
        if self.elapsed_seconds < 0:
            raise ValueError("elapsed time must not be negative")
        if min(self.model_calls, self.input_tokens, self.output_tokens) < 0:
            raise ValueError("model usage counts must not be negative")
        if self.estimated_cost_usd < 0:
            raise ValueError("estimated cost must not be negative")

    def metric_snapshot(self) -> dict[str, object]:
        """Return formulas and raw counts without inventing values for missing denominators."""
        snapshot: dict[str, object] = {
            "case_id": self.case_id,
            "gate_completion_ratio": _ratio(self.gates_completed, self.gates_total),
            "artifact_completion_ratio": _ratio(
                self.artifacts_completed,
                self.artifacts_total,
            ),
            "requirement_satisfaction_ratio": _ratio(
                self.requirements_satisfied,
                self.requirements_total,
            ),
            "acceptance_criterion_satisfaction_ratio": _ratio(
                self.criteria_satisfied,
                self.criteria_total,
            ),
            "traceability_coverage_ratio": _ratio(
                self.traceability_links_present,
                self.traceability_links_required,
            ),
            "test_pass_ratio": _ratio(self.tests_passed, self.tests_total),
            "repair_success_ratio": _ratio(self.repair_successes, self.repair_attempts),
            "build_succeeded": self.build_succeeded,
            "final_runtime_succeeded": self.final_runtime_succeeded,
            "elapsed_seconds": self.elapsed_seconds,
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "estimated_cost_usd": self.estimated_cost_usd,
        }
        snapshot["content_hash"] = _hash(snapshot)
        return snapshot


@dataclass(frozen=True, slots=True)
class AggregateCaseStudyMetrics:
    """Descriptive aggregate across formal cases, preserving missing ratios as missing."""

    case_count: int
    mean_gate_completion_ratio: float | None
    mean_artifact_completion_ratio: float | None
    mean_requirement_satisfaction_ratio: float | None
    mean_acceptance_criterion_satisfaction_ratio: float | None
    mean_traceability_coverage_ratio: float | None
    mean_test_pass_ratio: float | None
    mean_repair_success_ratio: float | None
    build_success_count: int
    runtime_success_count: int
    total_elapsed_seconds: float
    total_model_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_estimated_cost_usd: float


def _mean_available(values: list[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return fmean(available) if available else None


def aggregate_case_study_metrics(
    measurements: tuple[CaseStudyMeasurement, ...],
) -> AggregateCaseStudyMetrics:
    """Aggregate raw measurements using descriptive statistics only."""
    if not measurements:
        raise ValueError("at least one case-study measurement is required")
    snapshots = [measurement.metric_snapshot() for measurement in measurements]
    return AggregateCaseStudyMetrics(
        case_count=len(measurements),
        mean_gate_completion_ratio=_mean_available(
            [snapshot["gate_completion_ratio"] for snapshot in snapshots]
        ),
        mean_artifact_completion_ratio=_mean_available(
            [snapshot["artifact_completion_ratio"] for snapshot in snapshots]
        ),
        mean_requirement_satisfaction_ratio=_mean_available(
            [snapshot["requirement_satisfaction_ratio"] for snapshot in snapshots]
        ),
        mean_acceptance_criterion_satisfaction_ratio=_mean_available(
            [snapshot["acceptance_criterion_satisfaction_ratio"] for snapshot in snapshots]
        ),
        mean_traceability_coverage_ratio=_mean_available(
            [snapshot["traceability_coverage_ratio"] for snapshot in snapshots]
        ),
        mean_test_pass_ratio=_mean_available(
            [snapshot["test_pass_ratio"] for snapshot in snapshots]
        ),
        mean_repair_success_ratio=_mean_available(
            [snapshot["repair_success_ratio"] for snapshot in snapshots]
        ),
        build_success_count=sum(item.build_succeeded for item in measurements),
        runtime_success_count=sum(item.final_runtime_succeeded for item in measurements),
        total_elapsed_seconds=sum(item.elapsed_seconds for item in measurements),
        total_model_calls=sum(item.model_calls for item in measurements),
        total_input_tokens=sum(item.input_tokens for item in measurements),
        total_output_tokens=sum(item.output_tokens for item in measurements),
        total_estimated_cost_usd=sum(item.estimated_cost_usd for item in measurements),
    )
