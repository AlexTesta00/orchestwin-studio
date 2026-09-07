"""Tests for observed case-study measurement capture."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.case_metrics import CaseStudyMeasurement
from orchestwin.evaluation.case_observations import (
    create_case_study_observation_set,
    load_case_study_observation_set,
    write_case_study_observation_set,
)

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000012401")
NOW = datetime(2026, 9, 7, 15, 30, tzinfo=UTC)


def _measurement() -> CaseStudyMeasurement:
    return CaseStudyMeasurement(
        case_id="web-calculator",
        gates_completed=7,
        gates_total=7,
        artifacts_completed=8,
        artifacts_total=8,
        requirements_satisfied=7,
        requirements_total=7,
        criteria_satisfied=8,
        criteria_total=8,
        traceability_links_present=14,
        traceability_links_required=14,
        tests_passed=12,
        tests_total=12,
        repair_successes=1,
        repair_attempts=1,
        build_succeeded=True,
        final_runtime_succeeded=True,
        elapsed_seconds=321.5,
        model_calls=18,
        input_tokens=4200,
        output_tokens=1900,
        estimated_cost_usd=0.42,
    )


def test_observation_set_round_trips_explicit_raw_measurements(tmp_path) -> None:
    observations = create_case_study_observation_set(
        workflow_run_id=WORKFLOW_RUN_ID,
        measurement=_measurement(),
        source_evidence_paths=("workflow/events.json", "tests/report.json"),
        captured_at=NOW,
    )
    path = tmp_path / "observations.json"

    write_case_study_observation_set(path, observations)
    loaded = load_case_study_observation_set(path)

    assert loaded == observations
    assert loaded.observation_kind == "ACTUAL_RUN_EVIDENCE"
    assert loaded.source_evidence_paths == ("tests/report.json", "workflow/events.json")


def test_observation_loader_rejects_tampered_derived_metrics(tmp_path) -> None:
    observations = create_case_study_observation_set(
        workflow_run_id=WORKFLOW_RUN_ID,
        measurement=_measurement(),
        source_evidence_paths=("tests/report.json",),
        captured_at=NOW,
    )
    path = tmp_path / "observations.json"
    write_case_study_observation_set(path, observations)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["measurement"]["derived_metrics"]["test_pass_ratio"] = 0.5
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="derived metrics"):
        load_case_study_observation_set(path)
