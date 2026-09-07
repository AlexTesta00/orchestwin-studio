"""Tests for formal case-study environment identity and run binding."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.case_environment import (
    CaseStudyContainerImage,
    CaseStudyRuntimeVersion,
    create_case_study_environment_identity,
    verify_case_study_environment_binding,
)
from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_runs import (
    CaseStudyEvidenceReference,
    CaseStudyRunStatus,
    create_case_study_run_record,
)
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind

NOW = datetime(2026, 9, 7, 15, 30, tzinfo=UTC)


def _environment():
    return create_case_study_environment_identity(
        platform_commit="a" * 40,
        execution_profile="WEB_VUE_NODE",
        operating_system="Linux 6.6 WSL2",
        architecture="x86_64",
        python_version="3.14.0",
        runtime_versions=(
            CaseStudyRuntimeVersion(component="Node.js", version="24.8.0"),
            CaseStudyRuntimeVersion(component="npm", version="11.6.0"),
        ),
        container_images=(
            CaseStudyContainerImage(name="orchestwin/web-node-runner", digest="sha256:" + "b" * 64),
        ),
        network_policy=(
            "Network disabled during deterministic execution after dependency preparation."
        ),
        captured_at=NOW,
    )


def _run(environment_hash: str):
    measurement = CaseStudyMeasurement(
        case_id="hotel-management-web",
        gates_completed=1,
        gates_total=1,
        artifacts_completed=1,
        artifacts_total=1,
        requirements_satisfied=1,
        requirements_total=1,
        criteria_satisfied=1,
        criteria_total=1,
        traceability_links_present=1,
        traceability_links_required=1,
        tests_passed=1,
        tests_total=1,
        repair_successes=0,
        repair_attempts=0,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=3.0,
        model_calls=1,
        input_tokens=20,
        output_tokens=10,
        estimated_cost_usd=0.0,
    )
    evidence = CaseStudyEvidenceReference(
        kind=CaseStudyEvidenceKind.RUNTIME_REPORT,
        relative_path="runtime/report.json",
        sha256_digest="c" * 64,
        size_bytes=100,
        criterion_ids=("HOTEL-DOD-001",),
    )
    return create_case_study_run_record(
        run_id=UUID("00000000-0000-4000-8000-000000012301"),
        case_id="hotel-management-web",
        case_version=1,
        case_content_hash="d" * 64,
        workflow_run_id=UUID("00000000-0000-4000-8000-000000012302"),
        platform_commit="a" * 40,
        execution_profile="WEB_VUE_NODE",
        environment_identity_hash=environment_hash,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=3),
        status=CaseStudyRunStatus.COMPLETED,
        evidence=(evidence,),
        measurement=measurement,
    )


def test_environment_identity_is_deterministic_and_binds_exactly_to_run() -> None:
    first = _environment()
    second = _environment()
    run = _run(first.content_hash)

    assert first == second
    assert first.content_hash == second.content_hash
    verify_case_study_environment_binding(run, first)


def test_environment_binding_rejects_hash_mismatch() -> None:
    environment = _environment()
    run = _run("e" * 64)

    with pytest.raises(ValueError, match="not bound"):
        verify_case_study_environment_binding(run, environment)


def test_environment_rejects_unpinned_container_identity() -> None:
    with pytest.raises(ValueError, match="sha256"):
        CaseStudyContainerImage(name="runner", digest="latest")
