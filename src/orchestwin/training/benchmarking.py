"""Deterministic execution and scoring for the bilingual evaluator benchmark."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID, uuid5

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationPort,
    StructuredGenerationResult,
    StructuredGenerationStatus,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import (
    normalize_optional_text,
    snapshot_content_hash,
    validate_sha256,
)
from orchestwin.training.benchmark_tasks import (
    BenchmarkMetricId,
    EvaluatorBenchmarkSuite,
    EvaluatorBenchmarkTask,
)
from orchestwin.training.dataset_examples import DatasetLanguage

BENCHMARK_RUN_SCHEMA_VERSION: Final = 1
_BENCHMARK_REQUEST_NAMESPACE: Final = UUID("a65214a5-e1da-43dc-8e3d-48bc7654195d")
_ALLOWED_EPISTEMIC_STATUSES: Final = {item.value for item in SyntheticFindingEpistemicStatus}


@dataclass(frozen=True, slots=True)
class EvaluatorBenchmarkTaskScore:
    """Normalized protocol metrics and failure evidence for one frozen task."""

    task_id: str
    task_content_hash: str
    language: DatasetLanguage
    generation_status: StructuredGenerationStatus
    schema_valid_rate: float
    evidence_reference_precision: float
    unsupported_claim_rate: float
    abstention_accuracy: float
    role_adherence: float
    criterion_agreement: float
    severity_agreement: float
    context_reference_recall: float
    latency_milliseconds: int | None
    failure_code: StructuredGenerationFailureCode | None

    def __post_init__(self) -> None:
        validate_sha256(self.task_content_hash, label="benchmark task score content hash")
        for value, label in (
            (self.schema_valid_rate, "schema-valid rate"),
            (self.evidence_reference_precision, "evidence-reference precision"),
            (self.unsupported_claim_rate, "unsupported-claim rate"),
            (self.abstention_accuracy, "abstention accuracy"),
            (self.role_adherence, "role adherence"),
            (self.criterion_agreement, "criterion agreement"),
            (self.severity_agreement, "severity agreement"),
            (self.context_reference_recall, "context-reference recall"),
        ):
            if isinstance(value, bool) or not 0.0 <= value <= 1.0:
                raise ValueError(f"benchmark {label} must be between zero and one")
        if self.latency_milliseconds is not None and (
            isinstance(self.latency_milliseconds, bool) or self.latency_milliseconds < 0
        ):
            raise ValueError("benchmark latency must be a non-negative integer")
        succeeded = self.generation_status is StructuredGenerationStatus.SUCCEEDED
        if succeeded == (self.failure_code is not None):
            raise ValueError("benchmark task failure shape is inconsistent")
        if not succeeded and self.latency_milliseconds is not None:
            raise ValueError("failed benchmark tasks cannot report successful latency")

    def metric_value(self, metric_id: BenchmarkMetricId) -> float | None:
        values: dict[BenchmarkMetricId, float | None] = {
            BenchmarkMetricId.SCHEMA_VALID_RATE: self.schema_valid_rate,
            BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION: (self.evidence_reference_precision),
            BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE: self.unsupported_claim_rate,
            BenchmarkMetricId.ABSTENTION_ACCURACY: self.abstention_accuracy,
            BenchmarkMetricId.ROLE_ADHERENCE: self.role_adherence,
            BenchmarkMetricId.CRITERION_AGREEMENT: self.criterion_agreement,
            BenchmarkMetricId.SEVERITY_AGREEMENT: self.severity_agreement,
            BenchmarkMetricId.CONTEXT_REFERENCE_RECALL: self.context_reference_recall,
            BenchmarkMetricId.LATENCY_MILLISECONDS: (
                None if self.latency_milliseconds is None else float(self.latency_milliseconds)
            ),
            BenchmarkMetricId.PEAK_GPU_MEMORY_MB: None,
            BenchmarkMetricId.ADAPTER_EXPORT_LOAD: None,
        }
        return values[metric_id]

    def to_snapshot(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_content_hash": self.task_content_hash,
            "language": self.language.value,
            "generation_status": self.generation_status.value,
            "schema_valid_rate": self.schema_valid_rate,
            "evidence_reference_precision": self.evidence_reference_precision,
            "unsupported_claim_rate": self.unsupported_claim_rate,
            "abstention_accuracy": self.abstention_accuracy,
            "role_adherence": self.role_adherence,
            "criterion_agreement": self.criterion_agreement,
            "severity_agreement": self.severity_agreement,
            "context_reference_recall": self.context_reference_recall,
            "latency_milliseconds": self.latency_milliseconds,
            "failure_code": None if self.failure_code is None else self.failure_code.value,
        }


@dataclass(frozen=True, slots=True)
class EvaluatorBenchmarkMetricResult:
    """One aggregate metric with an explicit number of contributing tasks."""

    metric_id: BenchmarkMetricId
    value: float | None
    sample_count: int

    def __post_init__(self) -> None:
        if isinstance(self.sample_count, bool) or self.sample_count < 0:
            raise ValueError("benchmark metric sample count must be non-negative")
        if (self.value is None) != (self.sample_count == 0):
            raise ValueError("benchmark aggregate metric value shape is inconsistent")
        if (
            self.value is not None
            and self.metric_id
            not in {
                BenchmarkMetricId.LATENCY_MILLISECONDS,
                BenchmarkMetricId.PEAK_GPU_MEMORY_MB,
            }
            and not (0.0 <= self.value <= 1.0)
        ):
            raise ValueError("normalized aggregate metric must be between zero and one")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "metric_id": self.metric_id.value,
            "value": self.value,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True, slots=True)
class EvaluatorBenchmarkRun:
    """Immutable run over one exact suite and model identity."""

    run_id: UUID
    candidate_id: str
    suite_id: str
    suite_version_number: int
    suite_content_hash: str
    model_identity: ModelRuntimeIdentity
    task_scores: tuple[EvaluatorBenchmarkTaskScore, ...]
    metrics: tuple[EvaluatorBenchmarkMetricResult, ...]
    started_at: datetime
    completed_at: datetime
    complete: bool
    content_hash: str
    schema_version: int = BENCHMARK_RUN_SCHEMA_VERSION

    def __post_init__(self) -> None:
        validate_sha256(self.suite_content_hash, label="benchmark run suite hash")
        if self.schema_version != BENCHMARK_RUN_SCHEMA_VERSION:
            raise ValueError("unsupported benchmark run schema version")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("benchmark start timestamp must be timezone-aware")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("benchmark completion timestamp must be timezone-aware")
        if self.completed_at < self.started_at:
            raise ValueError("benchmark completion cannot precede its start")
        if not self.task_scores:
            raise ValueError("benchmark run requires task scores")
        if self.task_scores != tuple(sorted(self.task_scores, key=lambda item: item.task_id)):
            raise ValueError("benchmark task scores must use canonical order")
        if len({item.task_id for item in self.task_scores}) != len(self.task_scores):
            raise ValueError("benchmark task scores must be unique")
        expected_metric_order = tuple(sorted(self.metrics, key=lambda item: item.metric_id.value))
        if self.metrics != expected_metric_order:
            raise ValueError("benchmark aggregate metrics must use canonical order")
        if {item.metric_id for item in self.metrics} != set(BenchmarkMetricId):
            raise ValueError("benchmark run must expose every required metric")
        expected_complete = all(
            item.generation_status is StructuredGenerationStatus.SUCCEEDED
            for item in self.task_scores
        )
        if self.complete != expected_complete:
            raise ValueError("benchmark completeness is inconsistent with task outcomes")
        validate_sha256(self.content_hash, label="benchmark run content hash")
        if self.content_hash != _benchmark_run_hash(
            run_id=self.run_id,
            candidate_id=self.candidate_id,
            suite_id=self.suite_id,
            suite_version_number=self.suite_version_number,
            suite_content_hash=self.suite_content_hash,
            model_identity=self.model_identity,
            task_scores=self.task_scores,
            metrics=self.metrics,
            started_at=self.started_at,
            completed_at=self.completed_at,
            complete=self.complete,
            schema_version=self.schema_version,
        ):
            raise ValueError("benchmark run content hash is inconsistent")

    def metric(self, metric_id: BenchmarkMetricId) -> EvaluatorBenchmarkMetricResult:
        return next(item for item in self.metrics if item.metric_id is metric_id)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": str(self.run_id),
            "candidate_id": self.candidate_id,
            "suite_id": self.suite_id,
            "suite_version_number": self.suite_version_number,
            "suite_content_hash": self.suite_content_hash,
            "model_identity": self.model_identity.to_snapshot(),
            "task_scores": [item.to_snapshot() for item in self.task_scores],
            "metrics": [item.to_snapshot() for item in self.metrics],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "complete": self.complete,
            "content_hash": self.content_hash,
        }


async def run_evaluator_benchmark(
    *,
    run_id: UUID,
    candidate_id: str,
    suite: EvaluatorBenchmarkSuite,
    model_identity: ModelRuntimeIdentity,
    adapter: StructuredGenerationPort,
    started_at: datetime,
    completed_at: datetime,
) -> EvaluatorBenchmarkRun:
    """Execute frozen tasks sequentially and preserve every typed failure."""
    scores: list[EvaluatorBenchmarkTaskScore] = []
    for task in suite.tasks:
        request = create_benchmark_generation_request(
            run_id=run_id,
            task=task,
            model_identity=model_identity,
        )
        result = await adapter.generate(request)
        scores.append(score_benchmark_result(task=task, result=result))
    canonical_scores = tuple(sorted(scores, key=lambda item: item.task_id))
    metrics = aggregate_benchmark_metrics(canonical_scores)
    complete = all(
        item.generation_status is StructuredGenerationStatus.SUCCEEDED for item in canonical_scores
    )
    content_hash = _benchmark_run_hash(
        run_id=run_id,
        candidate_id=candidate_id,
        suite_id=suite.suite_id,
        suite_version_number=suite.version_number,
        suite_content_hash=suite.content_hash,
        model_identity=model_identity,
        task_scores=canonical_scores,
        metrics=metrics,
        started_at=started_at,
        completed_at=completed_at,
        complete=complete,
        schema_version=BENCHMARK_RUN_SCHEMA_VERSION,
    )
    return EvaluatorBenchmarkRun(
        run_id=run_id,
        candidate_id=candidate_id,
        suite_id=suite.suite_id,
        suite_version_number=suite.version_number,
        suite_content_hash=suite.content_hash,
        model_identity=model_identity,
        task_scores=canonical_scores,
        metrics=metrics,
        started_at=started_at,
        completed_at=completed_at,
        complete=complete,
        content_hash=content_hash,
    )


def create_benchmark_generation_request(
    *,
    run_id: UUID,
    task: EvaluatorBenchmarkTask,
    model_identity: ModelRuntimeIdentity,
):
    """Create the exact provider-neutral request without leaking frozen labels."""
    request_id = uuid5(
        _BENCHMARK_REQUEST_NAMESPACE,
        f"{run_id}:{task.task_id}:{task.version_number}:{task.content_hash}",
    )
    return create_structured_generation_request(
        request_id=request_id,
        task_id=task.task_id,
        expected_identity=model_identity,
        output_schema=evaluator_benchmark_output_schema(),
        system_instruction=_benchmark_system_instruction(task.language),
        input_payload={
            "language": task.language.value,
            "profile_summary": task.profile_summary,
            "scenario": task.scenario,
            "target_task": task.target_task,
            "artifact_summary": task.artifact_summary,
            "evidence": [item.to_snapshot() for item in task.evidence],
            "evaluation_criteria": [item.value for item in SyntheticFindingCriterion],
            "methodological_notice": (
                "The output is simulated feedback and a design hypothesis, "
                "not empirical evidence of real-user behavior."
            ),
        },
        allowed_evidence_refs=task.expected.allowed_evidence_refs,
        prompt_version_ref="ut-evaluator-benchmark-v1",
        temperature=0.0,
        max_output_tokens=1_024,
        timeout_seconds=60,
    )


def evaluator_benchmark_output_schema():
    """Return the stable structural schema scored by the model spike."""
    return create_structured_json_schema(
        schema_id="user-twin-evaluator-benchmark-output",
        version_number=1,
        schema_payload={
            "type": "object",
            "additionalProperties": False,
            "required": ["overall_summary", "findings", "evidence_gaps", "abstained"],
            "properties": {
                "overall_summary": {"type": "string"},
                "role_statement": {"type": ["string", "null"]},
                "evidence_gaps": {"type": "array", "items": {"type": "string"}},
                "abstained": {"type": "boolean"},
                "findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "finding_id",
                            "summary",
                            "rationale",
                            "criterion",
                            "severity",
                            "epistemic_status",
                            "evidence_refs",
                            "recommended_action",
                            "requires_human_validation",
                        ],
                        "properties": {
                            "finding_id": {"type": "string"},
                            "summary": {"type": "string"},
                            "rationale": {"type": "string"},
                            "criterion": {
                                "enum": [item.value for item in SyntheticFindingCriterion]
                            },
                            "severity": {"enum": [item.value for item in SyntheticFindingSeverity]},
                            "epistemic_status": {"enum": sorted(_ALLOWED_EPISTEMIC_STATUSES)},
                            "evidence_refs": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "recommended_action": {"type": "string"},
                            "requires_human_validation": {"type": "boolean"},
                        },
                    },
                },
            },
        },
    )


def score_benchmark_result(
    *,
    task: EvaluatorBenchmarkTask,
    result: StructuredGenerationResult,
) -> EvaluatorBenchmarkTaskScore:
    """Score only observable structured output and frozen task labels."""
    if result.status is StructuredGenerationStatus.FAILED:
        if result.failure is None:
            raise ValueError("failed generation result must contain failure evidence")
        return _failed_task_score(task, result.failure.code)
    if result.success is None:
        raise ValueError("successful generation result must contain a payload")
    try:
        raw = json.loads(result.success.payload_json)
    except json.JSONDecodeError:
        return _invalid_schema_score(task, result.success.usage.latency_milliseconds)
    parsed = _parse_evaluator_output(raw, task=task)
    if parsed is None:
        return _invalid_schema_score(task, result.success.usage.latency_milliseconds)
    summaries = " ".join(parsed.text_fragments).casefold()
    references = tuple(ref for finding in parsed.findings for ref in finding.evidence_refs)
    allowed = set(task.expected.allowed_evidence_refs)
    valid_reference_count = sum(reference in allowed for reference in references)
    if references:
        evidence_precision = valid_reference_count / len(references)
    else:
        evidence_precision = 1.0 if not parsed.findings else 0.0
    unsupported_flags = [
        _finding_is_unsupported(finding, task=task, all_text=summaries)
        for finding in parsed.findings
    ]
    forbidden_in_summary = any(
        fragment.casefold() in summaries for fragment in task.expected.forbidden_claim_fragments
    )
    unsupported_units = sum(unsupported_flags) + int(forbidden_in_summary)
    claim_units = max(1, len(parsed.findings) + 1)
    unsupported_rate = min(1.0, unsupported_units / claim_units)
    observed_criteria = {finding.criterion for finding in parsed.findings}
    observed_severities = {finding.severity for finding in parsed.findings}
    observed_references = set(references)
    return EvaluatorBenchmarkTaskScore(
        task_id=task.task_id,
        task_content_hash=task.content_hash,
        language=task.language,
        generation_status=StructuredGenerationStatus.SUCCEEDED,
        schema_valid_rate=1.0,
        evidence_reference_precision=evidence_precision,
        unsupported_claim_rate=unsupported_rate,
        abstention_accuracy=float(parsed.abstained is task.expected.should_abstain),
        role_adherence=_term_recall(task.expected.required_role_terms, summaries),
        criterion_agreement=_set_agreement(
            observed_criteria,
            set(task.expected.expected_criteria),
        ),
        severity_agreement=_set_agreement(
            observed_severities,
            set(task.expected.expected_severities),
        ),
        context_reference_recall=_set_recall(
            observed_references,
            set(task.expected.required_evidence_refs),
        ),
        latency_milliseconds=result.success.usage.latency_milliseconds,
        failure_code=None,
    )


def aggregate_benchmark_metrics(
    scores: tuple[EvaluatorBenchmarkTaskScore, ...],
) -> tuple[EvaluatorBenchmarkMetricResult, ...]:
    """Aggregate task metrics while leaving GPU and export evidence explicitly absent."""
    aggregates: list[EvaluatorBenchmarkMetricResult] = []
    for metric_id in sorted(BenchmarkMetricId, key=lambda item: item.value):
        values = [value for score in scores if (value := score.metric_value(metric_id)) is not None]
        aggregates.append(
            EvaluatorBenchmarkMetricResult(
                metric_id=metric_id,
                value=None if not values else sum(values) / len(values),
                sample_count=len(values),
            )
        )
    return tuple(aggregates)


@dataclass(frozen=True, slots=True)
class _ParsedFinding:
    finding_id: str
    summary: str
    rationale: str
    criterion: SyntheticFindingCriterion
    severity: SyntheticFindingSeverity
    epistemic_status: SyntheticFindingEpistemicStatus
    evidence_refs: tuple[str, ...]
    recommended_action: str
    requires_human_validation: bool


@dataclass(frozen=True, slots=True)
class _ParsedEvaluatorOutput:
    overall_summary: str
    role_statement: str | None
    evidence_gaps: tuple[str, ...]
    abstained: bool
    findings: tuple[_ParsedFinding, ...]

    @property
    def text_fragments(self) -> tuple[str, ...]:
        return (
            self.overall_summary,
            self.role_statement or "",
            *self.evidence_gaps,
            *(item.summary for item in self.findings),
            *(item.rationale for item in self.findings),
            *(item.recommended_action for item in self.findings),
        )


def _parse_evaluator_output(
    value: object,
    *,
    task: EvaluatorBenchmarkTask,
) -> _ParsedEvaluatorOutput | None:
    if not isinstance(value, dict):
        return None
    overall_summary = value.get("overall_summary")
    role_statement = value.get("role_statement")
    evidence_gaps = value.get("evidence_gaps")
    abstained = value.get("abstained")
    findings = value.get("findings")
    if not isinstance(overall_summary, str) or not overall_summary.strip():
        return None
    if role_statement is not None and not isinstance(role_statement, str):
        return None
    if not isinstance(evidence_gaps, list) or not all(
        isinstance(item, str) for item in evidence_gaps
    ):
        return None
    if not isinstance(abstained, bool) or not isinstance(findings, list):
        return None
    parsed_findings: list[_ParsedFinding] = []
    for finding in findings:
        parsed = _parse_finding(finding)
        if parsed is None:
            return None
        parsed_findings.append(parsed)
    if len({item.finding_id for item in parsed_findings}) != len(parsed_findings):
        return None
    if not task.expected.minimum_findings <= len(parsed_findings) <= task.expected.maximum_findings:
        return None
    if abstained and parsed_findings:
        return None
    return _ParsedEvaluatorOutput(
        overall_summary=overall_summary,
        role_statement=role_statement,
        evidence_gaps=tuple(evidence_gaps),
        abstained=abstained,
        findings=tuple(parsed_findings),
    )


def _parse_finding(value: object) -> _ParsedFinding | None:
    if not isinstance(value, dict):
        return None
    finding_id = value.get("finding_id")
    summary = value.get("summary")
    rationale = value.get("rationale")
    references = value.get("evidence_refs")
    recommended_action = value.get("recommended_action")
    requires_human_validation = value.get("requires_human_validation")
    if not all(
        isinstance(item, str) and item.strip()
        for item in (finding_id, summary, rationale, recommended_action)
    ):
        return None
    if not isinstance(references, list) or not all(isinstance(item, str) for item in references):
        return None
    if not isinstance(requires_human_validation, bool):
        return None
    try:
        criterion = SyntheticFindingCriterion(value.get("criterion"))
        severity = SyntheticFindingSeverity(value.get("severity"))
        epistemic_status = SyntheticFindingEpistemicStatus(value.get("epistemic_status"))
    except (TypeError, ValueError):
        return None
    return _ParsedFinding(
        finding_id=finding_id,
        summary=summary,
        rationale=rationale,
        criterion=criterion,
        severity=severity,
        epistemic_status=epistemic_status,
        evidence_refs=tuple(references),
        recommended_action=recommended_action,
        requires_human_validation=requires_human_validation,
    )


def _finding_is_unsupported(
    finding: _ParsedFinding,
    *,
    task: EvaluatorBenchmarkTask,
    all_text: str,
) -> bool:
    if not set(finding.evidence_refs).issubset(task.expected.allowed_evidence_refs):
        return True
    if finding.epistemic_status in {
        SyntheticFindingEpistemicStatus.EMPIRICALLY_SUPPORTED,
        SyntheticFindingEpistemicStatus.HUMAN_VALIDATED,
    }:
        return not any(
            reference.startswith(("EMP-", "HUM-")) for reference in finding.evidence_refs
        )
    return any(
        fragment.casefold() in all_text for fragment in task.expected.forbidden_claim_fragments
    )


def _term_recall(required_terms: tuple[str, ...], text: str) -> float:
    if not required_terms:
        return 1.0
    return sum(term.casefold() in text for term in required_terms) / len(required_terms)


def _set_agreement(observed: set[object], expected: set[object]) -> float:
    if not observed and not expected:
        return 1.0
    union = observed | expected
    return len(observed & expected) / len(union)


def _set_recall(observed: set[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    return len(observed & expected) / len(expected)


def _failed_task_score(
    task: EvaluatorBenchmarkTask,
    failure_code: StructuredGenerationFailureCode,
) -> EvaluatorBenchmarkTaskScore:
    return EvaluatorBenchmarkTaskScore(
        task_id=task.task_id,
        task_content_hash=task.content_hash,
        language=task.language,
        generation_status=StructuredGenerationStatus.FAILED,
        schema_valid_rate=0.0,
        evidence_reference_precision=0.0,
        unsupported_claim_rate=1.0,
        abstention_accuracy=0.0,
        role_adherence=0.0,
        criterion_agreement=0.0,
        severity_agreement=0.0,
        context_reference_recall=0.0,
        latency_milliseconds=None,
        failure_code=failure_code,
    )


def _invalid_schema_score(
    task: EvaluatorBenchmarkTask,
    latency_milliseconds: int,
) -> EvaluatorBenchmarkTaskScore:
    return EvaluatorBenchmarkTaskScore(
        task_id=task.task_id,
        task_content_hash=task.content_hash,
        language=task.language,
        generation_status=StructuredGenerationStatus.SUCCEEDED,
        schema_valid_rate=0.0,
        evidence_reference_precision=0.0,
        unsupported_claim_rate=1.0,
        abstention_accuracy=0.0,
        role_adherence=0.0,
        criterion_agreement=0.0,
        severity_agreement=0.0,
        context_reference_recall=0.0,
        latency_milliseconds=latency_milliseconds,
        failure_code=None,
    )


def _benchmark_system_instruction(language: DatasetLanguage) -> str:
    language_name = "English" if language is DatasetLanguage.ENGLISH else "Italian"
    return (
        f"Return one JSON object in {language_name} from the represented role. "
        "Use only supplied evidence references. Mark unsupported hypotheses as "
        "UNSUPPORTED_ASSUMPTION, abstain when evidence is insufficient, and never "
        "present simulated feedback as empirical evidence of real-user behavior."
    )


def _benchmark_run_hash(
    *,
    run_id: UUID,
    candidate_id: str,
    suite_id: str,
    suite_version_number: int,
    suite_content_hash: str,
    model_identity: ModelRuntimeIdentity,
    task_scores: tuple[EvaluatorBenchmarkTaskScore, ...],
    metrics: tuple[EvaluatorBenchmarkMetricResult, ...],
    started_at: datetime,
    completed_at: datetime,
    complete: bool,
    schema_version: int,
) -> str:
    normalized_candidate = normalize_optional_text(
        candidate_id,
        label="benchmark candidate ID",
        maximum_length=256,
    )
    if normalized_candidate != candidate_id or normalized_candidate is None:
        raise ValueError("benchmark candidate ID must be normalized")
    return snapshot_content_hash(
        {
            "schema_version": schema_version,
            "run_id": str(run_id),
            "candidate_id": candidate_id,
            "suite_id": suite_id,
            "suite_version_number": suite_version_number,
            "suite_content_hash": suite_content_hash,
            "model_identity": model_identity.to_snapshot(),
            "task_scores": [item.to_snapshot() for item in task_scores],
            "metrics": [item.to_snapshot() for item in metrics],
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "complete": complete,
        }
    )
