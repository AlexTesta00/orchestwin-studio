"""Tests for the strict OpenAI-compatible local structured adapter."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from uuid import UUID

import pytest

from orchestwin.models.openai_compatible import (
    OpenAICompatibleHttpResponse,
    OpenAICompatibleLocalConfig,
    OpenAICompatibleLocalStructuredAdapter,
    OpenAICompatibleTimeoutError,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationStatus,
    create_structured_generation_request,
    create_structured_json_schema,
)


def _identity(*, adapter: bool = True, provider: str = "local-openai") -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id=provider,
        runtime_id="local-evaluator-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="c" * 64,
        adapter_id="ut-evaluator-v1" if adapter else None,
        adapter_sha256="d" * 64 if adapter else None,
    )


def _request(*, identity: ModelRuntimeIdentity | None = None):
    return create_structured_generation_request(
        request_id=UUID("00000000-0000-4000-8000-000000116001"),
        task_id="bench-en-001",
        expected_identity=_identity() if identity is None else identity,
        output_schema=create_structured_json_schema(
            schema_id="user-twin-evaluation",
            version_number=1,
            schema_payload={
                "type": "object",
                "required": ["findings", "abstained"],
                "properties": {
                    "findings": {"type": "array"},
                    "abstained": {"type": "boolean"},
                },
            },
        ),
        system_instruction="Return only the requested structured evaluation.",
        input_payload={"scenario": "Recover from invalid input."},
        allowed_evidence_refs=("REQ-001",),
        prompt_version_ref="ut-eval-v5",
        temperature=0.0,
        max_output_tokens=512,
        timeout_seconds=30,
    )


@dataclass
class _FakeTransport:
    response: OpenAICompatibleHttpResponse | None = None
    timeout: bool = False
    calls: list[dict[str, object]] = field(default_factory=list)

    async def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> OpenAICompatibleHttpResponse:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "headers": headers,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.timeout:
            raise OpenAICompatibleTimeoutError("fixture timeout")
        if self.response is None:
            raise AssertionError("fake transport response was not configured")
        return self.response


def _response(
    *,
    identity: ModelRuntimeIdentity | None = None,
    status_code: int = 200,
    content: object | None = None,
) -> OpenAICompatibleHttpResponse:
    body = {
        "id": "local-request-001",
        "model_identity": (_identity() if identity is None else identity).to_snapshot(),
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"findings": [], "abstained": True} if content is None else content
                    )
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 18},
    }
    return OpenAICompatibleHttpResponse(
        status_code=status_code,
        body=json.dumps(body).encode(),
        elapsed_milliseconds=17,
    )


def _adapter(transport: _FakeTransport):
    return OpenAICompatibleLocalStructuredAdapter(
        config=OpenAICompatibleLocalConfig(
            base_url="http://127.0.0.1:8080",
            model_name="ut-evaluator",
            expected_identity=_identity(),
        ),
        transport=transport,
        bearer_token="local-test-token",
    )


def test_adapter_sends_json_schema_and_returns_exact_identity() -> None:
    transport = _FakeTransport(response=_response())
    request = _request()

    result = asyncio.run(_adapter(transport).generate(request))

    assert result.status is StructuredGenerationStatus.SUCCEEDED
    assert result.success is not None
    assert result.success.actual_identity == request.expected_identity
    assert result.success.usage.latency_milliseconds == 17
    call = transport.calls[0]
    assert call["url"] == "http://127.0.0.1:8080/v1/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer local-test-token"}
    payload = call["payload"]
    assert isinstance(payload, dict)
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "user-twin-evaluation",
            "strict": True,
            "schema": json.loads(request.output_schema.canonical_schema_json),
        },
    }


def test_adapter_rejects_request_identity_before_network() -> None:
    transport = _FakeTransport(response=_response())
    request = _request(identity=_identity(provider="different-provider"))

    result = asyncio.run(_adapter(transport).generate(request))

    assert result.failure is not None
    assert result.failure.code is StructuredGenerationFailureCode.IDENTITY_MISMATCH
    assert transport.calls == []


def test_adapter_detects_silent_adapter_fallback() -> None:
    transport = _FakeTransport(response=_response(identity=_identity(adapter=False)))

    result = asyncio.run(_adapter(transport).generate(_request()))

    assert result.failure is not None
    assert result.failure.code is StructuredGenerationFailureCode.ADAPTER_NOT_LOADED


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, StructuredGenerationFailureCode.AUTHENTICATION_FAILED, False),
        (429, StructuredGenerationFailureCode.RATE_LIMITED, True),
        (503, StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE, True),
        (422, StructuredGenerationFailureCode.INVALID_REQUEST, False),
    ],
)
def test_adapter_maps_http_errors(
    status_code: int,
    expected_code: StructuredGenerationFailureCode,
    retryable: bool,
) -> None:
    transport = _FakeTransport(
        response=OpenAICompatibleHttpResponse(
            status_code=status_code,
            body=b"{}",
            elapsed_milliseconds=1,
        )
    )

    result = asyncio.run(_adapter(transport).generate(_request()))

    assert result.failure is not None
    assert result.failure.code is expected_code
    assert result.failure.retryable is retryable
    assert result.failure.provider_status_code == status_code


def test_adapter_maps_timeout_and_invalid_completion_envelopes() -> None:
    timeout_result = asyncio.run(_adapter(_FakeTransport(timeout=True)).generate(_request()))
    invalid_result = asyncio.run(
        _adapter(
            _FakeTransport(
                response=OpenAICompatibleHttpResponse(
                    status_code=200,
                    body=b'{"choices": []}',
                    elapsed_milliseconds=1,
                )
            )
        ).generate(_request())
    )

    assert timeout_result.failure is not None
    assert timeout_result.failure.code is StructuredGenerationFailureCode.TIMEOUT
    assert invalid_result.failure is not None
    assert invalid_result.failure.code is StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR


@pytest.mark.parametrize("content", ["{\n", '{"files":[{"interface', "", "{}"])
def test_generation_limit_is_reported_without_parsing_or_accepting_partial_output(content):
    response = _response()
    payload = json.loads(response.body)
    payload["choices"][0]["finish_reason"] = "length"
    payload["choices"][0]["message"]["content"] = content
    transport = _FakeTransport(
        response=OpenAICompatibleHttpResponse(
            status_code=200, body=json.dumps(payload).encode(), elapsed_milliseconds=125000
        )
    )
    result = asyncio.run(_adapter(transport).generate(_request()))
    assert result.status is StructuredGenerationStatus.FAILED
    assert result.success is None
    assert result.failure.code is StructuredGenerationFailureCode.INCOMPLETE_OUTPUT
    assert result.failure.retryable is False
    assert len(transport.calls) == 1


def test_malformed_json_at_normal_stop_remains_a_schema_error():
    payload = json.loads(_response().body)
    payload["choices"][0]["message"]["content"] = '{"files":['
    transport = _FakeTransport(
        response=OpenAICompatibleHttpResponse(
            status_code=200, body=json.dumps(payload).encode(), elapsed_milliseconds=10
        )
    )
    result = asyncio.run(_adapter(transport).generate(_request()))
    assert result.failure.code is StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR


@pytest.mark.parametrize(
    "origin",
    ["https://models.example.com", "http://127.evil.example", "http://127.0.0.1.evil.example"],
)
def test_remote_endpoint_requires_explicit_authorization(origin) -> None:
    with pytest.raises(ValueError, match="explicit authorization"):
        OpenAICompatibleLocalConfig(
            base_url=origin,
            model_name="ut-evaluator",
            expected_identity=_identity(),
        )


@pytest.mark.parametrize(
    "origin", ["http://127.0.0.1:8000", "http://[::1]:8000", "http://localhost:8000"]
)
def test_literal_loopback_and_localhost_remain_supported(origin):
    assert (
        OpenAICompatibleLocalConfig(
            base_url=origin, model_name="local", expected_identity=_identity()
        ).base_url
        == origin
    )


def test_endpoint_credentials_cannot_be_hidden_in_the_url():
    with pytest.raises(ValueError, match="explicit bearer token"):
        OpenAICompatibleLocalConfig(
            base_url="http://user:password@127.0.0.1",
            model_name="local",
            expected_identity=_identity(),
        )


@pytest.mark.parametrize(
    "body,code",
    [
        (
            b'{"error":"CONTEXT_BUDGET_EXCEEDED"}',
            StructuredGenerationFailureCode.CONTEXT_BUDGET_EXCEEDED,
        ),
        (b'{"error":"OTHER_ERROR"}', StructuredGenerationFailureCode.INVALID_REQUEST),
        (
            b'{"error":"CONTEXT_BUDGET_EXCEEDED","secret":"not echoed"}',
            StructuredGenerationFailureCode.INVALID_REQUEST,
        ),
        (b"not json", StructuredGenerationFailureCode.INVALID_REQUEST),
    ],
)
def test_context_limit_is_typed_and_arbitrary_server_details_are_not_echoed(body, code):
    transport = _FakeTransport(
        response=OpenAICompatibleHttpResponse(status_code=422, body=body, elapsed_milliseconds=1)
    )
    result = asyncio.run(_adapter(transport).generate(_request()))
    assert result.failure.code is code and result.failure.retryable is False
    assert "not echoed" not in result.failure.message
    assert len(transport.calls) == 1
