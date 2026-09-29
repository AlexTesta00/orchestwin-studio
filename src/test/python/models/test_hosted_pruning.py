from __future__ import annotations

import asyncio
import copy
import json
from uuid import uuid4

import pytest

from orchestwin.models import anthropic_hosted, openai_hosted
from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.hosted_schema import (
    MAX_PRUNED_PROPERTIES,
    SchemaViolation,
    prune_undefined_properties,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.model_proposals import ModelRequirementsAdapter
from orchestwin.models.openai_compatible import OpenAICompatibleHttpResponse
from orchestwin.models.openai_hosted import build_openai_hosted_adapter
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationStatus,
    StructuredOutputMode,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.models.test_hosted_generation import Review
from src.test.python.models.test_hosted_negotiation import BUDGET, rejected
from src.test.python.models.test_hosted_support import (
    GATEWAY_KEY,
    TEST_KEY,
    FakeAnthropicClient,
    SpendingEvidence,
    message,
    providers,
    structured_request,
)
from src.test.python.models.test_model_proposals import make_generator
from src.test.python.models.test_proposal_evidence import stage_case

STRICT = StructuredOutputMode.STRICT
PROMPTED = StructuredOutputMode.PROMPTED
SCHEMA_ERROR = StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR
PROVIDERS = ("anthropic", "openai")
PLAN_SCHEMA = {
    "$defs": {
        "Detail": {
            "additionalProperties": False,
            "properties": {"owner": {"minLength": 1, "title": "Owner", "type": "string"}},
            "required": ["owner"],
            "title": "Detail",
            "type": "object",
        },
        "Step": {
            "additionalProperties": False,
            "properties": {
                "detail": {"$ref": "#/$defs/Detail"},
                "title": {"minLength": 3, "title": "Title", "type": "string"},
            },
            "required": ["detail", "title"],
            "title": "Step",
            "type": "object",
        },
    },
    "additionalProperties": False,
    "properties": {
        "meta": {
            "additionalProperties": False,
            "properties": {"author": {"title": "Author", "type": "string"}},
            "required": ["author"],
            "title": "Meta",
            "type": "object",
        },
        "note": {
            "anyOf": [
                {
                    "additionalProperties": False,
                    "properties": {"text": {"title": "Text", "type": "string"}},
                    "required": ["text"],
                    "type": "object",
                },
                {"type": "null"},
            ],
            "title": "Note",
        },
        "steps": {"items": {"$ref": "#/$defs/Step"}, "title": "Steps", "type": "array"},
        "summary": {"minLength": 3, "title": "Summary", "type": "string"},
    },
    "required": ["meta", "note", "steps", "summary"],
    "title": "Plan",
    "type": "object",
}
PLAN = {
    "meta": {"author": "Ada Riva"},
    "note": None,
    "steps": [
        {"detail": {"owner": "Ada Riva"}, "title": "Collect the open loans"},
        {"detail": {"owner": "Marco Pini"}, "title": "Send the reminders"},
    ],
    "summary": "Two steps for the loans that are late.",
}
CLOSED = {
    "additionalProperties": False,
    "properties": {"text": {"type": "string"}},
    "type": "object",
}
COMBINED = {
    "allOf": {"allOf": [CLOSED]},
    "anyOf": {"anyOf": [CLOSED, {"type": "null"}]},
    "oneOf": {"oneOf": [CLOSED, {"type": "null"}]},
    "then": {"if": {"type": "object"}, "then": CLOSED},
    "else": {"if": {"required": ["missing"]}, "else": CLOSED},
    "dependentSchemas": {"dependentSchemas": {"text": CLOSED}},
}


def _at_top(answer):
    answer["comment"] = "Reviewed by the desk."


def _in_item(answer):
    answer["steps"][1]["twins"] = []


def _in_nested(answer):
    answer["meta"]["extra"] = {"nested": True}


def _in_item_object(answer):
    answer["steps"][0]["detail"]["rank"] = 1


def _everywhere(answer):
    for change in (_at_top, _in_item, _in_nested, _in_item_object):
        change(answer)


def _spread(answer, count):
    for index in range(count):
        target = answer if index % 2 else answer["steps"][1]
        target[f"extra_{index:02d}"] = index


def _without_summary(answer):
    _at_top(answer)
    del answer["summary"]


def _short_title(answer):
    _in_item(answer)
    answer["steps"][0]["title"] = "ab"


def _in_branch(answer):
    answer["note"] = {"extra": 1, "text": "Due today."}


def _too_many(answer):
    _spread(answer, MAX_PRUNED_PROPERTIES + 1)


UNDEFINED = {
    "top level": (_at_top, ("$.comment",)),
    "array item": (_in_item, ("$.steps[1].twins",)),
    "nested object": (_in_nested, ("$.meta.extra",)),
    "object inside an item": (_in_item_object, ("$.steps[0].detail.rank",)),
    "everywhere": (
        _everywhere,
        ("$.comment", "$.meta.extra", "$.steps[0].detail.rank", "$.steps[1].twins"),
    ),
}
REJECTED = {
    "missing required property": _without_summary,
    "string too short": _short_title,
    "inside a branch of anyOf": _in_branch,
    "more than twenty": _too_many,
}


def _changed(change):
    answer = copy.deepcopy(PLAN)
    change(answer)
    return answer


def _note_schema(node):
    return {
        "additionalProperties": False,
        "properties": {"note": node},
        "required": ["note"],
        "type": "object",
    }


class Completion:
    def __init__(self, text):
        self.text, self.calls = text, []

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        body = {
            "id": "chatcmpl-pruning-0001",
            "model": "example-model-1",
            "choices": [{"finish_reason": "stop", "message": {"content": self.text}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }
        return OpenAICompatibleHttpResponse(200, json.dumps(body).encode("utf-8"), 5)


def generate(provider, answer, mode=PROMPTED):
    text = json.dumps(answer)
    if provider == "anthropic":
        configuration = providers().hosted_model("design")
        client = FakeAnthropicClient(message(text=text))
        port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    else:
        configuration = providers().hosted_model("review")
        port = build_openai_hosted_adapter(
            configuration, api_key=GATEWAY_KEY, transport=Completion(text)
        )
    request = structured_request(configuration, PLAN_SCHEMA)
    return asyncio.run(port.generate(request, output_mode=mode))


@pytest.mark.parametrize("case", sorted(UNDEFINED))
def test_undefined_properties_are_removed_and_reported(case):
    change, removed = UNDEFINED[case]
    answer = _changed(change)
    arrived = copy.deepcopy(answer)
    pruned = prune_undefined_properties(answer, PLAN_SCHEMA)
    assert pruned is not None
    assert pruned.payload == PLAN
    assert pruned.removed_paths == removed
    assert answer == arrived


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", sorted(UNDEFINED))
def test_a_prompted_answer_keeps_everything_but_the_undefined_properties(provider, case):
    result = generate(provider, _changed(UNDEFINED[case][0]))
    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert result.output_mode is PROMPTED
    assert result.success.payload_json == canonical_json(PLAN)


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", sorted(REJECTED))
def test_any_other_violation_is_reported_exactly_as_before(provider, case):
    answer = _changed(REJECTED[case])
    result = generate(provider, answer)
    failure = result.failure
    assert failure.code is SCHEMA_ERROR and failure.retryable is False
    assert failure.message == violation_message(validate_against_schema(answer, PLAN_SCHEMA))
    assert failure.usage is not None
    assert prune_undefined_properties(answer, PLAN_SCHEMA) is None


@pytest.mark.parametrize("provider", PROVIDERS)
def test_twenty_undefined_properties_are_still_removed(provider):
    answer = _changed(lambda item: _spread(item, MAX_PRUNED_PROPERTIES))
    assert len(prune_undefined_properties(answer, PLAN_SCHEMA).removed_paths) == 20
    result = generate(provider, answer)
    assert result.success.payload_json == canonical_json(PLAN)


@pytest.mark.parametrize("combinator", sorted(COMBINED))
def test_an_undefined_property_inside_a_combinator_is_never_removed(combinator):
    answer = {"note": {"extra": 1, "text": "Due today."}}
    schema = _note_schema(COMBINED[combinator])
    assert validate_against_schema(answer, schema)
    assert prune_undefined_properties(answer, schema) is None
    closed = prune_undefined_properties(answer, _note_schema(CLOSED))
    assert closed.payload == {"note": {"text": "Due today."}}
    assert closed.removed_paths == ("$.note.extra",)


def test_properties_named_like_combinators_are_ordinary_objects():
    schema = {
        "additionalProperties": False,
        "properties": {"allOf": CLOSED, "then": CLOSED},
        "required": ["allOf", "then"],
        "type": "object",
    }
    answer = {"allOf": {"extra": 1, "text": "a"}, "then": {"extra": 2, "text": "b"}}
    pruned = prune_undefined_properties(answer, schema)
    assert pruned.payload == {"allOf": {"text": "a"}, "then": {"text": "b"}}
    assert pruned.removed_paths == ("$.allOf.extra", "$.then.extra")


def test_names_matched_by_a_pattern_are_defined():
    schema = {
        "additionalProperties": False,
        "patternProperties": {"^x-": {"type": "string"}},
        "properties": {"text": {"type": "string"}},
        "type": "object",
    }
    pruned = prune_undefined_properties({"other": 1, "text": "a", "x-note": "b"}, schema)
    assert pruned.payload == {"text": "a", "x-note": "b"}
    assert pruned.removed_paths == ("$.other",)


def test_a_removal_that_breaks_the_schema_leaves_the_answer_rejected():
    schema = {
        "additionalProperties": False,
        "properties": {"text": {"type": "string"}},
        "required": ["code", "text"],
        "type": "object",
    }
    answer = {"code": "RSK-001", "text": "Late returns."}
    assert validate_against_schema(answer, schema) == (
        SchemaViolation("$", "additionalProperties"),
    )
    assert prune_undefined_properties(answer, schema) is None


def test_valid_answers_and_other_values_have_nothing_to_remove():
    assert prune_undefined_properties(PLAN, PLAN_SCHEMA) is None
    assert prune_undefined_properties([PLAN], PLAN_SCHEMA) is None


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("mode", [STRICT, PROMPTED], ids=["strict", "prompted"])
def test_a_valid_answer_is_kept_byte_for_byte(provider, mode):
    result = generate(provider, PLAN, mode)
    assert result.output_mode is mode
    assert result.success.payload_json == canonical_json(PLAN)


@pytest.mark.parametrize("provider", PROVIDERS)
def test_the_strict_mode_never_removes_anything(provider, monkeypatch):
    calls = []

    def spy(payload, schema):
        calls.append(payload)
        return prune_undefined_properties(payload, schema)

    monkeypatch.setattr(anthropic_hosted, "prune_undefined_properties", spy)
    monkeypatch.setattr(openai_hosted, "prune_undefined_properties", spy)
    answer = _changed(_in_item)
    strict = generate(provider, answer, STRICT)
    assert calls == []
    assert strict.failure.code is SCHEMA_ERROR
    assert strict.failure.message == violation_message(validate_against_schema(answer, PLAN_SCHEMA))
    prompted = generate(provider, answer, PROMPTED)
    assert len(calls) == 1
    assert prompted.success.payload_json == canonical_json(PLAN)


def test_the_local_route_is_unchanged(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(anthropic_hosted, "prune_undefined_properties", calls.append)
    monkeypatch.setattr(openai_hosted, "prune_undefined_properties", calls.append)
    generator, transport = make_generator(tmp_path, {"assessment": "Clear.", "twins": []})
    with pytest.raises(ProposalGenerationError) as failure:
        asyncio.run(
            generator.generate(
                task="team",
                context={"project_id": "p"},
                output_type=Review,
                instruction="Review.",
                retry_schema_errors=False,
            )
        )
    assert failure.value.code == "INVALID_PROVIDER_OUTPUT"
    assert calls == []
    assert len(transport.calls) == 1


def test_the_recorded_requirements_answer_is_kept_without_a_second_answer():
    request, answer, *_ = stage_case("requirements")
    arrived = copy.deepcopy(answer)
    arrived["risks"][0]["twins"] = []
    configuration = providers().hosted_model("general")
    client = FakeAnthropicClient(rejected(), message(arrived, model="claude-sonnet-5"))
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    generator = ProposalGenerator(configuration, port, BUDGET)
    store = SpendingEvidence()

    async def call():
        token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
        try:
            return await ModelRequirementsAdapter(generator).propose(request)
        finally:
            _SCOPE.reset(token)

    result = asyncio.run(call())
    assert len(result.specification.risks) == len(answer["risks"])
    first, second = client.messages.calls
    assert "format" in first["output_config"] and "format" not in second["output_config"]
    negotiated, accepted = store.events.values()
    assert negotiated[-1][1] == {"status": "SCHEMA_MODE_REJECTED", "role": "SCHEMA_NEGOTIATION"}
    assert [kind for kind, _, _ in accepted] == [
        "HTTP_REQUEST",
        "HTTP_RESPONSE",
        "PROVIDER_RESULT",
        "ADAPTER_ACCEPTED",
    ]
    outcome = accepted[2][1]
    assert (outcome["status"], outcome["output_mode"]) == ("SUCCEEDED", "PROMPTED")
    assert outcome["success"]["payload_json"] == canonical_json(answer)
    assert [item["role"] for item in accepted[3][1]["related_generations"]] == [
        "SCHEMA_NEGOTIATION"
    ]
    content = json.loads(accepted[1][2])["content"]
    text = next(block["text"] for block in content if block["type"] == "text")
    assert json.loads(text)["risks"][0]["twins"] == []
