"""Tests for converting actual workspace files into finalization-ready raw evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_harvest_pipeline import harvest_case_study_workspace_evidence
from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000038001")
NOW = datetime(2026, 9, 7, 19, 0, tzinfo=UTC)


def test_workspace_harvest_materializes_finalization_ready_raw_files(tmp_path) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="b" * 40)
    workspace, request = prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=NOW,
    )
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
    binding_set = create_case_metric_binding_set(
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
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
        relative_path = f"{kind.value.lower()}.json"
        (workspace.evidence_dir / relative_path).write_text("{}", encoding="utf-8")
        evidence_map.append(
            CaseStudyEvidenceMapEntry(
                kind=kind, relative_path=relative_path, criterion_ids=tuple(sorted(criteria))
            )
        )

    harvested = harvest_case_study_workspace_evidence(
        workspace=workspace,
        request=request,
        definition=definition,
        binding_set=binding_set,
        evidence_map=tuple(evidence_map),
        captured_at=NOW,
    )

    assert harvested.preflight.complete is True
    assert harvested.observations.measurement.criteria_total == len(definition.definition_of_done)
    assert harvested.manifest_path.is_file()
    assert harvested.observations_path.is_file()
    assert harvested.harvest_record_path.is_file()
    assert harvested.evidence_map_path.is_file()
