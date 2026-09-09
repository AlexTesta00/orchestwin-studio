from __future__ import annotations

import copy

import pytest

from orchestwin.models.strict_evaluator_json import (
    check_evaluator_schema,
    strict_json_object,
    validate_evaluator_value,
)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["findings", "abstained", "evidence_gaps", "overall_summary"],
    "properties": {
        "findings": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["severity", "requires_human_validation"],
                "properties": {
                    "severity": {"enum": ["minor", "major"]},
                    "requires_human_validation": {"type": "boolean"},
                },
            },
        },
        "abstained": {"type": "boolean"},
        "evidence_gaps": {"type": "array", "items": {"type": "string"}},
        "overall_summary": {"type": "string"},
    },
}
GOOD = {
    "findings": [],
    "abstained": True,
    "evidence_gaps": ["Not supplied."],
    "overall_summary": "Unavailable.",
}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":{"y":1,"y":2}}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":1e999}',
        b"[]",
        b"null",
        b"```json\n{}\n```",
        b"\xff",
        b"{",
    ],
)
def test_reject_invalid_json_without_repair(raw):
    with pytest.raises(ValueError):
        strict_json_object(raw)


def test_good_value_preserved():
    check_evaluator_schema(SCHEMA)
    value = copy.deepcopy(GOOD)
    validate_evaluator_value(value, SCHEMA)
    assert value == GOOD


@pytest.mark.parametrize("field", ["severity", "requires_human_validation", "unexpected"])
def test_extra_root_fields_are_rejected(field):
    with pytest.raises(ValueError, match="FIELDS_MISMATCH"):
        validate_evaluator_value({**GOOD, field: True}, SCHEMA)


@pytest.mark.parametrize("field", list(GOOD))
def test_missing_root_field_rejected(field):
    value = copy.deepcopy(GOOD)
    del value[field]
    with pytest.raises(ValueError):
        validate_evaluator_value(value, SCHEMA)


@pytest.mark.parametrize(
    "finding",
    [
        {"severity": "major", "requires_human_validation": True, "extra": 1},
        {"severity": "major"},
        {"severity": "BAD", "requires_human_validation": True},
        {"severity": "major", "requires_human_validation": 1},
    ],
)
def test_nested_fields_and_types_rejected(finding):
    with pytest.raises(ValueError):
        validate_evaluator_value({**GOOD, "findings": [finding]}, SCHEMA)


@pytest.mark.parametrize("keyword", ["$ref", "oneOf", "pattern", "unevaluatedProperties"])
def test_unknown_schema_vocabulary_fails_closed(keyword):
    with pytest.raises(ValueError):
        check_evaluator_schema({**SCHEMA, keyword: True})


@pytest.mark.parametrize("value", [True, "1", float("nan"), float("inf"), -0.1, 1.1])
def test_confidence_type_and_range(value):
    with pytest.raises(ValueError):
        validate_evaluator_value(value, {"type": "number", "minimum": 0, "maximum": 1})
