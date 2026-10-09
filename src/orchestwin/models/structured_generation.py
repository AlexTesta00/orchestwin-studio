"""Provider-independent contracts for exact-identity structured model generation."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

STRUCTURED_GENERATION_SCHEMA_VERSION: Final = 1
MAX_ATTACHMENTS: Final = 4
MAX_ATTACHMENT_BYTES: Final = 5 * 1024 * 1024
ATTACHMENT_MEDIA_TYPES: Final = frozenset({"image/png", "image/jpeg"})
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_TEXT_LENGTH: Final = 20_000
_MAX_PAYLOAD_LENGTH: Final = 1_000_000
_ATTACHMENT_NAME: Final = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class StructuredGenerationProviderKind(StrEnum):
    """Stable provider categories without SDK-specific public types."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    OPENAI_COMPATIBLE_LOCAL = "OPENAI_COMPATIBLE_LOCAL"
    UNSLOTH_DIRECT_LOCAL = "UNSLOTH_DIRECT_LOCAL"
    ANTHROPIC_HOSTED = "ANTHROPIC_HOSTED"
    OPENAI_COMPATIBLE_HOSTED = "OPENAI_COMPATIBLE_HOSTED"
    CLAUDE_CODE_CLI = "CLAUDE_CODE_CLI"


class StructuredGenerationStatus(StrEnum):
    """Stable result shape for successful and failed generation attempts."""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class StructuredOutputMode(StrEnum):
    STRICT = "STRICT"
    PROMPTED = "PROMPTED"


_HOSTED_PROVIDER_KINDS: Final = frozenset(
    {
        StructuredGenerationProviderKind.ANTHROPIC_HOSTED,
        StructuredGenerationProviderKind.OPENAI_COMPATIBLE_HOSTED,
        StructuredGenerationProviderKind.CLAUDE_CODE_CLI,
    }
)


class StructuredGenerationFinishReason(StrEnum):
    """Normalized successful provider termination reasons."""

    STOP = "STOP"
    LENGTH = "LENGTH"


class StructuredGenerationFailureCode(StrEnum):
    """Expected failures exposed by structured model adapters."""

    INVALID_REQUEST = "INVALID_REQUEST"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    RESPONSE_SCHEMA_ERROR = "RESPONSE_SCHEMA_ERROR"
    INCOMPLETE_OUTPUT = "INCOMPLETE_OUTPUT"
    CONTEXT_BUDGET_EXCEEDED = "CONTEXT_BUDGET_EXCEEDED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    ADAPTER_NOT_LOADED = "ADAPTER_NOT_LOADED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_REFUSED = "PROVIDER_REFUSED"
    GENERATION_BUDGET_EXCEEDED = "GENERATION_BUDGET_EXCEEDED"


@dataclass(frozen=True, slots=True)
class StructuredJsonSchema:
    """Canonical JSON Schema identity requested from every provider."""

    schema_id: str
    version_number: int
    canonical_schema_json: str
    content_hash: str

    def __post_init__(self) -> None:
        _require_normalized_identifier(self.schema_id, label="structured schema ID")
        validate_positive_integer(self.version_number, label="structured schema version")
        _require_canonical_json_object(
            self.canonical_schema_json,
            label="structured schema JSON",
        )
        validate_sha256(self.content_hash, label="structured schema content hash")
        expected = snapshot_content_hash(
            {
                "schema_id": self.schema_id,
                "version_number": self.version_number,
                "schema": json.loads(self.canonical_schema_json),
            }
        )
        if self.content_hash != expected:
            raise ValueError("structured schema content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_id": self.schema_id,
            "version_number": self.version_number,
            "canonical_schema_json": self.canonical_schema_json,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ModelRuntimeIdentity:
    """Exact base, tokenizer, optional adapter, and runtime configuration identity."""

    provider_id: str
    runtime_id: str
    base_model_repository: str
    base_model_revision: str
    tokenizer_revision: str
    configuration_sha256: str
    adapter_id: str | None = None
    adapter_sha256: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_id, "model provider ID"),
            (self.runtime_id, "model runtime ID"),
            (self.base_model_repository, "base model repository"),
            (self.base_model_revision, "base model revision"),
            (self.tokenizer_revision, "tokenizer revision"),
        ):
            _require_normalized_identifier(value, label=label)
        validate_sha256(self.configuration_sha256, label="model configuration digest")
        adapter_fields = (self.adapter_id, self.adapter_sha256)
        if (adapter_fields[0] is None) != (adapter_fields[1] is None):
            raise ValueError("adapter ID and digest must either both be present or both be absent")
        if self.adapter_id is not None:
            _require_normalized_identifier(self.adapter_id, label="model adapter ID")
            validate_sha256(self.adapter_sha256 or "", label="model adapter digest")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "runtime_id": self.runtime_id,
            "base_model_repository": self.base_model_repository,
            "base_model_revision": self.base_model_revision,
            "tokenizer_revision": self.tokenizer_revision,
            "configuration_sha256": self.configuration_sha256,
            "adapter_id": self.adapter_id,
            "adapter_sha256": self.adapter_sha256,
        }


@dataclass(frozen=True, slots=True)
class GenerationAttachment:
    name: str
    media_type: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _ATTACHMENT_NAME.fullmatch(self.name) is None:
            raise ValueError("generation attachment name is invalid")
        if not isinstance(self.media_type, str) or self.media_type not in ATTACHMENT_MEDIA_TYPES:
            raise ValueError("generation attachment media type is not supported")
        if not isinstance(self.content, bytes):
            raise ValueError("generation attachment content must be bytes")
        if not 0 < len(self.content) <= MAX_ATTACHMENT_BYTES:
            raise ValueError("generation attachment content has an invalid size")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()

    @property
    def byte_size(self) -> int:
        return len(self.content)

    def reference(self) -> dict[str, object]:
        return {
            "name": self.name,
            "media_type": self.media_type,
            "sha256": self.sha256,
            "byte_size": self.byte_size,
        }


@dataclass(frozen=True, slots=True)
class StructuredGenerationRequest:
    """Canonical structured request containing no provider-specific message objects."""

    request_id: UUID
    task_id: str
    expected_identity: ModelRuntimeIdentity
    output_schema: StructuredJsonSchema
    system_instruction: str
    input_payload_json: str
    allowed_evidence_refs: tuple[str, ...]
    prompt_version_ref: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: int
    content_hash: str
    schema_version: int = STRUCTURED_GENERATION_SCHEMA_VERSION
    attachments: tuple[GenerationAttachment, ...] = ()

    def __post_init__(self) -> None:
        _require_normalized_identifier(self.task_id, label="structured generation task ID")
        _require_normalized_text(
            self.system_instruction,
            label="structured generation system instruction",
        )
        _require_canonical_json_object(
            self.input_payload_json,
            label="structured generation input payload",
        )
        normalized_refs = normalize_text_items(
            self.allowed_evidence_refs,
            label="structured generation allowed evidence references",
            maximum_item_length=_MAX_IDENTIFIER_LENGTH,
            require_items=False,
        )
        if self.allowed_evidence_refs != tuple(sorted(normalized_refs)):
            raise ValueError(
                "structured generation evidence references must be canonical and unique"
            )
        _require_normalized_identifier(
            self.prompt_version_ref,
            label="structured generation prompt version",
        )
        if isinstance(self.temperature, bool) or not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("structured generation temperature must be between zero and two")
        validate_positive_integer(
            self.max_output_tokens,
            label="structured generation maximum output tokens",
        )
        validate_positive_integer(
            self.timeout_seconds,
            label="structured generation timeout seconds",
        )
        if self.schema_version != STRUCTURED_GENERATION_SCHEMA_VERSION:
            raise ValueError("unsupported structured generation schema version")
        _require_attachments(self.attachments)
        validate_sha256(self.content_hash, label="structured generation request content hash")
        if self.content_hash != structured_generation_request_hash(
            request_id=self.request_id,
            task_id=self.task_id,
            expected_identity=self.expected_identity,
            output_schema=self.output_schema,
            system_instruction=self.system_instruction,
            input_payload_json=self.input_payload_json,
            allowed_evidence_refs=self.allowed_evidence_refs,
            prompt_version_ref=self.prompt_version_ref,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            timeout_seconds=self.timeout_seconds,
            schema_version=self.schema_version,
            attachments=self.attachments,
        ):
            raise ValueError("structured generation request content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "schema_version": self.schema_version,
            "request_id": str(self.request_id),
            "task_id": self.task_id,
            "expected_identity": self.expected_identity.to_snapshot(),
            "output_schema": self.output_schema.to_snapshot(),
            "system_instruction": self.system_instruction,
            "input_payload_json": self.input_payload_json,
            "allowed_evidence_refs": list(self.allowed_evidence_refs),
            "prompt_version_ref": self.prompt_version_ref,
            "temperature": float(self.temperature),
            "max_output_tokens": self.max_output_tokens,
            "timeout_seconds": self.timeout_seconds,
            "content_hash": self.content_hash,
        }
        if self.attachments:
            snapshot["attachments"] = [item.reference() for item in self.attachments]
        return snapshot


@dataclass(frozen=True, slots=True)
class StructuredGenerationUsage:
    """Provider-neutral token, latency, and optional resource accounting."""

    input_tokens: int
    output_tokens: int
    latency_milliseconds: int
    cache_read_input_tokens: int = 0
    cache_write_input_tokens: int = 0
    cost_microusd: int | None = None
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        for value, label in (
            (self.input_tokens, "structured generation input tokens"),
            (self.output_tokens, "structured generation output tokens"),
            (self.latency_milliseconds, "structured generation latency"),
            (self.cache_read_input_tokens, "structured generation cache read tokens"),
            (self.cache_write_input_tokens, "structured generation cache write tokens"),
            (
                0 if self.cost_microusd is None else self.cost_microusd,
                "structured generation cost",
            ),
            (self.reasoning_tokens, "structured generation reasoning tokens"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_milliseconds": self.latency_milliseconds,
        }
        for key, value in (
            ("cache_read_input_tokens", self.cache_read_input_tokens),
            ("cache_write_input_tokens", self.cache_write_input_tokens),
            ("cost_microusd", self.cost_microusd),
            ("reasoning_tokens", self.reasoning_tokens),
        ):
            if value:
                snapshot[key] = value
        return snapshot


@dataclass(frozen=True, slots=True)
class StructuredGenerationSuccess:
    """Canonical successful structured output with actual runtime identity."""

    payload_json: str
    actual_identity: ModelRuntimeIdentity
    usage: StructuredGenerationUsage
    finish_reason: StructuredGenerationFinishReason
    provider_request_id: str | None
    content_hash: str

    def __post_init__(self) -> None:
        _require_canonical_json_object(
            self.payload_json,
            label="structured generation output payload",
        )
        normalized_request_id = normalize_optional_text(
            self.provider_request_id,
            label="provider request ID",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        if normalized_request_id != self.provider_request_id:
            raise ValueError("provider request ID must be normalized")
        validate_sha256(self.content_hash, label="structured generation success content hash")
        expected = snapshot_content_hash(
            {
                "payload": json.loads(self.payload_json),
                "actual_identity": self.actual_identity.to_snapshot(),
                "usage": self.usage.to_snapshot(),
                "finish_reason": self.finish_reason.value,
                "provider_request_id": self.provider_request_id,
            }
        )
        if self.content_hash != expected:
            raise ValueError("structured generation success content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "payload_json": self.payload_json,
            "actual_identity": self.actual_identity.to_snapshot(),
            "usage": self.usage.to_snapshot(),
            "finish_reason": self.finish_reason.value,
            "provider_request_id": self.provider_request_id,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class StructuredGenerationFailure:
    """Typed provider failure that never masquerades as a successful empty response."""

    code: StructuredGenerationFailureCode
    message: str
    retryable: bool
    provider_status_code: int | None = None
    usage: StructuredGenerationUsage | None = None

    def __post_init__(self) -> None:
        _require_normalized_text(self.message, label="structured generation failure message")
        if self.provider_status_code is not None and (
            isinstance(self.provider_status_code, bool) or self.provider_status_code < 100
        ):
            raise ValueError("provider status code must be a valid HTTP-style status")
        if self.usage is not None and not isinstance(self.usage, StructuredGenerationUsage):
            raise ValueError("structured generation failure usage has an invalid type")

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "code": self.code.value,
            "message": self.message,
            "retryable": self.retryable,
            "provider_status_code": self.provider_status_code,
        }
        if self.usage is not None:
            snapshot["usage"] = self.usage.to_snapshot()
        return snapshot


@dataclass(frozen=True, slots=True)
class StructuredGenerationResult:
    """Exclusive success/failure envelope returned by every structured adapter."""

    provider_kind: StructuredGenerationProviderKind
    status: StructuredGenerationStatus
    success: StructuredGenerationSuccess | None
    failure: StructuredGenerationFailure | None
    output_mode: StructuredOutputMode | None = None

    def __post_init__(self) -> None:
        succeeded = self.status is StructuredGenerationStatus.SUCCEEDED
        if succeeded != (self.success is not None):
            raise ValueError("structured generation success shape is inconsistent")
        if succeeded == (self.failure is not None):
            raise ValueError("structured generation failure shape is inconsistent")
        if self.output_mode is not None and (
            not isinstance(self.output_mode, StructuredOutputMode)
            or self.provider_kind not in _HOSTED_PROVIDER_KINDS
        ):
            raise ValueError("an output mode is recorded only for hosted results")

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())

    def to_snapshot(self) -> dict[str, object]:
        snapshot: dict[str, object] = {
            "provider_kind": self.provider_kind.value,
            "status": self.status.value,
            "success": None if self.success is None else self.success.to_snapshot(),
            "failure": None if self.failure is None else self.failure.to_snapshot(),
        }
        if self.output_mode is not None:
            snapshot["output_mode"] = self.output_mode.value
        return snapshot


@runtime_checkable
class StructuredGenerationPort(Protocol):
    """Provider-independent asynchronous structured-generation boundary."""

    async def generate(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult: ...


def create_structured_json_schema(
    *,
    schema_id: str,
    version_number: int,
    schema_payload: dict[str, object],
) -> StructuredJsonSchema:
    """Canonicalize one repository-owned output schema."""
    canonical_schema_json = canonical_json(schema_payload)
    content_hash = snapshot_content_hash(
        {
            "schema_id": schema_id,
            "version_number": version_number,
            "schema": schema_payload,
        }
    )
    return StructuredJsonSchema(
        schema_id=schema_id,
        version_number=version_number,
        canonical_schema_json=canonical_schema_json,
        content_hash=content_hash,
    )


def create_structured_generation_request(
    *,
    request_id: UUID,
    task_id: str,
    expected_identity: ModelRuntimeIdentity,
    output_schema: StructuredJsonSchema,
    system_instruction: str,
    input_payload: dict[str, object],
    allowed_evidence_refs: tuple[str, ...],
    prompt_version_ref: str,
    temperature: float,
    max_output_tokens: int,
    timeout_seconds: int,
    attachments: Sequence[GenerationAttachment] = (),
) -> StructuredGenerationRequest:
    """Canonicalize and content-address a provider-neutral request."""
    canonical_input = canonical_json(input_payload)
    canonical_refs = tuple(sorted(set(allowed_evidence_refs)))
    attached = tuple(attachments)
    _require_attachments(attached)
    content_hash = structured_generation_request_hash(
        request_id=request_id,
        task_id=task_id,
        expected_identity=expected_identity,
        output_schema=output_schema,
        system_instruction=system_instruction,
        input_payload_json=canonical_input,
        allowed_evidence_refs=canonical_refs,
        prompt_version_ref=prompt_version_ref,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        schema_version=STRUCTURED_GENERATION_SCHEMA_VERSION,
        attachments=attached,
    )
    return StructuredGenerationRequest(
        request_id=request_id,
        task_id=task_id,
        expected_identity=expected_identity,
        output_schema=output_schema,
        system_instruction=system_instruction,
        input_payload_json=canonical_input,
        allowed_evidence_refs=canonical_refs,
        prompt_version_ref=prompt_version_ref,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        timeout_seconds=timeout_seconds,
        content_hash=content_hash,
        attachments=attached,
    )


def create_structured_generation_success(
    *,
    payload: dict[str, object],
    actual_identity: ModelRuntimeIdentity,
    usage: StructuredGenerationUsage,
    finish_reason: StructuredGenerationFinishReason,
    provider_request_id: str | None,
) -> StructuredGenerationSuccess:
    """Create one canonical successful provider output."""
    payload_json = canonical_json(payload)
    content_hash = snapshot_content_hash(
        {
            "payload": payload,
            "actual_identity": actual_identity.to_snapshot(),
            "usage": usage.to_snapshot(),
            "finish_reason": finish_reason.value,
            "provider_request_id": provider_request_id,
        }
    )
    return StructuredGenerationSuccess(
        payload_json=payload_json,
        actual_identity=actual_identity,
        usage=usage,
        finish_reason=finish_reason,
        provider_request_id=provider_request_id,
        content_hash=content_hash,
    )


def successful_structured_generation_result(
    *,
    provider_kind: StructuredGenerationProviderKind,
    success: StructuredGenerationSuccess,
    output_mode: StructuredOutputMode | None = None,
) -> StructuredGenerationResult:
    return StructuredGenerationResult(
        provider_kind=provider_kind,
        status=StructuredGenerationStatus.SUCCEEDED,
        success=success,
        failure=None,
        output_mode=output_mode,
    )


def failed_structured_generation_result(
    *,
    provider_kind: StructuredGenerationProviderKind,
    code: StructuredGenerationFailureCode,
    message: str,
    retryable: bool,
    provider_status_code: int | None = None,
    usage: StructuredGenerationUsage | None = None,
    output_mode: StructuredOutputMode | None = None,
) -> StructuredGenerationResult:
    return StructuredGenerationResult(
        provider_kind=provider_kind,
        status=StructuredGenerationStatus.FAILED,
        output_mode=output_mode,
        success=None,
        failure=StructuredGenerationFailure(
            code=code,
            message=message,
            retryable=retryable,
            provider_status_code=provider_status_code,
            usage=usage,
        ),
    )


def structured_generation_request_hash(
    *,
    request_id: UUID,
    task_id: str,
    expected_identity: ModelRuntimeIdentity,
    output_schema: StructuredJsonSchema,
    system_instruction: str,
    input_payload_json: str,
    allowed_evidence_refs: tuple[str, ...],
    prompt_version_ref: str,
    temperature: float,
    max_output_tokens: int,
    timeout_seconds: int,
    schema_version: int,
    attachments: Sequence[GenerationAttachment] = (),
) -> str:
    material: dict[str, object] = {
        "schema_version": schema_version,
        "request_id": str(request_id),
        "task_id": task_id,
        "expected_identity": expected_identity.to_snapshot(),
        "output_schema": output_schema.to_snapshot(),
        "system_instruction": system_instruction,
        "input_payload": json.loads(input_payload_json),
        "allowed_evidence_refs": list(allowed_evidence_refs),
        "prompt_version_ref": prompt_version_ref,
        "temperature": float(temperature),
        "max_output_tokens": max_output_tokens,
        "timeout_seconds": timeout_seconds,
    }
    if attachments:
        material["attachments"] = [item.reference() for item in attachments]
    return snapshot_content_hash(material)


def _require_attachments(value: object) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, GenerationAttachment) for item in value
    ):
        raise ValueError("structured generation attachments must be a tuple of attachments")
    if len(value) > MAX_ATTACHMENTS:
        raise ValueError(f"structured generation accepts at most {MAX_ATTACHMENTS} attachments")
    if len({item.name for item in value}) != len(value):
        raise ValueError("structured generation attachment names must be unique")


def _require_canonical_json_object(value: str, *, label: str) -> None:
    if not value or len(value) > _MAX_PAYLOAD_LENGTH:
        raise ValueError(f"{label} has an invalid length")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError(f"{label} must be valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must be a JSON object")
    if canonical_json(parsed) != value:
        raise ValueError(f"{label} must use canonical JSON serialization")


def _require_normalized_identifier(value: str, *, label: str) -> None:
    if (
        normalize_required_text(
            value,
            label=label,
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        != value
    ):
        raise ValueError(f"{label} must be normalized")


def _require_normalized_text(value: str, *, label: str) -> None:
    if normalize_required_text(value, label=label, maximum_length=_MAX_TEXT_LENGTH) != value:
        raise ValueError(f"{label} must be normalized")
