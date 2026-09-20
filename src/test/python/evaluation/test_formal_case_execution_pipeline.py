"""Cross-case verification of the generic observed-evidence finalization pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_environment import create_case_study_environment_identity
from orchestwin.evaluation.case_execution_validation import (
    verify_sprint12_case_execution_pipeline,
)
from orchestwin.evaluation.case_finalization import finalize_case_study_run
from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_observations import create_case_study_observation_set
from orchestwin.evaluation.case_runs import CaseStudyRunStatus
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
PLATFORM_COMMIT = "9" * 40
NOW = datetime(2026, 9, 7, 17, 15, tzinfo=UTC)
CASE_FILES = (
    "web-calculator-v1.json",
    "hotel-management-web-v1.json",
    "weather-comparison-web-v1.json",
)


def _measurement(case_id: str, criteria_total: int) -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id=case_id,
        gates_completed=1,
        gates_total=1,
        artifacts_completed=1,
        artifacts_total=1,
        requirements_satisfied=1,
        requirements_total=1,
        criteria_satisfied=criteria_total,
        criteria_total=criteria_total,
        traceability_links_present=1,
        traceability_links_required=1,
        tests_passed=1,
        tests_total=1,
        repair_successes=0,
        repair_attempts=0,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=1.0,
        model_calls=1,
        input_tokens=1,
        output_tokens=1,
        estimated_cost_usd=0.0,
    )


def _fixture_evidence(definition, evidence_dir: Path):
    entries = []
    first_path = None
    for criterion in definition.definition_of_done:
        for kind in criterion.evidence:
            relative_path = f"{criterion.criterion_id.lower()}-{kind.value.lower()}.json"
            (evidence_dir / relative_path).write_text(
                '{"fixture":"pipeline-contract-test"}\n', encoding="utf-8"
            )
            entries.append(
                CaseStudyEvidenceMapEntry(
                    kind=kind,
                    relative_path=relative_path,
                    criterion_ids=(criterion.criterion_id,),
                )
            )
            first_path = first_path or relative_path
    return tuple(entries), first_path


def test_execution_pipeline_summary_preserves_revised_scope_and_evidence_boundaries() -> None:
    summary = verify_sprint12_case_execution_pipeline(
        REPO_ROOT,
        platform_commit=PLATFORM_COMMIT,
    )

    assert summary.formal_case_ids == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert summary.required_execution_profiles == ("WEB_STATIC", "WEB_VUE_NODE")
    assert summary.actual_files_only is True
    assert summary.observed_measurements_only is True
    assert summary.owner_gates_must_not_be_bypassed is True
    assert summary.jvm_validation_is_separate_fixture_matrix is True
    assert summary.mobile_platforms_in_scope is False
    assert summary.real_user_behavior_validated is False
    assert summary.empirical_user_evidence_created is False


@pytest.mark.parametrize("case_file", CASE_FILES)
def test_same_generic_finalizer_accepts_complete_fixture_evidence_for_every_formal_case(
    tmp_path,
    case_file: str,
) -> None:
    definition = load_case_study_definition(REPO_ROOT / "experiments" / "case-studies" / case_file)
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit=PLATFORM_COMMIT)
    workflow_run_id = UUID(int=1000 + CASE_FILES.index(case_file))
    workspace, request = prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id=definition.case_id,
        workflow_run_id=workflow_run_id,
        requested_at=NOW,
    )
    evidence_map, observation_source = _fixture_evidence(definition, workspace.evidence_dir)
    observations = create_case_study_observation_set(
        workflow_run_id=workflow_run_id,
        measurement=_measurement(definition.case_id, len(definition.definition_of_done)),
        source_evidence_paths=(observation_source,),
        captured_at=NOW,
    )
    environment = create_case_study_environment_identity(
        platform_commit=PLATFORM_COMMIT,
        execution_profile=definition.execution_profile,
        operating_system="fixture host",
        architecture="fixture architecture",
        python_version="3.14.0",
        runtime_versions=(),
        container_images=(),
        network_policy="Fixture-only test; no external network.",
        captured_at=NOW,
    )

    finalized = finalize_case_study_run(
        workspace=workspace,
        request=request,
        definition=definition,
        environment=environment,
        evidence_map=evidence_map,
        observations=observations,
        started_at=NOW,
        completed_at=NOW,
        status=CaseStudyRunStatus.COMPLETED,
    )

    assert finalized.coverage.is_complete is True
    assert finalized.record.case_id == definition.case_id
    assert finalized.record.execution_profile == definition.execution_profile
