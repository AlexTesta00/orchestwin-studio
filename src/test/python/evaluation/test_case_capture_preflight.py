"""Tests for semantic capture preflight against the frozen Definition of Done."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_artifact_capture import CaseStudyEvidenceMapEntry
from orchestwin.evaluation.case_campaign import build_formal_case_campaign_plan
from orchestwin.evaluation.case_capture_preflight import evaluate_case_capture_preflight
from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_source_manifest import capture_observed_evidence_manifest
from orchestwin.evaluation.case_studies import load_case_study_definition
from orchestwin.evaluation.case_workspace import prepare_case_study_run_workspace

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000037001")
NOW = datetime(2026, 9, 7, 18, 50, tzinfo=UTC)


def _entries(definition):
    by_kind = {}
    for criterion in definition.definition_of_done:
        for kind in criterion.evidence:
            by_kind.setdefault(kind, []).append(criterion.criterion_id)
    return tuple(
        CaseStudyEvidenceMapEntry(
            kind=kind,
            relative_path=f"{kind.value.lower()}.json",
            criterion_ids=tuple(sorted(criteria)),
        )
        for kind, criteria in sorted(by_kind.items(), key=lambda item: item[0].value)
    )


def test_capture_preflight_requires_complete_dod_mapping(tmp_path) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    campaign = build_formal_case_campaign_plan(REPO_ROOT, platform_commit="a" * 40)
    workspace, request = prepare_case_study_run_workspace(
        tmp_path,
        campaign,
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        requested_at=NOW,
    )
    (workspace.evidence_dir / "metrics.json").write_text(
        json.dumps({"metrics": {}}), encoding="utf-8"
    )
    entries = _entries(definition)
    for entry in entries:
        (workspace.evidence_dir / entry.relative_path).write_text("{}", encoding="utf-8")
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
    paths = tuple(sorted({"metrics.json", *(entry.relative_path for entry in entries)}))
    manifest = capture_observed_evidence_manifest(
        evidence_root=workspace.evidence_dir,
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        relative_paths=paths,
        captured_at=NOW,
    )

    summary = evaluate_case_capture_preflight(
        definition=definition,
        request=request,
        binding_set=binding_set,
        manifest=manifest,
        evidence_map=entries,
    )
    assert summary.complete is True
    assert summary.required_evidence_pairs == summary.covered_evidence_pairs

    with pytest.raises(ValueError, match="evidence mapping is incomplete"):
        evaluate_case_capture_preflight(
            definition=definition,
            request=request,
            binding_set=binding_set,
            manifest=manifest,
            evidence_map=entries[:-1],
        )
