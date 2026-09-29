from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

import anthropic
from jsonschema import Draft202012Validator, ValidationError

from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.structured_generation import StructuredGenerationProviderKind
from orchestwin.projects.requirements_primitives import canonical_json

MAX_LISTED_VIOLATIONS: Final = 5
MAX_PRUNED_PROPERTIES: Final = 20
VIOLATION_PREFIX: Final = "The hosted model answer violates the output schema at "
HOSTED_TASK_REQUEST: Final = (
    "Carry out the task of the system instruction on this input and answer with one complete "
    "JSON object that follows output_schema, where every list has all the items that the "
    "instruction and the schema require and every text is written in full, never a stub or a "
    "placeholder. Write only the JSON object, with no text before or after it."
)
_FENCE: Final = re.compile(
    r"\A```[A-Za-z0-9_+-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?[ \t]*```\Z", re.DOTALL
)
_MAX_PATH_LENGTH: Final = 200
_UNDEFINED_PROPERTY: Final = "additionalProperties"
_COMBINATORS: Final = frozenset(
    {"allOf", "anyOf", "oneOf", "not", "if", "then", "else", "dependentSchemas"}
)
_NAMED_SUBSCHEMAS: Final = frozenset({"properties", "patternProperties", "prefixItems"})
_DEFINITIONS_PREFIX: Final = "#/$defs/"
_COMPLETE_KEYWORDS: Final = frozenset({"$ref", "type", "anyOf", "oneOf", "enum", "const"})
_ANNOTATIONS: Final = frozenset({"title", "description"})
_DROPPED: Final = frozenset(
    {
        "$schema",
        "$id",
        "$comment",
        "not",
        "if",
        "then",
        "else",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "patternProperties",
        "propertyNames",
        "unevaluatedProperties",
        "unevaluatedItems",
        "contains",
        "minContains",
        "maxContains",
        "uniqueItems",
        "minProperties",
        "maxProperties",
        "discriminator",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
        "contentEncoding",
        "contentMediaType",
    }
)
_JSON_TYPES: Final = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (type(None), "null"),
)
OPENAI_STRING_FORMATS: Final = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "ipv4", "ipv6", "uuid"}
)
_OPENAI_NUMBER_KEYWORDS: Final = (
    "multipleOf",
    "maximum",
    "exclusiveMaximum",
    "minimum",
    "exclusiveMinimum",
)


class HostedSchemaError(ValueError):
    def __init__(self, code: str = "HOSTED_SCHEMA_UNSUPPORTED") -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SchemaViolation:
    path: str
    keyword: str

    def to_snapshot(self) -> dict[str, str]:
        return {"path": self.path, "keyword": self.keyword}


@dataclass(frozen=True, slots=True)
class PrunedAnswer:
    payload: dict[str, Any]
    removed_paths: tuple[str, ...]


def hosted_output_schema(
    schema: Mapping[str, Any], provider_kind: StructuredGenerationProviderKind
) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise HostedSchemaError()
    normalized = _prune_definitions(_normalized(copy.deepcopy(dict(schema))))
    if normalized.get("type") != "object":
        raise HostedSchemaError("HOSTED_SCHEMA_ROOT_OBJECT_REQUIRED")
    if provider_kind is StructuredGenerationProviderKind.ANTHROPIC_HOSTED:
        return _anthropic_schema(normalized)
    if provider_kind is StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED:
        return _openai_schema(normalized)
    raise HostedSchemaError("HOSTED_SCHEMA_PROVIDER_UNSUPPORTED")


def validate_against_schema(
    payload: object, schema: Mapping[str, Any]
) -> tuple[SchemaViolation, ...]:
    validator = Draft202012Validator(dict(schema))
    violations = {
        SchemaViolation(path=_bounded_path(error.json_path), keyword=str(error.validator))
        for error in validator.iter_errors(payload)
    }
    return tuple(sorted(violations, key=lambda item: (item.path, item.keyword)))


def prune_undefined_properties(payload: object, schema: Mapping[str, Any]) -> PrunedAnswer | None:
    if not isinstance(payload, dict):
        return None
    candidate = copy.deepcopy(payload)
    validator = Draft202012Validator(dict(schema))
    errors = list(validator.iter_errors(candidate))
    if not errors or not all(_prunable(error) for error in errors):
        return None
    undefined: dict[tuple[object, ...], tuple[dict[str, Any], str, set[str]]] = {}
    for error in errors:
        target, _path, names = undefined.setdefault(
            tuple(error.absolute_path), (error.instance, error.json_path, set())
        )
        names.update(_undefined_names(target, error.schema))
    count = sum(len(names) for _target, _path, names in undefined.values())
    if not 0 < count <= MAX_PRUNED_PROPERTIES:
        return None
    for target, _path, names in undefined.values():
        for name in names:
            del target[name]
    if not validator.is_valid(candidate):
        return None
    removed = sorted(
        _bounded_path(f"{path}.{name}")
        for _target, path, names in undefined.values()
        for name in names
    )
    return PrunedAnswer(payload=candidate, removed_paths=tuple(removed))


def violation_message(violations: tuple[SchemaViolation, ...]) -> str:
    listed = "; ".join(
        f"{item.path} ({item.keyword})" for item in violations[:MAX_LISTED_VIOLATIONS]
    )
    remaining = len(violations) - MAX_LISTED_VIOLATIONS
    suffix = f" and {remaining} more" if remaining > 0 else ""
    text = f"{VIOLATION_PREFIX}{listed}{suffix}."
    return " ".join(text.split())


def retry_sentence(failure_message: str) -> str:
    if failure_message.startswith(VIOLATION_PREFIX):
        listed = failure_message.removeprefix(VIOLATION_PREFIX).removesuffix(".")
        return (
            f"The previous answer did not follow output_schema at {listed}; answer again with "
            "the complete JSON object."
        )
    return (
        "The previous answer was not one complete JSON object that follows output_schema; "
        "answer again with the complete JSON object."
    )


def hosted_user_message(input_payload_json: str, retry_note: str | None = None) -> str:
    request = HOSTED_TASK_REQUEST if retry_note is None else f"{HOSTED_TASK_REQUEST} {retry_note}"
    return f"<input>\n{input_payload_json}\n</input>\n\n{request}"


def parse_prompted_answer(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = _FENCE.match(stripped)
    return strict_json_object(fenced.group("body").strip() if fenced else stripped)


class PromptedSchemas:
    def __init__(self) -> None:
        self._known: set[tuple[str, str]] = set()

    def requires_prompt(
        self, provider_kind: StructuredGenerationProviderKind, schema_hash: str
    ) -> bool:
        return (provider_kind.value, schema_hash) in self._known

    def remember(self, provider_kind: StructuredGenerationProviderKind, schema_hash: str) -> None:
        self._known.add((provider_kind.value, schema_hash))


def _bounded_path(path: str) -> str:
    compact = "".join(path.split())
    return compact if len(compact) <= _MAX_PATH_LENGTH else compact[:_MAX_PATH_LENGTH]


def _prunable(error: ValidationError) -> bool:
    return (
        error.validator == _UNDEFINED_PROPERTY
        and isinstance(error.instance, dict)
        and isinstance(error.schema, Mapping)
        and not _inside_combinator(error.absolute_schema_path)
    )


def _inside_combinator(schema_path: Iterable[object]) -> bool:
    steps = iter(schema_path)
    for step in steps:
        if step in _COMBINATORS:
            return True
        if step in _NAMED_SUBSCHEMAS:
            next(steps, None)
    return False


def _undefined_names(instance: Mapping[str, Any], schema: Mapping[str, Any]) -> set[str]:
    properties = schema.get("properties", {})
    patterns = tuple(schema.get("patternProperties", {}))
    return {
        name
        for name in instance
        if name not in properties and not any(re.search(pattern, name) for pattern in patterns)
    }


def _complete(node: Mapping[str, Any]) -> bool:
    return any(key in node for key in _COMPLETE_KEYWORDS)


def _normalized(node: object) -> dict[str, Any]:
    if not isinstance(node, dict):
        raise HostedSchemaError()
    node = {key: value for key, value in node.items() if key not in _DROPPED}
    if "allOf" in node:
        node = _relaxed_intersection(node)
    if "prefixItems" in node:
        node = _relaxed_tuple(node)
    if "oneOf" in node:
        if "anyOf" in node:
            raise HostedSchemaError()
        node["anyOf"] = node.pop("oneOf")
    if isinstance(node.get("type"), list):
        node = _typed_union(node)
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("properties", "$defs"):
            if not isinstance(value, dict):
                raise HostedSchemaError()
            result[key] = {name: _normalized(child) for name, child in value.items()}
        elif key == "items":
            result[key] = _normalized(value)
        elif key == "anyOf":
            result[key] = _union(node, value)
        elif key == "$ref":
            if not isinstance(value, str) or not value.startswith(_DEFINITIONS_PREFIX):
                raise HostedSchemaError("HOSTED_SCHEMA_REFERENCE_UNSUPPORTED")
            result[key] = value
        elif key in ("enum", "const"):
            _require_primitives(value if key == "enum" else [value])
            result[key] = value
        else:
            result[key] = value
    if result.get("anyOf") is None:
        result.pop("anyOf", None)
    _require_type(result)
    return _closed_object(result)


def _relaxed_intersection(node: dict[str, Any]) -> dict[str, Any]:
    branches = node.pop("allOf")
    if not isinstance(branches, list) or not branches:
        raise HostedSchemaError()
    if _complete(node):
        return node
    chosen = next((item for item in branches if isinstance(item, dict) and _complete(item)), None)
    if chosen is None:
        raise HostedSchemaError()
    merged = dict(chosen)
    for key, value in node.items():
        if key in _ANNOTATIONS and key not in merged:
            merged[key] = value
    return merged


def _relaxed_tuple(node: dict[str, Any]) -> dict[str, Any]:
    prefix = node.pop("prefixItems")
    additional = node.pop("items", True)
    if not isinstance(prefix, list) or not prefix:
        raise HostedSchemaError()
    if additional is not False and not isinstance(additional, dict):
        raise HostedSchemaError()
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in [*prefix, *([additional] if isinstance(additional, dict) else [])]:
        normalized = _normalized(item)
        key = canonical_json(normalized)
        if key not in seen:
            seen.add(key)
            variants.append(normalized)
    node["items"] = variants[0] if len(variants) == 1 else {"anyOf": variants}
    return node


def _typed_union(node: dict[str, Any]) -> dict[str, Any]:
    types = node.pop("type")
    if not types or not all(isinstance(item, str) for item in types):
        raise HostedSchemaError()
    annotations = {key: node.pop(key) for key in tuple(node) if key in _ANNOTATIONS}
    return {**annotations, "anyOf": [{**node, "type": item} for item in types]}


def _union(node: Mapping[str, Any], branches: object) -> list[dict[str, Any]] | None:
    if not isinstance(branches, list) or not branches:
        raise HostedSchemaError()
    base = {key: value for key, value in node.items() if key != "anyOf"}
    if _complete(base):
        if all(isinstance(item, dict) and not _complete(item) for item in branches):
            return None
        raise HostedSchemaError()
    return [_normalized(item) for item in branches]


def _require_primitives(values: object) -> None:
    if not isinstance(values, list) or not values:
        raise HostedSchemaError()
    if any(isinstance(item, (dict, list)) for item in values):
        raise HostedSchemaError("HOSTED_SCHEMA_COMPLEX_ENUM_UNSUPPORTED")


def _json_type(value: object) -> str:
    for python_type, name in _JSON_TYPES:
        if type(value) is python_type:
            return name
    raise HostedSchemaError()


def _require_type(node: dict[str, Any]) -> None:
    if "type" in node or "$ref" in node or "anyOf" in node:
        return
    values = node.get("enum", [node["const"]] if "const" in node else None)
    if values is None:
        raise HostedSchemaError("HOSTED_SCHEMA_UNTYPED_NODE")
    names = {_json_type(item) for item in values}
    if len(names) != 1:
        raise HostedSchemaError("HOSTED_SCHEMA_MIXED_ENUM_UNSUPPORTED")
    node["type"] = names.pop()


def _closed_object(node: dict[str, Any]) -> dict[str, Any]:
    if node.get("type") != "object":
        return node
    extra = node.get("additionalProperties")
    if isinstance(extra, dict) or ("properties" not in node and extra is not False):
        raise HostedSchemaError("HOSTED_SCHEMA_OPEN_OBJECT_UNSUPPORTED")
    node.setdefault("properties", {})
    node["additionalProperties"] = False
    return node


def _references(node: object) -> set[str]:
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.add(value.removeprefix(_DEFINITIONS_PREFIX))
            elif key != "$defs":
                found |= _references(value)
    elif isinstance(node, list):
        for item in node:
            found |= _references(item)
    return found


def _prune_definitions(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})
    reachable: set[str] = set()
    pending = list(_references(schema))
    while pending:
        name = pending.pop()
        if name in reachable:
            continue
        if name not in definitions:
            raise HostedSchemaError("HOSTED_SCHEMA_REFERENCE_UNSUPPORTED")
        reachable.add(name)
        pending.extend(_references(definitions[name]))
    kept = {name: value for name, value in definitions.items() if name in reachable}
    if kept:
        schema["$defs"] = kept
    else:
        schema.pop("$defs", None)
    return schema


def _require_acyclic(schema: Mapping[str, Any]) -> None:
    definitions = schema.get("$defs", {})
    edges = {name: _references(value) for name, value in definitions.items()}
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(name: str) -> None:
        if name in done:
            return
        if name in visiting:
            raise HostedSchemaError("HOSTED_SCHEMA_RECURSION_UNSUPPORTED")
        visiting.add(name)
        for target in edges.get(name, ()):
            visit(target)
        visiting.discard(name)
        done.add(name)

    for name in edges:
        visit(name)


def _anthropic_schema(schema: dict[str, Any]) -> dict[str, Any]:
    _require_acyclic(schema)
    constants: dict[tuple[object, ...], object] = {}
    prepared = _without_constants(schema, (), constants)
    transformed = anthropic.transform_schema(prepared)
    for path, value in constants.items():
        _node_at(transformed, path)["const"] = value
    return transformed


def _without_constants(
    node: dict[str, Any], path: tuple[object, ...], constants: dict[tuple[object, ...], object]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key == "const":
            constants[path] = value
        elif key in ("properties", "$defs"):
            result[key] = {
                name: _without_constants(child, (*path, key, name), constants)
                for name, child in value.items()
            }
        elif key == "items":
            result[key] = _without_constants(value, (*path, key), constants)
        elif key == "anyOf":
            result[key] = [
                _without_constants(child, (*path, key, index), constants)
                for index, child in enumerate(value)
            ]
        else:
            result[key] = value
    if result.get("type") == "object":
        result["required"] = list(result.get("properties", {}))
    return result


def _node_at(node: dict[str, Any], path: tuple[object, ...]) -> dict[str, Any]:
    current: Any = node
    for step in path:
        current = current[step]
    if not isinstance(current, dict):
        raise HostedSchemaError()
    return current


def _openai_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return _openai_node(schema)


def _openai_node(node: Mapping[str, Any]) -> dict[str, Any]:
    if "$ref" in node:
        return {"$ref": node["$ref"]}
    result: dict[str, Any] = {
        key: node[key] for key in ("title", "description") if isinstance(node.get(key), str)
    }
    if "anyOf" in node:
        result["anyOf"] = [_openai_node(item) for item in node["anyOf"]]
    else:
        kind = node["type"]
        result["type"] = kind
        for key in ("enum", "const"):
            if key in node:
                result[key] = node[key]
        if kind == "object":
            properties = node.get("properties", {})
            result["properties"] = {name: _openai_node(child) for name, child in properties.items()}
            result["required"] = list(properties)
            result["additionalProperties"] = False
        elif kind == "array":
            if "items" in node:
                result["items"] = _openai_node(node["items"])
            for key in ("minItems", "maxItems"):
                if key in node:
                    result[key] = node[key]
        elif kind == "string":
            if "pattern" in node:
                result["pattern"] = node["pattern"]
            if node.get("format") in OPENAI_STRING_FORMATS:
                result["format"] = node["format"]
        elif kind in ("number", "integer"):
            for key in _OPENAI_NUMBER_KEYWORDS:
                if key in node:
                    result[key] = node[key]
    if "$defs" in node:
        result["$defs"] = {name: _openai_node(child) for name, child in node["$defs"].items()}
    return result


__all__ = [
    "HOSTED_TASK_REQUEST",
    "MAX_LISTED_VIOLATIONS",
    "MAX_PRUNED_PROPERTIES",
    "OPENAI_STRING_FORMATS",
    "VIOLATION_PREFIX",
    "HostedSchemaError",
    "PromptedSchemas",
    "PrunedAnswer",
    "SchemaViolation",
    "hosted_output_schema",
    "hosted_user_message",
    "parse_prompted_answer",
    "prune_undefined_properties",
    "retry_sentence",
    "validate_against_schema",
    "violation_message",
]
