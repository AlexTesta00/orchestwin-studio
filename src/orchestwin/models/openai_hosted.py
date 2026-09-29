from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, Final
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from orchestwin.models.generation_budget import cost_microusd
from orchestwin.models.hosted_configuration import (
    HostedModelConfiguration,
    OpenAICompatibleHostedProviderEntry,
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
    UrllibOpenAICompatibleTransport,
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

READINESS_TIMEOUT_SECONDS: Final = 10
_MAX_MODEL_RESPONSE_BYTES: Final = 65_536
_MAX_IDENTIFIER_LENGTH: Final = 256
_KIND: Final = StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED
_Code = StructuredGenerationFailureCode
_DECLARED_WINDOW_KEYS: Final = ("context_window", "context_length", "max_context_length")
_DECLARED_OUTPUT_KEYS: Final = ("max_output_tokens", "max_completion_tokens")


class OpenAICompatibleHostedStructuredAdapter(StructuredGenerationPort):
    def __init__(
        self,
        *,
        configuration: HostedModelConfiguration,
        transport: Any,
        api_key: str,
    ) -> None:
        if configuration.provider_kind is not _KIND or not isinstance(
            configuration.provider, OpenAICompatibleHostedProviderEntry
        ):
            raise ValueError("the adapter requires an OpenAI compatible hosted model entry")
        if not api_key or any(character.isspace() for character in api_key):
            raise ValueError("the hosted provider key must be a non-empty token")
        self._configuration = configuration
        self._transport = transport
        self._api_key = api_key

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
                url=self._configuration.provider.completion_url,
                payload=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout_seconds=request.timeout_seconds,
            )
        except OpenAICompatibleTimeoutError:
            return _failure(
                _Code.TIMEOUT,
                "The hosted model request exceeded its timeout.",
                mode=mode,
                retryable=True,
            )
        except OpenAICompatibleTransportError:
            return _failure(
                _Code.PROVIDER_UNAVAILABLE,
                "The hosted model endpoint could not be reached.",
                mode=mode,
                retryable=True,
            )
        if response.status_code >= 400:
            return hosted_http_failure(response.status_code, output_mode=mode)
        return self._answer(response, full_schema, mode)

    def _answer(
        self, response: Any, full_schema: dict[str, Any], mode: StructuredOutputMode
    ) -> StructuredGenerationResult:
        try:
            body = strict_json_object(response.body)
            choice, message = _single_choice(body)
            usage = _usage(body.get("usage"), response.elapsed_milliseconds, self._configuration)
        except (ValueError, TypeError):
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model returned an invalid completion envelope.",
                mode=mode,
                retryable=False,
            )
        finish_reason = choice.get("finish_reason")
        if message.get("refusal") is not None or finish_reason == "content_filter":
            return _failure(
                _Code.PROVIDER_REFUSED,
                "The hosted model declined to answer.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if finish_reason == "length":
            return _failure(
                _Code.INCOMPLETE_OUTPUT,
                "The hosted model stopped at its output limit; no partial output was accepted.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        if finish_reason != "stop":
            return _failure(
                _Code.RESPONSE_SCHEMA_ERROR,
                "The hosted model ended with an unsupported finish reason.",
                mode=mode,
                retryable=False,
                usage=usage,
            )
        try:
            identity = _served_identity(self._configuration, body.get("model"))
            content = message.get("content")
            if not isinstance(content, str):
                raise ValueError("completion content must be a string")
            output = (
                strict_json_object(content)
                if mode is StructuredOutputMode.STRICT
                else parse_prompted_answer(content)
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
                provider_request_id=_provider_request_id(body.get("id")),
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
    payload: dict[str, object] = {
        "model": configuration.model,
        "messages": [
            {"role": "system", "content": request.system_instruction},
            {
                "role": "user",
                "content": hosted_user_message(request.input_payload_json, retry_note),
            },
        ],
        "max_completion_tokens": max_tokens,
    }
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": request.output_schema.schema_id,
                "strict": True,
                "schema": schema,
            },
        }
    if configuration.effort is not None:
        payload["reasoning_effort"] = configuration.effort
    return payload


def hosted_http_failure(
    status_code: int, *, output_mode: StructuredOutputMode = StructuredOutputMode.STRICT
) -> StructuredGenerationResult:
    if status_code in {401, 403}:
        code, message, retryable = (
            _Code.AUTHENTICATION_FAILED,
            "The hosted model endpoint rejected authentication.",
            False,
        )
    elif status_code == 429:
        code, message, retryable = (
            _Code.RATE_LIMITED,
            "The hosted model endpoint is rate limited.",
            True,
        )
    elif status_code in {408, 504}:
        code, message, retryable = (
            _Code.TIMEOUT,
            "The hosted model endpoint timed out.",
            True,
        )
    elif status_code >= 500:
        code, message, retryable = (
            _Code.PROVIDER_UNAVAILABLE,
            "The hosted model endpoint is temporarily unavailable.",
            True,
        )
    elif status_code in {400, 404, 409, 413, 422}:
        code, message, retryable = (
            _Code.INVALID_REQUEST,
            "The hosted model endpoint rejected the request.",
            False,
        )
    else:
        code, message, retryable = (
            _Code.PROVIDER_ERROR,
            "The hosted model endpoint returned an unexpected error.",
            False,
        )
    return _failure(code, message, mode=output_mode, retryable=retryable, status=status_code)


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


def _single_choice(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    choices = body.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("exactly one completion choice is required")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ValueError("completion choice must carry a message")
    return choice, choice["message"]


def _count(values: dict[str, Any], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _usage(
    value: object, elapsed_milliseconds: int, configuration: HostedModelConfiguration
) -> StructuredGenerationUsage:
    if not isinstance(value, dict):
        raise ValueError("completion usage is required")
    prompt_tokens = _count(value, "prompt_tokens")
    output_tokens = _count(value, "completion_tokens")
    details = value.get("prompt_tokens_details")
    cached = 0
    if isinstance(details, dict) and details.get("cached_tokens") is not None:
        cached = _count(details, "cached_tokens")
    if cached > prompt_tokens:
        raise ValueError("cached tokens exceed the prompt tokens")
    input_tokens = prompt_tokens - cached
    completion = value.get("completion_tokens_details")
    reasoning = 0
    if isinstance(completion, dict) and completion.get("reasoning_tokens") is not None:
        reasoning = _count(completion, "reasoning_tokens")
    return StructuredGenerationUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_milliseconds=elapsed_milliseconds,
        cache_read_input_tokens=cached,
        reasoning_tokens=reasoning,
        cost_microusd=cost_microusd(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cached,
            prices=configuration.prices,
        ),
    )


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


def build_openai_hosted_adapter(
    configuration: HostedModelConfiguration, *, api_key: str, transport: Any = None
) -> OpenAICompatibleHostedStructuredAdapter:
    return OpenAICompatibleHostedStructuredAdapter(
        configuration=configuration,
        transport=AuditedProposalTransport(
            transport if transport is not None else UrllibOpenAICompatibleTransport()
        ),
        api_key=api_key,
    )


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_model_description(
    provider: OpenAICompatibleHostedProviderEntry, model: str, api_key: str
) -> tuple[int, bytes]:
    url = f"{provider.base_url}/v1/models/{quote(model, safe='/:')}"
    request = Request(url, headers={"Authorization": f"Bearer {api_key}"}, method="GET")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=READINESS_TIMEOUT_SECONDS) as response:
            return int(response.status), response.read(_MAX_MODEL_RESPONSE_BYTES + 1)
    except HTTPError as error:
        with error:
            return int(error.code), b""
    except (URLError, OSError, TimeoutError):
        raise OpenAICompatibleTransportError("hosted model endpoint unavailable") from None


def _declared(description: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = description.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


async def openai_model_readiness(
    configuration: HostedModelConfiguration, *, api_key: str, fetch: Any = None
) -> dict[str, object]:
    observation: dict[str, object] = {"model": configuration.model}
    reader = fetch if fetch is not None else fetch_model_description
    try:
        status, body = await asyncio.to_thread(
            reader, configuration.provider, configuration.model, api_key
        )
    except OpenAICompatibleTransportError:
        return {**observation, "ready": False, "code": "HOSTED_PROVIDER_UNAVAILABLE"}
    if status in {401, 403}:
        return {**observation, "ready": False, "code": "HOSTED_PROVIDER_AUTHENTICATION_FAILED"}
    if status == 404:
        return {**observation, "ready": False, "code": "HOSTED_MODEL_NOT_FOUND"}
    try:
        if status != 200 or len(body) > _MAX_MODEL_RESPONSE_BYTES:
            raise ValueError("model description rejected")
        description = strict_json_object(body)
    except ValueError:
        return {**observation, "ready": False, "code": "HOSTED_PROVIDER_UNAVAILABLE"}
    served = description.get("id")
    if served is not None and not served_model_matches(configuration.model, served):
        return {**observation, "ready": False, "code": "HOSTED_MODEL_IDENTITY_MISMATCH"}
    context_window = _declared(description, _DECLARED_WINDOW_KEYS)
    max_output = _declared(description, _DECLARED_OUTPUT_KEYS)
    observation.update(
        declared_context_window_tokens=context_window,
        declared_max_output_tokens=max_output,
    )
    problem = declared_limits_problem(
        configuration, context_window_tokens=context_window, max_output_tokens=max_output
    )
    if problem is not None:
        return {**observation, "ready": False, "code": problem}
    return {**observation, "ready": True}


__all__ = [
    "OpenAICompatibleHostedStructuredAdapter",
    "build_openai_hosted_adapter",
    "fetch_model_description",
    "hosted_http_failure",
    "openai_model_readiness",
    "request_payload",
]
