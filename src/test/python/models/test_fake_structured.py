"""Tests for the deterministic structured-generation adapter."""

from __future__ import annotations

import asyncio
from uuid import UUID

from orchestwin.models.fake_structured import (
    FakeDeterministicStructuredAdapter,
    create_fake_failure_fixture,
    create_fake_success_fixture,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationStatus,
    create_structured_generation_request,
    create_structured_json_schema,
)


def _identity(*, provider_id: str = "fake-local-evaluator") -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id=provider_id,
        runtime_id="fake-structured-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="c" * 64,
        adapter_id=None,
        adapter_sha256=None,
    )


def _request(task_id: str = "bench-en-001"):
    return create_structured_generation_request(
        request_id=UUID("00000000-0000-4000-8000-000000115001"),
        task_id=task_id,
        expected_identity=_identity(),
        output_schema=create_structured_json_schema(
            schema_id="evaluator-output",
            version_number=1,
            schema_payload={"type": "object"},
        ),
        system_instruction="Return only the requested structured response.",
        input_payload={"scenario": "Correct a validation error."},
        allowed_evidence_refs=("REQ-001",),
        prompt_version_ref="ut-eval-v5",
        temperature=0.0,
        max_output_tokens=512,
        timeout_seconds=30,
    )


def test_fake_adapter_returns_repeatable_exact_fixture() -> None:
    request = _request()
    adapter = FakeDeterministicStructuredAdapter(
        identity=_identity(),
        fixtures=(
            create_fake_success_fixture(
                task_id=request.task_id,
                payload={"findings": [], "abstained": True},
                expected_request_hash=request.content_hash,
                input_tokens=100,
                output_tokens=20,
                latency_milliseconds=5,
            ),
        ),
    )

    first = asyncio.run(adapter.generate(request))
    second = asyncio.run(adapter.generate(request))

    assert first == second
    assert first.status is StructuredGenerationStatus.SUCCEEDED
    assert first.success is not None
    assert first.success.actual_identity == request.expected_identity
    assert first.content_hash == second.content_hash


def test_fake_adapter_rejects_identity_and_request_drift() -> None:
    request = _request()
    adapter = FakeDeterministicStructuredAdapter(
        identity=_identity(),
        fixtures=(
            create_fake_success_fixture(
                task_id=request.task_id,
                payload={"findings": [], "abstained": True},
                expected_request_hash=request.content_hash,
            ),
        ),
    )

    identity_request = create_structured_generation_request(
        request_id=request.request_id,
        task_id=request.task_id,
        expected_identity=_identity(provider_id="other"),
        output_schema=request.output_schema,
        system_instruction=request.system_instruction,
        input_payload={"scenario": "Correct a validation error."},
        allowed_evidence_refs=request.allowed_evidence_refs,
        prompt_version_ref=request.prompt_version_ref,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        timeout_seconds=request.timeout_seconds,
    )
    identity_result = asyncio.run(adapter.generate(identity_request))
    changed_request = create_structured_generation_request(
        request_id=request.request_id,
        task_id=request.task_id,
        expected_identity=request.expected_identity,
        output_schema=request.output_schema,
        system_instruction=request.system_instruction,
        input_payload={"scenario": "A changed scenario."},
        allowed_evidence_refs=request.allowed_evidence_refs,
        prompt_version_ref=request.prompt_version_ref,
        temperature=request.temperature,
        max_output_tokens=request.max_output_tokens,
        timeout_seconds=request.timeout_seconds,
    )
    drift_result = asyncio.run(adapter.generate(changed_request))

    assert identity_result.failure is not None
    assert identity_result.failure.code is StructuredGenerationFailureCode.IDENTITY_MISMATCH
    assert drift_result.failure is not None
    assert drift_result.failure.code is StructuredGenerationFailureCode.INVALID_REQUEST


def test_fake_adapter_returns_typed_missing_and_configured_failures() -> None:
    adapter = FakeDeterministicStructuredAdapter(
        identity=_identity(),
        fixtures=(
            create_fake_failure_fixture(
                task_id="bench-en-001",
                code=StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
                message="The simulated endpoint is offline.",
                retryable=True,
            ),
        ),
    )

    configured = asyncio.run(adapter.generate(_request()))
    missing = asyncio.run(adapter.generate(_request("bench-it-002")))

    assert configured.failure is not None and configured.failure.retryable is True
    assert missing.failure is not None
    assert missing.failure.code is StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
