"""Tests for deriving formal case measurements from bound observed JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest

from orchestwin.evaluation.case_measurement_harvest import harvest_case_study_measurement
from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
)
from orchestwin.evaluation.case_studies import load_case_study_definition

REPO_ROOT = Path(__file__).resolve().parents[4]
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000033001")


def _metric_values(criteria_total: int) -> dict[str, object]:
    values: dict[str, object] = {}
    for field, value_type in METRIC_FIELD_TYPES.items():
        if value_type is MetricValueType.BOOLEAN:
            values[field] = True
        elif value_type is MetricValueType.NUMBER:
            values[field] = 2.5
        else:
            values[field] = 1
    values["criteria_total"] = criteria_total
    values["criteria_satisfied"] = criteria_total
    values["repair_successes"] = 0
    values["repair_attempts"] = 0
    return values


def _binding_set(case_id: str):
    return create_case_metric_binding_set(
        case_id=case_id,
        workflow_run_id=WORKFLOW_RUN_ID,
        bindings=tuple(
            CaseMetricBinding(
                field=field,
                value_type=value_type,
                source_path="observed-summary.json",
                json_pointer=f"/metrics/{field}",
            )
            for field, value_type in METRIC_FIELD_TYPES.items()
        ),
    )


def test_measurement_harvest_reads_real_values_and_records_source_paths(tmp_path) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    values = _metric_values(len(definition.definition_of_done))
    (evidence / "observed-summary.json").write_text(
        json.dumps({"metrics": values}), encoding="utf-8"
    )

    harvested = harvest_case_study_measurement(
        definition=definition,
        workflow_run_id=WORKFLOW_RUN_ID,
        evidence_root=evidence,
        binding_set=_binding_set(definition.case_id),
    )

    assert harvested.measurement.criteria_total == len(definition.definition_of_done)
    assert harvested.measurement.elapsed_seconds == 2.5
    assert harvested.source_evidence_paths == ("observed-summary.json",)
    assert len(harvested.content_hash) == 64


def test_measurement_harvest_rejects_cross_case_binding_set(tmp_path) -> None:
    definition = load_case_study_definition(
        REPO_ROOT / "experiments" / "case-studies" / "web-calculator-v1.json"
    )
    with pytest.raises(ValueError, match="different formal case"):
        harvest_case_study_measurement(
            definition=definition,
            workflow_run_id=WORKFLOW_RUN_ID,
            evidence_root=tmp_path,
            binding_set=_binding_set("other-case"),
        )
