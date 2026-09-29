from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace
from typing import Any, Final

import anthropic

from orchestwin.models.generation_budget import cost_microusd
from orchestwin.models.hosted_configuration import (
    HostedModelConfiguration,
    declared_limits_problem,
    served_model_matches,
)
from orchestwin.models.hosted_schema import (
    HostedSchemaError,
    hosted_output_schema,
    hosted_user_message,
    parse_prompted_answer,
    prune_undefined_properties,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.openai_compatible import (
    OpenAICompatibleTimeoutError,
    OpenAICompatibleTransportError,
)
from orchestwin.models.proposal_evidence import AuditedProposalTransport
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationPort,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    StructuredOutputMode,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import canonical_json

ANTHROPIC_MESSAGES_URL: Final = "https://api.anthropic.com/v1/messages"
READINESS_TIMEOUT_SECONDS: Final = 10
_MAX_IDENTIFIER_LENGTH: Final = 256
_KIND: Final = StructuredGenerationProviderKind.ANTHROPIC_HOSTED
_Code = StructuredGenerationFailureCode
_ERROR_TYPES: Final = {
    "authentication_error": (_Code.AUTHENTICATION_FAILED, False),
    "permission_error": (_Code.AUTHENTICATION_FAILED, False),
    "rate_limit_error": (_Code.RATE_LIMITED, True),
    "timeout_error": (_Code.TIMEOUT, True),
    "overloaded_error": (_Code.PROVIDER_UNAVAILABLE, True),
    "api_error": (_Code.PROVIDER_UNAVAILABLE, True),
    "invalid_request_error": (_Code.INVALID_REQUEST, False),
    "not_found_error": (_Code.INVALID_REQUEST, False),
}
_FAILURE_MESSAGES: Final = {
    _Code.AUTHENTICATION_FAILED: "The hosted model provider rejected the credentials.",
    _Code.RATE_LIMITED: "The hosted model provider is rate limited.",
    _Code.TIMEOUT: "The hosted model request exceeded its timeout.",
    _Code.PROVIDER_UNAVAILABLE: "The hosted model provider is temporarily unavailable.",
    _Code.INVALID_REQUEST: "The hosted model provider rejected the request.",
    _Code.PROVIDER_ERROR: "The hosted model provider returned an unexpected error.",
}


@dataclass(frozen=True, slots=True)
class AnthropicTransportResponse:
    status_code: int
    body: bytes
    elapsed_milliseconds: int
    failure: tuple[StructuredGenerationFailureCode, bool] | None = None


def create_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    return anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)


class AnthropicMessagesTransport:
    def __init__(self, client: Any) -> None:
        self._client = client

    async def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> AnthropicTransportResponse:
        arguments = {key: value for key, value in payload.items() if key != "stream"}
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_seconds):
                async with self._client.messages.stream(
                    **arguments, timeout=timeout_seconds
                ) as stream:
                    message = await stream.get_final_message()
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as error:
            return _status_response(error, _Code.AUTHENTICATION_FAILED, False, started)
        except anthropic.RateLimitError as error:
            return _status_response(error, _Code.RATE_LIMITED, True, started)
        except anthropic.DeadlineExceededError as error:
            return _status_response(error, _Code.TIMEOUT, True, started)
        except (anthropic.OverloadedError, anthropic.ServiceUnavailableError) as error:
            return _status_response(error, _Code.PROVIDER_UNAVAILABLE, True, started)
        except anthropic.InternalServerError as error:
            code = _Code.TIMEOUT if error.status_code == 504 else _Code.PROVIDER_UNAVAILABLE
            return _status_response(error, code, True, started)
        except (
            anthropic.BadRequestError,
            anthropic.NotFoundError,
            anthropic.ConflictError,
            anthropic.RequestTooLargeError,
            anthropic.UnprocessableEntityError,
        ) as error:
            return _status_response(error, _Code.INVALID_REQUEST, False, started)
        except anthropic.APIStatusError as error:
            code, retryable = _generic_status_failure(error)
            return _status_response(error, code, retryable, started)
        except anthropic.APITimeoutError:
            raise OpenAICompatibleTimeoutError("hosted model request timed out") from None
        except anthropic.APIConnectionError:
            raise OpenAICompatibleTransportError("hosted model endpoint unavailable") from None
        except TimeoutError:
            raise OpenAICompatibleTimeoutError("hosted model request timed out") from None
        except anthropic.AnthropicError:
            raise OpenAICompatibleTransportError("hosted model client failed") from None
        body = canonical_json(message.to_dict(mode="json", exclude_unset=False, warnings=False))
        return AnthropicTransportResponse(
            status_code=200,
            body=body.encode("utf-8"),
            elapsed_milliseconds=_elapsed(started),
        )


def _elapsed(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _generic_status_failure(
    error: anthropic.APIStatusError,
) -> tuple[StructuredGenerationFailureCode, bool]:
    mapped = _ERROR_TYPES.get(str(error.type)) if error.type is not None else None
    if mapped is not None:
        return mapped
    status = error.status_code
    if status in {408, 504}:
        return _Code.TIMEOUT, True
    if status >= 500:
        return _Code.PROVIDER_UNAVAILABLE, True
    if status in {400, 404, 409, 413, 422}:
        return _Code.INVALID_REQUEST, False
    return _Code.PROVIDER_ERROR, False


def _error_body(error: anthropic.APIStatusError) -> bytes:
    if error.status_code >= 400:
        try:
            content = error.response.content
        except Exception:
            content = None
        if isinstance(content, bytes):
            return content
    body = error.body
    if body is None:
        return b""
    if isinstance(body, str):
        return body.encode("utf-8")
    return json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")


def _status_response(
    error: anthropic.APIStatusError,
    code: StructuredGenerationFailureCode,
    retryable: bool,
    started: float,
) -> AnthropicTransportResponse:
    status = error.status_code if 100 <= error.status_code <= 599 else 502
    return AnthropicTransportResponse(
        status_code=status,
        body=_error_body(error),
        elapsed_milliseconds=_elapsed(started),
        failure=(code, retryable),
    )


class AnthropicHostedStructuredAdapter(StructuredGenerationPort):
    def __init__(self, *, configuration: HostedModelConfiguration, transport: Any) -> None:
        if configuration.provider_kind is not _KIND:
            raise ValueError("the Anthropic adapter requires an Anthropic model entry")
        self._configuration = configuration
        self._transport = transport

    @property
    def identity(self) -> ModelRuntimeIdentity:
        return self._configuration.identity

    async def generate(
        self,
        request: StructuredGenerationRequest,
        *,
        output_mode: StructuredOutputMode = StructuredOutputMode.STRICT,
        retry_note: str | None = None,
    ) -> StructuredGenerationResult:
        mode = StructuredOutputMode(output_mode)
        if request.expected_identity != self._configuration.identity:
            return _failure(
                _Code.IDENTITY_MISMATCH,
                "The requested model identity differs from the configured hosted model.",
                mode=mode,
                retryable=False,
            )
        full_schema = json.loads(request.output_schema.canonical_schema_json)
        schema = None
        if mode is StructuredOutputMode.STRICT:
            try:
                schema = hosted_output_schema(full_schema, _KIND)
            except HostedSchemaError:
                return _failure(
                    _Code.INVALID_REQUEST,
                    "The output schema cannot be expressed for the hosted model provider.",
                    mode=mode,
                    retryable=False,
                )
        max_tokens = self._configuration.max_tokens(request.max_output_tokens)
        payload = request_payload(
            self._configuration, request, max_tokens, schema=schema, retry_note=retry_note
        )
        try:
            response = await self._transport.post_json(
                url=ANTHROPIC_MESSAGES_URL,
                payload=payload,
                headers={},
                timeout_seconds=request.timeout_seconds,
            )
        except OpenAICompatibleTimeoutError:
            return _failure(
                _Code.TIMEOUT, _FAILURE_MESSAGES[_Code.TIMEOUT], mode=mode, retryable=True
            )
        except OpenAICompatibleTransportError:
            return _failure(
                _Code.PROVIDER_UNAVAILABLE,
                "The hosted model provider could not be reached.",
                mode=mode,
                retryable=True,
            )
        failure = getattr(response, "failure", None)
        if failure is not None:
            code, retryable = failure
            return _failure(
                code,
                _FAILURE_MESSAGES[code],
                mode=mode,
                retryable=retryable,
                status=response.status_code,
            )
        return self._answer(response, full_schema, mode)

    def _answer(
        self, response: Any, full_schema: dict[str, Any], mode: StructuredOutputMode
    ) -> StructuredGenerationResult:
        try:
            message = strict_json_object(response.body)
            usage = _usage(message.get("usage"), response.elapsed_milliseconds, self._configuration)
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model returned an invalid message envelope.",
                mode=mode,
                retryable=False,
            )
        stop_reason = message.get("stop_reason")
        if stop_reason == "max_tokens":
            return _failure(
                _Code.INCOMPLETE_OUTPUT,
                "The hosted model stopped at its output limit; no partial output was accepted.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if stop_reason == "refusal":
            return _failure(
                _Code.PROVIDER_REFUSED,
                "The hosted model declined to answer.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if stop_reason != "end_turn":
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model ended with an unsupported stop reason.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            identity = _served_identity(self._configuration, message.get("model"))
            text = _text(message.get("content"))
            output = (
                strict_json_object(text)
                if mode is StructuredOutputMode.STRICT
                else parse_prompted_answer(text)
            )
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model answer is not one JSON object.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        violations = validate_against_schema(output, full_schema)
        if violations and mode is StructuredOutputMode.PROMPTED:
            pruned = prune_undefined_properties(output, full_schema)
            if pruned is not None:
                output, violations = pruned.payload, ()
        if violations:
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                violation_message(violations),
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            success = create_structured_generation_success(
                payload=output,
                actual_identity=identity,
                usage=usage,
                finish_reason=StructuredGenerationFinishReason.STOP,
                provider_request_id=_provider_request_id(message.get("id")),
            )
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model answer does not satisfy the structured contract.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        return successful_structured_generation_result(
            provider_kind=_KIND, success=success, output_mode=mode
        )


def request_payload(
    configuration: HostedModelConfiguration,
    request: StructuredGenerationRequest,
    max_tokens: int,
    *,
    schema: dict[str, Any] | None = None,
    retry_note: str | None = None,
) -> dict[str, object]:
    output_config: dict[str, object] = {}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}
    if configuration.effort is not None:
        output_config["effort"] = configuration.effort
    payload: dict[str, object] = {
        "model": configuration.model,
        "max_tokens": max_tokens,
        "system": request.system_instruction,
        "messages": [
            {
                "role": "user",
                "content": hosted_user_message(request.input_payload_json, retry_note),
            }
        ],
    }
    if output_config:
        payload["output_config"] = output_config
    payload["stream"] = True
    return payload


def _failure(
    code: StructuredGenerationFailureCode,
    message: str,
    *,
    mode: StructuredOutputMode,
    retryable: bool,
    status: int | None = None,
    usage: StructuredGenerationUsage | None = None,
) -> StructuredGenerationResult:
    return failed_structured_generation_result(
        provider_kind=_KIND,
        code=code,
        message=message,
        retryable=retryable,
        provider_status_code=status,
        usage=usage,
        output_mode=mode,
    )


def _count(values: dict[str, object], key: str, *, required: bool) -> int:
    value = values.get(key)
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _usage(
    value: object, elapsed_milliseconds: int, configuration: HostedModelConfiguration
) -> StructuredGenerationUsage:
    if not isinstance(value, dict):
        raise ValueError("message usage is required")
    input_tokens = _count(value, "input_tokens", required=True)
    output_tokens = _count(value, "output_tokens", required=True)
    cache_read = _count(value, "cache_read_input_tokens", required=False)
    cache_write = _count(value, "cache_creation_input_tokens", required=False)
    details = value.get("output_tokens_details")
    reasoning = (
        _count(details, "thinking_tokens", required=False) if isinstance(details, dict) else 0
    )
    return StructuredGenerationUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_milliseconds=elapsed_milliseconds,
        cache_read_input_tokens=cache_read,
        cache_write_input_tokens=cache_write,
        reasoning_tokens=reasoning,
        cost_microusd=cost_microusd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_write_input_tokens=cache_write,
            prices=configuration.prices,
        ),
    )


def _text(content: object) -> str:
    if not isinstance(content, list):
        raise ValueError("message content must be a list")
    texts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
    ]
    if not texts:
        raise ValueError("message content has no text block")
    return "".join(texts)


def _served_identity(
    configuration: HostedModelConfiguration, served: object
) -> ModelRuntimeIdentity:
    if not isinstance(served, str) or not served:
        raise ValueError("served model is required")
    if served_model_matches(configuration.model, served):
        return configuration.identity
    return replace(configuration.identity, base_model_revision=served)


def _provider_request_id(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value) <= _MAX_IDENTIFIER_LENGTH
        and not any(character.isspace() for character in value)
    ):
        return value
    return None


def build_anthropic_adapter(
    configuration: HostedModelConfiguration, *, client: Any, api_key: str
) -> AnthropicHostedStructuredAdapter:
    return AnthropicHostedStructuredAdapter(
        configuration=configuration,
        transport=AuditedProposalTransport(AnthropicMessagesTransport(client), credential=api_key),
    )


async def anthropic_model_readiness(
    client: Any, configuration: HostedModelConfiguration
) -> dict[str, object]:
    observation: dict[str, object] = {"model": configuration.model}
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            info = await client.models.retrieve(
                configuration.model, timeout=READINESS_TIMEOUT_SECONDS
            )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError):
        return {**observation, "ready": False, "code": "HOSTED_PROVIDER_AUTHENTICATION_FAILED"}
    except anthropic.NotFoundError:
        return {**observation, "ready": False, "code": "HOSTED_MODEL_NOT_FOUND"}
    except (anthropic.AnthropicError, TimeoutError):
        return {**observation, "ready": False, "code": "HOSTED_PROVIDER_UNAVAILABLE"}
    context_window = getattr(info, "max_input_tokens", None)
    max_output = getattr(info, "max_tokens", None)
    observation.update(
        declared_context_window_tokens=context_window,
        declared_max_output_tokens=max_output,
    )
    if not served_model_matches(configuration.model, getattr(info, "id", None)):
        return {**observation, "ready": False, "code": "HOSTED_MODEL_IDENTITY_MISMATCH"}
    problem = declared_limits_problem(
        configuration, context_window_tokens=context_window, max_output_tokens=max_output
    )
    if problem is not None:
        return {**observation, "ready": False, "code": problem}
    return {**observation, "ready": True}


__all__ = [
    "ANTHROPIC_MESSAGES_URL",
    "AnthropicHostedStructuredAdapter",
    "AnthropicMessagesTransport",
    "AnthropicTransportResponse",
    "anthropic_model_readiness",
    "build_anthropic_adapter",
    "create_anthropic_client",
    "request_payload",
]
