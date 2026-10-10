from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import TypeAdapter

from orchestwin.artifacts.generated_mockups import MAX_MARKUP_LENGTH, MAX_STYLES_LENGTH
from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.generated_mockup_drafts import (
    MAX_APPROACH_LENGTH,
    MAX_CHANGE_LENGTH,
    GeneratedIterationDraft,
)
from orchestwin.models.hosted_schema import (
    ELLIPSIS,
    SHORTENING_LIMIT,
    SchemaViolation,
    shorten_overlong_strings,
    validate_against_schema,
)
from orchestwin.models.openai_compatible import OpenAICompatibleHttpResponse
from orchestwin.models.openai_hosted import build_openai_hosted_adapter
from orchestwin.models.proposal_evidence import (
    _SCOPE,
    ProposalEvidenceScope,
    begin_model_generation,
    retain_provider_result,
)
from orchestwin.models.proposal_evidence_privacy import minimize_evidence_event
from orchestwin.models.structured_generation import (
    StructuredGenerationProviderKind,
    StructuredOutputMode,
    successful_structured_generation_result,
)
from src.test.python.models.test_hosted_support import (
    GATEWAY_KEY,
    TEST_KEY,
    VALID_REVIEW,
    FakeAnthropicClient,
    message,
    providers,
    structured_request,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

STRICT = StructuredOutputMode.STRICT
PROMPTED = StructuredOutputMode.PROMPTED
PROVIDERS = ("anthropic", "openai")
ITERATION_SCHEMA = TypeAdapter(GeneratedIterationDraft).json_schema()
PHRASE = "Il riepilogo finale mostra la sede di ritiro della tessera"
HEAD = " ".join([PHRASE] * 5)
LONG_CHANGE = (
    f"{HEAD}, conseguentemente la volontaria non cerca più l'indirizzo in un altro foglio."
)
LONG_REVIEW = {**VALID_REVIEW, "assessment": "The flow is clear and every step is short enough"}
SHORT_REVIEW = {**VALID_REVIEW, "assessment": "The flow is clear and every step is…"}
UNION_SCHEMA = {
    "$defs": {
        "Items": {
            "additionalProperties": False,
            "properties": {
                "items": {"items": {"maxLength": 12, "type": "string"}, "type": "array"},
                "kind": {"const": "ITEMS", "type": "string"},
            },
            "required": ["items", "kind"],
            "type": "object",
        },
        "Text": {
            "additionalProperties": False,
            "properties": {
                "kind": {"const": "TEXT", "type": "string"},
                "text": {"maxLength": 20, "type": "string"},
            },
            "required": ["kind", "text"],
            "type": "object",
        },
    },
    "additionalProperties": False,
    "properties": {
        "note": {"anyOf": [{"maxLength": 10, "type": "string"}, {"type": "null"}], "default": None},
        "title": {"allOf": [{"maxLength": 30}, {"maxLength": 16}], "type": "string"},
        "value": {
            "discriminator": {
                "mapping": {"ITEMS": "#/$defs/Items", "TEXT": "#/$defs/Text"},
                "propertyName": "kind",
            },
            "oneOf": [{"$ref": "#/$defs/Text"}, {"$ref": "#/$defs/Items"}],
        },
    },
    "required": ["note", "title", "value"],
    "type": "object",
}


def text_schema(maximum, **keywords):
    return {
        "additionalProperties": False,
        "properties": {"text": {"maxLength": maximum, "type": "string", **keywords}},
        "required": ["text"],
        "type": "object",
    }


def iteration(**changes):
    payload = {
        "approach": "Una sola colonna con il riepilogo sempre in alto.",
        "changes": ["Il riepilogo mostra la sede di ritiro."],
        "css": ".ot-screen { color: var(--vl-color-text); }",
        "screens": [
            {
                "code": "SCR-001",
                "heading": "Iscrizione",
                "kind": "DEFAULT",
                "markup": "<main><h1>Iscrizione</h1></main>",
            },
            {
                "code": "SCR-002",
                "heading": "Riepilogo",
                "kind": "SUCCESS",
                "markup": "<main><h1>Riepilogo</h1></main>",
            },
        ],
    }
    payload.update(changes)
    return payload


class Completion:
    def __init__(self, text):
        self.text = text

    async def post_json(self, **kwargs):
        body = {
            "id": "chatcmpl-shortening-0001",
            "model": "example-model-1",
            "choices": [{"finish_reason": "stop", "message": {"content": self.text}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }
        return OpenAICompatibleHttpResponse(200, json.dumps(body).encode("utf-8"), 5)


def generate(provider, answer, mode=STRICT):
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
    return asyncio.run(port.generate(structured_request(configuration), output_mode=mode))


async def _in_scope(store, port, request):
    token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
    try:
        await begin_model_generation(request)
        result = await port.generate(request)
        await retain_provider_result(result)
        return result
    finally:
        _SCOPE.reset(token)


def test_a_long_change_is_cut_after_the_last_whole_word_and_ends_with_an_ellipsis():
    answer = iteration(changes=[LONG_CHANGE, "Il pulsante dice Continua."])
    shortened, paths = shorten_overlong_strings(answer, ITERATION_SCHEMA)
    assert len(LONG_CHANGE) > MAX_CHANGE_LENGTH and len(HEAD) == 294
    assert shortened["changes"] == [f"{HEAD}{ELLIPSIS}", "Il pulsante dice Continua."]
    assert len(shortened["changes"][0]) <= MAX_CHANGE_LENGTH
    assert paths == ("$.changes[0]",)
    assert validate_against_schema(shortened, ITERATION_SCHEMA) == ()


@pytest.mark.parametrize(
    ("text", "maximum", "expected"),
    [
        ("x" * 41, 40, "x" * 39 + ELLIPSIS),
        ("a" * 24 + " " + "b" * 30, 40, "a" * 24 + ELLIPSIS),
        ("a" * 23 + " " + "b" * 30, 40, "a" * 23 + " " + "b" * 15 + ELLIPSIS),
        ("uno due tre quattro, cinque", 21, "uno due tre quattro" + ELLIPSIS),
        ("uno due tre quattro; cinquecentomila", 30, "uno due tre quattro" + ELLIPSIS),
        ("Pronto." + " " * 10 + "fine", 12, "Pronto" + ELLIPSIS),
        ("Prima parte\nseconda parte del testo", 18, "Prima parte" + ELLIPSIS),
    ],
    ids=[
        "one long word",
        "space at sixty percent",
        "space before sixty percent",
        "comma at the cut",
        "semicolon before the last word",
        "spaces and full stop",
        "line break",
    ],
)
def test_the_cut_goes_back_to_a_space_only_when_most_of_the_text_remains(text, maximum, expected):
    shortened, paths = shorten_overlong_strings({"text": text}, text_schema(maximum))
    assert shortened == {"text": expected}
    assert len(expected) <= maximum
    assert paths == ("$.text",)


def test_an_answer_within_every_limit_is_returned_as_it_arrived():
    answer = iteration()
    shortened, paths = shorten_overlong_strings(answer, ITERATION_SCHEMA)
    assert shortened is answer and paths == ()
    wrong_type = {"text": ["x" * 41]}
    kept, none = shorten_overlong_strings(wrong_type, text_schema(40))
    assert kept is wrong_type and none == ()


def test_markup_and_style_sheets_over_their_limit_are_never_shortened():
    answer = iteration(css="b" * (MAX_STYLES_LENGTH + 1))
    answer["screens"][0]["markup"] = "a" * (MAX_MARKUP_LENGTH + 1)
    shortened, paths = shorten_overlong_strings(answer, ITERATION_SCHEMA)
    assert shortened is answer and paths == ()
    assert validate_against_schema(shortened, ITERATION_SCHEMA) == (
        SchemaViolation("$.css", "maxLength"),
        SchemaViolation("$.screens[0].markup", "maxLength"),
    )


def test_only_a_maximum_length_within_the_limit_marks_a_text_as_prose():
    assert SHORTENING_LIMIT == 4000
    at_limit = shorten_overlong_strings({"text": "x" * 4001}, text_schema(4000))
    assert at_limit == ({"text": "x" * 3999 + ELLIPSIS}, ("$.text",))
    above = {"text": "x" * 4002}
    assert shorten_overlong_strings(above, text_schema(4001)) == (above, ())
    narrow = {"text": "x" * 301}
    assert shorten_overlong_strings(narrow, text_schema(300), limit=299) == (narrow, ())
    assert shorten_overlong_strings(narrow, text_schema(300), limit=300)[1] == ("$.text",)


def test_references_and_items_are_followed_in_the_order_of_the_answer():
    answer = iteration(
        approach="Una direzione " * 60, changes=["Breve.", "Breve anche questa.", LONG_CHANGE]
    )
    answer["screens"][1]["heading"] = "Riepilogo " * 30
    shortened, paths = shorten_overlong_strings(answer, ITERATION_SCHEMA)
    assert paths == ("$.approach", "$.changes[2]", "$.screens[1].heading")
    assert len(shortened["approach"]) <= MAX_APPROACH_LENGTH
    assert shortened["screens"][1]["heading"].endswith(ELLIPSIS)
    assert shortened["screens"][0] is answer["screens"][0]
    assert validate_against_schema(shortened, ITERATION_SCHEMA) == ()
    reordered = {key: answer[key] for key in ("screens", "css", "changes", "approach")}
    assert shorten_overlong_strings(reordered, ITERATION_SCHEMA)[1] == (
        "$.screens[1].heading",
        "$.changes[2]",
        "$.approach",
    )


def test_prefix_items_take_their_own_limits_and_the_rest_take_the_items():
    schema = {
        "items": {"maxLength": 5, "type": "string"},
        "prefixItems": [{"maxLength": 10, "type": "string"}, {"maxLength": 20, "type": "string"}],
        "type": "array",
    }
    shortened, paths = shorten_overlong_strings(["a" * 11, "b" * 21, "c" * 6, "dd"], schema)
    assert shortened == ["a" * 9 + ELLIPSIS, "b" * 19 + ELLIPSIS, "c" * 4 + ELLIPSIS, "dd"]
    assert paths == ("$[0]", "$[1]", "$[2]")


def test_combinators_shorten_the_branch_that_the_answer_follows():
    answer = {
        "note": "Una nota troppo lunga",
        "title": "Un titolo molto lungo davvero, e ancora",
        "value": {"items": ["breve", "una voce troppo lunga"], "kind": "ITEMS"},
    }
    shortened, paths = shorten_overlong_strings(answer, UNION_SCHEMA)
    assert shortened == {
        "note": "Una nota…",
        "title": "Un titolo molto…",
        "value": {"items": ["breve", "una voce…"], "kind": "ITEMS"},
    }
    assert paths == ("$.note", "$.title", "$.value.items[1]")
    assert validate_against_schema(shortened, UNION_SCHEMA) == ()
    value = {"kind": "TEXT", "text": "Un testo che supera venti caratteri"}
    shortened, paths = shorten_overlong_strings(
        {"note": None, "title": "Breve", "value": value}, UNION_SCHEMA
    )
    assert shortened["value"] == {"kind": "TEXT", "text": "Un testo che…"}
    assert shortened["note"] is None and paths == ("$.value.text",)


def test_an_answer_that_fits_no_branch_is_left_to_the_schema_check():
    answer = {"note": None, "title": "Breve", "value": {"kind": "OTHER", "text": "x" * 30}}
    kept, paths = shorten_overlong_strings(answer, UNION_SCHEMA)
    assert kept is answer and paths == ()
    assert validate_against_schema(kept, UNION_SCHEMA)


@pytest.mark.parametrize(
    "keywords",
    [
        {"pattern": "^REQ-[0-9]{3,}$"},
        {"format": "uri"},
        {"enum": ["x" * 41]},
        {"const": "x" * 41},
    ],
    ids=["pattern", "format", "enum", "const"],
)
def test_a_text_with_a_pattern_a_format_or_fixed_values_is_never_shortened(keywords):
    answer = {"text": "x" * 41}
    kept, paths = shorten_overlong_strings(answer, text_schema(40, **keywords))
    assert kept is answer and paths == ()


def test_a_text_under_its_minimum_length_is_left_to_the_schema_check():
    schema = text_schema(40, minLength=5)
    answer = {"text": "ab"}
    assert shorten_overlong_strings(answer, schema) == (answer, ())
    assert validate_against_schema(answer, schema) == (SchemaViolation("$.text", "minLength"),)


def test_the_answer_that_arrived_is_never_changed():
    answer = iteration(changes=[LONG_CHANGE])
    arrived = copy.deepcopy(answer)
    shortened, _paths = shorten_overlong_strings(answer, ITERATION_SCHEMA)
    assert answer == arrived and shortened != arrived


def test_paths_name_the_place_like_the_violations_and_never_the_text():
    schema = {
        "additionalProperties": False,
        "properties": {"note text": {"maxLength": 8, "type": "string"}},
        "type": "object",
    }
    answer = {"note text": "secret words here"}
    [violation] = validate_against_schema(answer, schema)
    _shortened, paths = shorten_overlong_strings(answer, schema)
    assert paths == (violation.path,) == ("$['notetext']",)
    assert "secret" not in paths[0]


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("mode", [STRICT, PROMPTED], ids=["strict", "prompted"])
def test_a_hosted_answer_with_a_long_text_is_accepted_shortened(provider, mode):
    result = generate(provider, LONG_REVIEW, mode)
    assert result.shortened_paths == ("$.assessment",)
    assert json.loads(result.success.payload_json) == SHORT_REVIEW
    snapshot = result.to_snapshot()
    assert list(snapshot)[-2:] == ["output_mode", "shortened_paths"]
    assert (snapshot["output_mode"], snapshot["shortened_paths"]) == (mode.value, ["$.assessment"])


@pytest.mark.parametrize("provider", PROVIDERS)
def test_a_rejected_answer_names_the_shortened_texts_and_only_the_other_violations(provider):
    result = generate(provider, {**LONG_REVIEW, "score": 2})
    assert result.failure.message == (
        "The hosted model answer violates the output schema at $.score (maximum)."
    )
    assert result.to_snapshot()["shortened_paths"] == ["$.assessment"]


def test_the_evidence_keeps_the_raw_answer_and_the_shortened_payload():
    store = MemoryEvidence()
    configuration = providers().hosted_model("design")
    request = structured_request(configuration)
    client = FakeAnthropicClient(message(LONG_REVIEW))
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    result = asyncio.run(_in_scope(store, port, request))
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    assert LONG_REVIEW["assessment"].encode("utf-8") in events[1][2]
    assert events[2][1] == result.to_snapshot()
    assert events[2][1]["shortened_paths"] == ["$.assessment"]
    assert json.loads(events[2][1]["success"]["payload_json"]) == SHORT_REVIEW


def test_a_result_records_shortened_paths_only_as_json_paths_of_a_hosted_answer():
    result = generate("anthropic", VALID_REVIEW)
    assert result.shortened_paths == ()
    assert "shortened_paths" not in result.to_snapshot()
    marked = replace(result, shortened_paths=("$.assessment",))
    assert list(marked.to_snapshot())[-2:] == ["output_mode", "shortened_paths"]
    assert marked.content_hash != result.content_hash
    for paths in (["$.assessment"], ("assessment",), ("$.assessment", 3)):
        with pytest.raises(ValueError):
            replace(result, shortened_paths=paths)
    local = successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        success=result.success,
    )
    assert local.shortened_paths == () and "shortened_paths" not in local.to_snapshot()
    with pytest.raises(ValueError):
        replace(local, shortened_paths=("$.assessment",))


def test_the_minimized_evidence_leaves_out_the_shortened_paths():
    snapshot = generate("anthropic", LONG_REVIEW).to_snapshot()
    minimal = minimize_evidence_event("PROVIDER_RESULT", snapshot)
    assert snapshot["shortened_paths"] == ["$.assessment"]
    assert "shortened_paths" not in minimal
    assert (minimal["status"], minimal["output_mode"]) == ("SUCCEEDED", "STRICT")
    assert minimize_evidence_event("PROVIDER_RESULT", minimal) == minimal
