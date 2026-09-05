"""Separated measurements must not convert syntax failures into semantic claims."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orchestwin.training.benchmark_measurement_v2 import (
    MeasurementV2Error,
    measure_evaluator_output_v2,
    summarize_measurements_v2,
)
from orchestwin.training.benchmark_suite_files import load_frozen_evaluator_benchmark_suite
from orchestwin.training.benchmarking import evaluator_benchmark_output_schema

ROOT = Path(__file__).resolve().parents[4]


def task():
    return load_frozen_evaluator_benchmark_suite(ROOT).tasks[0]


def schema():
    return json.loads(evaluator_benchmark_output_schema().canonical_schema_json)


def output():
    current = task()
    return {
        "overall_summary": current.profile_summary,
        "role_statement": current.profile_summary,
        "abstained": False,
        "evidence_gaps": [],
        "findings": [
            {
                "finding_id": "F-1",
                "summary": "A supplied requirement is not met.",
                "rationale": "This is a synthetic design hypothesis, not user research.",
                "criterion": current.expected.expected_criteria[0].value,
                "severity": current.expected.expected_severities[0].value,
                "epistemic_status": "MODEL_INFERRED",
                "evidence_refs": list(current.expected.required_evidence_refs),
                "recommended_action": "Review the interface with the represented role.",
                "requires_human_validation": True,
            }
        ],
    }


def measure(raw: str | None, *, current=None):
    return measure_evaluator_output_v2(
        task=current or task(),
        raw_output=raw,
        output_schema=schema(),
    ).to_snapshot()


def test_valid_output_separates_structure_and_protocol() -> None:
    record = measure(json.dumps(output()))
    assert record["json_object_valid"] is True
    assert record["json_schema_valid"] is True
    assert record["schema_issues"] == []
    assert all(record["protocol_checks"].values())
    assert record["semantic_metrics"]["evidence_reference_precision"]["value"] == 1.0
    assert record["semantic_metrics"]["unsupported_finding_heuristic_rate"]["value"] == 0.0


@pytest.mark.parametrize("raw", ["", "```json\n{}\n```", '{"findings":', "[]", "true", "null"])
def test_unparseable_or_non_object_outputs_have_no_semantic_scores(raw: str) -> None:
    record = measure(raw)
    assert record["json_object_valid"] is False
    assert record["json_schema_valid"] is None
    assert record["semantic_metrics"] is None
    assert all(value is None for value in record["protocol_checks"].values())


def test_missing_output_is_not_a_zero_score() -> None:
    record = measure(None)
    assert record["json_object_valid"] is None
    assert record["json_schema_valid"] is None
    assert record["semantic_metrics"] is None
    assert record["json_error"] is None


@pytest.mark.parametrize("raw", ['{"x":NaN}', '{"x":Infinity}', '{"x":1e999}', '{"x":1,"x":2}'])
def test_ambiguous_or_nonstandard_json_is_rejected_without_repair(raw: str) -> None:
    record = measure(raw)
    assert record["json_object_valid"] is False
    assert record["semantic_metrics"] is None


@pytest.mark.parametrize(
    "mutation",
    ["extra_root", "extra_finding", "missing", "bool_as_int", "enum"],
)
def test_exact_supplied_schema_is_enforced(mutation: str) -> None:
    value = output()
    if mutation == "extra_root":
        value["extra"] = 1
    elif mutation == "extra_finding":
        value["findings"][0]["extra"] = "not allowed"
    elif mutation == "missing":
        del value["findings"][0]["summary"]
    elif mutation == "bool_as_int":
        value["findings"][0]["requires_human_validation"] = 1
    else:
        value["findings"][0]["criterion"] = "not-an-enum"
    record = measure(json.dumps(value))
    assert record["json_object_valid"] is True
    assert record["json_schema_valid"] is False
    assert record["schema_issues"]
    assert record["semantic_metrics"] is None


def test_hidden_finding_count_does_not_become_a_schema_error() -> None:
    value = output()
    value["findings"] = [
        {**copy.deepcopy(value["findings"][0]), "finding_id": f"F-{index}"}
        for index in range(task().expected.maximum_findings + 1)
    ]
    record = measure(json.dumps(value))
    assert record["json_schema_valid"] is True
    assert record["protocol_checks"]["expected_finding_count"] is False
    assert record["semantic_metrics"]["evidence_reference_precision"]["value"] == 1.0
    assert record["finding_count_constraint_origin"] == "FROZEN_LABEL_NOT_IN_JSON_SCHEMA"


def test_nonempty_text_and_duplicate_ids_are_protocol_checks() -> None:
    value = output()
    value["overall_summary"] = " "
    value["findings"] *= 2
    record = measure(json.dumps(value))
    assert record["json_schema_valid"] is True
    assert record["protocol_checks"]["nonempty_text"] is False
    assert record["protocol_checks"]["unique_finding_ids"] is False


def test_abstention_is_measurable_even_when_an_unrelated_schema_field_is_missing() -> None:
    current = next(
        item
        for item in load_frozen_evaluator_benchmark_suite(ROOT).tasks
        if item.task_id == "bench-it-003"
    )
    value = output()
    value["abstained"] = False
    value["unexpected"] = "schema failure must not censor the decision"
    record = measure(json.dumps(value), current=current)
    assert record["json_schema_valid"] is False
    assert record["protocol_checks"]["abstention_matches_label"] is False


def test_abstention_with_findings_is_not_a_json_schema_failure() -> None:
    value = output()
    value["abstained"] = True
    record = measure(json.dumps(value))
    assert record["json_schema_valid"] is True
    assert record["protocol_checks"]["abstention_shape"] is False


def test_empty_reference_denominator_is_unobserved_not_perfect() -> None:
    value = output()
    value["findings"][0]["evidence_refs"] = []
    record = measure(json.dumps(value))
    ratio = record["semantic_metrics"]["evidence_reference_precision"]
    assert ratio == {"numerator": 0, "denominator": 0, "value": None}


def test_unknown_references_are_measured_with_explicit_denominator() -> None:
    value = output()
    value["findings"][0]["evidence_refs"] = [task().evidence[0].reference_id, "INVENTED"]
    record = measure(json.dumps(value))
    ratio = record["semantic_metrics"]["evidence_reference_precision"]
    assert ratio == {"numerator": 1, "denominator": 2, "value": 0.5}
    assert record["semantic_metrics"]["unsupported_finding_heuristic_rate"]["value"] == 1.0


def test_privileged_epistemic_status_and_human_flags_are_separate_observations() -> None:
    value = output()
    value["findings"][0]["epistemic_status"] = "EMPIRICALLY_SUPPORTED"
    value["findings"][0]["requires_human_validation"] = False
    record = measure(json.dumps(value))
    assert record["json_schema_valid"] is True
    assert record["semantic_metrics"]["unsupported_finding_heuristic_rate"]["value"] == 1.0
    assert record["semantic_metrics"]["human_validation_false_rate"]["value"] == 1.0


def test_abstention_without_findings_has_no_finding_based_semantic_denominator() -> None:
    value = output()
    value.update(abstained=True, findings=[])
    record = measure(json.dumps(value))
    assert record["semantic_metrics"]["unsupported_finding_heuristic_rate"] == {
        "numerator": 0,
        "denominator": 0,
        "value": None,
    }


def test_unknown_schema_revision_is_rejected_not_partially_interpreted() -> None:
    changed = schema()
    changed["properties"]["findings"]["maxItems"] = 2
    with pytest.raises(MeasurementV2Error, match="frozen output schema"):
        measure_evaluator_output_v2(
            task=task(),
            raw_output=json.dumps(output()),
            output_schema=changed,
        )


def test_summary_uses_real_generation_status_and_does_not_fabricate_semantic_scores() -> None:
    records = [
        {
            "generation_succeeded": True,
            "measurement": measure("```json\n{}\n```"),
            "finish_reason": "STOP",
        },
        {
            "generation_succeeded": True,
            "measurement": measure(json.dumps(output())),
            "finish_reason": "STOP",
        },
        {"generation_succeeded": False, "measurement": measure(None), "finish_reason": None},
        {"generation_succeeded": None, "measurement": measure(None), "finish_reason": None},
    ]
    summary = summarize_measurements_v2(records)
    assert summary["expected_task_count"] == 4
    assert summary["observed_task_count"] == 3
    assert summary["successful_generation_count"] == 2
    assert summary["failed_generation_count"] == 1
    assert summary["unobserved_generation_count"] == 1
    assert summary["json_object_valid_count"] == 1
    assert summary["json_schema_valid_count"] == 1
    assert summary["rates"]["json_schema_valid_given_generation"] == {
        "numerator": 1,
        "denominator": 2,
        "value": 0.5,
    }
    assert summary["semantic_metrics"]["unsupported_finding_heuristic_rate"]["value"] == 0.0
    assert summary["schema_evaluated_task_count"] == 1
    assert summary["semantic_evaluated_task_count"] == 1


def test_summary_of_only_invalid_json_has_null_semantic_metrics() -> None:
    summary = summarize_measurements_v2(
        [{"generation_succeeded": True, "measurement": measure("bad"), "finish_reason": "LENGTH"}]
    )
    assert summary["length_terminated_count"] == 1
    for metric in summary["semantic_metrics"].values():
        assert metric["value"] is None
        assert metric["denominator"] == 0
