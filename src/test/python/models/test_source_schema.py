"""Manifest compaction preserves every field constraint and source obligation."""

import json
from copy import deepcopy

from orchestwin.models.source_file_generation import _coverage_manifest_type
from orchestwin.models.source_schema import share_manifest_field_schemas


def test_repeated_field_schemas_are_lossless_and_reduce_large_manifest_prompts():
    model = _coverage_manifest_type(
        "WEB_STATIC", None, {"statements": [{"source": f"requirements[{n}]"} for n in range(20)]}
    )
    original = model.model_json_schema()
    compact = deepcopy(original)
    share_manifest_field_schemas(compact)
    assert len(json.dumps(compact)) < len(json.dumps(original)) * 0.85
    expanded = deepcopy(compact)
    for definition in expanded["$defs"].values():
        for key, field in tuple(definition.get("properties", {}).items()):
            reference = field.get("$ref", "")
            if reference in {"#/$defs/ManifestPublicInterface", "#/$defs/ManifestPostcondition"}:
                definition["properties"][key] = deepcopy(
                    expanded["$defs"][reference.split("/")[-1]]
                )
    for name in ("ManifestPublicInterface", "ManifestPostcondition"):
        del expanded["$defs"][name]
    assert expanded == original


def test_different_constraints_are_never_merged():
    schema = {
        "$defs": {
            f"ApprovedStatementCheck{n}": {"properties": {"public_interface": {"maxLength": n + 1}}}
            for n in range(2)
        }
    }
    original = deepcopy(schema)
    share_manifest_field_schemas(schema)
    assert schema == original
