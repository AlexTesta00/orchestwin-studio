"""Auditable hard constraints and deterministic ranking for model-spike evidence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.training.benchmark_tasks import BenchmarkMetricId
from orchestwin.training.benchmarking import EvaluatorBenchmarkRun
from orchestwin.training.dataset_examples import DatasetLanguage
from orchestwin.training.environment_evidence import (
    AdapterExportLoadEvidence,
    InferenceResourceSummary,
    TrainingEnvironmentSnapshot,
)
from orchestwin.training.model_candidates import (
    ModelBenchmarkCandidate,
    ModelCandidateAvailability,
    ModelLicenseCompatibility,
)

MODEL_RANKING_POLICY_SCHEMA_VERSION: Final = 1
MODEL_RANKING_SCHEMA_VERSION: Final = 1
_MAX_IDENTIFIER_LENGTH: Final = 256


class ModelRankingThresholdDirection(StrEnum):
    """Direction used by one hard protocol threshold."""

    MINIMUM = "MINIMUM"
    MAXIMUM = "MAXIMUM"


class ModelRankingComponent(StrEnum):
    """Normalized components used only after all hard constraints pass."""

    PROTOCOL_QUALITY = "PROTOCOL_QUALITY"
    LATENCY = "LATENCY"
    GPU_MEMORY = "GPU_MEMORY"
    CONTEXT_CAPACITY = "CONTEXT_CAPACITY"


class ModelRankingExclusionReason(StrEnum):
    """Stable reasons that make a candidate ineligible for owner selection."""

    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    NOT_INSTRUCT_TUNED = "NOT_INSTRUCT_TUNED"
    LANGUAGE_COVERAGE_MISSING = "LANGUAGE_COVERAGE_MISSING"
    LICENSE_INCOMPATIBLE = "LICENSE_INCOMPATIBLE"
    ADAPTER_REDISTRIBUTION_NOT_ALLOWED = "ADAPTER_REDISTRIBUTION_NOT_ALLOWED"
    CONTEXT_LIMIT_TOO_SMALL = "CONTEXT_LIMIT_TOO_SMALL"
    SERVING_RUNTIME_UNSUPPORTED = "SERVING_RUNTIME_UNSUPPORTED"
    BENCHMARK_SUITE_MISMATCH = "BENCHMARK_SUITE_MISMATCH"
    BENCHMARK_INCOMPLETE = "BENCHMARK_INCOMPLETE"
    PROTOCOL_THRESHOLD_FAILED = "PROTOCOL_THRESHOLD_FAILED"
    ENVIRONMENT_EVIDENCE_INCOMPLETE = "ENVIRONMENT_EVIDENCE_INCOMPLETE"
    RESOURCE_EVIDENCE_INCOMPLETE = "RESOURCE_EVIDENCE_INCOMPLETE"
    GPU_MEMORY_LIMIT_EXCEEDED = "GPU_MEMORY_LIMIT_EXCEEDED"
    LATENCY_LIMIT_EXCEEDED = "LATENCY_LIMIT_EXCEEDED"
    ADAPTER_SMOKE_FAILED = "ADAPTER_SMOKE_FAILED"
    MODEL_IDENTITY_MISMATCH = "MODEL_IDENTITY_MISMATCH"


@dataclass(frozen=True, slots=True)
class ModelRankingThreshold:
    """One normalized metric threshold applied before weighted ranking."""

    metric_id: BenchmarkMetricId
    direction: ModelRankingThresholdDirection
    value: float

    def __post_init__(self) -> None:
        if self.metric_id in {
            BenchmarkMetricId.LATENCY_MILLISECONDS,
            BenchmarkMetricId.PEAK_GPU_MEMORY_MB,
            BenchmarkMetricId.ADAPTER_EXPORT_LOAD,
        }:
            raise ValueError("resource and adapter checks use dedicated hard constraints")
        if isinstance(self.value, bool) or not 0.0 <= self.value <= 1.0:
            raise ValueError("model ranking threshold must be between zero and one")

    def accepts(self, observed: float) -> bool:
        if self.direction is ModelRankingThresholdDirection.MINIMUM:
            return observed >= self.value
        return observed <= self.value

    def to_snapshot(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id.value,
            "direction": self.direction.value,
            "value": self.value,
        }


@dataclass(frozen=True, slots=True)
class ModelRankingWeight:
    """Integer weight for one post-eligibility ranking component."""

    component: ModelRankingComponent
    weight: int

    def __post_init__(self) -> None:
        validate_positive_integer(self.weight, label="model ranking component weight")

    def to_snapshot(self) -> dict[str, object]:
        return {"component": self.component.value, "weight": self.weight}


@dataclass(frozen=True, slots=True)
class ModelRankingPolicy:
    """Content-addressed policy separating hard admission from soft ordering."""

    policy_id: str
    version_number: int
    benchmark_suite_content_hash: str
    required_languages: tuple[DatasetLanguage, ...]
    required_serving_runtime_id: str
    minimum_context_tokens: int
    preferred_context_tokens: int
    maximum_gpu_memory_mb: int
    maximum_mean_latency_milliseconds: int
    protocol_thresholds: tuple[ModelRankingThreshold, ...]
    weights: tuple[ModelRankingWeight, ...]
    content_hash: str
    schema_version: int = MODEL_RANKING_POLICY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_RANKING_POLICY_SCHEMA_VERSION:
            raise ValueError("unsupported model ranking policy schema version")
        if (
            normalize_required_text(
                self.policy_id,
                label="model ranking policy ID",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            != self.policy_id
        ):
            raise ValueError("model ranking policy ID must be normalized")
        validate_positive_integer(self.version_number, label="model ranking policy version")
        validate_sha256(
            self.benchmark_suite_content_hash,
            label="model ranking benchmark suite hash",
        )
        if self.required_languages != tuple(
            sorted(set(self.required_languages), key=lambda item: item.value)
        ):
            raise ValueError("model ranking required languages must use canonical order")
        if not self.required_languages:
            raise ValueError("model ranking policy requires at least one language")
        if (
            normalize_required_text(
                self.required_serving_runtime_id,
                label="required serving runtime ID",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            != self.required_serving_runtime_id
        ):
            raise ValueError("required serving runtime ID must be normalized")
        for value, label in (
            (self.minimum_context_tokens, "minimum model context"),
            (self.preferred_context_tokens, "preferred model context"),
            (self.maximum_gpu_memory_mb, "maximum GPU memory"),
            (self.maximum_mean_latency_milliseconds, "maximum mean latency"),
        ):
            validate_positive_integer(value, label=label)
        if self.preferred_context_tokens < self.minimum_context_tokens:
            raise ValueError("preferred context must not be below the minimum")
        threshold_order = tuple(
            sorted(self.protocol_thresholds, key=lambda item: item.metric_id.value)
        )
        if self.protocol_thresholds != threshold_order:
            raise ValueError("model ranking thresholds must use canonical order")
        if len({item.metric_id for item in self.protocol_thresholds}) != len(
            self.protocol_thresholds
        ):
            raise ValueError("model ranking thresholds must be unique")
        expected_weight_order = tuple(sorted(self.weights, key=lambda item: item.component.value))
        if self.weights != expected_weight_order:
            raise ValueError("model ranking weights must use canonical order")
        if {item.component for item in self.weights} != set(ModelRankingComponent):
            raise ValueError("model ranking policy must weight every component")
        validate_sha256(self.content_hash, label="model ranking policy content hash")
        if self.content_hash != _ranking_policy_hash(
            policy_id=self.policy_id,
            version_number=self.version_number,
            benchmark_suite_content_hash=self.benchmark_suite_content_hash,
            required_languages=self.required_languages,
            required_serving_runtime_id=self.required_serving_runtime_id,
            minimum_context_tokens=self.minimum_context_tokens,
            preferred_context_tokens=self.preferred_context_tokens,
            maximum_gpu_memory_mb=self.maximum_gpu_memory_mb,
            maximum_mean_latency_milliseconds=self.maximum_mean_latency_milliseconds,
            protocol_thresholds=self.protocol_thresholds,
            weights=self.weights,
            schema_version=self.schema_version,
        ):
            raise ValueError("model ranking policy content hash is inconsistent")

    def weight(self, component: ModelRankingComponent) -> int:
        return next(item.weight for item in self.weights if item.component is component)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "version_number": self.version_number,
            "benchmark_suite_content_hash": self.benchmark_suite_content_hash,
            "required_languages": [item.value for item in self.required_languages],
            "required_serving_runtime_id": self.required_serving_runtime_id,
            "minimum_context_tokens": self.minimum_context_tokens,
            "preferred_context_tokens": self.preferred_context_tokens,
            "maximum_gpu_memory_mb": self.maximum_gpu_memory_mb,
            "maximum_mean_latency_milliseconds": self.maximum_mean_latency_milliseconds,
            "protocol_thresholds": [item.to_snapshot() for item in self.protocol_thresholds],
            "weights": [item.to_snapshot() for item in self.weights],
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ModelCandidateSpikeEvidence:
    """Exact candidate, benchmark, environment, resource, and adapter evidence."""

    candidate: ModelBenchmarkCandidate
    benchmark_run: EvaluatorBenchmarkRun
    environment: TrainingEnvironmentSnapshot
    resources: InferenceResourceSummary
    adapter_evidence: AdapterExportLoadEvidence

    def __post_init__(self) -> None:
        candidate_id = self.candidate.candidate_id
        if any(
            observed != candidate_id
            for observed in (
                self.benchmark_run.candidate_id,
                self.resources.candidate_id,
                self.adapter_evidence.candidate_id,
            )
        ):
            raise ValueError("model spike evidence candidate identities must agree")


@dataclass(frozen=True, slots=True)
class ModelRankingComponentScore:
    """One normalized component contribution to an eligible candidate score."""

    component: ModelRankingComponent
    normalized_value: float
    weight: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.normalized_value <= 1.0:
            raise ValueError("model ranking component value must be normalized")
        validate_positive_integer(self.weight, label="model ranking component score weight")

    @property
    def weighted_value(self) -> float:
        return self.normalized_value * self.weight

    def to_snapshot(self) -> dict[str, object]:
        return {
            "component": self.component.value,
            "normalized_value": self.normalized_value,
            "weight": self.weight,
            "weighted_value": self.weighted_value,
        }


@dataclass(frozen=True, slots=True)
class ModelCandidateRankingEntry:
    """Eligibility decision and optional weighted score for one candidate."""

    candidate_id: str
    candidate_content_hash: str
    eligible: bool
    exclusion_reasons: tuple[ModelRankingExclusionReason, ...]
    failed_protocol_metrics: tuple[BenchmarkMetricId, ...]
    component_scores: tuple[ModelRankingComponentScore, ...]
    weighted_score: float | None
    rank: int | None

    def __post_init__(self) -> None:
        validate_sha256(self.candidate_content_hash, label="ranked model candidate hash")
        if self.exclusion_reasons != tuple(
            sorted(set(self.exclusion_reasons), key=lambda item: item.value)
        ):
            raise ValueError("model ranking exclusions must use canonical order")
        if self.failed_protocol_metrics != tuple(
            sorted(set(self.failed_protocol_metrics), key=lambda item: item.value)
        ):
            raise ValueError("failed protocol metrics must use canonical order")
        expected_components = tuple(
            sorted(self.component_scores, key=lambda item: item.component.value)
        )
        if self.component_scores != expected_components:
            raise ValueError("model ranking component scores must use canonical order")
        if self.eligible == bool(self.exclusion_reasons):
            raise ValueError("model ranking eligibility and exclusions are inconsistent")
        if self.eligible != (self.weighted_score is not None and self.rank is not None):
            raise ValueError("eligible model ranking entries require score and rank")
        if not self.eligible and self.component_scores:
            raise ValueError("ineligible model ranking entries cannot contain component scores")
        if self.eligible and self.failed_protocol_metrics:
            raise ValueError("eligible model ranking entries cannot fail protocol metrics")
        if self.rank is not None:
            validate_positive_integer(self.rank, label="model candidate rank")
        if self.weighted_score is not None and not 0.0 <= self.weighted_score <= 1.0:
            raise ValueError("model candidate weighted score must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_content_hash": self.candidate_content_hash,
            "eligible": self.eligible,
            "exclusion_reasons": [item.value for item in self.exclusion_reasons],
            "failed_protocol_metrics": [item.value for item in self.failed_protocol_metrics],
            "component_scores": [item.to_snapshot() for item in self.component_scores],
            "weighted_score": self.weighted_score,
            "rank": self.rank,
        }


@dataclass(frozen=True, slots=True)
class ModelCandidateRanking:
    """Deterministic ranking recommendation that remains distinct from owner approval."""

    policy_id: str
    policy_version_number: int
    policy_content_hash: str
    entries: tuple[ModelCandidateRankingEntry, ...]
    recommended_candidate_id: str | None
    content_hash: str
    schema_version: int = MODEL_RANKING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != MODEL_RANKING_SCHEMA_VERSION:
            raise ValueError("unsupported model candidate ranking schema version")
        validate_sha256(self.policy_content_hash, label="model ranking policy hash")
        if not self.entries:
            raise ValueError("model candidate ranking requires entries")
        if len({item.candidate_id for item in self.entries}) != len(self.entries):
            raise ValueError("model candidate ranking entries must be unique")
        eligible = tuple(item for item in self.entries if item.eligible)
        if [item.rank for item in eligible] != list(range(1, len(eligible) + 1)):
            raise ValueError("eligible model candidate ranks must be contiguous")
        expected_recommendation = None if not eligible else eligible[0].candidate_id
        if self.recommended_candidate_id != expected_recommendation:
            raise ValueError("model ranking recommendation is inconsistent")
        validate_sha256(self.content_hash, label="model candidate ranking content hash")
        if self.content_hash != _candidate_ranking_hash(
            policy_id=self.policy_id,
            policy_version_number=self.policy_version_number,
            policy_content_hash=self.policy_content_hash,
            entries=self.entries,
            recommended_candidate_id=self.recommended_candidate_id,
            schema_version=self.schema_version,
        ):
            raise ValueError("model candidate ranking content hash is inconsistent")

    def entry(self, candidate_id: str) -> ModelCandidateRankingEntry:
        return next(item for item in self.entries if item.candidate_id == candidate_id)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "policy_version_number": self.policy_version_number,
            "policy_content_hash": self.policy_content_hash,
            "entries": [item.to_snapshot() for item in self.entries],
            "recommended_candidate_id": self.recommended_candidate_id,
            "content_hash": self.content_hash,
        }


def create_default_model_ranking_policy(
    *,
    benchmark_suite_content_hash: str,
) -> ModelRankingPolicy:
    """Create the first evidence policy for the 8 GB local feasibility target."""
    thresholds = tuple(
        sorted(
            (
                ModelRankingThreshold(
                    BenchmarkMetricId.SCHEMA_VALID_RATE,
                    ModelRankingThresholdDirection.MINIMUM,
                    1.0,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION,
                    ModelRankingThresholdDirection.MINIMUM,
                    1.0,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE,
                    ModelRankingThresholdDirection.MAXIMUM,
                    0.0,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.ABSTENTION_ACCURACY,
                    ModelRankingThresholdDirection.MINIMUM,
                    1.0,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.ROLE_ADHERENCE,
                    ModelRankingThresholdDirection.MINIMUM,
                    0.5,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.CRITERION_AGREEMENT,
                    ModelRankingThresholdDirection.MINIMUM,
                    0.5,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.SEVERITY_AGREEMENT,
                    ModelRankingThresholdDirection.MINIMUM,
                    0.5,
                ),
                ModelRankingThreshold(
                    BenchmarkMetricId.CONTEXT_REFERENCE_RECALL,
                    ModelRankingThresholdDirection.MINIMUM,
                    0.5,
                ),
            ),
            key=lambda item: item.metric_id.value,
        )
    )
    weights = tuple(
        sorted(
            (
                ModelRankingWeight(ModelRankingComponent.PROTOCOL_QUALITY, 70),
                ModelRankingWeight(ModelRankingComponent.LATENCY, 10),
                ModelRankingWeight(ModelRankingComponent.GPU_MEMORY, 15),
                ModelRankingWeight(ModelRankingComponent.CONTEXT_CAPACITY, 5),
            ),
            key=lambda item: item.component.value,
        )
    )
    return create_model_ranking_policy(
        policy_id="model-spike-ranking-v1",
        version_number=1,
        benchmark_suite_content_hash=benchmark_suite_content_hash,
        required_languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
        required_serving_runtime_id="openai-compatible-local",
        minimum_context_tokens=4_096,
        preferred_context_tokens=16_384,
        maximum_gpu_memory_mb=8_192,
        maximum_mean_latency_milliseconds=30_000,
        protocol_thresholds=thresholds,
        weights=weights,
    )


def create_model_ranking_policy(
    *,
    policy_id: str,
    version_number: int,
    benchmark_suite_content_hash: str,
    required_languages: tuple[DatasetLanguage, ...],
    required_serving_runtime_id: str,
    minimum_context_tokens: int,
    preferred_context_tokens: int,
    maximum_gpu_memory_mb: int,
    maximum_mean_latency_milliseconds: int,
    protocol_thresholds: tuple[ModelRankingThreshold, ...],
    weights: tuple[ModelRankingWeight, ...],
) -> ModelRankingPolicy:
    canonical_languages = tuple(sorted(set(required_languages), key=lambda item: item.value))
    canonical_thresholds = tuple(sorted(protocol_thresholds, key=lambda item: item.metric_id.value))
    canonical_weights = tuple(sorted(weights, key=lambda item: item.component.value))
    content_hash = _ranking_policy_hash(
        policy_id=policy_id,
        version_number=version_number,
        benchmark_suite_content_hash=benchmark_suite_content_hash,
        required_languages=canonical_languages,
        required_serving_runtime_id=required_serving_runtime_id,
        minimum_context_tokens=minimum_context_tokens,
        preferred_context_tokens=preferred_context_tokens,
        maximum_gpu_memory_mb=maximum_gpu_memory_mb,
        maximum_mean_latency_milliseconds=maximum_mean_latency_milliseconds,
        protocol_thresholds=canonical_thresholds,
        weights=canonical_weights,
        schema_version=MODEL_RANKING_POLICY_SCHEMA_VERSION,
    )
    return ModelRankingPolicy(
        policy_id=policy_id,
        version_number=version_number,
        benchmark_suite_content_hash=benchmark_suite_content_hash,
        required_languages=canonical_languages,
        required_serving_runtime_id=required_serving_runtime_id,
        minimum_context_tokens=minimum_context_tokens,
        preferred_context_tokens=preferred_context_tokens,
        maximum_gpu_memory_mb=maximum_gpu_memory_mb,
        maximum_mean_latency_milliseconds=maximum_mean_latency_milliseconds,
        protocol_thresholds=canonical_thresholds,
        weights=canonical_weights,
        content_hash=content_hash,
    )


def rank_model_candidates(
    *,
    policy: ModelRankingPolicy,
    evidence: tuple[ModelCandidateSpikeEvidence, ...],
) -> ModelCandidateRanking:
    """Apply hard constraints, then rank only eligible candidates deterministically."""
    if not evidence:
        raise ValueError("model candidate ranking requires evidence")
    provisional = [_evaluate_candidate(policy, item) for item in evidence]
    eligible = [item for item in provisional if item[1] is not None]
    eligible.sort(
        key=lambda item: (
            -(item[1] or 0.0),
            item[2],
            item[3],
            item[0].candidate.candidate_id,
        )
    )
    ranks = {item[0].candidate.candidate_id: index for index, item in enumerate(eligible, 1)}
    entries: list[ModelCandidateRankingEntry] = []
    by_candidate = {item[0].candidate.candidate_id: item for item in provisional}
    ordered_ids = [item[0].candidate.candidate_id for item in eligible]
    ordered_ids.extend(sorted(set(by_candidate) - set(ordered_ids)))
    for candidate_id in ordered_ids:
        item, weighted_score, _peak, _latency, exclusions, failed_metrics, components = (
            by_candidate[candidate_id]
        )
        entries.append(
            ModelCandidateRankingEntry(
                candidate_id=candidate_id,
                candidate_content_hash=item.candidate.content_hash,
                eligible=weighted_score is not None,
                exclusion_reasons=tuple(sorted(exclusions, key=lambda value: value.value)),
                failed_protocol_metrics=tuple(
                    sorted(failed_metrics, key=lambda value: value.value)
                ),
                component_scores=components if weighted_score is not None else (),
                weighted_score=weighted_score,
                rank=ranks.get(candidate_id),
            )
        )
    canonical_entries = tuple(entries)
    recommendation = None if not eligible else eligible[0][0].candidate.candidate_id
    content_hash = _candidate_ranking_hash(
        policy_id=policy.policy_id,
        policy_version_number=policy.version_number,
        policy_content_hash=policy.content_hash,
        entries=canonical_entries,
        recommended_candidate_id=recommendation,
        schema_version=MODEL_RANKING_SCHEMA_VERSION,
    )
    return ModelCandidateRanking(
        policy_id=policy.policy_id,
        policy_version_number=policy.version_number,
        policy_content_hash=policy.content_hash,
        entries=canonical_entries,
        recommended_candidate_id=recommendation,
        content_hash=content_hash,
    )


def _evaluate_candidate(
    policy: ModelRankingPolicy,
    item: ModelCandidateSpikeEvidence,
) -> tuple[
    ModelCandidateSpikeEvidence,
    float | None,
    int,
    float,
    set[ModelRankingExclusionReason],
    set[BenchmarkMetricId],
    tuple[ModelRankingComponentScore, ...],
]:
    candidate = item.candidate
    exclusions: set[ModelRankingExclusionReason] = set()
    failed_metrics: set[BenchmarkMetricId] = set()
    if candidate.availability is not ModelCandidateAvailability.AVAILABLE:
        exclusions.add(ModelRankingExclusionReason.MODEL_UNAVAILABLE)
    if not candidate.instruct_tuned:
        exclusions.add(ModelRankingExclusionReason.NOT_INSTRUCT_TUNED)
    if not set(policy.required_languages).issubset(candidate.languages):
        exclusions.add(ModelRankingExclusionReason.LANGUAGE_COVERAGE_MISSING)
    if candidate.license_evidence.compatibility is not ModelLicenseCompatibility.COMPATIBLE:
        exclusions.add(ModelRankingExclusionReason.LICENSE_INCOMPATIBLE)
    if not candidate.license_evidence.allows_adapter_redistribution:
        exclusions.add(ModelRankingExclusionReason.ADAPTER_REDISTRIBUTION_NOT_ALLOWED)
    if candidate.context_limit_tokens < policy.minimum_context_tokens:
        exclusions.add(ModelRankingExclusionReason.CONTEXT_LIMIT_TOO_SMALL)
    compatible_runtimes = {
        evidence.runtime_id for evidence in candidate.serving_compatibility if evidence.compatible
    }
    if policy.required_serving_runtime_id not in compatible_runtimes:
        exclusions.add(ModelRankingExclusionReason.SERVING_RUNTIME_UNSUPPORTED)
    if item.benchmark_run.suite_content_hash != policy.benchmark_suite_content_hash:
        exclusions.add(ModelRankingExclusionReason.BENCHMARK_SUITE_MISMATCH)
    if not item.benchmark_run.complete:
        exclusions.add(ModelRankingExclusionReason.BENCHMARK_INCOMPLETE)
    if not _identity_matches_candidate(item):
        exclusions.add(ModelRankingExclusionReason.MODEL_IDENTITY_MISMATCH)
    for threshold in policy.protocol_thresholds:
        observed = item.benchmark_run.metric(threshold.metric_id).value
        if observed is None or not threshold.accepts(observed):
            failed_metrics.add(threshold.metric_id)
    if failed_metrics:
        exclusions.add(ModelRankingExclusionReason.PROTOCOL_THRESHOLD_FAILED)
    if not item.environment.complete:
        exclusions.add(ModelRankingExclusionReason.ENVIRONMENT_EVIDENCE_INCOMPLETE)
    if not item.resources.complete:
        exclusions.add(ModelRankingExclusionReason.RESOURCE_EVIDENCE_INCOMPLETE)
    peak_memory = item.resources.peak_gpu_memory_mb or policy.maximum_gpu_memory_mb + 1
    latency = (
        item.resources.mean_latency_milliseconds
        if item.resources.mean_latency_milliseconds is not None
        else float(policy.maximum_mean_latency_milliseconds + 1)
    )
    if peak_memory > policy.maximum_gpu_memory_mb:
        exclusions.add(ModelRankingExclusionReason.GPU_MEMORY_LIMIT_EXCEEDED)
    if latency > policy.maximum_mean_latency_milliseconds:
        exclusions.add(ModelRankingExclusionReason.LATENCY_LIMIT_EXCEEDED)
    if not item.adapter_evidence.passed:
        exclusions.add(ModelRankingExclusionReason.ADAPTER_SMOKE_FAILED)
    if exclusions:
        return item, None, peak_memory, latency, exclusions, failed_metrics, ()
    components = _component_scores(policy, item, peak_memory=peak_memory, latency=latency)
    total_weight = sum(component.weight for component in components)
    weighted_score = round(
        sum(component.weighted_value for component in components) / total_weight,
        6,
    )
    return item, weighted_score, peak_memory, latency, exclusions, failed_metrics, components


def _component_scores(
    policy: ModelRankingPolicy,
    item: ModelCandidateSpikeEvidence,
    *,
    peak_memory: int,
    latency: float,
) -> tuple[ModelRankingComponentScore, ...]:
    quality_metric_ids = (
        BenchmarkMetricId.SCHEMA_VALID_RATE,
        BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION,
        BenchmarkMetricId.ABSTENTION_ACCURACY,
        BenchmarkMetricId.ROLE_ADHERENCE,
        BenchmarkMetricId.CRITERION_AGREEMENT,
        BenchmarkMetricId.SEVERITY_AGREEMENT,
        BenchmarkMetricId.CONTEXT_REFERENCE_RECALL,
    )
    quality_values = [
        item.benchmark_run.metric(metric_id).value or 0.0 for metric_id in quality_metric_ids
    ]
    unsupported = item.benchmark_run.metric(BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE).value
    quality_values.append(1.0 - (unsupported or 0.0))
    values = {
        ModelRankingComponent.PROTOCOL_QUALITY: sum(quality_values) / len(quality_values),
        ModelRankingComponent.LATENCY: max(
            0.0,
            1.0 - latency / policy.maximum_mean_latency_milliseconds,
        ),
        ModelRankingComponent.GPU_MEMORY: max(
            0.0,
            1.0 - peak_memory / policy.maximum_gpu_memory_mb,
        ),
        ModelRankingComponent.CONTEXT_CAPACITY: min(
            1.0,
            item.candidate.context_limit_tokens / policy.preferred_context_tokens,
        ),
    }
    return tuple(
        ModelRankingComponentScore(
            component=component,
            normalized_value=round(values[component], 6),
            weight=policy.weight(component),
        )
        for component in sorted(ModelRankingComponent, key=lambda value: value.value)
    )


def _identity_matches_candidate(item: ModelCandidateSpikeEvidence) -> bool:
    identity = item.benchmark_run.model_identity
    candidate = item.candidate
    return (
        identity.base_model_repository == candidate.repository_id
        and identity.base_model_revision == candidate.revision
        and identity.tokenizer_revision == candidate.tokenizer.revision
    )


def _ranking_policy_hash(
    *,
    policy_id: str,
    version_number: int,
    benchmark_suite_content_hash: str,
    required_languages: tuple[DatasetLanguage, ...],
    required_serving_runtime_id: str,
    minimum_context_tokens: int,
    preferred_context_tokens: int,
    maximum_gpu_memory_mb: int,
    maximum_mean_latency_milliseconds: int,
    protocol_thresholds: tuple[ModelRankingThreshold, ...],
    weights: tuple[ModelRankingWeight, ...],
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "policy_id": policy_id,
            "version_number": version_number,
            "benchmark_suite_content_hash": benchmark_suite_content_hash,
            "required_languages": [item.value for item in required_languages],
            "required_serving_runtime_id": required_serving_runtime_id,
            "minimum_context_tokens": minimum_context_tokens,
            "preferred_context_tokens": preferred_context_tokens,
            "maximum_gpu_memory_mb": maximum_gpu_memory_mb,
            "maximum_mean_latency_milliseconds": maximum_mean_latency_milliseconds,
            "protocol_thresholds": [item.to_snapshot() for item in protocol_thresholds],
            "weights": [item.to_snapshot() for item in weights],
        }
    )


def _candidate_ranking_hash(
    *,
    policy_id: str,
    policy_version_number: int,
    policy_content_hash: str,
    entries: tuple[ModelCandidateRankingEntry, ...],
    recommended_candidate_id: str | None,
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "policy_id": policy_id,
            "policy_version_number": policy_version_number,
            "policy_content_hash": policy_content_hash,
            "entries": [item.to_snapshot() for item in entries],
            "recommended_candidate_id": recommended_candidate_id,
        }
    )
