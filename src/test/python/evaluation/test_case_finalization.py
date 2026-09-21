"""Tests for finalizing formal runs strictly from observed evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_environment import create_case_study_environment_identity
from orchestwin.evaluation.case_finalization import finalize_case_study_run
from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_observations import create_case_study_observation_set
from orchestwin.evaluation.case_runs import CaseStudyRunStatus
from orchestwin.evaluation.case_studies import (
    CaseStudyEvidenceKind,
    load_case_study_definition,
)
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
CASE_PATH = REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000012801")
PLATFORM_COMMIT = "6" * 40
STARTED = datetime(2026, 9, 7, 16, 45, tzinfo=UTC)
COMPLETED = datetime(2026, 9, 7, 16, 55, tzinfo=UTC)


def _measurement(criteria_satisfied: int) -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id="web-calculator",
        gates_completed=7,
        gates_total=7,
        artifacts_completed=9,
        artifacts_total=9,
        requirements_satisfied=7,
        requirements_total=7,
        criteria_satisfied=criteria_satisfied,
        criteria_total=8,
        traceability_links_present=14,
        traceability_links_required=14,
        tests_passed=12,
        tests_total=12,
        repair_successes=1,
        repair_attempts=1,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=600.0,
        model_calls=18,
        input_tokens=4200,
        output_tokens=1900,
        estimated_cost_usd=0.42,
    )


def _environment():
    return create_case_study_environment_identity(
        platform_commit=PLATFORM_COMMIT,
        execution_profile="WEB_STATIC",
        operating_system="Linux evaluation host",
        architecture="x86_64",
        python_version="3.14.0",
        runtime_versions=(),
        container_images=(),
        network_policy="No external network during generated application execution.",
        captured_at=STARTED,
    )


def _workspace(tmp_path):
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)
    return prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=STARTED,
    )


def _complete_map_and_files(evidence_dir: Path):
    specification = (
        (CaseStudyEvidenceKind.REQUIREMENTS, "requirements.json", ("CALC-001",)),
        (CaseStudyEvidenceKind.TRACEABILITY, "traceability.json", ("CALC-001", "CALC-007")),
        (CaseStudyEvidenceKind.BUILD_REPORT, "build.json", ("CALC-002",)),
        (CaseStudyEvidenceKind.TEST_REPORT, "tests.json", ("CALC-003",)),
        (CaseStudyEvidenceKind.RUNTIME_REPORT, "runtime.json", ("CALC-004",)),
        (
            CaseStudyEvidenceKind.ACCESSIBILITY_REPORT,
            "accessibility.json",
            ("CALC-004", "CALC-005"),
        ),
        (CaseStudyEvidenceKind.USER_TWIN_FINDINGS, "twins.json", ("CALC-006",)),
        (CaseStudyEvidenceKind.REPAIR_HISTORY, "repairs.json", ("CALC-007",)),
        (CaseStudyEvidenceKind.FINAL_EXPORT, "export.json", ("CALC-008",)),
    )
    entries = []
    for kind, relative_path, criterion_ids in specification:
        (evidence_dir / relative_path).write_text(
            f'{{"observed":"{relative_path}"}}\n', encoding="utf-8"
        )
        entries.append(
            CaseStudyEvidenceMapEntry(
                kind=kind,
                relative_path=relative_path,
                criterion_ids=criterion_ids,
            )
        )
    return tuple(entries)


def test_completed_run_requires_and_persists_complete_observed_evidence(tmp_path) -> None:
    workspace, request = _workspace(tmp_path)
    evidence_map = _complete_map_and_files(workspace.evidence_dir)
    observations = create_case_study_observation_set(
        workflow_run_id=WORKFLOW_RUN_ID,
        measurement=_measurement(8),
        source_evidence_paths=("runtime.json", "tests.json"),
        captured_at=COMPLETED,
    )

    finalized = finalize_case_study_run(
        workspace=workspace,
        request=request,
        definition=load_case_study_definition(CASE_PATH),
        environment=_environment(),
        evidence_map=evidence_map,
        observations=observations,
        started_at=STARTED,
        completed_at=COMPLETED,
        status=CaseStudyRunStatus.COMPLETED,
    )

    assert finalized.coverage.is_complete is True
    assert finalized.record.status is CaseStudyRunStatus.COMPLETED
    assert finalized.record.real_user_behavior_validated is False
    assert finalized.record.empirical_user_evidence_created is False
    assert finalized.record_path.is_file()


def test_completed_run_rejects_incomplete_definition_of_done_evidence(tmp_path) -> None:
    workspace, request = _workspace(tmp_path)
    (workspace.evidence_dir / "build.json").write_text('{"build":"ok"}\n', encoding="utf-8")
    evidence_map = (
        CaseStudyEvidenceMapEntry(
            kind=CaseStudyEvidenceKind.BUILD_REPORT,
            relative_path="build.json",
            criterion_ids=("CALC-002",),
        ),
    )
    observations = create_case_study_observation_set(
        workflow_run_id=WORKFLOW_RUN_ID,
        measurement=_measurement(1),
        source_evidence_paths=("build.json",),
        captured_at=COMPLETED,
    )

    with pytest.raises(ValueError, match="complete Definition-of-Done evidence"):
        finalize_case_study_run(
            workspace=workspace,
            request=request,
            definition=load_case_study_definition(CASE_PATH),
            environment=_environment(),
            evidence_map=evidence_map,
            observations=observations,
            started_at=STARTED,
            completed_at=COMPLETED,
            status=CaseStudyRunStatus.COMPLETED,
        )
