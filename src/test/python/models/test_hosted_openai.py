from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from uuid import uuid4

import pytest

from orchestwin.models.hosted_schema import hosted_output_schema, hosted_user_message
from orchestwin.models.openai_compatible import (
    OpenAICompatibleHttpResponse,
    OpenAICompatibleTimeoutError,
    OpenAICompatibleTransportError,
)
from orchestwin.models.openai_hosted import (
    OpenAICompatibleHostedStructuredAdapter,
    build_openai_hosted_adapter,
    hosted_http_failure,
    openai_model_readiness,
)
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
)
from src.test.python.models.test_hosted_support import (
    GATEWAY_KEY,
    REVIEW_SCHEMA,
    VALID_REVIEW,
    providers,
    structured_request,
)
from src.test.python.models.test_proposal_evidence import MemoryEvidence

Code = StructuredGenerationFailureCode


def completion(
    content=None,
    *,
    finish_reason="stop",
    refusal=None,
    model="example-model-1",
    usage=None,
    choices=None,
):
    body = {
        "id": "chatcmpl-synthetic-0001",
        "object": "chat.completion",
        "model": model,
        "choices": choices
        if choices is not None
        else [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(VALID_REVIEW) if content is None else content,
                    "refusal": refusal,
                },
            }
        ],
        "usage": usage
        or {
            "prompt_tokens": 2000,
            "completion_tokens": 700,
            "total_tokens": 2700,
            "prompt_tokens_details": {"cached_tokens": 1024},
        },
    }
    return json.dumps(body).encode("utf-8")


class RecordedTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def post_json(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.responses.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        status, body = outcome
        return OpenAICompatibleHttpResponse(status, body, 15)


def configuration():
    return providers().hosted_model("review")


def adapter(transport):
    return build_openai_hosted_adapter(configuration(), api_key=GATEWAY_KEY, transport=transport)


def generate(*responses, request=None):
    transport = RecordedTransport(*responses)
    selected = configuration()
    result = asyncio.run(adapter(transport).generate(request or structured_request(selected)))
    return result, transport


def test_a_recorded_completion_is_validated_and_costed():
    result, transport = generate((200, completion()))
    assert len(transport.calls) == 1
    assert result.provider_kind is StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED
    success = result.success
    assert json.loads(success.payload_json) == VALID_REVIEW
    assert success.actual_identity == configuration().identity
    assert success.provider_request_id == "chatcmpl-synthetic-0001"
    usage = success.usage
    assert (usage.input_tokens, usage.cache_read_input_tokens, usage.output_tokens) == (
        976,
        1024,
        700,
    )
    assert usage.cache_write_input_tokens == 0 and usage.latency_milliseconds == 15
    assert usage.cost_microusd == round(976 * 4 + 1024 * 0.2 + 700 * 20)


def test_the_payload_uses_strict_json_schema_and_no_local_fields():
    selected = configuration()
    request = structured_request(selected, max_output_tokens=4096)
    _, transport = generate((200, completion()), request=request)
    [call] = transport.calls
    assert call["url"] == "https://llm.example.com/v1/chat/completions"
    assert call["headers"] == {"Authorization": f"Bearer {GATEWAY_KEY}"}
    assert call["timeout_seconds"] == 300
    payload = call["payload"]
    assert payload == {
        "model": "example-model-1",
        "messages": [
            {"role": "system", "content": request.system_instruction},
            {"role": "user", "content": hosted_user_message(request.input_payload_json)},
        ],
        "max_completion_tokens": 4096,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "proposal-team-v1",
                "strict": True,
                "schema": hosted_output_schema(REVIEW_SCHEMA, selected.provider_kind),
            },
        },
    }
    assert payload["response_format"]["json_schema"]["schema"]["required"] == [
        "assessment",
        "score",
        "tags",
    ]
    effort = replace(selected, entry=selected.entry.model_copy(update={"effort": "low"}))
    transport = RecordedTransport((200, completion()))
    port = build_openai_hosted_adapter(effort, api_key=GATEWAY_KEY, transport=transport)
    asyncio.run(port.generate(structured_request(effort)))
    assert transport.calls[0]["payload"]["reasoning_effort"] == "low"


@pytest.mark.parametrize(
    "body,code",
    [
        (completion(finish_reason="length", content='{"partial": '), Code.INCOMPLETE_OUTPUT),
        (completion(refusal="I cannot help with that.", content=None), Code.PROVIDER_REFUSED),
        (completion(finish_reason="content_filter"), Code.PROVIDER_REFUSED),
        (completion(finish_reason="tool_calls"), Code.RESPONSE_SCHEMA_ERROR),
        (
            completion(content=json.dumps({**VALID_REVIEW, "assessment": "y" * 41})),
            Code.RESPONSE_SCHEMA_ERROR,
        ),
        (completion(content="plain text"), Code.RESPONSE_SCHEMA_ERROR),
    ],
)
def test_finish_reasons_refusals_and_violations_keep_the_usage(body, code):
    result, _ = generate((200, body))
    assert result.failure.code is code
    assert result.failure.usage.output_tokens == 700


@pytest.mark.parametrize(
    "body",
    [
        b"{broken",
        completion(choices=[]),
        completion(usage={"prompt_tokens": 10}),
        completion(
            usage={
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 11},
            }
        ),
    ],
)
def test_an_invalid_envelope_is_a_schema_error_without_usage(body):
    result, _ = generate((200, body))
    assert result.failure.code is Code.RESPONSE_SCHEMA_ERROR
    assert result.failure.usage is None


def test_the_served_model_decides_the_identity():
    mismatch, _ = generate((200, completion(model="other-model")))
    assert mismatch.success.actual_identity.base_model_revision == "other-model"
    dated, _ = generate((200, completion(model="example-model-1-2026-09-01")))
    assert dated.success.actual_identity == configuration().identity


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (401, Code.AUTHENTICATION_FAILED, False),
        (403, Code.AUTHENTICATION_FAILED, False),
        (429, Code.RATE_LIMITED, True),
        (408, Code.TIMEOUT, True),
        (504, Code.TIMEOUT, True),
        (500, Code.PROVIDER_UNAVAILABLE, True),
        (503, Code.PROVIDER_UNAVAILABLE, True),
        (400, Code.INVALID_REQUEST, False),
        (404, Code.INVALID_REQUEST, False),
        (409, Code.INVALID_REQUEST, False),
        (413, Code.INVALID_REQUEST, False),
        (422, Code.INVALID_REQUEST, False),
        (418, Code.PROVIDER_ERROR, False),
    ],
)
def test_http_errors_follow_the_table_of_the_local_adapter(status, code, retryable):
    result, _ = generate((status, b'{"error": {"message": "synthetic"}}'))
    failure = result.failure
    assert (failure.code, failure.retryable, failure.provider_status_code) == (
        code,
        retryable,
        status,
    )
    assert hosted_http_failure(status).failure == failure


@pytest.mark.parametrize(
    "error,code",
    [
        (OpenAICompatibleTimeoutError("synthetic"), Code.TIMEOUT),
        (OpenAICompatibleTransportError("synthetic"), Code.PROVIDER_UNAVAILABLE),
    ],
)
def test_transport_failures_are_retryable(error, code):
    result, _ = generate(error)
    assert result.failure.code is code and result.failure.retryable is True


def test_a_foreign_identity_never_reaches_the_endpoint():
    transport = RecordedTransport()
    foreign = structured_request(providers().hosted_model("design"))
    result = asyncio.run(adapter(transport).generate(foreign))
    assert result.failure.code is Code.IDENTITY_MISMATCH and transport.calls == []
    with pytest.raises(ValueError):
        OpenAICompatibleHostedStructuredAdapter(
            configuration=providers().hosted_model("design"), transport=transport, api_key="k"
        )
    with pytest.raises(ValueError):
        OpenAICompatibleHostedStructuredAdapter(
            configuration=configuration(), transport=transport, api_key="two words"
        )


async def _in_scope(store, port, request):
    token = _SCOPE.set(ProposalEvidenceScope(store, uuid4(), uuid4()))
    try:
        await begin_model_generation(request)
        result = await port.generate(request)
        await retain_provider_result(result)
        return result
    finally:
        _SCOPE.reset(token)


def test_evidence_retains_the_body_and_withholds_a_reflected_bearer_key():
    store = MemoryEvidence()
    request = structured_request(configuration())
    body = completion()
    result = asyncio.run(_in_scope(store, adapter(RecordedTransport((200, body))), request))
    events = store.events[request.request_id]
    assert [kind for kind, _, _ in events] == ["HTTP_REQUEST", "HTTP_RESPONSE", "PROVIDER_RESULT"]
    assert events[1][2] == body and events[2][1] == result.to_snapshot()
    assert GATEWAY_KEY not in json.dumps(events[0][1])
    reflected = structured_request(configuration())
    echo = completion().replace(b"Clear flow.", GATEWAY_KEY.encode())
    with pytest.raises(ProposalEvidenceError, match="PROVIDER_REFLECTED_CREDENTIAL"):
        asyncio.run(_in_scope(store, adapter(RecordedTransport((200, echo))), reflected))
    events = store.events[reflected.request_id]
    assert events[-1][0] == "HTTP_RESPONSE" and events[-1][2] is None
    assert GATEWAY_KEY not in repr(store.events)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, {"id": "example-model-1", "object": "model"}, (True, None)),
        (
            200,
            {"id": "example-model-1", "context_window": 2_000_000, "max_output_tokens": 16_000},
            (True, None),
        ),
        (
            200,
            {"id": "example-model-1", "context_length": 8192},
            (False, "HOSTED_MODEL_WINDOW_TOO_SMALL"),
        ),
        (
            200,
            {"id": "example-model-1", "max_completion_tokens": 4096},
            (False, "HOSTED_MODEL_OUTPUT_TOO_SMALL"),
        ),
        (200, {"id": "other-model"}, (False, "HOSTED_MODEL_IDENTITY_MISMATCH")),
        (401, None, (False, "HOSTED_PROVIDER_AUTHENTICATION_FAILED")),
        (404, None, (False, "HOSTED_MODEL_NOT_FOUND")),
        (500, None, (False, "HOSTED_PROVIDER_UNAVAILABLE")),
    ],
)
def test_readiness_reads_the_model_description_with_the_bearer_key(status, body, expected):
    calls = []

    def fetch(provider, model, api_key):
        calls.append((provider.base_url, model, api_key == GATEWAY_KEY))
        return status, b"" if body is None else json.dumps(body).encode()

    observation = asyncio.run(
        openai_model_readiness(configuration(), api_key=GATEWAY_KEY, fetch=fetch)
    )
    assert (observation["ready"], observation.get("code")) == expected
    assert calls == [("https://llm.example.com", "example-model-1", True)]
    assert GATEWAY_KEY not in json.dumps(observation)


def test_readiness_reports_an_unreachable_endpoint():
    def fetch(provider, model, api_key):
        raise OpenAICompatibleTransportError("synthetic")

    observation = asyncio.run(
        openai_model_readiness(configuration(), api_key=GATEWAY_KEY, fetch=fetch)
    )
    assert observation == {
        "model": "example-model-1",
        "ready": False,
        "code": "HOSTED_PROVIDER_UNAVAILABLE",
    }
