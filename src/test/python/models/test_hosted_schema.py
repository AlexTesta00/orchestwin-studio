from __future__ import annotations

import asyncio
import copy
import json

import anthropic
import pytest

from orchestwin.models import hosted_schema
from orchestwin.models.hosted_schema import (
    CLAUDE_CODE_SCHEMA_MAX_CHARACTERS,
    HostedSchemaError,
    SchemaViolation,
    hosted_output_schema,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.model_proposals import ModelDesignAdapter, ModelRequirementsAdapter
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    failed_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.evaluation import test_proposer_evaluator as review
from src.test.python.models.test_hosted_support import REVIEW_SCHEMA, VALID_REVIEW
from src.test.python.models.test_model_proposals import make_generator
from src.test.python.models.test_proposal_evidence import stage_case

ANTHROPIC = StructuredGenerationProviderKind.ANTHROPIC_HOSTED
OPENAI = StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED
CLAUDE_CODE = StructuredGenerationProviderKind.CLAUDE_CODE_CLI
TASKS = ("design", "requirements", "user-twin-evaluation")
ANTHROPIC_UNSUPPORTED = frozenset(
    {
        "allOf",
        "oneOf",
        "prefixItems",
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "maxItems",
        "pattern",
        "default",
    }
)
OPENAI_UNSUPPORTED = frozenset(
    {"allOf", "oneOf", "prefixItems", "minLength", "maxLength", "default", "not", "if"}
)


class CapturePort:
    def __init__(self):
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return failed_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            code=StructuredGenerationFailureCode.PROVIDER_ERROR,
            message="Captured before inference.",
            retryable=False,
        )


def _captured_schema(tmp_path, call):
    base, _ = make_generator(tmp_path, {})
    port = CapturePort()
    with pytest.raises(ProposalGenerationError):
        asyncio.run(call(ProposalGenerator(base.configuration, port)))
    [request] = port.requests
    return json.loads(request.output_schema.canonical_schema_json)


def _valid_design(answer):
    trimmed = copy.deepcopy(answer)
    kept = ("DES-001", "DES-002")
    trimmed["alternatives"] = trimmed["alternatives"][:2]
    trimmed["critiques"] = [item for item in trimmed["critiques"] if item["alternative"] in kept]
    for concern in trimmed["concerns"]:
        concern["alternatives"] = [item for item in concern["alternatives"] if item in kept]
    return trimmed


@pytest.fixture(scope="module")
def real_cases(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("hosted-schemas")
    design_request, design_output, *_ = stage_case("design")
    requirements_request, requirements_output, *_ = stage_case("requirements")
    return {
        "design": (
            _captured_schema(tmp_path, lambda g: ModelDesignAdapter(g).propose(design_request)),
            _valid_design(design_output),
        ),
        "requirements": (
            _captured_schema(
                tmp_path, lambda g: ModelRequirementsAdapter(g).propose(requirements_request)
            ),
            requirements_output,
        ),
        "user-twin-evaluation": (
            _captured_schema(tmp_path, lambda g: review.reviewer(g).evaluate(review.request())),
            review.output(review.finding(), gaps=("Colours are not visible.",)),
        ),
    }


def _nodes(schema):
    pending = [schema]
    while pending:
        node = pending.pop()
        yield node
        for key, value in node.items():
            if key in ("properties", "$defs"):
                pending.extend(value.values())
            elif key == "items" and isinstance(value, dict):
                pending.append(value)
            elif key == "anyOf":
                pending.extend(value)


def _objects(schema):
    return [node for node in _nodes(schema) if node.get("type") == "object"]


@pytest.mark.parametrize("task", TASKS)
def test_the_anthropic_schema_keeps_only_the_documented_subset(real_cases, task):
    canonical, _ = real_cases[task]
    before = copy.deepcopy(canonical)
    hosted = hosted_output_schema(canonical, ANTHROPIC)
    assert canonical == before
    keywords = {key for node in _nodes(hosted) for key in node}
    assert not keywords & ANTHROPIC_UNSUPPORTED
    assert {"type", "properties", "required", "additionalProperties", "enum"} <= keywords
    for node in _objects(hosted):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    assert all(node.get("minItems", 0) in (0, 1) for node in _nodes(hosted))
    for name, definition in hosted.get("$defs", {}).items():
        if "properties" in definition:
            assert list(definition["properties"]) == list(canonical["$defs"][name]["properties"])
            assert list(definition["properties"]) == sorted(definition["properties"])
    assert list(hosted["properties"]) == list(canonical["properties"])
    unions = sum("anyOf" in node for node in _nodes(hosted))
    optional = sum(len(set(n["properties"]) - set(n["required"])) for n in _objects(hosted))
    assert unions <= 16 and optional == 0


@pytest.mark.parametrize("task", TASKS)
def test_the_openai_schema_lists_every_property_as_required(real_cases, task):
    canonical, _ = real_cases[task]
    hosted = hosted_output_schema(canonical, OPENAI)
    keywords = {key for node in _nodes(hosted) for key in node}
    assert not keywords & OPENAI_UNSUPPORTED
    assert hosted["type"] == "object"
    for node in _objects(hosted):
        assert node["additionalProperties"] is False
        assert node["required"] == list(node["properties"])
    for node in _nodes(hosted):
        if "$ref" in node:
            assert list(node) == ["$ref"]


@pytest.mark.parametrize("task", TASKS)
@pytest.mark.parametrize("kind", [ANTHROPIC, OPENAI])
def test_the_hosted_schema_accepts_every_answer_the_full_schema_accepts(real_cases, task, kind):
    canonical, answer = real_cases[task]
    assert validate_against_schema(answer, canonical) == ()
    assert validate_against_schema(answer, hosted_output_schema(canonical, kind)) == ()


def test_design_keeps_the_vocabulary_of_its_definitions(real_cases):
    canonical, _ = real_cases["design"]
    anthropic_schema = hosted_output_schema(canonical, ANTHROPIC)
    critique = anthropic_schema["$defs"]["CritiqueDraft"]["properties"]
    assert critique["alternative"]["enum"] == ["DES-001", "DES-002"]
    assert critique["as_twin"]["enum"] == ["T1", "T2"]
    assert anthropic_schema["properties"]["critiques"]["items"] == {"$ref": "#/$defs/CritiqueDraft"}
    assert anthropic_schema["properties"]["recommendation"]["enum"] == ["DES-001", "DES-002"]
    openai_schema = hosted_output_schema(canonical, OPENAI)
    critiques = openai_schema["properties"]["critiques"]
    assert (critiques["minItems"], critiques["maxItems"]) == (4, 4)
    assert openai_schema["$defs"]["CritiqueDraft"]["properties"]["code"]["pattern"] == (
        "^CRQ-[0-9]{3,}$"
    )
    assert "minLength" not in json.dumps(openai_schema)


def test_the_full_schema_catches_a_positional_constraint_that_the_provider_cannot_express(
    real_cases,
):
    canonical, answer = real_cases["design"]
    swapped = copy.deepcopy(answer)
    swapped["critiques"][0], swapped["critiques"][1] = (
        swapped["critiques"][1],
        swapped["critiques"][0],
    )
    assert validate_against_schema(swapped, hosted_output_schema(canonical, ANTHROPIC)) == ()
    violations = validate_against_schema(swapped, canonical)
    assert SchemaViolation("$.critiques[0].as_twin", "const") in violations
    assert SchemaViolation("$.critiques[0].code", "const") in violations


def test_the_anthropic_transformation_uses_the_sdk_helper(monkeypatch):
    calls = []
    original = anthropic.transform_schema

    def spy(schema):
        calls.append(copy.deepcopy(schema))
        return original(schema)

    monkeypatch.setattr(anthropic, "transform_schema", spy)
    hosted = hosted_output_schema(REVIEW_SCHEMA, ANTHROPIC)
    assert len(calls) == 1
    assert hosted["properties"]["assessment"] == {
        "type": "string",
        "title": "Assessment",
        "description": "{maxLength: 40, minLength: 1}",
    }
    assert hosted["properties"]["tags"]["description"] == "{maxItems: 2}"
    assert hosted["properties"]["tags"]["items"]["enum"] == ["accessible", "fast"]
    assert hosted_schema.anthropic is anthropic


def test_constants_survive_the_sdk_helper_that_would_move_them_into_descriptions():
    schema = {
        "type": "object",
        "properties": {
            "kind": {"const": "TEXT"},
            "code": {"const": "DES-001", "type": "string", "title": "Code"},
            "text": {"type": "string"},
        },
        "required": ["kind", "code", "text"],
        "additionalProperties": False,
    }
    for kind in (ANTHROPIC, OPENAI):
        hosted = hosted_output_schema(schema, kind)
        assert hosted["properties"]["kind"]["const"] == "TEXT"
        assert hosted["properties"]["kind"]["type"] == "string"
        assert hosted["properties"]["code"]["const"] == "DES-001"
        assert "{const" not in json.dumps(hosted)
        assert "description" not in hosted["properties"]["code"]
    assert anthropic.transform_schema(schema["properties"]["code"])["description"] == (
        "{const: DES-001}"
    )


def test_tuples_and_intersections_become_their_common_definition():
    schema = {
        "$defs": {
            "Item": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "unused": {"type": "string"}},
                "required": ["code", "unused"],
                "additionalProperties": False,
            },
            "Orphan": {"type": "string"},
        },
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "prefixItems": [
                    {"allOf": [{"$ref": "#/$defs/Item"}, {"properties": {"code": {"const": "A"}}}]},
                    {"allOf": [{"$ref": "#/$defs/Item"}, {"properties": {"code": {"const": "B"}}}]},
                ],
                "items": False,
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }
    for kind in (ANTHROPIC, OPENAI):
        hosted = hosted_output_schema(schema, kind)
        assert hosted["properties"]["items"]["items"] == {"$ref": "#/$defs/Item"}
        assert list(hosted["$defs"]) == ["Item"]
    assert hosted_output_schema(schema, OPENAI)["properties"]["items"]["maxItems"] == 2


@pytest.mark.parametrize(
    "schema,code",
    [
        (
            {"type": "object", "properties": {"x": {"type": "object"}}, "required": ["x"]},
            "HOSTED_SCHEMA_OPEN_OBJECT_UNSUPPORTED",
        ),
        (
            {
                "type": "object",
                "properties": {"x": {"type": "object", "additionalProperties": {"type": "string"}}},
            },
            "HOSTED_SCHEMA_OPEN_OBJECT_UNSUPPORTED",
        ),
        (
            {"type": "object", "properties": {"x": {"$ref": "https://example.com/x.json"}}},
            "HOSTED_SCHEMA_REFERENCE_UNSUPPORTED",
        ),
        (
            {"type": "object", "properties": {"x": {"$ref": "#/$defs/Missing"}}},
            "HOSTED_SCHEMA_REFERENCE_UNSUPPORTED",
        ),
        ({"type": "object", "properties": {"x": {"title": "Any"}}}, "HOSTED_SCHEMA_UNTYPED_NODE"),
        (
            {"type": "object", "properties": {"x": {"enum": ["a", 1]}}},
            "HOSTED_SCHEMA_MIXED_ENUM_UNSUPPORTED",
        ),
        (
            {"type": "object", "properties": {"x": {"enum": [{"a": 1}], "type": "object"}}},
            "HOSTED_SCHEMA_COMPLEX_ENUM_UNSUPPORTED",
        ),
        ({"anyOf": [{"type": "object", "properties": {}}]}, "HOSTED_SCHEMA_ROOT_OBJECT_REQUIRED"),
        ({"type": "array", "items": {"type": "string"}}, "HOSTED_SCHEMA_ROOT_OBJECT_REQUIRED"),
    ],
)
def test_constructs_outside_both_subsets_fail_before_any_request(schema, code):
    for kind in (ANTHROPIC, OPENAI, CLAUDE_CODE):
        with pytest.raises(HostedSchemaError) as failure:
            hosted_output_schema(schema, kind)
        assert failure.value.code == code


def test_recursion_is_refused_for_anthropic_and_accepted_for_openai():
    schema = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {
                    "children": {"type": "array", "items": {"$ref": "#/$defs/Node"}},
                    "name": {"type": "string"},
                },
                "required": ["children", "name"],
                "additionalProperties": False,
            }
        },
        "type": "object",
        "properties": {"root": {"$ref": "#/$defs/Node"}},
        "required": ["root"],
        "additionalProperties": False,
    }
    with pytest.raises(HostedSchemaError, match="HOSTED_SCHEMA_RECURSION_UNSUPPORTED"):
        hosted_output_schema(schema, ANTHROPIC)
    assert hosted_output_schema(schema, OPENAI)["$defs"]["Node"]["required"] == [
        "children",
        "name",
    ]
    with pytest.raises(HostedSchemaError, match="HOSTED_SCHEMA_PROVIDER_UNSUPPORTED"):
        hosted_output_schema(schema, StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL)


def test_nullable_types_and_one_of_become_supported_unions():
    schema = {
        "type": "object",
        "properties": {
            "note": {"type": ["string", "null"], "title": "Note"},
            "shape": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
            "email": {"type": "string", "format": "email"},
            "link": {"type": "string", "format": "uri"},
        },
        "required": ["note", "shape", "email", "link"],
        "additionalProperties": False,
    }
    anthropic_schema = hosted_output_schema(schema, ANTHROPIC)
    assert anthropic_schema["properties"]["note"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert anthropic_schema["properties"]["shape"]["anyOf"] == [
        {"type": "string"},
        {"type": "integer"},
    ]
    assert anthropic_schema["properties"]["link"]["format"] == "uri"
    openai_schema = hosted_output_schema(schema, OPENAI)
    assert openai_schema["properties"]["email"]["format"] == "email"
    assert "format" not in openai_schema["properties"]["link"]


def test_violations_name_paths_and_keywords_but_never_the_values():
    answer = {
        "assessment": "SECRET-VALUE-" * 10,
        "score": 1.5,
        "tags": ["fast", "accessible", "fast"],
        "extra": "SECRET-EXTRA",
    }
    violations = validate_against_schema(answer, REVIEW_SCHEMA)
    assert violations == (
        SchemaViolation("$", "additionalProperties"),
        SchemaViolation("$.assessment", "maxLength"),
        SchemaViolation("$.score", "maximum"),
        SchemaViolation("$.tags", "maxItems"),
    )
    message = violation_message(violations)
    assert "SECRET" not in message
    assert message == (
        "The hosted model answer violates the output schema at $ (additionalProperties); "
        "$.assessment (maxLength); $.score (maximum); $.tags (maxItems)."
    )
    assert validate_against_schema(VALID_REVIEW, REVIEW_SCHEMA) == ()
    assert SchemaViolation("$", "type").to_snapshot() == {"path": "$", "keyword": "type"}


def test_the_message_lists_at_most_five_paths():
    violations = tuple(SchemaViolation(f"$.item[{index}]", "type") for index in range(8))
    message = violation_message(violations)
    assert message.count("(type)") == 5
    assert message.endswith("and 3 more.")


@pytest.mark.parametrize("task", TASKS)
def test_the_claude_code_schema_is_the_anthropic_reduction(real_cases, task):
    canonical, answer = real_cases[task]
    before = copy.deepcopy(canonical)
    reduced = hosted_output_schema(canonical, CLAUDE_CODE)
    assert canonical == before
    assert reduced == hosted_output_schema(canonical, ANTHROPIC)
    assert len(canonical_json(reduced)) <= CLAUDE_CODE_SCHEMA_MAX_CHARACTERS
    assert validate_against_schema(answer, reduced) == ()


def _schema_with_choices(count, padding=0):
    choices = [f"{index:08d}" for index in range(count)]
    choices[0] += "x" * padding
    return {
        "type": "object",
        "properties": {"choice": {"type": "string", "enum": choices}},
        "required": ["choice"],
        "additionalProperties": False,
    }


def test_a_claude_code_schema_longer_than_the_command_line_allows_is_refused():
    limit = CLAUDE_CODE_SCHEMA_MAX_CHARACTERS
    assert limit == 24_000
    base = len(canonical_json(hosted_output_schema(_schema_with_choices(1), CLAUDE_CODE)))
    count = (limit - base) // 11 + 1
    padding = limit - base - 11 * (count - 1)
    fitting = hosted_output_schema(_schema_with_choices(count, padding), CLAUDE_CODE)
    assert len(canonical_json(fitting)) == limit
    longer = _schema_with_choices(count, padding + 1)
    with pytest.raises(HostedSchemaError) as failure:
        hosted_output_schema(longer, CLAUDE_CODE)
    assert failure.value.code == "HOSTED_SCHEMA_TOO_LARGE"
    assert len(canonical_json(hosted_output_schema(longer, ANTHROPIC))) == limit + 1


def test_recursion_is_refused_for_claude_code_as_for_anthropic():
    schema = {
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"children": {"type": "array", "items": {"$ref": "#/$defs/Node"}}},
                "required": ["children"],
                "additionalProperties": False,
            }
        },
        "type": "object",
        "properties": {"root": {"$ref": "#/$defs/Node"}},
        "required": ["root"],
        "additionalProperties": False,
    }
    with pytest.raises(HostedSchemaError, match="HOSTED_SCHEMA_RECURSION_UNSUPPORTED"):
        hosted_output_schema(schema, CLAUDE_CODE)
