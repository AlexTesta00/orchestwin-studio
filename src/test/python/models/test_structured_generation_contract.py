"""Tests for provider-independent structured generation contracts."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationStatus,
    StructuredGenerationUsage,
    create_structured_generation_request,
    create_structured_generation_success,
    create_structured_json_schema,
    failed_structured_generation_result,
    successful_structured_generation_result,
)


def _identity(*, adapter: bool = False) -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="local-evaluator",
        runtime_id="openai-compatible-local-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="c" * 64,
        adapter_id="ut-evaluator-v1" if adapter else None,
        adapter_sha256="d" * 64 if adapter else None,
    )


def _request():
    schema = create_structured_json_schema(
        schema_id="synthetic-finding-envelope",
        version_number=1,
        schema_payload={
            "type": "object",
            "required": ["findings", "abstained"],
            "properties": {
                "findings": {"type": "array"},
                "abstained": {"type": "boolean"},
            },
        },
    )
    return create_structured_generation_request(
        request_id=UUID("00000000-0000-4000-8000-000000114001"),
        task_id="benchmark-en-001",
        expected_identity=_identity(adapter=True),
        output_schema=schema,
        system_instruction="Return only the required structured evaluator response.",
        input_payload={"scenario": "Recover from an invalid value."},
        allowed_evidence_refs=("REQ-002", "REQ-001"),
        prompt_version_ref="ut-eval-v5",
        temperature=0.0,
        max_output_tokens=1_024,
        timeout_seconds=60,
    )


def test_request_is_canonical_content_addressed_and_provider_neutral() -> None:
    request = _request()

    assert request.allowed_evidence_refs == ("REQ-001", "REQ-002")
    assert request.input_payload_json == '{"scenario":"Recover from an invalid value."}'
    assert len(request.content_hash) == 64
    assert request.expected_identity.adapter_id == "ut-evaluator-v1"


def test_success_and_failure_envelopes_are_exclusive() -> None:
    success = create_structured_generation_success(
        payload={"findings": [], "abstained": True},
        actual_identity=_identity(adapter=True),
        usage=StructuredGenerationUsage(
            input_tokens=120,
            output_tokens=32,
            latency_milliseconds=48,
        ),
        finish_reason=StructuredGenerationFinishReason.STOP,
        provider_request_id="local-request-001",
    )
    successful = successful_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
        success=success,
    )
    failed = failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        code=StructuredGenerationFailureCode.TIMEOUT,
        message="The local model endpoint exceeded the configured timeout.",
        retryable=True,
    )

    assert successful.status is StructuredGenerationStatus.SUCCEEDED
    assert successful.failure is None
    assert failed.status is StructuredGenerationStatus.FAILED
    assert failed.success is None
    assert failed.failure is not None and failed.failure.retryable is True


def test_request_hash_and_adapter_identity_reject_silent_changes() -> None:
    request = _request()

    with pytest.raises(ValueError, match="content hash is inconsistent"):
        replace(request, max_output_tokens=2_048)

    with pytest.raises(ValueError, match="both be present"):
        replace(_identity(), adapter_id="ut-evaluator-v1")


def test_schema_and_payload_must_be_canonical_json_objects() -> None:
    request = _request()

    with pytest.raises(ValueError, match="canonical JSON"):
        replace(request, input_payload_json='{ "scenario": "changed" }')


def test_usage_rejects_negative_accounting_values() -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        StructuredGenerationUsage(
            input_tokens=-1,
            output_tokens=0,
            latency_milliseconds=0,
        )
