"""Strict OpenAI-compatible adapter for a locally served structured evaluator."""

from __future__ import annotations

import asyncio
import json
import socket
import time
from dataclasses import dataclass
from typing import Final, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationPort,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    normalize_required_text,
    validate_positive_integer,
)

_DEFAULT_COMPLETION_PATH: Final = "/v1/chat/completions"
_MAX_RESPONSE_BYTES: Final = 4_000_000
_MAX_IDENTIFIER_LENGTH: Final = 256


class OpenAICompatibleTransportError(RuntimeError):
    """Network or operating-system failure at the HTTP adapter boundary."""


class OpenAICompatibleTimeoutError(OpenAICompatibleTransportError):
    """Timeout raised before a valid HTTP response is available."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleHttpResponse:
    """Minimal transport response independent from an HTTP client library."""

    status_code: int
    body: bytes
    elapsed_milliseconds: int

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not 100 <= self.status_code <= 599:
            raise ValueError("HTTP response status code must be between 100 and 599")
        if not isinstance(self.body, bytes):
            raise ValueError("HTTP response body must use bytes")
        if len(self.body) > _MAX_RESPONSE_BYTES:
            raise ValueError("HTTP response exceeds the configured safety limit")
        if (
            isinstance(self.elapsed_milliseconds, bool)
            or not isinstance(self.elapsed_milliseconds, int)
            or self.elapsed_milliseconds < 0
        ):
            raise ValueError("HTTP response latency must be a non-negative integer")


class OpenAICompatibleHttpTransport(Protocol):
    """Injectable asynchronous JSON transport used by the local model adapter."""

    async def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> OpenAICompatibleHttpResponse: ...


@dataclass(frozen=True, slots=True)
class OpenAICompatibleLocalConfig:
    """Non-secret configuration for one exact local OpenAI-compatible endpoint."""

    base_url: str
    model_name: str
    expected_identity: ModelRuntimeIdentity
    completion_path: str = _DEFAULT_COMPLETION_PATH
    allow_non_loopback: bool = False

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("local model base URL must use HTTP or HTTPS with a hostname")
        if parsed.query or parsed.fragment:
            raise ValueError("local model base URL cannot contain a query or fragment")
        if not self.allow_non_loopback and not _is_loopback_host(parsed.hostname):
            raise ValueError("non-loopback model endpoints require explicit authorization")
        if self.base_url.endswith("/"):
            raise ValueError("local model base URL must not end with a slash")
        if not self.completion_path.startswith("/") or "?" in self.completion_path:
            raise ValueError("local model completion path must be an absolute path")
        if "#" in self.completion_path:
            raise ValueError("local model completion path cannot contain a fragment")
        if (
            normalize_required_text(
                self.model_name,
                label="local model name",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            != self.model_name
        ):
            raise ValueError("local model name must be normalized")

    @property
    def completion_url(self) -> str:
        return f"{self.base_url}{self.completion_path}"


class UrllibOpenAICompatibleTransport:
    """Small standard-library transport; tests should inject a deterministic fake."""

    async def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> OpenAICompatibleHttpResponse:
        validate_positive_integer(timeout_seconds, label="local model HTTP timeout")
        return await asyncio.to_thread(
            self._post_json_sync,
            url=url,
            payload=payload,
            headers=headers,
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    def _post_json_sync(
        *,
        url: str,
        payload: dict[str, object],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> OpenAICompatibleHttpResponse:
        body = canonical_json(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read(_MAX_RESPONSE_BYTES + 1)
                status_code = int(response.status)
        except HTTPError as error:
            response_body = error.read(_MAX_RESPONSE_BYTES + 1)
            status_code = int(error.code)
        except TimeoutError as error:
            raise OpenAICompatibleTimeoutError("local model request timed out") from error
        except URLError as error:
            if isinstance(error.reason, (TimeoutError, socket.timeout)):
                raise OpenAICompatibleTimeoutError("local model request timed out") from error
            raise OpenAICompatibleTransportError("local model endpoint is unavailable") from error
        except OSError as error:
            raise OpenAICompatibleTransportError(
                "local model transport failed before receiving a response"
            ) from error
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise OpenAICompatibleTransportError("local model response exceeded the size limit")
        elapsed = max(0, round((time.perf_counter() - started) * 1_000))
        return OpenAICompatibleHttpResponse(
            status_code=status_code,
            body=response_body,
            elapsed_milliseconds=elapsed,
        )


class OpenAICompatibleLocalStructuredAdapter(StructuredGenerationPort):
    """Strict local adapter that rejects identity drift and silent base-model fallback."""

    def __init__(
        self,
        *,
        config: OpenAICompatibleLocalConfig,
        transport: OpenAICompatibleHttpTransport,
        bearer_token: str | None = None,
    ) -> None:
        normalized_token = normalize_optional_text(
            bearer_token,
            label="local model bearer token",
            maximum_length=4_096,
        )
        if normalized_token != bearer_token:
            raise ValueError("local model bearer token must be normalized")
        self._config = config
        self._transport = transport
        self._bearer_token = bearer_token

    @property
    def identity(self) -> ModelRuntimeIdentity:
        return self._config.expected_identity

    async def generate(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        if request.expected_identity != self._config.expected_identity:
            return self._failure(
                StructuredGenerationFailureCode.IDENTITY_MISMATCH,
                "The requested model identity differs from the configured local runtime.",
                retryable=False,
            )
        headers: dict[str, str] = {}
        if self._bearer_token is not None:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        try:
            response = await self._transport.post_json(
                url=self._config.completion_url,
                payload=_request_payload(self._config, request),
                headers=headers,
                timeout_seconds=request.timeout_seconds,
            )
        except OpenAICompatibleTimeoutError:
            return self._failure(
                StructuredGenerationFailureCode.TIMEOUT,
                "The local model request exceeded its timeout.",
                retryable=True,
            )
        except OpenAICompatibleTransportError:
            return self._failure(
                StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
                "The local model endpoint could not be reached.",
                retryable=True,
            )
        if response.status_code >= 400:
            return _http_failure(response.status_code)
        try:
            payload = _parse_response_payload(response.body)
            actual_identity = _parse_runtime_identity(payload.get("model_identity"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
            return self._failure(
                StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR,
                "The local model returned an invalid structured response envelope.",
                retryable=False,
            )
        if actual_identity != request.expected_identity:
            code = (
                StructuredGenerationFailureCode.ADAPTER_NOT_LOADED
                if request.expected_identity.adapter_id is not None
                and actual_identity.adapter_id is None
                else StructuredGenerationFailureCode.IDENTITY_MISMATCH
            )
            return self._failure(
                code,
                "The local runtime did not report the exact requested model identity.",
                retryable=False,
            )
        try:
            output_payload, finish_reason, provider_request_id, usage = _parse_success(
                payload,
                elapsed_milliseconds=response.elapsed_milliseconds,
            )
            success = create_structured_generation_success(
                payload=output_payload,
                actual_identity=actual_identity,
                usage=usage,
                finish_reason=finish_reason,
                provider_request_id=provider_request_id,
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            return self._failure(
                StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR,
                "The local model completion does not satisfy the structured contract.",
                retryable=False,
            )
        return successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            success=success,
        )

    @staticmethod
    def _failure(
        code: StructuredGenerationFailureCode,
        message: str,
        *,
        retryable: bool,
    ) -> StructuredGenerationResult:
        return failed_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            code=code,
            message=message,
            retryable=retryable,
        )


def _request_payload(
    config: OpenAICompatibleLocalConfig,
    request: StructuredGenerationRequest,
) -> dict[str, object]:
    return {
        "model": config.model_name,
        "messages": [
            {"role": "system", "content": request.system_instruction},
            {"role": "user", "content": request.input_payload_json},
        ],
        "temperature": float(request.temperature),
        "max_tokens": request.max_output_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": request.output_schema.schema_id,
                "strict": True,
                "schema": json.loads(request.output_schema.canonical_schema_json),
            },
        },
        "metadata": {
            "orchestwin_request_id": str(request.request_id),
            "orchestwin_request_hash": request.content_hash,
            "expected_model_identity": request.expected_identity.to_snapshot(),
        },
    }


def _parse_response_payload(body: bytes) -> dict[str, object]:
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("completion response must be an object")
    return parsed


def _parse_runtime_identity(value: object) -> ModelRuntimeIdentity:
    if not isinstance(value, dict):
        raise ValueError("model identity is required")
    return ModelRuntimeIdentity(
        provider_id=_required_string(value, "provider_id"),
        runtime_id=_required_string(value, "runtime_id"),
        base_model_repository=_required_string(value, "base_model_repository"),
        base_model_revision=_required_string(value, "base_model_revision"),
        tokenizer_revision=_required_string(value, "tokenizer_revision"),
        configuration_sha256=_required_string(value, "configuration_sha256"),
        adapter_id=_optional_string(value, "adapter_id"),
        adapter_sha256=_optional_string(value, "adapter_sha256"),
    )


def _parse_success(
    payload: dict[str, object],
    *,
    elapsed_milliseconds: int,
) -> tuple[
    dict[str, object],
    StructuredGenerationFinishReason,
    str | None,
    StructuredGenerationUsage,
]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("exactly one completion choice is required")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("completion choice must be an object")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("completion message must be an object")
    content = message.get("content")
    output_payload = json.loads(content) if isinstance(content, str) else content
    if not isinstance(output_payload, dict):
        raise ValueError("completion content must be a JSON object")
    finish_value = choice.get("finish_reason")
    finish_reason = {
        "stop": StructuredGenerationFinishReason.STOP,
        "length": StructuredGenerationFinishReason.LENGTH,
    }.get(finish_value)
    if finish_reason is None:
        raise ValueError("completion finish reason is unsupported")
    usage_value = payload.get("usage")
    if not isinstance(usage_value, dict):
        raise ValueError("completion usage is required")
    usage = StructuredGenerationUsage(
        input_tokens=_non_negative_integer(usage_value, "prompt_tokens"),
        output_tokens=_non_negative_integer(usage_value, "completion_tokens"),
        latency_milliseconds=elapsed_milliseconds,
    )
    provider_request_id = _optional_string(payload, "id")
    return output_payload, finish_reason, provider_request_id, usage


def _required_string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_string(values: dict[str, object], key: str) -> str | None:
    value = values.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string or null")
    return value


def _non_negative_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def _http_failure(status_code: int) -> StructuredGenerationResult:
    if status_code in {401, 403}:
        code = StructuredGenerationFailureCode.AUTHENTICATION_FAILED
        message = "The local model endpoint rejected authentication."
        retryable = False
    elif status_code == 429:
        code = StructuredGenerationFailureCode.RATE_LIMITED
        message = "The local model endpoint is rate limited."
        retryable = True
    elif status_code in {408, 504}:
        code = StructuredGenerationFailureCode.TIMEOUT
        message = "The local model endpoint timed out."
        retryable = True
    elif status_code >= 500:
        code = StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
        message = "The local model endpoint is temporarily unavailable."
        retryable = True
    elif status_code in {400, 404, 409, 413, 422}:
        code = StructuredGenerationFailureCode.INVALID_REQUEST
        message = "The local model endpoint rejected the request."
        retryable = False
    else:
        code = StructuredGenerationFailureCode.PROVIDER_ERROR
        message = "The local model endpoint returned an unexpected error."
        retryable = False
    return failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        code=code,
        message=message,
        retryable=retryable,
        provider_status_code=status_code,
    )


def _is_loopback_host(hostname: str) -> bool:
    normalized = hostname.casefold()
    return normalized == "localhost" or normalized == "::1" or normalized.startswith("127.")
