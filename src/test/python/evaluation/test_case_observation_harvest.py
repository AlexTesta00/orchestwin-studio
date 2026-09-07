"""Tests for provenance-preserving observation materialization."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_observation_harvest import (
    harvest_case_study_observations,
    load_case_observation_harvest_record,
    write_case_observation_harvest_record,
)
from orchestwin.evaluation.case_source_manifest import capture_observed_evidence_manifest
from orchestwin.evaluation.case_studies import load_case_study_definition

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000036001")
NOW = datetime(2026, 9, 7, 18, 40, tzinfo=UTC)


def test_observation_harvest_links_measurements_to_binding_and_manifest_hashes(tmp_path) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    values = {}
    for field, value_type in METRIC_FIELD_TYPES.items():
        if value_type is MetricValueType.BOOLEAN:
            values[field] = True
        elif value_type is MetricValueType.NUMBER:
            values[field] = 1.0
        else:
            values[field] = 1
    values["criteria_total"] = len(definition.definition_of_done)
    values["criteria_satisfied"] = len(definition.definition_of_done)
    values["repair_successes"] = 0
    values["repair_attempts"] = 0
    (evidence / "metrics.json").write_text(json.dumps({"metrics": values}), encoding="utf-8")
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
    manifest = capture_observed_evidence_manifest(
        evidence_root=evidence,
        case_id=definition.case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        relative_paths=("metrics.json",),
        captured_at=NOW,
    )

    observations, record = harvest_case_study_observations(
        definition=definition,
        workflow_run_id=WORKFLOW_RUN_ID,
        evidence_root=evidence,
        binding_set=binding_set,
        manifest=manifest,
        captured_at=NOW,
    )
    path = tmp_path / "harvest.json"
    write_case_observation_harvest_record(path, record)

    assert observations.measurement.case_id == definition.case_id
    assert record.binding_set_hash == binding_set.content_hash
    assert record.evidence_manifest_hash == manifest.content_hash
    assert load_case_observation_harvest_record(path) == record
