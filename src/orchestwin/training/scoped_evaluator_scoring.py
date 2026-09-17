"""Development screen for exact targets, partial gaps and native evaluator outputs.

This does not infer arbitrary narrative truth or replace expert review. It never
repairs a response, consults model scores to change labels, or promotes a model.
"""

from __future__ import annotations

import re

from orchestwin.evaluation.model_evaluator import ModelGatewayEvaluationError
from orchestwin.models.strict_evaluator_json import strict_json_object, validate_evaluator_value
from orchestwin.training.evaluator_assessment import validate_domain_response

SCORING_VERSION = "scoped-evaluator-development-v1"


def mentioned_targets(text):
    return set(re.findall(r"#[A-Za-z][A-Za-z0-9_-]*", text))


def assess(raw, row, *, eos_finished, schema_finished):
    controls = row["control_judgements"]
    if not controls or len({c["target"] for c in controls}) != len(controls):
        raise ValueError("unique labelled requested controls required")
    if any(c["state"] not in {"MISSING", "PRESENT", "INSUFFICIENT"} for c in controls):
        raise ValueError("unknown target state")
    expected = {"dom:#" + c["target"] for c in controls if c["state"] == "MISSING"}
    absent = {"#" + c["target"] for c in controls if c["state"] == "INSUFFICIENT"}
    requested = {"#" + c["target"] for c in controls}
    criteria = {
        "dom:#" + c["target"]: "actionability"
        if c["family"] == "error_guidance"
        else "accessibility"
        for c in controls
    }
    checks = dict.fromkeys(
        ("schema", "domain", "locations", "criterion", "gaps", "abstention", "summary_scope"),
        False,
    )
    checks.update(eos=eos_finished is True, schema_finished=schema_finished is True)
    errors, predicted, locations = [], set(), []
    try:
        value = strict_json_object(raw)
        schema = strict_json_object(row["messages"][1]["content"])["output_schema"]
        validate_evaluator_value(value, schema)
        checks["schema"] = True
        validate_domain_response(value, row)
        checks["domain"] = True
    except (ValueError, TypeError, KeyError, ModelGatewayEvaluationError) as error:
        errors.append(type(error).__name__ + ": " + str(error)[:300])
    else:
        locations = [f["location"] for f in value["findings"]]
        predicted = set(locations)
        checks["locations"] = predicted == expected and len(locations) == len(expected)
        checks["criterion"] = all(
            f["criterion"] == criteria.get(f["location"]) for f in value["findings"]
        )
        # One gap per unavailable target. Wrong, extra and duplicate gap targets fail.
        gap_targets = [mentioned_targets(text) for text in value["evidence_gaps"]]
        checks["gaps"] = (
            len(gap_targets) == len(absent)
            and all(len(targets) == 1 and targets <= absent for targets in gap_targets)
            and set().union(*gap_targets) == absent
        )
        checks["abstention"] = value["abstained"] == (len(absent) == len(controls))
        checks["summary_scope"] = mentioned_targets(value["overall_summary"]) <= requested
    return dict(
        scoring_version=SCORING_VERSION,
        passed=all(checks.values()),
        checks=checks,
        errors=errors,
        expected_missing=sorted(expected),
        predicted_missing=sorted(predicted),
        true_positive=len(predicted & expected),
        false_positive=len(predicted - expected),
        false_negative=len(expected - predicted),
        duplicate_locations=len(locations) - len(predicted),
        narrative_review_required=True,
        human_expert_validation=False,
        promotion=False,
    )
