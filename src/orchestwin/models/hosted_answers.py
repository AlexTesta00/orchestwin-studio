from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Final

from orchestwin.models.hosted_configuration import HostedModelConfiguration, served_model_matches
from orchestwin.models.hosted_schema import (
    HostedSchemaError,
    PrunedAnswer,
    hosted_output_schema,
    shorten_overlong_strings,
    validate_against_schema,
    violation_message,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    StructuredOutputMode,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)

_MAX_IDENTIFIER_LENGTH: Final = 256
_Code = StructuredGenerationFailureCode


def strict_schema(
    request: StructuredGenerationRequest,
    configuration: HostedModelConfiguration,
    mode: StructuredOutputMode,
    kind: StructuredGenerationProviderKind,
) -> StructuredGenerationResult | tuple[dict[str, Any], dict[str, Any] | None]:
    if request.expected_identity != configuration.identity:
        return hosted_failure(
            kind,
            _Code.IDENTITY_MISMATCH,
            "The requested model identity differs from the configured hosted model.",
            mode=mode,
            retryable=False,
        )
    full_schema = json.loads(request.output_schema.canonical_schema_json)
    if mode is not StructuredOutputMode.STRICT:
        return full_schema, None
    try:
        return full_schema, hosted_output_schema(full_schema, kind)
    except HostedSchemaError:
        return hosted_failure(
            kind,
            _Code.INVALID_REQUEST,
            "The output schema cannot be expressed for the hosted model provider.",
            mode=mode,
            retryable=False,
        )


def checked_answer(
    output: dict[str, Any],
    full_schema: dict[str, Any],
    *,
    mode: StructuredOutputMode,
    kind: StructuredGenerationProviderKind,
    identity: ModelRuntimeIdentity,
    usage: StructuredGenerationUsage,
    request_id: object,
    prune: Callable[[object, Mapping[str, Any]], PrunedAnswer | None],
) -> StructuredGenerationResult:
    output, shortened = shorten_overlong_strings(output, full_schema)
    violations = validate_against_schema(output, full_schema)
    if violations and mode is StructuredOutputMode.PROMPTED:
        pruned = prune(output, full_schema)
        if pruned is not None:
            output, violations = pruned.payload, ()
    if violations:
        return hosted_failure(
            kind,
            _Code.RESPONSE_SCHEMA_ERROR,
            violation_message(violations),
            mode=mode,
            retryable=False,
            usage=usage,
            shortened_paths=shortened,
        )
    try:
        success = create_structured_generation_success(
            payload=output,
            actual_identity=identity,
            usage=usage,
            finish_reason=StructuredGenerationFinishReason.STOP,
            provider_request_id=_provider_request_id(request_id),
        )
    except (ValueError, TypeError):
        return hosted_failure(
            kind,
            _Code.RESPONSE_SCHEMA_ERROR,
            "The hosted model answer does not satisfy the structured contract.",
            mode=mode,
            retryable=False,
            usage=usage,
            shortened_paths=shortened,
        )
    return successful_structured_generation_result(
        provider_kind=kind, success=success, output_mode=mode, shortened_paths=shortened
    )


def hosted_failure(
    kind: StructuredGenerationProviderKind,
    code: StructuredGenerationFailureCode,
    message: str,
    *,
    mode: StructuredOutputMode,
    retryable: bool,
    status: int | None = None,
    usage: StructuredGenerationUsage | None = None,
    shortened_paths: tuple[str, ...] = (),
) -> StructuredGenerationResult:
    return failed_structured_generation_result(
        provider_kind=kind,
        code=code,
        message=message,
        retryable=retryable,
        provider_status_code=status,
        usage=usage,
        output_mode=mode,
        shortened_paths=shortened_paths,
    )


def served_identity(
    configuration: HostedModelConfiguration, served: object
) -> ModelRuntimeIdentity:
    if not isinstance(served, str) or not served:
        raise ValueError("served model is required")
    if served_model_matches(configuration.model, served):
        return configuration.identity
    return replace(configuration.identity, base_model_revision=served)


def count(values: Mapping[str, object], key: str, *, required: bool) -> int:
    value = values.get(key)
    if value is None and not required:
        return 0
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def elapsed(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _provider_request_id(value: object) -> str | None:
    if (
        isinstance(value, str)
        and value
        and len(value) <= _MAX_IDENTIFIER_LENGTH
        and not any(character.isspace() for character in value)
    ):
        return value
    return None
