"""Freeze the raw-metric binding contract before real case-study evidence is harvested."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CONTRACT = REPO_ROOT / "experiments" / "case-studies" / "observed-metric-bindings-contract-v1.json"

EXPECTED_FIELDS = {
    "gates_completed": "INTEGER",
    "gates_total": "INTEGER",
    "artifacts_completed": "INTEGER",
    "artifacts_total": "INTEGER",
    "requirements_satisfied": "INTEGER",
    "requirements_total": "INTEGER",
    "criteria_satisfied": "INTEGER",
    "criteria_total": "INTEGER",
    "traceability_links_present": "INTEGER",
    "traceability_links_required": "INTEGER",
    "tests_passed": "INTEGER",
    "tests_total": "INTEGER",
    "repair_successes": "INTEGER",
    "repair_attempts": "INTEGER",
    "build_succeeded": "BOOLEAN",
    "final_runtime_succeeded": "BOOLEAN",
    "elapsed_seconds": "NUMBER",
    "model_calls": "INTEGER",
    "input_tokens": "INTEGER",
    "output_tokens": "INTEGER",
    "estimated_cost_usd": "NUMBER",
}


def test_observed_metric_binding_contract_requires_actual_json_pointer_evidence() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["binding_kind"] == "JSON_POINTER_EVIDENCE"
    assert payload["source_truth"] == "ACTUAL_WORKFLOW_EVIDENCE"
    assert payload["values_must_be_read_from_source"] is True
    assert payload["fabricated_values_allowed"] is False
    assert payload["case_specific_logic_allowed"] is False
    assert {item["field"]: item["type"] for item in payload["required_fields"]} == EXPECTED_FIELDS


def test_metric_binding_contract_contains_no_stale_mobile_scope() -> None:
    raw = CONTRACT.read_text(encoding="utf-8").lower()
    assert "android" not in raw
    assert "flutter" not in raw
