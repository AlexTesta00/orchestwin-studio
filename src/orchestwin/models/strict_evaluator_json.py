"""Strict JSON and the small JSON Schema vocabulary used by the User Twin evaluator.

This is not a general JSON Schema engine. Unknown keywords fail before inference.
Outputs are validated unchanged; no field deletion, coercion or JSON repair occurs.
"""

from __future__ import annotations

import json
import math
from typing import Any
from uuid import UUID

MAX_JSON_BYTES = 4_000_000
KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "maxItems",
        "enum",
        "minimum",
        "maximum",
        "format",
    }
)


def require(value: object, code: str) -> None:
    if not value:
        raise ValueError(code)


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        require(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _constant(_value: str) -> None:
    raise ValueError("NONFINITE_JSON_NUMBER")


def strict_json_object(raw: bytes | str) -> dict[str, Any]:
    try:
        data = raw.encode("utf-8") if isinstance(raw, str) else raw
        require(isinstance(data, bytes) and len(data) <= MAX_JSON_BYTES, "JSON_SIZE_LIMIT")
        result = json.loads(
            data.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
        require(isinstance(result, dict), "JSON_OBJECT_REQUIRED")
        canonical_bytes(result)  # Reject float overflow such as 1e999 too.
        return result
    except (UnicodeError, RecursionError):
        raise ValueError("INVALID_JSON") from None


def check_evaluator_schema(schema: dict[str, Any], *, _depth: int = 0) -> None:
    require(_depth <= 20, "EVALUATOR_SCHEMA_DEPTH_LIMIT")
    require(
        isinstance(schema, dict) and set(schema) <= KEYWORDS, "EVALUATOR_SCHEMA_KEYWORD_UNSUPPORTED"
    )
    kind = schema.get("type")
    require(
        kind in (None, "object", "array", "string", "integer", "number", "boolean"),
        "EVALUATOR_SCHEMA_TYPE_UNSUPPORTED",
    )
    require(schema.get("format") in (None, "uuid"), "EVALUATOR_SCHEMA_FORMAT_UNSUPPORTED")
    if "enum" in schema:
        require(isinstance(schema["enum"], list) and bool(schema["enum"]), "INVALID_ENUM_SCHEMA")
    require(kind is not None or "enum" in schema, "EMPTY_SCHEMA_UNSUPPORTED")
    if kind == "object":
        properties, required = schema.get("properties"), schema.get("required")
        require(
            isinstance(properties, dict)
            and isinstance(required, list)
            and all(isinstance(key, str) for key in required)
            and len(required) == len(set(required))
            and set(required) == set(properties)
            and schema.get("additionalProperties") is False,
            "EVALUATOR_OBJECT_SCHEMA_UNSUPPORTED",
        )
        for child in properties.values():
            check_evaluator_schema(child, _depth=_depth + 1)
    if kind == "array":
        require(
            "maxItems" not in schema
            or (type(schema["maxItems"]) is int and schema["maxItems"] >= 0),
            "INVALID_ARRAY_LIMIT",
        )
        check_evaluator_schema(schema.get("items"), _depth=_depth + 1)


def validate_evaluator_value(value: Any, schema: dict[str, Any]) -> None:
    """Caller must first check_evaluator_schema; preserve the unmodified value."""
    kind = schema.get("type")
    if "enum" in schema:
        require(
            any(type(value) is type(item) and value == item for item in schema["enum"]),
            "OUTPUT_SCHEMA_ENUM_MISMATCH",
        )
    if kind == "object":
        require(
            isinstance(value, dict) and set(value) == set(schema["properties"]),
            "OUTPUT_SCHEMA_OBJECT_FIELDS_MISMATCH",
        )
        for key, child in schema["properties"].items():
            validate_evaluator_value(value[key], child)
    elif kind == "array":
        require(
            isinstance(value, list) and len(value) <= schema.get("maxItems", 1000),
            "OUTPUT_SCHEMA_ARRAY_INVALID",
        )
        for item in value:
            validate_evaluator_value(item, schema["items"])
    elif kind == "string":
        require(isinstance(value, str), "OUTPUT_SCHEMA_STRING_INVALID")
        if schema.get("format") == "uuid":
            require(str(UUID(value)) == value.casefold(), "OUTPUT_SCHEMA_UUID_INVALID")
    elif kind == "boolean":
        require(type(value) is bool, "OUTPUT_SCHEMA_BOOLEAN_INVALID")
    elif kind in ("number", "integer"):
        require(
            type(value) in ((int,) if kind == "integer" else (int, float))
            and math.isfinite(value)
            and schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf),
            "OUTPUT_SCHEMA_NUMBER_INVALID",
        )
