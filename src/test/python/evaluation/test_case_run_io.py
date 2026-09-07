"""Tests for finalized case-study run manifest persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_run_io import (
    load_case_study_run_record,
    write_case_study_run_record,
)
from orchestwin.evaluation.case_runs import (
    CaseStudyEvidenceReference,
    CaseStudyRunStatus,
    create_case_study_run_record,
)
from orchestwin.evaluation.case_studies import CaseStudyEvidenceKind

NOW = datetime(2026, 9, 7, 15, 0, tzinfo=UTC)


def _record():
    measurement = CaseStudyMeasurement(
        case_id="web-calculator",
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
        tests_passed=2,
        tests_total=2,
        repair_successes=0,
        repair_attempts=0,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=2.0,
        model_calls=1,
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.0,
    )
    evidence = CaseStudyEvidenceReference(
        kind=CaseStudyEvidenceKind.TEST_REPORT,
        relative_path="tests/report.json",
        sha256_digest="a" * 64,
        size_bytes=200,
        criterion_ids=("CALC-DOD-001",),
    )
    return create_case_study_run_record(
        run_id=UUID("00000000-0000-4000-8000-000000012201"),
        case_id="web-calculator",
        case_version=1,
        case_content_hash="b" * 64,
        workflow_run_id=UUID("00000000-0000-4000-8000-000000012202"),
        platform_commit="c" * 40,
        execution_profile="WEB_STATIC",
        environment_identity_hash="d" * 64,
        started_at=NOW,
        completed_at=NOW + timedelta(seconds=2),
        status=CaseStudyRunStatus.COMPLETED,
        evidence=(evidence,),
        measurement=measurement,
    )


def test_case_run_record_round_trips_without_semantic_changes(tmp_path) -> None:
    record = _record()
    path = tmp_path / "run.json"

    write_case_study_run_record(path, record)
    loaded = load_case_study_run_record(path)

    assert loaded == record
    assert loaded.content_hash == record.content_hash
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_case_run_record_is_immutable_by_default(tmp_path) -> None:
    record = _record()
    path = tmp_path / "run.json"
    write_case_study_run_record(path, record)

    with pytest.raises(FileExistsError, match="already exists"):
        write_case_study_run_record(path, record)


def test_case_run_loader_rejects_tampered_derived_metrics(tmp_path) -> None:
    record = _record()
    path = tmp_path / "run.json"
    write_case_study_run_record(path, record)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measurement"]["derived_metrics"]["test_pass_ratio"] = 0.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="derived case-study metrics"):
        load_case_study_run_record(path)
