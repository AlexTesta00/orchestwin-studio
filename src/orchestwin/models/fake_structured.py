"""Deterministic structured-generation adapter for tests and offline workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum

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
    validate_sha256,
)

_MAX_TEXT_LENGTH = 4_000
_MAX_IDENTIFIER_LENGTH = 256


class FakeStructuredFixtureOutcome(StrEnum):
    """Explicit fixture outcomes used by the deterministic adapter."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


@dataclass(frozen=True, slots=True)
class FakeStructuredGenerationFixture:
    """One exact task response or typed failure with optional request binding."""

    task_id: str
    outcome: FakeStructuredFixtureOutcome
    expected_request_hash: str | None
    payload_json: str | None
    input_tokens: int
    output_tokens: int
    latency_milliseconds: int
    finish_reason: StructuredGenerationFinishReason | None
    failure_code: StructuredGenerationFailureCode | None
    failure_message: str | None
    failure_retryable: bool

    def __post_init__(self) -> None:
        if (
            normalize_required_text(
                self.task_id,
                label="fake structured fixture task ID",
                maximum_length=_MAX_IDENTIFIER_LENGTH,
            )
            != self.task_id
        ):
            raise ValueError("fake structured fixture task ID must be normalized")
        if self.expected_request_hash is not None:
            validate_sha256(
                self.expected_request_hash,
                label="fake structured fixture request hash",
            )
        for value, label in (
            (self.input_tokens, "fake fixture input tokens"),
            (self.output_tokens, "fake fixture output tokens"),
            (self.latency_milliseconds, "fake fixture latency"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{label} must be a non-negative integer")
        if self.outcome is FakeStructuredFixtureOutcome.SUCCESS:
            if self.payload_json is None or self.finish_reason is None:
                raise ValueError("successful fake fixtures require payload and finish reason")
            if self.failure_code is not None or self.failure_message is not None:
                raise ValueError("successful fake fixtures cannot contain failure details")
            _require_canonical_payload(self.payload_json)
        else:
            if self.payload_json is not None or self.finish_reason is not None:
                raise ValueError("failed fake fixtures cannot contain a success payload")
            if self.failure_code is None or self.failure_message is None:
                raise ValueError("failed fake fixtures require a code and message")
            normalized_message = normalize_optional_text(
                self.failure_message,
                label="fake structured fixture failure message",
                maximum_length=_MAX_TEXT_LENGTH,
            )
            if normalized_message != self.failure_message:
                raise ValueError("fake structured fixture failure message must be normalized")

    @property
    def sort_key(self) -> str:
        return self.task_id


class FakeDeterministicStructuredAdapter(StructuredGenerationPort):
    """Offline exact-fixture adapter with no network, credentials, or hidden fallback."""

    def __init__(
        self,
        *,
        identity: ModelRuntimeIdentity,
        fixtures: tuple[FakeStructuredGenerationFixture, ...],
    ) -> None:
        if not fixtures:
            raise ValueError("fake structured adapter requires at least one fixture")
        ordered = tuple(sorted(fixtures, key=lambda item: item.sort_key))
        if len({item.task_id for item in ordered}) != len(ordered):
            raise ValueError("fake structured adapter task fixtures must be unique")
        self._identity = identity
        self._fixtures = {item.task_id: item for item in ordered}

    @property
    def identity(self) -> ModelRuntimeIdentity:
        return self._identity

    async def generate(
        self,
        request: StructuredGenerationRequest,
    ) -> StructuredGenerationResult:
        """Return the exact configured fixture while enforcing model identity."""
        if request.expected_identity != self._identity:
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                code=StructuredGenerationFailureCode.IDENTITY_MISMATCH,
                message="The fake adapter identity does not match the requested model identity.",
                retryable=False,
            )
        fixture = self._fixtures.get(request.task_id)
        if fixture is None:
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                code=StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
                message="No deterministic structured-generation fixture exists for this task.",
                retryable=False,
            )
        if (
            fixture.expected_request_hash is not None
            and fixture.expected_request_hash != request.content_hash
        ):
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                code=StructuredGenerationFailureCode.INVALID_REQUEST,
                message="The request changed after the deterministic fixture was frozen.",
                retryable=False,
            )
        if fixture.outcome is FakeStructuredFixtureOutcome.FAILURE:
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
                code=fixture.failure_code or StructuredGenerationFailureCode.PROVIDER_ERROR,
                message=fixture.failure_message or "The deterministic fixture failed.",
                retryable=fixture.failure_retryable,
            )
        payload = json.loads(fixture.payload_json or "{}")
        success = create_structured_generation_success(
            payload=payload,
            actual_identity=self._identity,
            usage=StructuredGenerationUsage(
                input_tokens=fixture.input_tokens,
                output_tokens=fixture.output_tokens,
                latency_milliseconds=fixture.latency_milliseconds,
            ),
            finish_reason=fixture.finish_reason or StructuredGenerationFinishReason.STOP,
            provider_request_id=f"fake-{request.request_id}",
        )
        return successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.FAKE_DETERMINISTIC,
            success=success,
        )


def create_fake_success_fixture(
    *,
    task_id: str,
    payload: dict[str, object],
    expected_request_hash: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    latency_milliseconds: int = 0,
    finish_reason: StructuredGenerationFinishReason = StructuredGenerationFinishReason.STOP,
) -> FakeStructuredGenerationFixture:
    """Create a canonical successful fixture."""
    return FakeStructuredGenerationFixture(
        task_id=task_id,
        outcome=FakeStructuredFixtureOutcome.SUCCESS,
        expected_request_hash=expected_request_hash,
        payload_json=canonical_json(payload),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_milliseconds=latency_milliseconds,
        finish_reason=finish_reason,
        failure_code=None,
        failure_message=None,
        failure_retryable=False,
    )


def create_fake_failure_fixture(
    *,
    task_id: str,
    code: StructuredGenerationFailureCode,
    message: str,
    retryable: bool,
    expected_request_hash: str | None = None,
) -> FakeStructuredGenerationFixture:
    """Create a typed failed fixture without a misleading output payload."""
    return FakeStructuredGenerationFixture(
        task_id=task_id,
        outcome=FakeStructuredFixtureOutcome.FAILURE,
        expected_request_hash=expected_request_hash,
        payload_json=None,
        input_tokens=0,
        output_tokens=0,
        latency_milliseconds=0,
        finish_reason=None,
        failure_code=code,
        failure_message=message,
        failure_retryable=retryable,
    )


def _require_canonical_payload(value: str) -> None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("fake structured fixture payload must be valid JSON") from error
    if not isinstance(parsed, dict):
        raise ValueError("fake structured fixture payload must be a JSON object")
    if canonical_json(parsed) != value:
        raise ValueError("fake structured fixture payload must use canonical JSON")
