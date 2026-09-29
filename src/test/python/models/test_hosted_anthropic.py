from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import anthropic
import pytest

from orchestwin.models.anthropic_hosted import (
    ANTHROPIC_MESSAGES_URL,
    AnthropicHostedStructuredAdapter,
    AnthropicMessagesTransport,
    anthropic_model_readiness,
    build_anthropic_adapter,
    create_anthropic_client,
)
from orchestwin.models.hosted_schema import hosted_output_schema, hosted_user_message
from orchestwin.models.proposal_evidence import (
    _SCOPE,
    ProposalEvidenceError,
    ProposalEvidenceScope,
    begin_model_generation,
    retain_provider_result,
)
from orchestwin.models.structured_generation import (
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
)
from orchestwin.projects.requirements_primitives import canonical_json
from src.test.python.models.test_hosted_support import (
    REVIEW_SCHEMA,
    TEST_KEY,
    VALID_REVIEW,
    FakeAnthropicClient,
    connection_error,
    message,
    model_info,
    providers,
    status_error,
    structured_request,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

Code = StructuredGenerationFailureCode


def configuration(entry="design"):
    return providers().hosted_model(entry)


def adapter(client, entry="design"):
    return build_anthropic_adapter(configuration(entry), client=client, api_key=TEST_KEY)


def generate(client, request=None, entry="design"):
    selected = configuration(entry)
    return asyncio.run(adapter(client, entry).generate(request or structured_request(selected)))


async def _in_scope(store, port, request):
    token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
    try:
        await begin_model_generation(request)
        result = await port.generate(request)
        await retain_provider_result(result)
        return result
    finally:
        _SCOPE.reset(token)


def test_a_successful_answer_is_validated_costed_and_bound_to_the_expected_identity():
    client = FakeAnthropicClient(message())
    selected = configuration()
    request = structured_request(selected)
    result = asyncio.run(adapter(client).generate(request))
    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert result.provider_kind is StructuredGenerationProviderKind.ANTHROPIC_HOSTED
    success = result.success
    assert json.loads(success.payload_json) == VALID_REVIEW
    assert success.actual_identity == selected.identity == request.expected_identity
    assert success.provider_request_id == "msg_synthetic_0001"
    usage = success.usage
    assert (usage.input_tokens, usage.output_tokens) == (1200, 900)
    assert (usage.cache_read_input_tokens, usage.cache_write_input_tokens) == (100, 50)
    assert usage.cost_microusd == 1200 * 4 + 900 * 20 + round(100 * 0.2) + 50 * 5
    assert usage.latency_milliseconds >= 0
    assert usage.to_snapshot()["cost_microusd"] == 23_070


def test_the_request_carries_only_the_documented_parameters():
    client = FakeAnthropicClient(message())
    selected = configuration()
    request = structured_request(selected, max_output_tokens=4096)
    asyncio.run(adapter(client).generate(request))
    [call] = client.messages.calls
    assert set(call) == {"model", "max_tokens", "system", "messages", "output_config", "timeout"}
    assert call["model"] == "claude-opus-5-5"
    assert call["max_tokens"] == 4096 + 16_000
    assert call["system"] == request.system_instruction
    assert call["messages"] == [
        {"role": "user", "content": hosted_user_message(request.input_payload_json)}
    ]
    assert call["output_config"] == {
        "format": {
            "type": "json_schema",
            "schema": hosted_output_schema(REVIEW_SCHEMA, selected.provider_kind),
        },
        "effort": "high",
    }
    assert call["timeout"] == selected.timeout_seconds
    ceiling = FakeAnthropicClient(message())
    asyncio.run(adapter(ceiling).generate(structured_request(selected, max_output_tokens=90_000)))
    assert ceiling.messages.calls[0]["max_tokens"] == 64_000 + 16_000


def test_an_entry_without_effort_sends_no_effort():
    document_entry = providers().hosted_model("general")
    unset = replace(document_entry, entry=document_entry.entry.model_copy(update={"effort": None}))
    client = FakeAnthropicClient(message(model="claude-sonnet-5"))
    port = AnthropicHostedStructuredAdapter(
        configuration=unset, transport=AnthropicMessagesTransport(client)
    )
    request = structured_request(unset)
    assert asyncio.run(port.generate(request)).success is not None
    assert "effort" not in client.messages.calls[0]["output_config"]


@pytest.mark.parametrize(
    "stop_reason,code",
    [
        ("max_tokens", Code.INCOMPLETE_OUTPUT),
        ("refusal", Code.PROVIDER_REFUSED),
        ("pause_turn", Code.RESPONSE_SCHEMA_ERROR),
        ("tool_use", Code.RESPONSE_SCHEMA_ERROR),
        ("model_context_window_exceeded", Code.RESPONSE_SCHEMA_ERROR),
    ],
)
def test_stop_reasons_other_than_end_turn_fail_and_keep_their_cost(stop_reason, code):
    result = generate(FakeAnthropicClient(message(stop_reason=stop_reason, text='{"partial": ')))
    failure = result.failure
    assert failure.code is code and failure.retryable is False
    assert failure.usage.cost_microusd == 23_070
    assert failure.to_snapshot()["usage"]["output_tokens"] == 900


@pytest.mark.parametrize(
    "text,path",
    [
        (json.dumps({**VALID_REVIEW, "assessment": "x" * 41}), "$.assessment (maxLength)"),
        (json.dumps({**VALID_REVIEW, "score": 2}), "$.score (maximum)"),
        (json.dumps({**VALID_REVIEW, "tags": ["fast"] * 3}), "$.tags (maxItems)"),
    ],
)
def test_an_answer_that_breaks_a_removed_constraint_is_a_schema_error(text, path):
    failure = generate(FakeAnthropicClient(message(text=text))).failure
    assert failure.code is Code.RESPONSE_SCHEMA_ERROR
    assert path in failure.message
    assert "xxxxxxxxxx" not in failure.message
    assert failure.usage is not None


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '{"a": 1, "a": 2}'])
def test_an_answer_that_is_not_one_json_object_is_a_schema_error(text):
    failure = generate(FakeAnthropicClient(message(text=text))).failure
    assert failure.code is Code.RESPONSE_SCHEMA_ERROR
    assert failure.message == "The hosted model answer is not one JSON object."


def test_a_different_served_model_is_reported_in_the_identity():
    selected = configuration()
    mismatch = generate(FakeAnthropicClient(message(model="claude-opus-5"))).success
    assert mismatch.actual_identity == replace(
        selected.identity, base_model_revision="claude-opus-5"
    )
    snapshot = generate(FakeAnthropicClient(message(model="claude-opus-5-5-20261001"))).success
    assert snapshot.actual_identity == selected.identity


def _mapped_errors():
    return [
        (status_error(anthropic.AuthenticationError, 401), Code.AUTHENTICATION_FAILED, False, 401),
        (
            status_error(anthropic.PermissionDeniedError, 403),
            Code.AUTHENTICATION_FAILED,
            False,
            403,
        ),
        (status_error(anthropic.RateLimitError, 429), Code.RATE_LIMITED, True, 429),
        (status_error(anthropic.InternalServerError, 500), Code.PROVIDER_UNAVAILABLE, True, 500),
        (status_error(anthropic.InternalServerError, 504), Code.TIMEOUT, True, 504),
        (
            status_error(anthropic.ServiceUnavailableError, 503),
            Code.PROVIDER_UNAVAILABLE,
            True,
            503,
        ),
        (status_error(anthropic.OverloadedError, 529), Code.PROVIDER_UNAVAILABLE, True, 529),
        (status_error(anthropic.DeadlineExceededError, 504), Code.TIMEOUT, True, 504),
        (status_error(anthropic.BadRequestError, 400), Code.INVALID_REQUEST, False, 400),
        (status_error(anthropic.NotFoundError, 404), Code.INVALID_REQUEST, False, 404),
        (status_error(anthropic.ConflictError, 409), Code.INVALID_REQUEST, False, 409),
        (status_error(anthropic.RequestTooLargeError, 413), Code.INVALID_REQUEST, False, 413),
        (status_error(anthropic.UnprocessableEntityError, 422), Code.INVALID_REQUEST, False, 422),
        (
            status_error(
                anthropic.APIStatusError, 402, {"type": "error", "error": {"type": "billing_error"}}
            ),
            Code.PROVIDER_ERROR,
            False,
            402,
        ),
        (
            status_error(
                anthropic.APIStatusError,
                200,
                {"type": "error", "error": {"type": "overloaded_error"}},
            ),
            Code.PROVIDER_UNAVAILABLE,
            True,
            200,
        ),
        (
            status_error(anthropic.APIStatusError, 408, {"type": "error", "error": {}}),
            Code.TIMEOUT,
            True,
            408,
        ),
        (connection_error(anthropic.APITimeoutError), Code.TIMEOUT, True, None),
        (connection_error(), Code.PROVIDER_UNAVAILABLE, True, None),
    ]


@pytest.mark.parametrize("error,code,retryable,status", _mapped_errors())
def test_sdk_exceptions_map_to_the_failures_of_the_local_adapter(error, code, retryable, status):
    failure = generate(FakeAnthropicClient(error)).failure
    assert (failure.code, failure.retryable, failure.provider_status_code) == (
        code,
        retryable,
        status,
    )
    assert failure.usage is None
    assert TEST_KEY not in json.dumps(failure.to_snapshot())


def test_the_whole_call_is_bounded_by_the_timeout():
    async def slow():
        await asyncio.sleep(30)

    selected = configuration()
    request = replace_timeout(structured_request(selected), 1)
    failure = asyncio.run(adapter(FakeAnthropicClient(slow)).generate(request)).failure
    assert failure.code is Code.TIMEOUT and failure.retryable is True


def replace_timeout(request, seconds):
    from orchestwin.models.structured_generation import create_structured_generation_request

    return create_structured_generation_request(
        request_id=request.request_id,
        task_id=request.task_id,
        expected_identity=request.expected_identity,
        output_schema=request.output_schema,
        system_instruction=request.system_instruction,
        input_payload=json.loads(request.input_payload_json),
        allowed_evidence_refs=request.allowed_evidence_refs,
        prompt_version_ref=request.prompt_version_ref,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        timeout_seconds=seconds,
    )


def test_a_foreign_identity_or_an_inexpressible_schema_never_reaches_the_provider():
    client = FakeAnthropicClient()
    selected = configuration()
    foreign = structured_request(configuration("general"))
    assert asyncio.run(adapter(client).generate(foreign)).failure.code is Code.IDENTITY_MISMATCH
    open_schema = {
        "type": "object",
        "properties": {"notes": {"type": "object", "additionalProperties": {"type": "string"}}},
        "required": ["notes"],
        "additionalProperties": False,
    }
    failure = asyncio.run(
        adapter(client).generate(structured_request(selected, open_schema))
    ).failure
    assert failure.code is Code.INVALID_REQUEST
    assert client.messages.calls == []
    with pytest.raises(ValueError):
        AnthropicHostedStructuredAdapter(
            configuration=configuration("review"), transport=AnthropicMessagesTransport(client)
        )


def test_evidence_keeps_the_exact_body_and_the_final_message_in_order():
    client = FakeAnthropicClient(message())
    store = MemoryEvidence()
    selected = configuration()
    request = structured_request(selected)
    result = asyncio.run(_in_scope(store, adapter(client), request))
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    sent = events[0][1]["payload"]
    assert sent == {
        "model": "claude-opus-5-5",
        "max_tokens": request.max_output_tokens + 16_000,
        "system": request.system_instruction,
        "messages": [{"role": "user", "content": hosted_user_message(request.input_payload_json)}],
        "output_config": client.messages.calls[0]["output_config"],
        "stream": True,
    }
    response, raw = events[1][1], events[1][2]
    assert raw == canonical_json(
        message().to_dict(mode="json", exclude_unset=False, warnings=False)
    ).encode("utf-8")
    assert response["status_code"] == 200 and response["body_retained"] is True
    assert response["body_sha256"] == hashlib.sha256(raw).hexdigest()
    assert events[2][1] == result.to_snapshot()
    assert events[2][1]["success"]["usage"]["cost_microusd"] == 23_070
    assert TEST_KEY not in repr(store.events) and TEST_KEY not in repr(store.requests)


def test_an_error_status_keeps_the_error_body_and_a_lost_connection_is_a_transport_error():
    store = MemoryEvidence()
    selected = configuration()
    request = structured_request(selected)
    body = {"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}
    asyncio.run(
        _in_scope(
            store,
            adapter(FakeAnthropicClient(status_error(anthropic.RateLimitError, 429, body))),
            request,
        )
    )
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    assert events[1][1]["status_code"] == 429
    assert json.loads(events[1][2]) == body
    lost = structured_request(selected)
    asyncio.run(_in_scope(store, adapter(FakeAnthropicClient(connection_error())), lost))
    events = store.events[lost.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "TRANSPORT_ERROR", "PROVIDER_RESULT"]
    assert events[1][1] == {"code": "OpenAICompatibleTransportError"}


def test_a_reflected_key_is_withheld_and_stops_the_generation():
    store = MemoryEvidence()
    selected = configuration()
    request = structured_request(selected)
    reflected = message(text=f'{{"assessment": "{TEST_KEY}", "score": 0.1, "tags": []}}')
    with pytest.raises(ProposalEvidenceError, match="PROVIDER_REFLECTED_CREDENTIAL"):
        asyncio.run(_in_scope(store, adapter(FakeAnthropicClient(reflected)), request))
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE"]
    assert events[1][1]["withheld_reason"] == "CREDENTIAL_REFLECTION" and events[1][2] is None
    assert TEST_KEY not in repr(store.events)


def test_the_client_has_no_retries_and_hides_the_key():
    client = create_anthropic_client(TEST_KEY)
    try:
        assert client.max_retries == 0
        assert TEST_KEY not in repr(client)
        port = build_anthropic_adapter(configuration(), client=client, api_key=TEST_KEY)
        assert TEST_KEY not in repr(port) and TEST_KEY not in repr(vars(port))
        assert port.identity == configuration().identity
        assert ANTHROPIC_MESSAGES_URL == "https://api.anthropic.com/v1/messages"
    finally:
        asyncio.run(client.close())


@pytest.mark.parametrize(
    "info,expected",
    [
        (model_info("claude-opus-5-5"), (True, None)),
        (model_info("claude-opus-5-5-20261001"), (True, None)),
        (
            model_info("claude-opus-5-5", max_input_tokens=200_000),
            (False, "HOSTED_MODEL_WINDOW_TOO_SMALL"),
        ),
        (
            model_info("claude-opus-5-5", max_tokens=64_000),
            (False, "HOSTED_MODEL_OUTPUT_TOO_SMALL"),
        ),
        (model_info("claude-sonnet-5"), (False, "HOSTED_MODEL_IDENTITY_MISMATCH")),
        (status_error(anthropic.NotFoundError, 404), (False, "HOSTED_MODEL_NOT_FOUND")),
        (
            status_error(anthropic.AuthenticationError, 401),
            (False, "HOSTED_PROVIDER_AUTHENTICATION_FAILED"),
        ),
        (connection_error(), (False, "HOSTED_PROVIDER_UNAVAILABLE")),
    ],
)
def test_readiness_asks_the_models_endpoint_without_inference(info, expected):
    client = FakeAnthropicClient(models={"claude-opus-5-5": info})
    observation = asyncio.run(anthropic_model_readiness(client, configuration()))
    assert (observation["ready"], observation.get("code")) == expected
    assert observation["model"] == "claude-opus-5-5"
    assert client.models.calls[0][0] == "claude-opus-5-5"
    assert client.messages.calls == []
    if expected[0]:
        assert observation["declared_context_window_tokens"] == 1_000_000
        assert observation["declared_max_output_tokens"] == 128_000
