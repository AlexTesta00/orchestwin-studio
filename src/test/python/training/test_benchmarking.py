"""Tests for deterministic bilingual evaluator benchmark execution and scoring."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.models.fake_structured import (
    FakeDeterministicStructuredAdapter,
    create_fake_failure_fixture,
    create_fake_success_fixture,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationUsage,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.training.benchmark_tasks import (
    BenchmarkEvidenceItem,
    BenchmarkExpectedEvaluation,
    BenchmarkMetricId,
    BenchmarkTaskCategory,
    create_benchmark_suite,
    create_benchmark_task,
)
from orchestwin.training.benchmarking import (
    create_benchmark_generation_request,
    run_evaluator_benchmark,
    score_benchmark_result,
)
from orchestwin.training.dataset_examples import DatasetLanguage

RUN_ID = UUID("00000000-0000-4000-8000-000000117001")
STARTED_AT = datetime(2026, 10, 13, 14, 0, tzinfo=UTC)
COMPLETED_AT = datetime(2026, 10, 13, 14, 1, tzinfo=UTC)


def _identity() -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="fake-benchmark",
        runtime_id="fake-evaluator-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="c" * 64,
    )


def _task(language: DatasetLanguage, number: int, *, abstain: bool = False):
    reference = f"REQ-{number:03d}"
    return create_benchmark_task(
        task_id=f"bench-{language.value}-{number:03d}",
        version_number=1,
        category=(
            BenchmarkTaskCategory.ABSTENTION
            if abstain
            else BenchmarkTaskCategory.SCHEMA_AND_PROVENANCE
        ),
        language=language,
        profile_summary="Operations coordinator working under time pressure.",
        scenario="Recover from invalid input without losing entered information.",
        target_task="Correct the value and continue the workflow.",
        artifact_summary="The error appears only at the top of the form.",
        evidence=(
            BenchmarkEvidenceItem(
                reference_id=reference,
                text="Inline recovery guidance is required for invalid fields.",
            ),
        ),
        expected=BenchmarkExpectedEvaluation(
            should_abstain=abstain,
            minimum_findings=0 if abstain else 1,
            maximum_findings=0 if abstain else 1,
            allowed_evidence_refs=(reference,),
            required_evidence_refs=() if abstain else (reference,),
            expected_criteria=() if abstain else (SyntheticFindingCriterion.ACTIONABILITY,),
            expected_severities=() if abstain else (SyntheticFindingSeverity.MAJOR,),
            required_role_terms=() if abstain else ("coordinator",),
            forbidden_claim_fragments=("real users will",),
        ),
    )


def _suite():
    return create_benchmark_suite(
        suite_id="evaluator-benchmark-protocol-v1",
        version_number=1,
        tasks=(
            _task(DatasetLanguage.ENGLISH, 1),
            _task(DatasetLanguage.ITALIAN, 2, abstain=True),
        ),
        source_manifest_sha256="d" * 64,
        frozen_at=STARTED_AT,
    )


def _valid_output(task):
    if task.expected.should_abstain:
        return {
            "overall_summary": "Le prove fornite non consentono una valutazione affidabile.",
            "role_statement": None,
            "findings": [],
            "evidence_gaps": ["Manca un artefatto interattivo."],
            "abstained": True,
        }
    reference = task.expected.required_evidence_refs[0]
    return {
        "overall_summary": "As the operations coordinator, I need actionable recovery guidance.",
        "role_statement": "Operations coordinator under time pressure.",
        "findings": [
            {
                "finding_id": "UTF-BENCH-001",
                "summary": "The recovery instruction is not visible near the invalid field.",
                "rationale": "The coordinator needs immediate guidance to continue the task.",
                "criterion": "actionability",
                "severity": "major",
                "epistemic_status": "MODEL_INFERRED",
                "evidence_refs": [reference],
                "recommended_action": "Add an inline explanation and retain keyboard focus.",
                "requires_human_validation": True,
            }
        ],
        "evidence_gaps": [],
        "abstained": False,
    }


def test_run_executes_bilingual_tasks_and_aggregates_protocol_metrics() -> None:
    suite = _suite()
    fixtures = []
    for task in suite.tasks:
        request = create_benchmark_generation_request(
            run_id=RUN_ID,
            task=task,
            model_identity=_identity(),
        )
        fixtures.append(
            create_fake_success_fixture(
                task_id=task.task_id,
                payload=_valid_output(task),
                expected_request_hash=request.content_hash,
                latency_milliseconds=10 if task.language is DatasetLanguage.ENGLISH else 20,
            )
        )
    adapter = FakeDeterministicStructuredAdapter(
        identity=_identity(),
        fixtures=tuple(fixtures),
    )

    run = asyncio.run(
        run_evaluator_benchmark(
            run_id=RUN_ID,
            candidate_id="model-candidate-small-instruct",
            suite=suite,
            model_identity=_identity(),
            adapter=adapter,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )
    )

    assert run.complete is True
    assert [item.language for item in run.task_scores] == [
        DatasetLanguage.ENGLISH,
        DatasetLanguage.ITALIAN,
    ]
    assert run.metric(BenchmarkMetricId.SCHEMA_VALID_RATE).value == 1.0
    assert run.metric(BenchmarkMetricId.EVIDENCE_REFERENCE_PRECISION).value == 1.0
    assert run.metric(BenchmarkMetricId.UNSUPPORTED_CLAIM_RATE).value == 0.0
    assert run.metric(BenchmarkMetricId.LATENCY_MILLISECONDS).value == 15.0
    assert run.metric(BenchmarkMetricId.PEAK_GPU_MEMORY_MB).value is None


def test_scorer_penalizes_unauthorized_evidence_and_empirical_overclaim() -> None:
    task = _task(DatasetLanguage.ENGLISH, 1)
    payload = _valid_output(task)
    finding = payload["findings"][0]
    finding["evidence_refs"] = ["REQ-NOT-ALLOWED"]
    finding["epistemic_status"] = "EMPIRICALLY_SUPPORTED"
    payload["overall_summary"] = "Real users will certainly complete the task."
    success = create_structured_generation_success(
        payload=payload,
        actual_identity=_identity(),
        usage=StructuredGenerationUsage(100, 50, 12),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="fixture-001",
    )
    result = successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
        success=success,
    )

    score = score_benchmark_result(task=task, result=result)

    assert score.schema_valid_rate == 1.0
    assert score.evidence_reference_precision == 0.0
    assert score.context_reference_recall == 0.0
    assert score.unsupported_claim_rate == 1.0


def test_invalid_output_is_preserved_as_schema_failure_without_crashing() -> None:
    task = _task(DatasetLanguage.ENGLISH, 1)
    success = create_structured_generation_success(
        payload={"findings": []},
        actual_identity=_identity(),
        usage=StructuredGenerationUsage(10, 5, 2),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id=None,
    )
    result = successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
        success=success,
    )

    score = score_benchmark_result(task=task, result=result)

    assert score.schema_valid_rate == 0.0
    assert score.generation_status.value == "SUCCEEDED"
    assert score.failure_code is None


def test_provider_failure_keeps_run_incomplete_and_failure_code_visible() -> None:
    suite = _suite()
    adapter = FakeDeterministicStructuredAdapter(
        identity=_identity(),
        fixtures=tuple(
            create_fake_failure_fixture(
                task_id=task.task_id,
                code=StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
                message="The benchmark fixture is unavailable.",
                retryable=True,
            )
            for task in suite.tasks
        ),
    )

    run = asyncio.run(
        run_evaluator_benchmark(
            run_id=RUN_ID,
            candidate_id="model-candidate-small-instruct",
            suite=suite,
            model_identity=_identity(),
            adapter=adapter,
            started_at=STARTED_AT,
            completed_at=COMPLETED_AT,
        )
    )

    assert run.complete is False
    assert {item.failure_code for item in run.task_scores} == {
        StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
    }
    assert run.metric(BenchmarkMetricId.LATENCY_MILLISECONDS).value is None


def test_direct_failed_result_scores_zero_without_inventing_latency() -> None:
    result = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
        code=StructuredGenerationFailureCode.TIMEOUT,
        message="The candidate timed out.",
        retryable=True,
    )

    score = score_benchmark_result(
        task=_task(DatasetLanguage.ITALIAN, 2, abstain=True),
        result=result,
    )

    assert score.failure_code is StructuredGenerationFailureCode.TIMEOUT
    assert score.latency_milliseconds is None
    assert score.schema_valid_rate == 0.0
