from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from uuid import UUID

from orchestwin.cli.folder import IGNORED_NAMES


def schema_valid(value, schema, root=None):
    root = schema if root is None else root
    if not isinstance(schema, Mapping):
        return schema is True
    reference = schema.get("$ref")
    if reference:
        if not reference.startswith("#/"):
            return False
        target = root
        for part in reference[2:].split("/"):
            target = target.get(part.replace("~1", "/").replace("~0", "~"), {})
        if not schema_valid(value, target, root):
            return False
    if "const" in schema and value != schema["const"]:
        return False
    if "enum" in schema and value not in schema["enum"]:
        return False
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            matches = sum(schema_valid(value, item, root) for item in schema[key])
            if (key == "anyOf" and not matches) or (key == "oneOf" and matches != 1):
                return False
            if key == "allOf" and matches != len(schema[key]):
                return False
    if "if" in schema:
        branch = "then" if schema_valid(value, schema["if"], root) else "else"
        if branch in schema and not schema_valid(value, schema[branch], root):
            return False
    kinds = {
        "null": value is None,
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, int | float) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }
    expected = schema.get("type")
    if expected and not any(
        kinds.get(kind, False) for kind in ([expected] if isinstance(expected, str) else expected)
    ):
        return False
    if isinstance(value, dict):
        if any(key not in value for key in schema.get("required", ())):
            return False
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            rules = [properties[key]] if key in properties else []
            rules.extend(
                rule
                for pattern, rule in schema.get("patternProperties", {}).items()
                if re.search(pattern, key) is not None
            )
            if any(not schema_valid(item, rule, root) for rule in rules or [additional]):
                return False
        for key, required in schema.get("dependentRequired", {}).items():
            if key in value and any(item not in value for item in required):
                return False
        if "propertyNames" in schema and any(
            not schema_valid(key, schema["propertyNames"], root) for key in value
        ):
            return False
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get(
            "maxItems", len(value)
        ):
            return False
        if schema.get("uniqueItems") and len(
            {json.dumps(item, sort_keys=True) for item in value}
        ) != len(value):
            return False
        if "items" in schema and any(
            not schema_valid(item, schema["items"], root) for item in value
        ):
            return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get(
            "maxLength", len(value)
        ):
            return False
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            return False
        try:
            if schema.get("format") == "uuid":
                UUID(value)
            if schema.get("format") == "date-time":
                datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
    if kinds["number"]:
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            return False
    return True


def verify_files(root: Path, manifest: Mapping, *, inside, fail):
    declared = manifest.get("files")
    if not isinstance(declared, dict):
        raise fail("orchestwin.json")
    found = {}
    for path in root.rglob("*"):
        if path.name in IGNORED_NAMES:
            continue
        if path.is_symlink():
            raise fail(path.relative_to(root).as_posix())
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            if inside(root, relative) is None:
                raise fail(relative)
            found[relative] = path.read_bytes()
    extra = set(found) - set(declared) - {"orchestwin.json", "ORCHESTWIN.md"}
    if extra:
        raise fail(sorted(extra)[0])
    for relative, digest in declared.items():
        if not isinstance(relative, str) or inside(root, relative) is None:
            raise fail(str(relative))
        if relative not in found or hashlib.sha256(found[relative]).hexdigest() != digest:
            raise fail(relative)
    schemas = manifest.get("schemas", {})
    if not isinstance(schemas, dict):
        raise fail("orchestwin.json")
    for name, relative in schemas.items():
        basename = "learned" if name == "learning" else name
        if relative != f"schema/{basename}.schema.json" or relative not in declared:
            raise fail(str(relative))
    try:
        for relative, content in found.items():
            if not relative.endswith(".json") or relative.startswith("schema/"):
                continue
            payload = json.loads(content.decode("utf-8"))
            if relative == "orchestwin.json":
                name = "manifest"
            else:
                name = {
                    "traceability/why.json": "why",
                    "validation/human-validation.json": "validation",
                    "twins/evidence.json": "evidence",
                    "twins/feedback/reviews.json": "reviews",
                    "twins/feedback/discussions.json": "discussions",
                    "twins/feedback/insights.json": "insights",
                    "state/state.json": "state",
                    "twins/feedback/changes.json": "changes",
                    "twins/feedback/tests.json": "tests",
                    "twins/feedback/learned.json": "learning",
                    **{f"{stage}/{stage}.json": stage for stage in manifest.get("stages", {})},
                }.get(relative)
            if name:
                if name not in schemas:
                    raise fail(relative)
                schema = json.loads(found[schemas[name]].decode("utf-8"))
                if not schema_valid(payload, schema):
                    raise fail(relative)
            if (
                name
                and name != "manifest"
                and payload.get("project_id") != manifest.get("project", {}).get("id")
            ):
                raise fail(relative)
    except (KeyError, TypeError, ValueError, UnicodeDecodeError, RecursionError):
        raise fail(relative) from None
