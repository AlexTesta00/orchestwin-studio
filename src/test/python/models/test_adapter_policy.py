"""Tests for exact model routing and explicit fallback authorization."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.models.adapter_policy import (
    ExactIdentityStructuredGateway,
    ModelFallbackPolicy,
    StructuredGenerationRoute,
    create_explicit_base_fallback_authorization,
    create_explicit_base_fallback_request,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    create_structured_generation_request,
    create_structured_generation_success,
    create_structured_json_schema,
    successful_structured_generation_result,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000127001")
AUTHORIZATION_ID = UUID("00000000-0000-4000-8000-000000127002")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000127003")
FALLBACK_REQUEST_ID = UUID("00000000-0000-4000-8000-000000127004")
AUTHORIZED_AT = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


def _identity(*, adapter: bool, configuration: str) -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="local-openai",
        runtime_id="local-evaluator-v1",
        base_model_repository="example/small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256=configuration * 64,
        adapter_id="ut-evaluator-v1" if adapter else None,
        adapter_sha256="d" * 64 if adapter else None,
    )


def _request(identity: ModelRuntimeIdentity) -> StructuredGenerationRequest:
    return create_structured_generation_request(
        request_id=REQUEST_ID,
        task_id="user-twin-evaluation",
        expected_identity=identity,
        output_schema=create_structured_json_schema(
            schema_id="user-twin-evaluation",
            version_number=1,
            schema_payload={"type": "object", "required": ["findings"]},
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
class _RecordingPort:
    actual_identity: ModelRuntimeIdentity
    calls: list[StructuredGenerationRequest] = field(default_factory=list)

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResult:
        self.calls.append(request)
        success = create_structured_generation_success(
            payload={"findings": [], "abstained": True},
            actual_identity=self.actual_identity,
            usage=StructuredGenerationUsage(1, 1, 1),
            finish_reason=StructuredGenerationFinishReason.STOP,
            provider_request_id="fixture-request",
        )
        return successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
            success=success,
        )


def test_gateway_routes_only_to_the_exact_adapter_identity() -> None:
    adapter_identity = _identity(adapter=True, configuration="c")
    base_identity = _identity(adapter=False, configuration="e")
    adapter_port = _RecordingPort(adapter_identity)
    base_port = _RecordingPort(base_identity)
    gateway = ExactIdentityStructuredGateway(
        routes=(
            StructuredGenerationRoute(
                adapter_identity,
                StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                adapter_port,
            ),
            StructuredGenerationRoute(
                base_identity,
                StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                base_port,
            ),
        ),
        fallback_policy=ModelFallbackPolicy.REQUIRE_EXPLICIT_OWNER_AUTHORIZATION,
    )

    result = asyncio.run(gateway.generate(_request(adapter_identity)))

    assert result.success is not None
    assert result.success.actual_identity == adapter_identity
    assert len(adapter_port.calls) == 1
    assert base_port.calls == []


def test_missing_adapter_route_fails_without_calling_the_base_route() -> None:
    adapter_identity = _identity(adapter=True, configuration="c")
    base_identity = _identity(adapter=False, configuration="e")
    base_port = _RecordingPort(base_identity)
    gateway = ExactIdentityStructuredGateway(
        routes=(
            StructuredGenerationRoute(
                base_identity,
                StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                base_port,
            ),
        ),
        fallback_policy=ModelFallbackPolicy.REQUIRE_EXPLICIT_OWNER_AUTHORIZATION,
    )

    result = asyncio.run(gateway.generate(_request(adapter_identity)))

    assert result.failure is not None
    assert result.failure.code is StructuredGenerationFailureCode.ADAPTER_NOT_LOADED
    assert "no base-model fallback" in result.failure.message
    assert base_port.calls == []


def test_gateway_rejects_a_provider_that_silently_returns_the_base_model() -> None:
    adapter_identity = _identity(adapter=True, configuration="c")
    base_identity = _identity(adapter=False, configuration="e")
    gateway = ExactIdentityStructuredGateway(
        routes=(
            StructuredGenerationRoute(
                adapter_identity,
                StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                _RecordingPort(base_identity),
            ),
        )
    )

    result = asyncio.run(gateway.generate(_request(adapter_identity)))

    assert result.failure is not None
    assert result.failure.code is StructuredGenerationFailureCode.ADAPTER_NOT_LOADED


def test_explicit_owner_authorization_creates_a_visible_new_base_request() -> None:
    adapter_identity = _identity(adapter=True, configuration="c")
    base_identity = _identity(adapter=False, configuration="e")
    failed_request = _request(adapter_identity)
    authorization = create_explicit_base_fallback_authorization(
        authorization_id=AUTHORIZATION_ID,
        owner_user_id=OWNER_ID,
        failed_request=failed_request,
        base_identity=base_identity,
        reason="Continue the governed evaluation with the exact base model.",
        authorized_at=AUTHORIZED_AT,
    )

    fallback_request = create_explicit_base_fallback_request(
        request_id=FALLBACK_REQUEST_ID,
        owner_user_id=OWNER_ID,
        failed_request=failed_request,
        base_identity=base_identity,
        authorization=authorization,
    )

    payload = json.loads(fallback_request.input_payload_json)
    audit = payload["orchestwin_explicit_base_fallback"]
    assert fallback_request.expected_identity == base_identity
    assert fallback_request.content_hash != failed_request.content_hash
    assert audit["authorization_sha256"] == authorization.content_hash
    assert audit["failed_request_sha256"] == failed_request.content_hash
    assert audit["adapter_identity_sha256"] == adapter_identity.content_hash
    assert audit["base_identity_sha256"] == base_identity.content_hash


def test_fallback_authorization_rejects_forged_scope_and_different_models() -> None:
    adapter_identity = _identity(adapter=True, configuration="c")
    base_identity = _identity(adapter=False, configuration="e")
    failed_request = _request(adapter_identity)
    authorization = create_explicit_base_fallback_authorization(
        authorization_id=AUTHORIZATION_ID,
        owner_user_id=OWNER_ID,
        failed_request=failed_request,
        base_identity=base_identity,
        reason="Run an explicitly authorized base-model retry.",
        authorized_at=AUTHORIZED_AT,
    )

    with pytest.raises(ValueError, match="requesting owner"):
        create_explicit_base_fallback_request(
            request_id=FALLBACK_REQUEST_ID,
            owner_user_id=UUID("00000000-0000-4000-8000-000000127999"),
            failed_request=failed_request,
            base_identity=base_identity,
            authorization=authorization,
        )

    changed_request = create_structured_generation_request(
        request_id=FALLBACK_REQUEST_ID,
        task_id=failed_request.task_id,
        expected_identity=adapter_identity,
        output_schema=failed_request.output_schema,
        system_instruction=failed_request.system_instruction,
        input_payload={"scenario": "A different governed retry."},
        allowed_evidence_refs=failed_request.allowed_evidence_refs,
        prompt_version_ref=failed_request.prompt_version_ref,
        temperature=failed_request.temperature,
        max_output_tokens=failed_request.max_output_tokens,
        timeout_seconds=failed_request.timeout_seconds,
    )
    with pytest.raises(ValueError, match="stale"):
        create_explicit_base_fallback_request(
            request_id=FALLBACK_REQUEST_ID,
            owner_user_id=OWNER_ID,
            failed_request=changed_request,
            base_identity=base_identity,
            authorization=authorization,
        )

    different_base = replace(base_identity, base_model_repository="example/different-model")
    with pytest.raises(ValueError, match="same provider, runtime, base, and tokenizer"):
        create_explicit_base_fallback_authorization(
            authorization_id=AUTHORIZATION_ID,
            owner_user_id=OWNER_ID,
            failed_request=failed_request,
            base_identity=different_base,
            reason="This must fail.",
            authorized_at=AUTHORIZED_AT,
        )
