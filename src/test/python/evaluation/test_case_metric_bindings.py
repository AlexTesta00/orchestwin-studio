"""Tests for complete metric bindings resolved from actual JSON evidence."""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from orchestwin.evaluation.case_metric_bindings import (
    METRIC_FIELD_TYPES,
    CaseMetricBinding,
    MetricValueType,
    create_case_metric_binding_set,
    load_case_metric_binding_set,
    resolve_case_metric_values,
    resolve_json_pointer,
    write_case_metric_binding_set,
)

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000031001")


def _value(field: str) -> object:
    value_type = METRIC_FIELD_TYPES[field]
    if value_type is MetricValueType.BOOLEAN:
        return True
    if value_type is MetricValueType.NUMBER:
        return 1.5
    return 1


def _bindings():
    return tuple(
        CaseMetricBinding(
            field=field,
            value_type=value_type,
            source_path="workflow-summary.json",
            json_pointer=f"/metrics/{field}",
        )
        for field, value_type in METRIC_FIELD_TYPES.items()
    )


def test_binding_set_resolves_every_metric_from_json_and_round_trips(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    expected = {field: _value(field) for field in METRIC_FIELD_TYPES}
    (evidence / "workflow-summary.json").write_text(
        json.dumps({"metrics": expected}), encoding="utf-8"
    )
    binding_set = create_case_metric_binding_set(
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        bindings=_bindings(),
    )
    path = tmp_path / "bindings.json"
    write_case_metric_binding_set(path, binding_set)

    loaded = load_case_metric_binding_set(path)

    assert loaded == binding_set
    assert resolve_case_metric_values(evidence, loaded) == expected


def test_binding_set_rejects_missing_fields_and_wrong_types(tmp_path) -> None:
    with pytest.raises(ValueError, match="field set is incomplete"):
        create_case_metric_binding_set(
            case_id="web-calculator",
            workflow_run_id=WORKFLOW_RUN_ID,
            bindings=_bindings()[:-1],
        )

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    values = {field: _value(field) for field in METRIC_FIELD_TYPES}
    values["tests_passed"] = True
    (evidence / "workflow-summary.json").write_text(
        json.dumps({"metrics": values}), encoding="utf-8"
    )
    binding_set = create_case_metric_binding_set(
        case_id="web-calculator",
        workflow_run_id=WORKFLOW_RUN_ID,
        bindings=_bindings(),
    )
    with pytest.raises(ValueError, match="tests_passed must resolve to an integer"):
        resolve_case_metric_values(evidence, binding_set)


def test_json_pointer_supports_escaped_tokens_and_rejects_missing_tokens() -> None:
    document = {"a/b": {"til~de": ["zero", "one"]}}
    assert resolve_json_pointer(document, "/a~1b/til~0de/1") == "one"
    with pytest.raises(ValueError, match="not found"):
        resolve_json_pointer(document, "/missing/value")
