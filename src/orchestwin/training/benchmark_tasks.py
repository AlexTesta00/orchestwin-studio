"""Frozen bilingual benchmark tasks and auditable evaluator metric definitions."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.dataset_examples import DatasetLanguage

BENCHMARK_TASK_SCHEMA_VERSION: Final = 1
BENCHMARK_SUITE_SCHEMA_VERSION: Final = 1

_TASK_ID_PATTERN: Final = re.compile(r"bench-(en|it)-[0-9]{3,6}")
_SUITE_ID_PATTERN: Final = re.compile(r"evaluator-benchmark-[a-z0-9][a-z0-9-]{2,95}")
_MAX_TEXT_LENGTH: Final = 8_000
_MAX_REFERENCE_LENGTH: Final = 512


class BenchmarkTaskCategory(StrEnum):
    """Protocol behaviors isolated by the model-feasibility spike."""

    SCHEMA_AND_PROVENANCE = "SCHEMA_AND_PROVENANCE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    ABSTENTION = "ABSTENTION"
    ROLE_ADHERENCE = "ROLE_ADHERENCE"
    CRITERION_AND_SEVERITY = "CRITERION_AND_SEVERITY"
    CONTEXT_HANDLING = "CONTEXT_HANDLING"


class BenchmarkMetricDirection(StrEnum):
    """Whether larger or smaller metric values are preferable."""

    MAXIMIZE = "MAXIMIZE"
    MINIMIZE = "MINIMIZE"


class BenchmarkMetricId(StrEnum):
    """Stable automatic and resource metrics required by the spike."""

    SCHEMA_VALID_RATE = "schema_valid_rate"
    EVIDENCE_REFERENCE_PRECISION = "evidence_reference_precision"
    UNSUPPORTED_CLAIM_RATE = "unsupported_claim_rate"
    ABSTENTION_ACCURACY = "abstention_accuracy"
    ROLE_ADHERENCE = "role_adherence"
    CRITERION_AGREEMENT = "criterion_agreement"
    SEVERITY_AGREEMENT = "severity_agreement"
    CONTEXT_REFERENCE_RECALL = "context_reference_recall"
    LATENCY_MILLISECONDS = "latency_milliseconds"
    PEAK_GPU_MEMORY_MB = "peak_gpu_memory_mb"
    ADAPTER_EXPORT_LOAD = "adapter_export_load"


@dataclass(frozen=True, slots=True)
class BenchmarkEvidenceItem:
    """One exact model-visible evidence item and its allowed reference."""

    reference_id: str
    text: str

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.reference_id, "benchmark evidence reference", _MAX_REFERENCE_LENGTH),
            (self.text, "benchmark evidence text", _MAX_TEXT_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum) != value:
                raise ValueError(f"{label} must be normalized")

    @property
    def sort_key(self) -> str:
        return self.reference_id

    def to_snapshot(self) -> dict[str, object]:
        return {"reference_id": self.reference_id, "text": self.text}


@dataclass(frozen=True, slots=True)
class BenchmarkExpectedEvaluation:
    """Frozen labels used to score one evaluator response without prompt tuning."""

    should_abstain: bool
    minimum_findings: int
    maximum_findings: int
    allowed_evidence_refs: tuple[str, ...]
    required_evidence_refs: tuple[str, ...]
    expected_criteria: tuple[SyntheticFindingCriterion, ...]
    expected_severities: tuple[SyntheticFindingSeverity, ...]
    required_role_terms: tuple[str, ...]
    forbidden_claim_fragments: tuple[str, ...]

    def __post_init__(self) -> None:
        if isinstance(self.minimum_findings, bool) or self.minimum_findings < 0:
            raise ValueError("benchmark minimum findings must be a non-negative integer")
        if self.should_abstain and self.minimum_findings != 0:
            raise ValueError("abstention tasks cannot require findings")
        if isinstance(self.maximum_findings, bool) or self.maximum_findings < self.minimum_findings:
            raise ValueError("benchmark maximum findings must not be below the minimum")
        _require_sorted_unique(self.allowed_evidence_refs, label="allowed evidence references")
        _require_sorted_unique(self.required_evidence_refs, label="required evidence references")
        if not set(self.required_evidence_refs).issubset(self.allowed_evidence_refs):
            raise ValueError("required evidence references must be allowed")
        _require_enum_order(self.expected_criteria, label="expected criteria")
        _require_enum_order(self.expected_severities, label="expected severities")
        for values, label in (
            (self.required_role_terms, "required role terms"),
            (self.forbidden_claim_fragments, "forbidden claim fragments"),
        ):
            normalized = normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_REFERENCE_LENGTH,
                require_items=False,
            )
            if values != tuple(sorted(normalized, key=str.casefold)):
                raise ValueError(f"{label} must be normalized, unique, and canonically ordered")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "should_abstain": self.should_abstain,
            "minimum_findings": self.minimum_findings,
            "maximum_findings": self.maximum_findings,
            "allowed_evidence_refs": list(self.allowed_evidence_refs),
            "required_evidence_refs": list(self.required_evidence_refs),
            "expected_criteria": [value.value for value in self.expected_criteria],
            "expected_severities": [value.value for value in self.expected_severities],
            "required_role_terms": list(self.required_role_terms),
            "forbidden_claim_fragments": list(self.forbidden_claim_fragments),
        }


@dataclass(frozen=True, slots=True)
class EvaluatorBenchmarkTask:
    """One immutable benchmark task with frozen protocol expectations."""

    task_id: str
    version_number: int
    category: BenchmarkTaskCategory
    language: DatasetLanguage
    profile_summary: str
    scenario: str
    target_task: str
    artifact_summary: str
    evidence: tuple[BenchmarkEvidenceItem, ...]
    expected: BenchmarkExpectedEvaluation
    content_hash: str
    schema_version: int = BENCHMARK_TASK_SCHEMA_VERSION

    def __post_init__(self) -> None:
        match = _TASK_ID_PATTERN.fullmatch(self.task_id)
        if match is None:
            raise ValueError("benchmark task ID must use bench-<language>-NNN")
        if match.group(1) != self.language.value:
            raise ValueError("benchmark task ID language must match the declared language")
        validate_positive_integer(self.version_number, label="benchmark task version")
        if self.schema_version != BENCHMARK_TASK_SCHEMA_VERSION:
            raise ValueError("unsupported benchmark task schema version")
        for value, label in (
            (self.profile_summary, "benchmark profile summary"),
            (self.scenario, "benchmark scenario"),
            (self.target_task, "benchmark target task"),
            (self.artifact_summary, "benchmark artifact summary"),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=_MAX_TEXT_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")
        if not self.evidence:
            raise ValueError("benchmark task evidence must not be empty")
        if self.evidence != tuple(sorted(self.evidence, key=lambda item: item.sort_key)):
            raise ValueError("benchmark task evidence must use canonical order")
        if len({item.reference_id for item in self.evidence}) != len(self.evidence):
            raise ValueError("benchmark task evidence references must be unique")
        available_refs = {item.reference_id for item in self.evidence}
        if set(self.expected.allowed_evidence_refs) != available_refs:
            raise ValueError("benchmark allowed evidence references must match supplied evidence")
        validate_sha256(self.content_hash, label="benchmark task content hash")
        if self.content_hash != benchmark_task_hash(
            task_id=self.task_id,
            version_number=self.version_number,
            category=self.category,
            language=self.language,
            profile_summary=self.profile_summary,
            scenario=self.scenario,
            target_task=self.target_task,
            artifact_summary=self.artifact_summary,
            evidence=self.evidence,
            expected=self.expected,
            schema_version=self.schema_version,
        ):
            raise ValueError("benchmark task content hash is inconsistent")

    @property
    def sort_key(self) -> tuple[str, int]:
        return (self.task_id, self.version_number)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "version_number": self.version_number,
            "category": self.category.value,
            "language": self.language.value,
            "profile_summary": self.profile_summary,
            "scenario": self.scenario,
            "target_task": self.target_task,
            "artifact_summary": self.artifact_summary,
            "evidence": [item.to_snapshot() for item in self.evidence],
            "expected": self.expected.to_snapshot(),
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class BenchmarkMetricDefinition:
    """One frozen metric, direction, ranking weight, and acceptance threshold."""

    metric_id: BenchmarkMetricId
    direction: BenchmarkMetricDirection
    ranking_weight: int
    threshold: float | None

    def __post_init__(self) -> None:
        validate_positive_integer(self.ranking_weight, label="benchmark metric ranking weight")
        if self.threshold is not None and not 0.0 <= self.threshold <= 1.0:
            raise ValueError("normalized benchmark metric threshold must be between zero and one")
        normalized_metrics = {
            BenchmarkMetricId.SCHEMA_VALID_RATE,
            BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION,
            BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE,
            BenchmarkMetricId.ABSTENTION_ACCURACY,
            BenchmarkMetricId.ROLE_ADHERENCE,
            BenchmarkMetricId.CRITERION_AGREEMENT,
            BenchmarkMetricId.SEVERITY_AGREEMENT,
            BenchmarkMetricId.CONTEXT_REFERENCE_RECALL,
            BenchmarkMetricId.ADAPTER_EXPORT_LOAD,
        }
        if self.metric_id not in normalized_metrics and self.threshold is not None:
            raise ValueError("resource metrics cannot use normalized acceptance thresholds")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id.value,
            "direction": self.direction.value,
            "ranking_weight": self.ranking_weight,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class EvaluatorBenchmarkSuite:
    """Frozen bilingual task and metric manifest used for every candidate."""

    suite_id: str
    version_number: int
    tasks: tuple[EvaluatorBenchmarkTask, ...]
    metrics: tuple[BenchmarkMetricDefinition, ...]
    source_manifest_sha256: str
    frozen_at: datetime
    content_hash: str
    schema_version: int = BENCHMARK_SUITE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if _SUITE_ID_PATTERN.fullmatch(self.suite_id) is None:
            raise ValueError("benchmark suite ID must use evaluator-benchmark-<slug>")
        validate_positive_integer(self.version_number, label="benchmark suite version")
        if self.schema_version != BENCHMARK_SUITE_SCHEMA_VERSION:
            raise ValueError("unsupported benchmark suite schema version")
        if not self.tasks:
            raise ValueError("benchmark suite tasks must not be empty")
        if self.tasks != tuple(sorted(self.tasks, key=lambda item: item.sort_key)):
            raise ValueError("benchmark suite tasks must use canonical order")
        if len({item.sort_key for item in self.tasks}) != len(self.tasks):
            raise ValueError("benchmark suite task identities must be unique")
        languages = {item.language for item in self.tasks}
        if languages != {DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN}:
            raise ValueError("benchmark suite must contain English and Italian tasks")
        expected_metric_order = tuple(sorted(self.metrics, key=lambda item: item.metric_id.value))
        if self.metrics != expected_metric_order:
            raise ValueError("benchmark suite metrics must use canonical order")
        if len({item.metric_id for item in self.metrics}) != len(self.metrics):
            raise ValueError("benchmark suite metrics must be unique")
        if {item.metric_id for item in self.metrics} != set(BenchmarkMetricId):
            raise ValueError("benchmark suite must define every required metric")
        validate_sha256(self.source_manifest_sha256, label="benchmark source manifest digest")
        if self.frozen_at.tzinfo is None or self.frozen_at.utcoffset() is None:
            raise ValueError("benchmark suite freeze timestamp must be timezone-aware")
        validate_sha256(self.content_hash, label="benchmark suite content hash")
        if self.content_hash != benchmark_suite_hash(
            suite_id=self.suite_id,
            version_number=self.version_number,
            tasks=self.tasks,
            metrics=self.metrics,
            source_manifest_sha256=self.source_manifest_sha256,
            frozen_at=self.frozen_at,
            schema_version=self.schema_version,
        ):
            raise ValueError("benchmark suite content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "suite_id": self.suite_id,
            "version_number": self.version_number,
            "tasks": [item.to_snapshot() for item in self.tasks],
            "metrics": [item.to_snapshot() for item in self.metrics],
            "source_manifest_sha256": self.source_manifest_sha256,
            "frozen_at": self.frozen_at.isoformat(),
            "content_hash": self.content_hash,
        }


def create_benchmark_task(
    *,
    task_id: str,
    version_number: int,
    category: BenchmarkTaskCategory,
    language: DatasetLanguage,
    profile_summary: str,
    scenario: str,
    target_task: str,
    artifact_summary: str,
    evidence: Iterable[BenchmarkEvidenceItem],
    expected: BenchmarkExpectedEvaluation,
) -> EvaluatorBenchmarkTask:
    """Create one canonical immutable task."""
    canonical_evidence = tuple(sorted(evidence, key=lambda item: item.sort_key))
    content_hash = benchmark_task_hash(
        task_id=task_id,
        version_number=version_number,
        category=category,
        language=language,
        profile_summary=profile_summary,
        scenario=scenario,
        target_task=target_task,
        artifact_summary=artifact_summary,
        evidence=canonical_evidence,
        expected=expected,
        schema_version=BENCHMARK_TASK_SCHEMA_VERSION,
    )
    return EvaluatorBenchmarkTask(
        task_id=task_id,
        version_number=version_number,
        category=category,
        language=language,
        profile_summary=profile_summary,
        scenario=scenario,
        target_task=target_task,
        artifact_summary=artifact_summary,
        evidence=canonical_evidence,
        expected=expected,
        content_hash=content_hash,
    )


def create_benchmark_suite(
    *,
    suite_id: str,
    version_number: int,
    tasks: Iterable[EvaluatorBenchmarkTask],
    source_manifest_sha256: str,
    frozen_at: datetime,
    metrics: Iterable[BenchmarkMetricDefinition] | None = None,
) -> EvaluatorBenchmarkSuite:
    """Freeze task identities and metric policy before candidate ranking."""
    canonical_tasks = tuple(sorted(tasks, key=lambda item: item.sort_key))
    canonical_metrics = tuple(
        sorted(
            default_benchmark_metric_definitions() if metrics is None else tuple(metrics),
            key=lambda item: item.metric_id.value,
        )
    )
    content_hash = benchmark_suite_hash(
        suite_id=suite_id,
        version_number=version_number,
        tasks=canonical_tasks,
        metrics=canonical_metrics,
        source_manifest_sha256=source_manifest_sha256,
        frozen_at=frozen_at,
        schema_version=BENCHMARK_SUITE_SCHEMA_VERSION,
    )
    return EvaluatorBenchmarkSuite(
        suite_id=suite_id,
        version_number=version_number,
        tasks=canonical_tasks,
        metrics=canonical_metrics,
        source_manifest_sha256=source_manifest_sha256,
        frozen_at=frozen_at,
        content_hash=content_hash,
    )


def default_benchmark_metric_definitions() -> tuple[BenchmarkMetricDefinition, ...]:
    """Return the complete frozen metric set used by the first model spike."""
    directions = {
        BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE: BenchmarkMetricDirection.MINIMIZE,
        BenchmarkMetricId.LATENCY_MILLISECONDS: BenchmarkMetricDirection.MINIMIZE,
        BenchmarkMetricId.PEAK_GPU_MEMORY_MB: BenchmarkMetricDirection.MINIMIZE,
    }
    thresholds = {
        BenchmarkMetricId.SCHEMA_VALID_RATE: 1.0,
        BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION: 1.0,
        BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE: 0.0,
        BenchmarkMetricId.ABSTENTION_ACCURACY: 1.0,
        BenchmarkMetricId.ROLE_ADHERENCE: 0.5,
        BenchmarkMetricId.CONTEXT_REFERENCE_RECALL: 0.5,
        BenchmarkMetricId.ADAPTER_EXPORT_LOAD: 1.0,
    }
    return tuple(
        BenchmarkMetricDefinition(
            metric_id=metric_id,
            direction=directions.get(metric_id, BenchmarkMetricDirection.MAXIMIZE),
            ranking_weight=2 if metric_id in thresholds else 1,
            threshold=thresholds.get(metric_id),
        )
        for metric_id in sorted(BenchmarkMetricId, key=lambda item: item.value)
    )


def benchmark_task_hash(
    *,
    task_id: str,
    version_number: int,
    category: BenchmarkTaskCategory,
    language: DatasetLanguage,
    profile_summary: str,
    scenario: str,
    target_task: str,
    artifact_summary: str,
    evidence: tuple[BenchmarkEvidenceItem, ...],
    expected: BenchmarkExpectedEvaluation,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "task_id": task_id,
            "version_number": version_number,
            "category": category.value,
            "language": language.value,
            "profile_summary": profile_summary,
            "scenario": scenario,
            "target_task": target_task,
            "artifact_summary": artifact_summary,
            "evidence": [item.to_snapshot() for item in evidence],
            "expected": expected.to_snapshot(),
        }
    )


def benchmark_suite_hash(
    *,
    suite_id: str,
    version_number: int,
    tasks: tuple[EvaluatorBenchmarkTask, ...],
    metrics: tuple[BenchmarkMetricDefinition, ...],
    source_manifest_sha256: str,
    frozen_at: datetime,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "suite_id": suite_id,
            "version_number": version_number,
            "task_refs": [
                {
                    "task_id": item.task_id,
                    "version_number": item.version_number,
                    "content_hash": item.content_hash,
                }
                for item in tasks
            ],
            "metrics": [item.to_snapshot() for item in metrics],
            "source_manifest_sha256": source_manifest_sha256,
            "frozen_at": frozen_at.isoformat(),
        }
    )


def _require_sorted_unique(values: tuple[str, ...], *, label: str) -> None:
    normalized = normalize_text_items(
        values,
        label=label,
        maximum_item_length=_MAX_REFERENCE_LENGTH,
        require_items=False,
    )
    if values != tuple(sorted(normalized)):
        raise ValueError(f"benchmark {label} must be normalized, unique, and canonically ordered")


def _require_enum_order(values: tuple[StrEnum, ...], *, label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"benchmark {label} must be unique")
    if values != tuple(sorted(values, key=lambda item: item.value)):
        raise ValueError(f"benchmark {label} must use canonical order")
