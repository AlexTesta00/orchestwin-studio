"""Versioned field-placement prompt observed in the S12 R2 technical control.

The version deliberately retains its observed identity after repository integration.
One successful abstention control does not establish general evaluation accuracy.
"""

from __future__ import annotations

from typing import Any

from orchestwin.models.strict_evaluator_json import check_evaluator_schema, require

FIELD_SCOPE_PROMPT_VERSION = "s12-local-inference-contract-v2-field-scope"
ROOT_FIELDS = frozenset({"overall_summary", "findings", "evidence_gaps", "abstained"})


def field_scope_instruction(base: str, schema: dict[str, Any]) -> str:
    """Clarify schema nesting without a sample answer, semantic repair, or forced abstention."""
    check_evaluator_schema(schema)
    require(
        schema.get("type") == "object" and set(schema["properties"]) == ROOT_FIELDS,
        "FIELD_SCOPE_SCHEMA_CHANGED",
    )
    properties = schema["properties"]
    require(properties["findings"].get("type") == "array", "FIELD_SCOPE_SCHEMA_CHANGED")
    finding_fields = properties["findings"]["items"]["properties"]
    require(
        {"severity", "requires_human_validation"} <= set(finding_fields),
        "FINDING_FIELD_SCOPE_CHANGED",
    )
    root_names = ", ".join(sorted(properties))
    root_types = "; ".join(f"{name}: {properties[name]['type']}" for name in sorted(properties))
    guidance = (
        " Output field placement contract: The root JSON object must have exactly these four "
        f"keys and no others: {root_names}. Root value types are {root_types}. "
        "severity and requires_human_validation are properties of each individual object "
        "inside findings, never properties of the root object. The same placement rule applies "
        "to all other finding-specific fields in the supplied schema. Do not copy, repeat or "
        "promote finding fields outside findings. When findings is empty, do not create root "
        "fields to stand in for a nonexistent finding. Determine findings and abstained from "
        "the available evidence; these serialization rules do not dictate a positive finding "
        "or an abstention. If evidence is insufficient, explain the limitations using the "
        "existing overall_summary and evidence_gaps fields, not additional root properties. "
        "Before returning the JSON, check the allowed keys separately at each object level."
    )
    require(isinstance(base, str) and bool(base), "SYSTEM_INSTRUCTION_MISSING")
    return base + guidance
