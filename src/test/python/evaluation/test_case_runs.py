"""Tests for immutable formal case-study run records."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import (
    CaseStudyEvidenceReference,
    CaseStudyRunStatus,
    create_case_study_run_record,
)
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind

RUN_ID = UUID("00000000-0000-4000-8000-000000012001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000012002")
STARTED = datetime(2026, 9, 7, 14, 0, tzinfo=UTC)


def _measurement() -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id="web-calculator",
        gates_completed=5,
        gates_total=5,
        artifacts_completed=6,
        artifacts_total=6,
        requirements_satisfied=4,
        requirements_total=4,
        criteria_satisfied=3,
        criteria_total=3,
        traceability_links_present=4,
        traceability_links_required=4,
        tests_passed=8,
        tests_total=8,
        repair_successes=0,
        repair_attempts=0,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=42.5,
        model_calls=12,
        input_tokens=1_200,
        output_tokens=800,
        estimated_cost_usd=0.0,
    )


def _evidence() -> tuple[CaseStudyEvidenceReference, ...]:
    return (
        CaseStudyEvidenceReference(
            kind=CaseStudyEvidenceKind.TEST_REPORT,
            relative_path="tests/report.json",
            sha256_digest="a" * 64,
            size_bytes=512,
            criterion_ids=("CALC-DOD-002",),
        ),
        CaseStudyEvidenceReference(
            kind=CaseStudyEvidenceKind.FINAL_EXPORT,
            relative_path="export/project.zip",
            sha256_digest="b" * 64,
            size_bytes=4_096,
            criterion_ids=("CALC-DOD-001", "CALC-DOD-003"),
        ),
    )


def _record():
    return create_case_study_run_record(
        run_id=RUN_ID,
        case_id="web-calculator",
        case_version=1,
        case_content_hash="c" * 64,
        workflow_run_id=WORKFLOW_RUN_ID,
        platform_commit="d" * 40,
        execution_profile="WEB_STATIC",
        environment_identity_hash="e" * 64,
        started_at=STARTED,
        completed_at=STARTED + timedelta(seconds=42.5),
        status=CaseStudyRunStatus.COMPLETED,
        evidence=_evidence(),
        measurement=_measurement(),
        notes=("Formal thesis run; no empirical target-user study was performed.",),
    )


def test_case_run_record_is_deterministic_and_conservative() -> None:
    first = _record()
    second = _record()

    assert first == second
    assert first.content_hash == second.content_hash
    assert first.evidence[0].kind is CaseStudyEvidenceKind.FINAL_EXPORT
    assert first.real_user_behavior_validated is False
    assert first.empirical_user_evidence_created is False
    snapshot = first.to_snapshot()
    assert snapshot["measurement"]["derived_metrics"]["test_pass_ratio"] == 1.0


def test_case_run_record_rejects_tampering_and_unsafe_evidence_paths() -> None:
    record = _record()

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(record, platform_commit="f" * 40)
    with pytest.raises(ValueError, match="inside the case evidence root"):
        CaseStudyEvidenceReference(
            kind=CaseStudyEvidenceKind.TEST_REPORT,
            relative_path="../outside.json",
            sha256_digest="a" * 64,
            size_bytes=1,
            criterion_ids=("CALC-DOD-002",),
        )


def test_completed_case_run_requires_measurement_and_rejects_empirical_claims() -> None:
    record = _record()

    with pytest.raises(ValueError, match="require raw measurements"):
        replace(record, measurement=None, content_hash="0" * 64)
    with pytest.raises(ValueError, match="real-user behavior"):
        replace(record, real_user_behavior_validated=True, content_hash="0" * 64)
