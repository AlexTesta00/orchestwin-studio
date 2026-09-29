from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import anthropic
import pytest

from orchestwin.models.anthropic_hosted import build_anthropic_adapter
from orchestwin.models.generation_budget import GenerationBudget
from orchestwin.models.generation_routing import RoutingProposalGenerator
from orchestwin.models.hosted_configuration import ModelRoutes
from orchestwin.models.hosted_schema import (
    HOSTED_TASK_REQUEST,
    PromptedSchemas,
    hosted_user_message,
    parse_prompted_answer,
    retry_sentence,
)
from orchestwin.models.openai_compatible import OpenAICompatibleHttpResponse
from orchestwin.models.openai_hosted import build_openai_hosted_adapter
from orchestwin.models.proposal_evidence import _SCOPE, ProposalEvidenceScope
from orchestwin.models.proposal_generation import ProposalGenerationError, ProposalGenerator
from orchestwin.models.structured_generation import (
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
    StructuredGenerationUsage,
    StructuredOutputMode,
    create_structured_generation_success,
    successful_structured_generation_result,
)
from src.test.python.models.test_hosted_generation import Review
from src.test.python.models.test_hosted_support import (
    GATEWAY_KEY,
    TEST_KEY,
    VALID_REVIEW,
    FakeAnthropicClient,
    SpendingEvidence,
    message,
    providers,
    status_error,
    structured_request,
)

BUDGET = GenerationBudget(1_500_000, 10_000_000, 60_000_000)
VALID = {"assessment": "Clear."}
TOO_LONG = {"assessment": "x" * 41}
GRAMMAR_TOO_LARGE = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "message": "The compiled grammar is too large, which would cause performance issues.",
    },
}
STRICT = StructuredOutputMode.STRICT
PROMPTED = StructuredOutputMode.PROMPTED


def rejected():
    return status_error(anthropic.BadRequestError, 400, GRAMMAR_TOO_LARGE)


def anthropic_generator(*outcomes, memory=None, entry="design"):
    configuration = providers().hosted_model(entry)
    client = FakeAnthropicClient(*outcomes)
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    return ProposalGenerator(configuration, port, BUDGET, memory), client


def run(generator, store, **options):
    scope = ProposalEvidenceScope(store, uuid4(), uuid4())

    async def call():
        token = _SCOPE.set(scope)
        try:
            return await generator.generate(
                task="team",
                context={"project_id": "p"},
                output_type=Review,
                instruction="Review the design.",
                **options,
            )
        finally:
            _SCOPE.reset(token)

    return asyncio.run(call()), scope


def failing(generator, store, code, **options):
    with pytest.raises(ProposalGenerationError) as failure:
        run(generator, store, **options)
    assert failure.value.code == code
    return failure.value


def kinds(store):
    return [[kind for kind, _, _ in events] for events in store.events.values()]


def results(store):
    return [
        next(payload for kind, payload, _ in events if kind == "PROVIDER_RESULT")
        for events in store.events.values()
    ]


def test_the_user_message_wraps_the_payload_and_ends_with_the_constant_request():
    assert (
        hosted_user_message('{"a":1}') == f'<input>\n{{"a":1}}\n</input>\n\n{HOSTED_TASK_REQUEST}'
    )
    note = retry_sentence("The hosted model answer violates the output schema at $.a (maxLength).")
    assert note == (
        "The previous answer did not follow output_schema at $.a (maxLength); answer again with "
        "the complete JSON object."
    )
    assert hosted_user_message("{}", note).endswith(f"{HOSTED_TASK_REQUEST} {note}")
    assert "stub or a placeholder" in HOSTED_TASK_REQUEST
    assert retry_sentence("The hosted model answer is not one JSON object.").startswith(
        "The previous answer was not one complete JSON object"
    )


@pytest.mark.parametrize(
    "text",
    [
        '{"assessment": "Clear."}',
        '  {"assessment": "Clear."}\n',
        '```json\n{"assessment": "Clear."}\n```',
        '```\n{"assessment": "Clear."}\n```',
        '\n```JSON\n  {"assessment": "Clear."}  \n```\n',
    ],
)
def test_a_prompted_answer_may_carry_one_code_fence(text):
    assert parse_prompted_answer(text) == VALID


@pytest.mark.parametrize(
    "text",
    [
        'Here is the answer: {"assessment": "Clear."}',
        '{"assessment": "Clear."} I hope this helps.',
        '```json\n{"assessment": "Clear."}\n```\nDone.',
        'Answer:\n```json\n{"assessment": "Clear."}\n```',
        '```json\n{"assessment": "Clear."}\n```\n```json\n{"assessment": "Again."}\n```',
        '[{"assessment": "Clear."}]',
    ],
)
def test_text_around_the_json_is_rejected(text):
    with pytest.raises(ValueError):
        parse_prompted_answer(text)


def test_the_prompted_request_sends_no_output_format_and_parses_the_fenced_answer():
    configuration = providers().hosted_model("design")
    fenced = message(text=f"```json\n{json.dumps(VALID_REVIEW)}\n```")
    client = FakeAnthropicClient(fenced)
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    request = structured_request(configuration, max_output_tokens=4096)
    result = asyncio.run(port.generate(request, output_mode=PROMPTED, retry_note="Try again."))
    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert result.output_mode is PROMPTED and result.to_snapshot()["output_mode"] == "PROMPTED"
    [call] = client.messages.calls
    assert call["output_config"] == {"effort": "high"}
    assert call["messages"][0]["content"] == hosted_user_message(
        request.input_payload_json, "Try again."
    )
    strict = FakeAnthropicClient(fenced)
    strict_port = build_anthropic_adapter(configuration, client=strict, api_key=TEST_KEY)
    refused = asyncio.run(strict_port.generate(request))
    assert refused.failure.code.value == "RESPONSE_SCHEMA_ERROR"
    assert refused.to_snapshot()["output_mode"] == "STRICT"
    assert "format" in strict.messages.calls[0]["output_config"]


def test_the_openai_prompted_request_has_no_response_format():
    configuration = providers().hosted_model("review")

    class Transport:
        def __init__(self):
            self.calls = []

        async def post_json(self, **kwargs):
            self.calls.append(kwargs)
            body = {
                "id": "chatcmpl-1",
                "model": "example-model-1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": f"```json\n{json.dumps(VALID_REVIEW)}\n```"},
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 10,
                    "completion_tokens_details": {"reasoning_tokens": 4},
                },
            }
            return OpenAICompatibleHttpResponse(200, json.dumps(body).encode(), 5)

    transport = Transport()
    port = build_openai_hosted_adapter(configuration, api_key=GATEWAY_KEY, transport=transport)
    request = structured_request(configuration)
    result = asyncio.run(port.generate(request, output_mode=PROMPTED))
    assert result.success is not None and result.output_mode is PROMPTED
    assert result.success.usage.reasoning_tokens == 4
    assert result.success.usage.to_snapshot()["reasoning_tokens"] == 4
    assert "response_format" not in transport.calls[0]["payload"]


def test_reasoning_tokens_are_recorded_only_when_reported():
    configuration = providers().hosted_model("design")
    usage = {
        "input_tokens": 10,
        "output_tokens": 900,
        "output_tokens_details": {"thinking_tokens": 700},
    }
    client = FakeAnthropicClient(message(usage=usage), message())
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    first = asyncio.run(port.generate(structured_request(configuration)))
    assert first.success.usage.reasoning_tokens == 700
    assert first.success.usage.to_snapshot()["reasoning_tokens"] == 700
    second = asyncio.run(port.generate(structured_request(configuration)))
    assert second.success.usage.reasoning_tokens == 0
    assert "reasoning_tokens" not in second.success.usage.to_snapshot()


def test_only_hosted_results_carry_an_output_mode():
    configuration = providers().hosted_model("design")
    success = create_structured_generation_success(
        payload=VALID,
        actual_identity=configuration.identity,
        usage=StructuredGenerationUsage(input_tokens=1, output_tokens=1, latency_milliseconds=1),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id=None,
    )
    local = successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL, success=success
    )
    assert "output_mode" not in local.to_snapshot()
    with pytest.raises(ValueError):
        successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            success=success,
            output_mode=STRICT,
        )


def test_a_rejected_grammar_falls_back_once_to_a_prompted_generation():
    memory = PromptedSchemas()
    generator, client = anthropic_generator(rejected(), message(VALID), memory=memory)
    store = SpendingEvidence()
    output, scope = run(generator, store)
    assert output == Review(assessment="Clear.")
    first, second = client.messages.calls
    assert "format" in first["output_config"] and "format" not in second["output_config"]
    assert kinds(store) == [
        ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT", "APPLICATION_RESULT"],
        ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"],
    ]
    rejected_result, accepted = results(store)
    assert rejected_result["output_mode"] == "STRICT"
    assert rejected_result["failure"]["code"] == "INVALID_REQUEST"
    assert accepted["output_mode"] == "PROMPTED" and accepted["status"] == "SUCCEEDED"
    first_id, second_id = store.requests
    closing = store.events[first_id][-1][1]
    assert closing == {"status": "SCHEMA_MODE_REJECTED", "role": "SCHEMA_NEGOTIATION"}
    assert scope.related_generations == [
        {
            "role": "SCHEMA_NEGOTIATION",
            "generation_id": str(first_id),
            "request_hash": store.requests[first_id][0].content_hash,
            "code": "SCHEMA_MODE_REJECTED",
        }
    ]
    assert scope.request.request_id == second_id
    schema_hash = store.requests[first_id][0].output_schema.content_hash
    assert memory.requires_prompt(StructuredGenerationProviderKind.ANTHROPIC_HOSTED, schema_hash)
    assert not memory.requires_prompt(
        StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED, schema_hash
    )


def test_there_is_no_second_fallback():
    generator, client = anthropic_generator(rejected(), rejected())
    store = SpendingEvidence()
    failure = failing(generator, store, "INVALID_REQUEST")
    assert len(client.messages.calls) == 2
    assert failure.result.output_mode is PROMPTED
    assert [item["output_mode"] for item in results(store)] == ["STRICT", "PROMPTED"]


def test_a_remembered_schema_starts_in_prompted_mode():
    memory = PromptedSchemas()
    generator, client = anthropic_generator(
        rejected(), message(VALID), message(VALID), memory=memory
    )
    run(generator, SpendingEvidence())
    store = SpendingEvidence()
    run(generator, store)
    assert len(client.messages.calls) == 3
    assert "format" not in client.messages.calls[2]["output_config"]
    assert kinds(store) == [["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]]
    shared, other = anthropic_generator(
        message(VALID, model="claude-sonnet-5"), memory=memory, entry="general"
    )
    run(shared, SpendingEvidence())
    assert "format" not in other.messages.calls[0]["output_config"]


def test_a_schema_the_provider_cannot_express_starts_in_prompted_mode():
    configuration = providers().hosted_model("design")
    client = FakeAnthropicClient(message(VALID))
    port = build_anthropic_adapter(configuration, client=client, api_key=TEST_KEY)
    generator = ProposalGenerator(configuration, port, BUDGET)

    async def call():
        token = _SCOPE.set(ProposalEvidenceScope(SpendingEvidence(), uuid4(), uuid4()))
        try:
            return await generator.generate(
                task="team",
                context={"project_id": "p"},
                output_type=dict[str, str],
                instruction="Label the flow.",
            )
        finally:
            _SCOPE.reset(token)

    assert asyncio.run(call()) == VALID
    [call_arguments] = client.messages.calls
    assert call_arguments["output_config"] == {"effort": "high"}


def test_a_schema_violation_is_retried_once_with_the_violations():
    generator, client = anthropic_generator(message(TOO_LONG), message(VALID))
    store = SpendingEvidence()
    output, scope = run(generator, store)
    assert output.assessment == "Clear."
    first, second = client.messages.calls
    assert "format" in first["output_config"] and "format" in second["output_config"]
    assert first["messages"][0]["content"].endswith(HOSTED_TASK_REQUEST)
    assert second["messages"][0]["content"].endswith(
        "The previous answer did not follow output_schema at $.assessment (maxLength); answer "
        "again with the complete JSON object."
    )
    assert "x" * 41 not in second["messages"][0]["content"]
    first_id, _ = store.requests
    assert store.events[first_id][-1][1] == {
        "status": "RESPONSE_SCHEMA_ERROR",
        "role": "SCHEMA_RETRY",
    }
    assert [item["role"] for item in scope.related_generations] == ["SCHEMA_RETRY"]
    assert scope.related_generations[0]["code"] == "RESPONSE_SCHEMA_ERROR"
    assert len(store.reads) == 4


def test_an_unparseable_answer_is_retried_like_a_violation():
    garbage = message(text="Sure! Here it is: {not json")
    generator, client = anthropic_generator(garbage, message(VALID))
    output, _ = run(generator, SpendingEvidence())
    assert output.assessment == "Clear."
    assert client.messages.calls[1]["messages"][0]["content"].endswith(
        "The previous answer was not one complete JSON object that follows output_schema; "
        "answer again with the complete JSON object."
    )


def test_two_invalid_answers_fail_and_a_disabled_retry_fails_at_once():
    generator, client = anthropic_generator(message(TOO_LONG), message(TOO_LONG))
    store = SpendingEvidence()
    failure = failing(generator, store, "RESPONSE_SCHEMA_ERROR")
    assert len(client.messages.calls) == 2 and failure.result.failure.usage is not None
    assert kinds(store)[0][-1] == "APPLICATION_RESULT"
    assert kinds(store)[1] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    once, single = anthropic_generator(message(TOO_LONG), message(VALID))
    failing(once, SpendingEvidence(), "RESPONSE_SCHEMA_ERROR", retry_schema_errors=False)
    assert len(single.messages.calls) == 1


def test_the_longest_sequence_has_two_paid_generations():
    generator, client = anthropic_generator(rejected(), message(TOO_LONG), message(TOO_LONG))
    store = SpendingEvidence()
    failing(generator, store, "RESPONSE_SCHEMA_ERROR")
    assert len(client.messages.calls) == 3
    paid = [item for item in results(store) if (item["failure"] or {}).get("usage")]
    assert len(paid) == 2
    assert [item["output_mode"] for item in results(store)] == ["STRICT", "PROMPTED", "PROMPTED"]
    closing = [events[-1][1] for events in store.events.values()][:2]
    assert closing == [
        {"status": "SCHEMA_MODE_REJECTED", "role": "SCHEMA_NEGOTIATION"},
        {"status": "RESPONSE_SCHEMA_ERROR", "role": "SCHEMA_RETRY"},
    ]


def test_the_budget_is_checked_before_every_generation():
    class Rising(SpendingEvidence):
        async def spent_microusd(self, *, project_id=None, since=None):
            self.reads.append((project_id, since))
            if project_id is not None and len(self.reads) > 2:
                return 9_999_000
            return 0

    generator, client = anthropic_generator(message(TOO_LONG), message(VALID))
    store = Rising()
    failing(generator, store, "GENERATION_BUDGET_EXCEEDED")
    assert len(client.messages.calls) == 1
    assert len(store.requests) == 1 and len(store.reads) == 3


def test_the_openai_adapter_falls_back_after_a_bad_request():
    configuration = providers().hosted_model("review")

    class Transport:
        def __init__(self):
            self.calls = []

        async def post_json(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                return OpenAICompatibleHttpResponse(400, b'{"error": {"message": "schema"}}', 3)
            body = {
                "id": "chatcmpl-2",
                "model": "example-model-1",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(VALID)}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            }
            return OpenAICompatibleHttpResponse(200, json.dumps(body).encode(), 5)

    transport = Transport()
    port = build_openai_hosted_adapter(configuration, api_key=GATEWAY_KEY, transport=transport)
    generator = ProposalGenerator(configuration, port, BUDGET)
    output, _ = run(generator, SpendingEvidence())
    assert output.assessment == "Clear."
    first, second = (call["payload"] for call in transport.calls)
    assert "response_format" in first and "response_format" not in second


def test_callers_can_turn_the_retry_off_through_the_router():
    generator, client = anthropic_generator(message(TOO_LONG), message(VALID))
    router = RoutingProposalGenerator({"general": generator}, ModelRoutes(default="general"))
    failing(router, SpendingEvidence(), "RESPONSE_SCHEMA_ERROR", retry_schema_errors=False)
    assert len(client.messages.calls) == 1


def test_a_local_generator_calls_its_port_without_output_options(tmp_path):
    from src.test.python.models.test_model_proposals import make_generator

    generator, transport = make_generator(tmp_path, VALID)
    output = asyncio.run(
        generator.generate(
            task="team",
            context={"project_id": "p"},
            output_type=Review,
            instruction="Review.",
            retry_schema_errors=False,
        )
    )
    assert output.assessment == "Clear."
    [call] = transport.calls
    assert call["payload"]["messages"][1]["content"].startswith("{")
