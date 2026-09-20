"""Verify one generic actual-file harvester across all three frozen formal Web cases."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_harvest_pipeline import harvest_case_study_workspace_evidence
from orchestwin.evaluation.case_harvest_validation import verify_sprint12_case_harvest_contract
from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
NOW = datetime(2026, 9, 7, 19, 20, tzinfo=UTC)
CASE_FILES = (
    "web-calculator-v1.json",
    "hotel-management-web-v1.json",
    "weather-comparison-web-v1.json",
)


def _write_fixture_sources(workspace, definition, workflow_run_id):
    values = {}
    for field, value_type in METRIC_FIELD_TYPES.items():
        values[field] = True if value_type is MetricValueType.BOOLEAN else 1
    values["criteria_total"] = len(definition.definition_of_done)
    values["criteria_satisfied"] = len(definition.definition_of_done)
    values["repair_successes"] = 0
    values["repair_attempts"] = 0
    (workspace.evidence_dir / "metrics.json").write_text(
        json.dumps({"metrics": values}), encoding="utf-8"
    )
    bindings = create_case_metric_binding_set(
        case_id=definition.case_id,
        workflow_run_id=workflow_run_id,
        bindings=tuple(
            CaseMetricBinding(
                field=field,
                value_type=value_type,
                source_path="metrics.json",
                json_pointer=f"/metrics/{field}",
            )
            for field, value_type in METRIC_FIELD_TYPES.items()
        ),
    )
    by_kind = {}
    for criterion in definition.definition_of_done:
        for kind in criterion.evidence:
            by_kind.setdefault(kind, []).append(criterion.criterion_id)
    evidence_map = []
    for kind, criteria in sorted(by_kind.items(), key=lambda item: item[0].value):
        path = f"{kind.value.lower()}.json"
        (workspace.evidence_dir / path).write_text(
            json.dumps({"fixture": "harvest-contract-test", "kind": kind.value}), encoding="utf-8"
        )
        evidence_map.append(
            CaseStudyEvidenceMapEntry(
                kind=kind, relative_path=path, criterion_ids=tuple(sorted(criteria))
            )
        )
    return bindings, tuple(evidence_map)


def test_harvest_contract_preserves_revised_scope_and_conservative_claims() -> None:
    summary = verify_sprint12_case_harvest_contract(REPO_ROOT)
    assert summary.formal_case_ids == (
        "web-calculator",
        "hotel-management-web",
        "weather-comparison-web",
    )
    assert summary.metric_field_count == 21
    assert summary.binding_kind == "JSON_POINTER_EVIDENCE"
    assert summary.actual_file_values_required is True
    assert summary.fabricated_values_allowed is False
    assert summary.case_specific_logic_allowed is False
    assert summary.mobile_platforms_in_scope is False
    assert summary.real_user_behavior_validated is False
    assert summary.empirical_user_evidence_created is False


@pytest.mark.parametrize("case_file", CASE_FILES)
def test_same_generic_harvester_reads_fixture_files_for_every_formal_case(
    tmp_path, case_file: str
) -> None:
    definition = load_case_study_definition(REPO_ROOT / "experiments" / "case-studies" / case_file)
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="d" * 40)
    workflow_run_id = UUID(int=4000 + CASE_FILES.index(case_file))
    workspace, request = prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id=definition.case_id,
        workflow_run_id=workflow_run_id,
        requested_at=NOW,
    )
    bindings, evidence_map = _write_fixture_sources(workspace, definition, workflow_run_id)

    harvested = harvest_case_study_workspace_evidence(
        workspace=workspace,
        request=request,
        definition=definition,
        binding_set=bindings,
        evidence_map=evidence_map,
        captured_at=NOW,
    )

    assert harvested.observations.case_id == definition.case_id
    assert harvested.observations.workflow_run_id == workflow_run_id
    assert harvested.preflight.complete is True
    assert harvested.observations.measurement.criteria_satisfied == len(
        definition.definition_of_done
    )
