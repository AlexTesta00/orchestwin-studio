"""Exact model routing and explicit, owner-bound base fallback authorization."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationPort,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationStatus,
    create_structured_generation_request,
    failed_structured_generation_result,
)
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_sha256,
)

_MAX_REASON_LENGTH: Final = 2_000
_FALLBACK_AUDIT_KEY: Final = "orchestwin_explicit_base_fallback"


class ModelFallbackPolicy(StrEnum):
    """Stable fallback modes exposed by the model gateway."""

    FORBID = "FORBID"
    REQUIRE_EXPLICIT_OWNER_AUTHORIZATION = "REQUIRE_EXPLICIT_OWNER_AUTHORIZATION"


@dataclass(frozen=True, slots=True)
class StructuredGenerationRoute:
    """One exact model identity bound to one provider-neutral port."""

    identity: ModelRuntimeIdentity
    provider_kind: StructuredGenerationProviderKind
    port: StructuredGenerationPort


@dataclass(frozen=True, slots=True)
class ExplicitBaseFallbackAuthorization:
    """Owner authorization bound to one failed request and two exact identities."""

    authorization_id: UUID
    owner_user_id: UUID
    failed_request_hash: str
    adapter_identity_hash: str
    base_identity_hash: str
    reason: str
    authorized_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.failed_request_hash, "fallback failed request hash"),
            (self.adapter_identity_hash, "fallback adapter identity hash"),
            (self.base_identity_hash, "fallback base identity hash"),
            (self.content_hash, "fallback authorization content hash"),
        ):
            validate_sha256(value, label=label)
        normalized_reason = normalize_required_text(
            self.reason,
            label="fallback authorization reason",
            maximum_length=_MAX_REASON_LENGTH,
        )
        if normalized_reason != self.reason:
            raise ValueError("fallback authorization reason must be normalized")
        if self.authorized_at.tzinfo is None or self.authorized_at.utcoffset() is None:
            raise ValueError("fallback authorization timestamp must be timezone-aware")
        expected_hash = explicit_base_fallback_authorization_hash(
            authorization_id=self.authorization_id,
            owner_user_id=self.owner_user_id,
            failed_request_hash=self.failed_request_hash,
            adapter_identity_hash=self.adapter_identity_hash,
            base_identity_hash=self.base_identity_hash,
            reason=self.reason,
            authorized_at=self.authorized_at,
        )
        if self.content_hash != expected_hash:
            raise ValueError("fallback authorization content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "authorization_id": str(self.authorization_id),
            "owner_user_id": str(self.owner_user_id),
            "failed_request_hash": self.failed_request_hash,
            "adapter_identity_hash": self.adapter_identity_hash,
            "base_identity_hash": self.base_identity_hash,
            "reason": self.reason,
            "authorized_at": self.authorized_at.isoformat(),
            "content_hash": self.content_hash,
        }


class ExactIdentityStructuredGateway(StructuredGenerationPort):
    """Route only to an exact identity and never substitute another model."""

    def __init__(
        self,
        *,
        routes: tuple[StructuredGenerationRoute, ...],
        fallback_policy: ModelFallbackPolicy = ModelFallbackPolicy.FORBID,
        missing_route_provider_kind: StructuredGenerationProviderKind = (
            StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL
        ),
    ) -> None:
        if not routes:
            raise ValueError("the exact identity gateway requires at least one route")
        route_by_hash: dict[str, StructuredGenerationRoute] = {}
        for route in routes:
            identity_hash = route.identity.content_hash
            if identity_hash in route_by_hash:
                raise ValueError("structured generation route identities must be unique")
            route_by_hash[identity_hash] = route
        self._routes = route_by_hash
        self._fallback_policy = fallback_policy
        self._missing_route_provider_kind = missing_route_provider_kind

    @property
    def fallback_policy(self) -> ModelFallbackPolicy:
        return self._fallback_policy

    async def generate(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        """Execute the exact route or fail without attempting a base-model route."""
        route = self._routes.get(request.expected_identity.content_hash)
        if route is None:
            requires_adapter = request.expected_identity.adapter_id is not None
            return failed_structured_generation_result(
                provider_kind=self._missing_route_provider_kind,
                code=(
                    StructuredGenerationFailureCode.ADAPTER_NOT_LOADED
                    if requires_adapter
                    else StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
                ),
                message=(
                    "The exact adapter identity is not registered; no base-model fallback "
                    "was attempted."
                    if requires_adapter
                    else "The exact base-model identity is not registered."
                ),
                retryable=False,
            )

        result = await route.port.generate(request)
        if result.status is StructuredGenerationStatus.FAILED:
            return result
        success = result.success
        if success is None:
            raise AssertionError("successful structured generation result has no payload")
        if success.actual_identity == request.expected_identity:
            return result
        expected_adapter = request.expected_identity.adapter_id is not None
        actual_adapter = success.actual_identity.adapter_id is not None
        return failed_structured_generation_result(
            provider_kind=route.provider_kind,
            code=(
                StructuredGenerationFailureCode.ADAPTER_NOT_LOADED
                if expected_adapter and not actual_adapter
                else StructuredGenerationFailureCode.IDENTITY_MISMATCH
            ),
            message=(
                "The provider returned the base model while the exact adapter was required; "
                "the response was rejected."
                if expected_adapter and not actual_adapter
                else "The provider returned a model identity different from the requested identity."
            ),
            retryable=False,
        )


def create_explicit_base_fallback_authorization(
    *,
    authorization_id: UUID,
    owner_user_id: UUID,
    failed_request: StructuredGenerationRequest,
    base_identity: ModelRuntimeIdentity,
    reason: str,
    authorized_at: datetime,
) -> ExplicitBaseFallbackAuthorization:
    """Authorize one visible base-model retry after an adapter request failed."""
    _validate_adapter_to_base_identity_pair(
        adapter_identity=failed_request.expected_identity,
        base_identity=base_identity,
    )
    content_hash = explicit_base_fallback_authorization_hash(
        authorization_id=authorization_id,
        owner_user_id=owner_user_id,
        failed_request_hash=failed_request.content_hash,
        adapter_identity_hash=failed_request.expected_identity.content_hash,
        base_identity_hash=base_identity.content_hash,
        reason=reason,
        authorized_at=authorized_at,
    )
    return ExplicitBaseFallbackAuthorization(
        authorization_id=authorization_id,
        owner_user_id=owner_user_id,
        failed_request_hash=failed_request.content_hash,
        adapter_identity_hash=failed_request.expected_identity.content_hash,
        base_identity_hash=base_identity.content_hash,
        reason=reason,
        authorized_at=authorized_at,
        content_hash=content_hash,
    )


def create_explicit_base_fallback_request(
    *,
    request_id: UUID,
    owner_user_id: UUID,
    failed_request: StructuredGenerationRequest,
    base_identity: ModelRuntimeIdentity,
    authorization: ExplicitBaseFallbackAuthorization,
) -> StructuredGenerationRequest:
    """Create a new auditable request; this function never executes it automatically."""
    _validate_adapter_to_base_identity_pair(
        adapter_identity=failed_request.expected_identity,
        base_identity=base_identity,
    )
    if owner_user_id != authorization.owner_user_id:
        raise ValueError("fallback authorization does not belong to the requesting owner")
    if authorization.failed_request_hash != failed_request.content_hash:
        raise ValueError("fallback authorization is stale for the failed request")
    if authorization.adapter_identity_hash != failed_request.expected_identity.content_hash:
        raise ValueError("fallback authorization references a different adapter identity")
    if authorization.base_identity_hash != base_identity.content_hash:
        raise ValueError("fallback authorization references a different base identity")

    payload = json.loads(failed_request.input_payload_json)
    if _FALLBACK_AUDIT_KEY in payload:
        raise ValueError("structured input already contains the reserved fallback audit key")
    payload[_FALLBACK_AUDIT_KEY] = {
        "authorization_id": str(authorization.authorization_id),
        "authorization_sha256": authorization.content_hash,
        "failed_request_sha256": failed_request.content_hash,
        "adapter_identity_sha256": authorization.adapter_identity_hash,
        "base_identity_sha256": authorization.base_identity_hash,
        "reason": authorization.reason,
        "authorized_at": authorization.authorized_at.isoformat(),
    }
    return create_structured_generation_request(
        request_id=request_id,
        task_id=failed_request.task_id,
        expected_identity=base_identity,
        output_schema=failed_request.output_schema,
        system_instruction=failed_request.system_instruction,
        input_payload=payload,
        allowed_evidence_refs=failed_request.allowed_evidence_refs,
        prompt_version_ref=failed_request.prompt_version_ref,
        temperature=failed_request.temperature,
        max_output_tokens=failed_request.max_output_tokens,
        timeout_seconds=failed_request.timeout_seconds,
    )


def explicit_base_fallback_authorization_hash(
    *,
    authorization_id: UUID,
    owner_user_id: UUID,
    failed_request_hash: str,
    adapter_identity_hash: str,
    base_identity_hash: str,
    reason: str,
    authorized_at: datetime,
) -> str:
    return snapshot_content_hash(
        {
            "authorization_id": str(authorization_id),
            "owner_user_id": str(owner_user_id),
            "failed_request_hash": failed_request_hash,
            "adapter_identity_hash": adapter_identity_hash,
            "base_identity_hash": base_identity_hash,
            "reason": reason,
            "authorized_at": authorized_at.isoformat(),
        }
    )


def _validate_adapter_to_base_identity_pair(
    *,
    adapter_identity: ModelRuntimeIdentity,
    base_identity: ModelRuntimeIdentity,
) -> None:
    if adapter_identity.adapter_id is None:
        raise ValueError("explicit base fallback requires a failed adapter request")
    if base_identity.adapter_id is not None:
        raise ValueError("explicit base fallback target must not contain an adapter")
    if (
        adapter_identity.provider_id,
        adapter_identity.runtime_id,
        adapter_identity.base_model_repository,
        adapter_identity.base_model_revision,
        adapter_identity.tokenizer_revision,
    ) != (
        base_identity.provider_id,
        base_identity.runtime_id,
        base_identity.base_model_repository,
        base_identity.base_model_revision,
        base_identity.tokenizer_revision,
    ):
        raise ValueError("fallback must use the same provider, runtime, base, and tokenizer")
