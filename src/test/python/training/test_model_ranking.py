"""Tests for hard model admission and deterministic evidence-based ranking."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.models.fake_structured import (
    FakeDeterministicStructuredAdapter,
    create_fake_success_fixture,
)
from orchestwin.models.structured_generation import ModelRuntimeIdentity
from orchestwin.training.benchmark_tasks import (
    BenchmarkEvidenceItem,
    BenchmarkExpectedEvaluation,
    BenchmarkTaskCategory,
    create_benchmark_suite,
    create_benchmark_task,
)
from orchestwin.training.benchmarking import (
    create_benchmark_generation_request,
    run_evaluator_benchmark,
)
from orchestwin.training.dataset_examples import DatasetLanguage
from orchestwin.training.environment_evidence import (
    AdapterExportLoadEvidence,
    InferenceResourceSummary,
    TrainingEnvironmentObservation,
    TrainingEnvironmentObservationStatus,
    TrainingEnvironmentProbeId,
    capture_training_environment,
    create_adapter_export_load_evidence,
)
from orchestwin.training.model_candidates import (
    ModelCandidateAvailability,
    ModelLicenseCompatibility,
    ModelLicenseEvidence,
    ModelQuantizationPath,
    ModelServingCompatibility,
    ModelTokenizerIdentity,
    create_model_benchmark_candidate,
)
from orchestwin.training.model_ranking import (
    ModelCandidateSpikeEvidence,
    ModelRankingExclusionReason,
    create_default_model_ranking_policy,
    rank_model_candidates,
)

OBSERVED_AT = datetime(2026, 10, 13, 16, 0, tzinfo=UTC)
RUN_ID = UUID("00000000-0000-4000-8000-000000119101")


def _suite():
    tasks = []
    for language, number in (
        (DatasetLanguage.ENGLISH, 1),
        (DatasetLanguage.ITALIAN, 2),
    ):
        reference = f"REQ-{number:03d}"
        tasks.append(
            create_benchmark_task(
                task_id=f"bench-{language.value}-{number:03d}",
                version_number=1,
                category=BenchmarkTaskCategory.SCHEMA_AND_PROVENANCE,
                language=language,
                profile_summary="Operations coordinator under time pressure.",
                scenario="Correct invalid input without losing work.",
                target_task="Recover and continue.",
                artifact_summary="The error is remote from the invalid field.",
                evidence=(BenchmarkEvidenceItem(reference, "Inline guidance is required."),),
                expected=BenchmarkExpectedEvaluation(
                    should_abstain=False,
                    minimum_findings=1,
                    maximum_findings=1,
                    allowed_evidence_refs=(reference,),
                    required_evidence_refs=(reference,),
                    expected_criteria=(SyntheticFindingCriterion.ACTIONABILITY,),
                    expected_severities=(SyntheticFindingSeverity.MAJOR,),
                    required_role_terms=("coordinator",),
                    forbidden_claim_fragments=("real users will",),
                ),
            )
        )
    return create_benchmark_suite(
        suite_id="evaluator-benchmark-ranking-v1",
        version_number=1,
        tasks=tuple(tasks),
        source_manifest_sha256="1" * 64,
        frozen_at=OBSERVED_AT,
    )


def _candidate(
    suffix: str,
    *,
    compatibility: ModelLicenseCompatibility = ModelLicenseCompatibility.COMPATIBLE,
    availability: ModelCandidateAvailability = ModelCandidateAvailability.AVAILABLE,
):
    repository = f"example/small-{suffix}"
    revision = ("a" if suffix == "a" else "b") * 40
    tokenizer_revision = ("c" if suffix == "a" else "d") * 40
    return create_model_benchmark_candidate(
        candidate_id=f"model-candidate-small-{suffix}",
        repository_id=repository,
        revision=revision,
        model_card_sha256="2" * 64,
        parameter_count_millions=3_000,
        context_limit_tokens=16_384,
        languages=(DatasetLanguage.ENGLISH, DatasetLanguage.ITALIAN),
        instruct_tuned=True,
        availability=availability,
        tokenizer=ModelTokenizerIdentity(
            repository_id=repository,
            revision=tokenizer_revision,
            vocabulary_sha256="3" * 64,
            configuration_sha256="4" * 64,
        ),
        quantization=ModelQuantizationPath(
            implementation="bitsandbytes",
            format_name="nf4",
            bit_width=4,
            compute_dtype="bfloat16",
            double_quantization=True,
        ),
        license_evidence=ModelLicenseEvidence(
            license_id=(
                "Apache-2.0" if compatibility is ModelLicenseCompatibility.COMPATIBLE else "Custom"
            ),
            source_url=f"https://example.test/{suffix}/license",
            source_revision="5" * 40,
            document_sha256="6" * 64,
            compatibility=compatibility,
            allows_adapter_redistribution=(compatibility is ModelLicenseCompatibility.COMPATIBLE),
            allows_weight_redistribution=True,
            attribution_required=True,
            captured_at=OBSERVED_AT,
        ),
        serving_compatibility=(
            ModelServingCompatibility(
                runtime_id="openai-compatible-local",
                runtime_version="1.0.0",
                compatible=True,
                evidence_reference="spike:local-serving",
                evidence_sha256="7" * 64,
            ),
        ),
        created_at=OBSERVED_AT,
    )


def _identity(candidate) -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="fake-ranking",
        runtime_id="fake-evaluator-v1",
        base_model_repository=candidate.repository_id,
        base_model_revision=candidate.revision,
        tokenizer_revision=candidate.tokenizer.revision,
        configuration_sha256="8" * 64,
    )


def _output(reference: str) -> dict[str, object]:
    return {
        "overall_summary": "The coordinator needs actionable recovery guidance.",
        "role_statement": "Operations coordinator under time pressure.",
        "findings": [
            {
                "finding_id": "UTF-RANK-001",
                "summary": "The recovery instruction is too remote.",
                "rationale": "The coordinator needs immediate task guidance.",
                "criterion": "actionability",
                "severity": "major",
                "epistemic_status": "MODEL_INFERRED",
                "evidence_refs": [reference],
                "recommended_action": "Add inline recovery guidance.",
                "requires_human_validation": True,
            }
        ],
        "evidence_gaps": [],
        "abstained": False,
    }


async def _benchmark(candidate, suite):
    identity = _identity(candidate)
    fixtures = []
    for task in suite.tasks:
        request = create_benchmark_generation_request(
            run_id=RUN_ID,
            task=task,
            model_identity=identity,
        )
        fixtures.append(
            create_fake_success_fixture(
                task_id=task.task_id,
                payload=_output(task.expected.required_evidence_refs[0]),
                expected_request_hash=request.content_hash,
                latency_milliseconds=10,
            )
        )
    return await run_evaluator_benchmark(
        run_id=RUN_ID,
        candidate_id=candidate.candidate_id,
        suite=suite,
        model_identity=identity,
        adapter=FakeDeterministicStructuredAdapter(
            identity=identity,
            fixtures=tuple(fixtures),
        ),
        started_at=OBSERVED_AT,
        completed_at=OBSERVED_AT,
    )


@dataclass
class _EnvironmentProbe:
    async def observe(self, probe_id):
        value = "8192" if probe_id is TrainingEnvironmentProbeId.GPU_MEMORY_MB else "observed"
        return TrainingEnvironmentObservation(
            probe_id=probe_id,
            status=TrainingEnvironmentObservationStatus.OBSERVED,
            value=value,
            source=f"fixture:{probe_id.value}",
        )


async def _environment():
    return await capture_training_environment(
        capture_id=UUID("00000000-0000-4000-8000-000000119102"),
        probe=_EnvironmentProbe(),
        package_lock_sha256="9" * 64,
        captured_at=OBSERVED_AT,
    )


def _resources(candidate_id: str, *, latency: float, peak_memory: int, complete: bool = True):
    return InferenceResourceSummary(
        candidate_id=candidate_id,
        measurement_count=2,
        successful_count=2 if complete else 1,
        mean_latency_milliseconds=latency,
        peak_gpu_memory_mb=peak_memory,
        complete=complete,
    )


def _adapter_evidence(candidate_id: str, *, passed: bool = True) -> AdapterExportLoadEvidence:
    return create_adapter_export_load_evidence(
        candidate_id=candidate_id,
        smoke_training_succeeded=passed,
        adapter_exported=passed,
        adapter_loaded=passed,
        structured_output_valid=passed,
        adapter_artifact_sha256="a" * 64 if passed else None,
        evidence_references=("artifact:adapter-smoke",),
        observed_at=OBSERVED_AT,
    )


def _evidence(candidate, suite, *, latency: float, memory: int, adapter_passed: bool = True):
    return ModelCandidateSpikeEvidence(
        candidate=candidate,
        benchmark_run=asyncio.run(_benchmark(candidate, suite)),
        environment=asyncio.run(_environment()),
        resources=_resources(candidate.candidate_id, latency=latency, peak_memory=memory),
        adapter_evidence=_adapter_evidence(candidate.candidate_id, passed=adapter_passed),
    )


def test_eligible_candidates_are_ranked_by_policy_with_deterministic_tie_breaks() -> None:
    suite = _suite()
    candidate_a = _candidate("a")
    candidate_b = _candidate("b")
    policy = create_default_model_ranking_policy(benchmark_suite_content_hash=suite.content_hash)

    ranking = rank_model_candidates(
        policy=policy,
        evidence=(
            _evidence(candidate_b, suite, latency=900, memory=6_000),
            _evidence(candidate_a, suite, latency=400, memory=4_000),
        ),
    )

    assert ranking.recommended_candidate_id == candidate_a.candidate_id
    assert ranking.entry(candidate_a.candidate_id).rank == 1
    assert ranking.entry(candidate_b.candidate_id).rank == 2
    assert ranking.entry(candidate_a.candidate_id).weighted_score is not None
    assert ranking.entry(candidate_a.candidate_id).weighted_score > (
        ranking.entry(candidate_b.candidate_id).weighted_score or 0.0
    )


def test_hard_constraints_preserve_all_exclusion_reasons() -> None:
    suite = _suite()
    candidate = _candidate(
        "a",
        compatibility=ModelLicenseCompatibility.INCOMPATIBLE,
        availability=ModelCandidateAvailability.REQUIRES_ACCESS,
    )
    policy = create_default_model_ranking_policy(benchmark_suite_content_hash=suite.content_hash)

    ranking = rank_model_candidates(
        policy=policy,
        evidence=(_evidence(candidate, suite, latency=40_000, memory=9_000, adapter_passed=False),),
    )
    entry = ranking.entries[0]

    assert entry.eligible is False
    assert ranking.recommended_candidate_id is None
    assert {
        ModelRankingExclusionReason.MODEL_UNAVAILABLE,
        ModelRankingExclusionReason.LICENSE_INCOMPATIBLE,
        ModelRankingExclusionReason.ADAPTER_REDISTRIBUTION_NOT_ALLOWED,
        ModelRankingExclusionReason.GPU_MEMORY_LIMIT_EXCEEDED,
        ModelRankingExclusionReason.LATENCY_LIMIT_EXCEEDED,
        ModelRankingExclusionReason.ADAPTER_SMOKE_FAILED,
    }.issubset(entry.exclusion_reasons)


def test_resource_incompleteness_blocks_ranking_instead_of_imputing_values() -> None:
    suite = _suite()
    candidate = _candidate("a")
    evidence = _evidence(candidate, suite, latency=500, memory=4_000)
    incomplete = ModelCandidateSpikeEvidence(
        candidate=evidence.candidate,
        benchmark_run=evidence.benchmark_run,
        environment=evidence.environment,
        resources=_resources(
            candidate.candidate_id,
            latency=500,
            peak_memory=4_000,
            complete=False,
        ),
        adapter_evidence=evidence.adapter_evidence,
    )

    ranking = rank_model_candidates(
        policy=create_default_model_ranking_policy(benchmark_suite_content_hash=suite.content_hash),
        evidence=(incomplete,),
    )

    assert ranking.entries[0].weighted_score is None
    assert ModelRankingExclusionReason.RESOURCE_EVIDENCE_INCOMPLETE in (
        ranking.entries[0].exclusion_reasons
    )


def test_ranking_is_a_recommendation_and_contains_no_owner_approval_state() -> None:
    suite = _suite()
    candidate = _candidate("a")
    ranking = rank_model_candidates(
        policy=create_default_model_ranking_policy(benchmark_suite_content_hash=suite.content_hash),
        evidence=(_evidence(candidate, suite, latency=500, memory=4_000),),
    )

    snapshot = ranking.to_snapshot()
    assert snapshot["recommended_candidate_id"] == candidate.candidate_id
    assert "approved" not in snapshot
    assert "owner_decision" not in snapshot
