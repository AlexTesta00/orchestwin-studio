"""Tests for frozen bilingual evaluator benchmark tasks and metrics."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingSeverity,
)
from orchestwin.training.benchmark_tasks import (
    BenchmarkEvidenceItem,
    BenchmarkExpectedEvaluation,
    BenchmarkMetricId,
    BenchmarkTaskCategory,
    create_benchmark_suite,
    create_benchmark_task,
)
from orchestwin.training.dataset_examples import DatasetLanguage

FROZEN_AT = datetime(2026, 10, 13, 13, 0, tzinfo=UTC)


def _expected(reference: str, *, abstain: bool = False) -> BenchmarkExpectedEvaluation:
    return BenchmarkExpectedEvaluation(
        should_abstain=abstain,
        minimum_findings=0 if abstain else 1,
        maximum_findings=0 if abstain else 2,
        allowed_evidence_refs=(reference,),
        required_evidence_refs=() if abstain else (reference,),
        expected_criteria=() if abstain else (SyntheticFindingCriterion.ACTIONABILITY,),
        expected_severities=() if abstain else (SyntheticFindingSeverity.MAJOR,),
        required_role_terms=("coordinator",) if not abstain else (),
        forbidden_claim_fragments=("real users will",),
    )


def _task(language: DatasetLanguage, number: int, *, abstain: bool = False):
    reference = f"REQ-{number:03d}"
    return create_benchmark_task(
        task_id=f"bench-{language.value}-{number:03d}",
        version_number=1,
        category=BenchmarkTaskCategory.ABSTENTION
        if abstain
        else BenchmarkTaskCategory.SCHEMA_AND_PROVENANCE,
        language=language,
        profile_summary="Operations coordinator working under time pressure.",
        scenario="Recover from a validation error without losing entered information.",
        target_task="Correct the invalid value and continue the workflow.",
        artifact_summary="The form reports an error only at the top of the page.",
        evidence=(
            BenchmarkEvidenceItem(
                reference_id=reference,
                text="Inline recovery guidance is required for invalid fields.",
            ),
        ),
        expected=_expected(reference, abstain=abstain),
    )


def test_suite_freezes_bilingual_tasks_and_complete_metric_policy() -> None:
    italian = _task(DatasetLanguage.ITALIAN, 2, abstain=True)
    english = _task(DatasetLanguage.ENGLISH, 1)

    suite = create_benchmark_suite(
        suite_id="evaluator-benchmark-protocol-v1",
        version_number=1,
        tasks=(italian, english),
        source_manifest_sha256="a" * 64,
        frozen_at=FROZEN_AT,
    )

    assert [task.task_id for task in suite.tasks] == ["bench-en-001", "bench-it-002"]
    assert {metric.metric_id for metric in suite.metrics} == set(BenchmarkMetricId)
    assert len(suite.content_hash) == 64


def test_task_hash_rejects_changed_frozen_labels() -> None:
    task = _task(DatasetLanguage.ENGLISH, 1)

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(task, artifact_summary="A different artifact is shown.")


def test_expected_references_must_be_present_and_allowed() -> None:
    with pytest.raises(ValueError, match="must be allowed"):
        BenchmarkExpectedEvaluation(
            should_abstain=False,
            minimum_findings=1,
            maximum_findings=1,
            allowed_evidence_refs=("REQ-001",),
            required_evidence_refs=("REQ-002",),
            expected_criteria=(SyntheticFindingCriterion.ACTIONABILITY,),
            expected_severities=(SyntheticFindingSeverity.MAJOR,),
            required_role_terms=(),
            forbidden_claim_fragments=(),
        )


def test_suite_rejects_missing_language_and_duplicate_task_identity() -> None:
    english = _task(DatasetLanguage.ENGLISH, 1)

    with pytest.raises(ValueError, match="English and Italian"):
        create_benchmark_suite(
            suite_id="evaluator-benchmark-protocol-v1",
            version_number=1,
            tasks=(english,),
            source_manifest_sha256="b" * 64,
            frozen_at=FROZEN_AT,
        )

    with pytest.raises(ValueError, match="identities must be unique"):
        create_benchmark_suite(
            suite_id="evaluator-benchmark-protocol-v1",
            version_number=1,
            tasks=(english, english, _task(DatasetLanguage.ITALIAN, 2)),
            source_manifest_sha256="c" * 64,
            frozen_at=FROZEN_AT,
        )


def test_abstention_task_cannot_require_findings() -> None:
    with pytest.raises(ValueError, match="cannot require findings"):
        replace(_expected("REQ-001", abstain=True), minimum_findings=1)
