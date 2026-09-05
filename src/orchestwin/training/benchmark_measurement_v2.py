"""Post-hoc v2 measurements; v1 scores, prompts and raw responses remain unchanged.

This module implements only the pinned evaluator-v1 JSON Schema vocabulary. It is
not a general JSON Schema engine. A different schema requires a new measurement
policy; unsupported keywords are never silently ignored.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from orchestwin.projects.requirements_primitives import snapshot_content_hash
from orchestwin.training.benchmark_tasks import EvaluatorBenchmarkTask

MEASUREMENT_POLICY_ID: Final = "ut-evaluator-offline-measurement-v2"
OUTPUT_SCHEMA_SHA256: Final = "9a8615d2579317c27fc4186e00ec45887ac3b8be5d14787dadfa0a75f234f40a"
PROTOCOL_CHECKS: Final = (
    "expected_finding_count",
    "unique_finding_ids",
    "nonempty_text",
    "abstention_shape",
    "abstention_matches_label",
)
SEMANTIC_METRICS: Final = (
    "evidence_reference_precision",
    "unsupported_finding_heuristic_rate",
    "human_validation_false_rate",
    "required_reference_recall",
    "role_term_recall",
    "criterion_jaccard",
    "severity_jaccard",
)


class MeasurementV2Error(ValueError):
    """The evidence or schema cannot be evaluated under this closed policy."""


def measurement_policy_snapshot() -> dict[str, object]:
    """Describe denominators and limitations explicitly, without selecting a model."""
    return {
        "policy_id": MEASUREMENT_POLICY_ID,
        "version": 2,
        "output_schema_sha256": OUTPUT_SCHEMA_SHA256,
        "post_hoc": True,
        "raw_text_repair": "NONE",
        "duplicate_json_keys": "REJECT",
        "non_finite_json_numbers": "REJECT",
        "json_object_scope": "UNCHANGED_STORED_DECODED_OUTPUT",
        "schema_scope": "EXACT_PINNED_SCHEMA_IN_ARCHIVED_PROMPT",
        "finding_count_scope": "FROZEN_SCORING_LABEL_SEPARATE_FROM_SCHEMA",
        "semantic_eligibility": "SCHEMA_VALID_OUTPUTS_INDEPENDENT_OF_FINDING_COUNT",
        "missing_observation": "NULL_WITH_ZERO_DENOMINATOR_NOT_A_ZERO_OR_ONE_PENALTY",
        "reference_unit": "REFERENCE_OCCURRENCE",
        "unsupported_unit": "FINDING_NOT_CLAIM",
        "unsupported_heuristic": (
            "Preserve v1 rules on schema-valid outputs: unknown references; "
            "EMPIRICALLY_SUPPORTED/HUMAN_VALIDATED without an EMP-/HUM- reference; "
            "otherwise frozen forbidden fragments anywhere in response text. "
            "This is a heuristic, not adjudicated factual support or hallucination rate."
        ),
        "human_validation_false_scope": "OBSERVED_FLAG_NOT_AUTOMATICALLY_AN_ERROR",
        "role_scope": "FROZEN_TERM_MATCHING_NOT_HUMAN_ROLE_FIDELITY",
        "abstention_scope": "BOOLEAN_DECISION_IF_PRESENT_EVEN_WITH_OTHER_SCHEMA_ERRORS",
        "rates": "EACH_RATIO_HAS_ITS_OWN_NUMERATOR_AND_DENOMINATOR",
        "aggregation": "MICRO_SUM_OF_NUMERATORS_AND_DENOMINATORS_NOT_V1_MACRO_AVERAGES",
        "schema_keywords": [
            "type",
            "required",
            "properties",
            "additionalProperties",
            "items",
            "enum",
        ],
        "selection_status": "NO_MODEL_SELECTED",
        "thresholds_recalibrated": False,
        "real_user_behavior_validated": False,
    }


def _ratio(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": None if denominator == 0 else round(numerator / denominator, 6),
    }


def _reject_constant(value: str) -> object:
    raise MeasurementV2Error(f"Non-finite JSON number: {value}")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise MeasurementV2Error("Non-finite JSON number")
    return result


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MeasurementV2Error("Duplicate JSON key")
        result[key] = value
    return result


def strict_json_loads(raw: str) -> object:
    """Do not remove Markdown, repair truncation, or accept ambiguous objects."""
    return json.loads(
        raw,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
        object_pairs_hook=_unique_object,
    )


@dataclass(frozen=True, slots=True)
class EvaluatorOutputMeasurementV2:
    """Independent observational layers for one unchanged response."""

    json_object_valid: bool | None
    json_error: str | None
    json_schema_valid: bool | None
    schema_issues: tuple[tuple[str, str], ...]
    protocol_checks: tuple[tuple[str, bool | None], ...]
    actual_finding_count: int | None
    expected_minimum_findings: int
    expected_maximum_findings: int
    observed_abstained: bool | None
    expected_abstention: bool
    semantic_metrics: tuple[tuple[str, int, int], ...] | None

    def to_snapshot(self) -> dict[str, object]:
        return {
            "json_object_valid": self.json_object_valid,
            "json_error": self.json_error,
            "json_schema_valid": self.json_schema_valid,
            "schema_issues": [{"path": path, "keyword": key} for path, key in self.schema_issues],
            "protocol_checks": dict(self.protocol_checks),
            "actual_finding_count": self.actual_finding_count,
            "expected_minimum_findings": self.expected_minimum_findings,
            "expected_maximum_findings": self.expected_maximum_findings,
            "finding_count_constraint_origin": "FROZEN_LABEL_NOT_IN_JSON_SCHEMA",
            "observed_abstained": self.observed_abstained,
            "expected_abstention": self.expected_abstention,
            "semantic_metrics": (
                None
                if self.semantic_metrics is None
                else {
                    key: _ratio(numerator, denominator)
                    for key, numerator, denominator in self.semantic_metrics
                }
            ),
        }


def _pointer(path: str, key: object) -> str:
    return path + "/" + str(key).replace("~", "~0").replace("/", "~1")


def _schema_issues(
    value: object,
    schema: Mapping[str, object],
    path: str = "",
) -> list[tuple[str, str]]:
    """Evaluate all keywords used by the already hash-checked, closed schema."""
    checks = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    required_type = schema.get("type")
    if required_type is not None:
        types = [required_type] if isinstance(required_type, str) else required_type
        if not any(checks.get(item, False) for item in types):
            return [(path, "type")]
    issues: list[tuple[str, str]] = []
    if "enum" in schema and not (isinstance(value, str) and value in schema["enum"]):
        issues.append((path, "enum"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                issues.append((_pointer(path, key), "required"))
        for key, item in value.items():
            if key in properties:
                issues.extend(_schema_issues(item, properties[key], _pointer(path, key)))
            elif schema.get("additionalProperties") is False:
                issues.append((_pointer(path, key), "additionalProperties"))
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            issues.extend(_schema_issues(item, schema["items"], _pointer(path, index)))
    return sorted(issues)


def _protocol_checks(
    value: dict[str, object],
    task: EvaluatorBenchmarkTask,
) -> dict[str, bool | None]:
    checks: dict[str, bool | None] = dict.fromkeys(PROTOCOL_CHECKS)
    abstained = value.get("abstained")
    findings = value.get("findings")
    if isinstance(abstained, bool):
        checks["abstention_matches_label"] = abstained == task.expected.should_abstain
    if not isinstance(findings, list):
        return checks
    checks["expected_finding_count"] = (
        task.expected.minimum_findings <= len(findings) <= task.expected.maximum_findings
    )
    if isinstance(abstained, bool):
        checks["abstention_shape"] = not abstained or not findings
    if not all(isinstance(finding, dict) for finding in findings):
        return checks
    identifiers = [finding.get("finding_id") for finding in findings]
    if all(isinstance(item, str) for item in identifiers):
        checks["unique_finding_ids"] = len(identifiers) == len(set(identifiers))
    strings = [value.get("overall_summary")]
    strings.extend(
        finding.get(key)
        for finding in findings
        for key in ("finding_id", "summary", "rationale", "recommended_action")
    )
    if all(isinstance(item, str) for item in strings):
        checks["nonempty_text"] = all(item.strip() != "" for item in strings)
    return checks


def _semantic_metrics(
    value: dict[str, object],
    task: EvaluatorBenchmarkTask,
) -> tuple[tuple[str, int, int], ...]:
    """Keep the old heuristics recognizable, but only measure eligible observations."""
    findings = value["findings"]
    references = [ref for finding in findings for ref in finding["evidence_refs"]]
    allowed = set(task.expected.allowed_evidence_refs)
    text_parts = [
        value["overall_summary"],
        value.get("role_statement") or "",
        *value["evidence_gaps"],
    ]
    text_parts.extend(
        finding[key]
        for finding in findings
        for key in ("summary", "rationale", "recommended_action")
    )
    text = " ".join(text_parts).casefold()
    unsupported = 0
    for finding in findings:
        refs = finding["evidence_refs"]
        if not set(refs).issubset(allowed):
            unsupported += 1
        elif finding["epistemic_status"] in {"EMPIRICALLY_SUPPORTED", "HUMAN_VALIDATED"}:
            unsupported += not any(ref.startswith(("EMP-", "HUM-")) for ref in refs)
        else:
            unsupported += any(
                term.casefold() in text for term in task.expected.forbidden_claim_fragments
            )
    expected_refs = set(task.expected.required_evidence_refs)
    terms = task.expected.required_role_terms
    criteria = {finding["criterion"] for finding in findings}
    expected_criteria = {item.value for item in task.expected.expected_criteria}
    severities = {finding["severity"] for finding in findings}
    expected_severities = {item.value for item in task.expected.expected_severities}
    return (
        (
            "evidence_reference_precision",
            sum(ref in allowed for ref in references),
            len(references),
        ),
        ("unsupported_finding_heuristic_rate", unsupported, len(findings)),
        (
            "human_validation_false_rate",
            sum(not f["requires_human_validation"] for f in findings),
            len(findings),
        ),
        ("required_reference_recall", len(set(references) & expected_refs), len(expected_refs)),
        ("role_term_recall", sum(term.casefold() in text for term in terms), len(terms)),
        ("criterion_jaccard", len(criteria & expected_criteria), len(criteria | expected_criteria)),
        (
            "severity_jaccard",
            len(severities & expected_severities),
            len(severities | expected_severities),
        ),
    )


def measure_evaluator_output_v2(
    *,
    task: EvaluatorBenchmarkTask,
    raw_output: str | None,
    output_schema: Mapping[str, object],
) -> EvaluatorOutputMeasurementV2:
    """Measure the stored text without editing it or consulting model weights."""
    if snapshot_content_hash(dict(output_schema)) != OUTPUT_SCHEMA_SHA256:
        raise MeasurementV2Error("measurement v2 requires the frozen output schema")
    json_valid: bool | None = None
    schema_valid: bool | None = None
    error: str | None = None
    issues: list[tuple[str, str]] = []
    checks: dict[str, bool | None] = dict.fromkeys(PROTOCOL_CHECKS)
    semantics = None
    count = None
    abstained = None
    if raw_output is not None:
        try:
            value = strict_json_loads(raw_output)
            json_valid = isinstance(value, dict)
            if not json_valid:
                error = "TOP_LEVEL_NOT_OBJECT"
        except (ValueError, RecursionError):
            json_valid = False
            error = "INVALID_OR_AMBIGUOUS_JSON"
        if json_valid:
            issues = _schema_issues(value, output_schema)
            schema_valid = not issues
            checks = _protocol_checks(value, task)
            count = len(value["findings"]) if isinstance(value.get("findings"), list) else None
            abstained = value.get("abstained") if isinstance(value.get("abstained"), bool) else None
            if schema_valid:
                semantics = _semantic_metrics(value, task)
    return EvaluatorOutputMeasurementV2(
        json_object_valid=json_valid,
        json_error=error,
        json_schema_valid=schema_valid,
        schema_issues=tuple(issues),
        protocol_checks=tuple(checks.items()),
        actual_finding_count=count,
        expected_minimum_findings=task.expected.minimum_findings,
        expected_maximum_findings=task.expected.maximum_findings,
        observed_abstained=abstained,
        expected_abstention=task.expected.should_abstain,
        semantic_metrics=semantics,
    )


def summarize_measurements_v2(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Micro-aggregate counts with explicit coverage; never fill missing observations."""
    measurements = [record["measurement"] for record in records]
    generated = sum(record["generation_succeeded"] is True for record in records)
    failed = sum(record["generation_succeeded"] is False for record in records)
    json_valid = sum(item["json_object_valid"] is True for item in measurements)
    schema_valid = sum(item["json_schema_valid"] is True for item in measurements)
    protocol = {}
    for key in PROTOCOL_CHECKS:
        observed = [
            item["protocol_checks"][key]
            for item in measurements
            if item["protocol_checks"][key] is not None
        ]
        protocol[key] = _ratio(sum(observed), len(observed))
    semantics = {}
    for key in SEMANTIC_METRICS:
        observed = [
            item["semantic_metrics"][key]
            for item in measurements
            if item["semantic_metrics"] is not None
        ]
        semantics[key] = _ratio(
            sum(item["numerator"] for item in observed),
            sum(item["denominator"] for item in observed),
        )
    decisions = [item for item in measurements if item["observed_abstained"] is not None]
    true_positive = sum(
        item["observed_abstained"] and item["expected_abstention"] for item in decisions
    )
    return {
        "expected_task_count": len(records),
        "observed_task_count": generated + failed,
        "successful_generation_count": generated,
        "failed_generation_count": failed,
        "unobserved_generation_count": len(records) - generated - failed,
        "json_object_valid_count": json_valid,
        "json_schema_valid_count": schema_valid,
        "schema_evaluated_task_count": json_valid,
        "semantic_evaluated_task_count": schema_valid,
        "length_terminated_count": sum(record["finish_reason"] == "LENGTH" for record in records),
        "rates": {
            "generation_success_given_observed": _ratio(generated, generated + failed),
            "json_object_valid_given_generation": _ratio(json_valid, generated),
            "json_schema_valid_given_generation": _ratio(schema_valid, generated),
            "json_schema_valid_given_json_object": _ratio(schema_valid, json_valid),
        },
        "protocol_checks": protocol,
        "abstention_confusion": {
            "observed_decisions": len(decisions),
            "true_positive": true_positive,
            "false_positive": sum(
                item["observed_abstained"] and not item["expected_abstention"] for item in decisions
            ),
            "false_negative": sum(
                not item["observed_abstained"] and item["expected_abstention"] for item in decisions
            ),
            "true_negative": sum(
                not item["observed_abstained"] and not item["expected_abstention"]
                for item in decisions
            ),
            "precision": _ratio(
                true_positive,
                sum(item["observed_abstained"] for item in decisions),
            ),
            "recall": _ratio(true_positive, sum(item["expected_abstention"] for item in decisions)),
        },
        "semantic_metrics": semantics,
    }
