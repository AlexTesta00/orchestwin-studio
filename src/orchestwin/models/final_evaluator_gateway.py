"""Exact S67 generation through the existing OpenAI-compatible adapter.

Each call has its own validation transport: no shared mutable current-request
slot, metadata recovery from benchmarks, repair, retry or base-model fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable

from orchestwin.evaluation.field_scope_prompt import FIELD_SCOPE_PROMPT_VERSION
from orchestwin.models.final_evaluator_session import (
    MODEL_NAME,
    FinalEvaluatorSession,
    FinalEvaluatorSessionError,
    SessionHttpResponse,
    session_http,
)
from orchestwin.models.openai_compatible import (
    OpenAICompatibleHttpResponse,
    OpenAICompatibleLocalConfig,
    OpenAICompatibleLocalStructuredAdapter,
)
from orchestwin.models.strict_evaluator_json import (
    canonical_bytes,
    check_evaluator_schema,
    require,
    strict_json_object,
    validate_evaluator_value,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    failed_structured_generation_result,
)

RESPONSE_CONTRACT = (
    "Return exactly one JSON object and no other text.",
    "Do not wrap the JSON object in Markdown fences.",
    "Do not expose hidden reasoning or chain-of-thought.",
)


def model_visible_messages(request: StructuredGenerationRequest) -> list[dict[str, str]]:
    user = {
        "task_id": request.task_id,
        "input": strict_json_object(request.input_payload_json),
        "allowed_evidence_refs": list(request.allowed_evidence_refs),
        "output_schema": strict_json_object(request.output_schema.canonical_schema_json),
        "response_contract": list(RESPONSE_CONTRACT),
    }
    return [
        {"role": "system", "content": request.system_instruction},
        {"role": "user", "content": canonical_bytes(user).decode("utf-8")},
    ]


def validate_final_completion(
    raw: bytes, request: StructuredGenerationRequest, session: FinalEvaluatorSession
) -> None:
    value = strict_json_object(raw)
    require(
        value.get("model") == MODEL_NAME and value.get("model_identity") == session.identity,
        "FINAL_COMPLETION_IDENTITY_MISMATCH",
    )
    choices = value.get("choices")
    require(
        isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict),
        "FINAL_COMPLETION_CHOICES_INVALID",
    )
    require(choices[0].get("finish_reason") == "stop", "FINAL_COMPLETION_NOT_STOPPED")
    message = choices[0].get("message", {})
    require(
        message.get("role") == "assistant" and isinstance(message.get("content"), str),
        "FINAL_COMPLETION_MESSAGE_INVALID",
    )
    payload = strict_json_object(message["content"])
    schema = strict_json_object(request.output_schema.canonical_schema_json)
    check_evaluator_schema(schema)
    validate_evaluator_value(payload, schema)
    usage = value.get("usage", {})
    require(
        all(
            type(usage.get(key)) is int and usage[key] > 0
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        )
        and usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
        and usage["completion_tokens"] <= request.max_output_tokens,
        "FINAL_COMPLETION_USAGE_INVALID",
    )
    proof = value.get("orchestwin_serving", {})
    expected = hashlib.sha256(
        canonical_bytes({"messages": model_visible_messages(request)})
    ).hexdigest()
    require(
        proof.get("model_visible_messages_sha256") == expected
        and proof.get("output_repair_used") is False,
        "FINAL_COMPLETION_PROMPT_OR_REPAIR_MISMATCH",
    )


class _RequestTransport:
    def __init__(self, session, request, exchange):
        self.session, self.request, self.exchange = session, request, exchange
        self.attempts = 0

    async def post_json(self, *, url, payload, headers, timeout_seconds):
        request = self.request
        require(self.attempts == 0, "FINAL_GENERATION_RETRY_FORBIDDEN")
        require(
            url == self.session.base_url + "/v1/chat/completions"
            and headers == {"Authorization": "Bearer " + self.session.token},
            "FINAL_GENERATION_TRANSPORT_MISMATCH",
        )
        require(
            payload.get("metadata")
            == {
                "orchestwin_request_id": str(request.request_id),
                "orchestwin_request_hash": request.content_hash,
                "expected_model_identity": request.expected_identity.to_snapshot(),
                "orchestwin_task_id": request.task_id,
                "orchestwin_prompt_version_ref": request.prompt_version_ref,
                "allowed_evidence_refs": list(request.allowed_evidence_refs),
            },
            "FINAL_GENERATION_METADATA_MISMATCH",
        )
        self.attempts += 1
        response = await asyncio.to_thread(
            self.exchange,
            self.session,
            "POST",
            "/v1/chat/completions",
            canonical_bytes(payload),
            timeout_seconds,
        )
        if response.status_code == 200:
            validate_final_completion(response.body, request, self.session)
        # Preserve the raw response; the existing adapter performs its normal mapping.
        return OpenAICompatibleHttpResponse(
            response.status_code, response.body, response.elapsed_milliseconds
        )


class FinalEvaluatorGenerationPort:
    """Application-owned port. An injected exchange is trusted test/replay infrastructure only."""

    def __init__(
        self,
        session: FinalEvaluatorSession,
        *,
        exchange: Callable[..., SessionHttpResponse] = session_http,
    ):
        self.session = session
        self._exchange = exchange
        self.identity = ModelRuntimeIdentity(**session.identity)

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResult:
        if request.expected_identity != self.identity:
            return _failure(
                StructuredGenerationFailureCode.IDENTITY_MISMATCH,
                "The requested identity differs from the configured S67 session.",
            )
        try:
            require(
                request.task_id == "user-twin-evaluation-v1"
                and request.prompt_version_ref == FIELD_SCOPE_PROMPT_VERSION
                and request.temperature == 0.0
                and type(request.max_output_tokens) is int
                and 1 <= request.max_output_tokens <= 1024
                and type(request.timeout_seconds) is int
                and 1 <= request.timeout_seconds <= 90,
                "FINAL_EVALUATOR_REQUEST_OUTSIDE_CONTRACT",
            )
            check_evaluator_schema(strict_json_object(request.output_schema.canonical_schema_json))
            self.session.assert_unchanged()
        except (FinalEvaluatorSessionError, ValueError, TypeError, KeyError):
            return _failure(
                StructuredGenerationFailureCode.INVALID_REQUEST,
                "S67 session or request contract verification failed before generation.",
            )
        adapter = OpenAICompatibleLocalStructuredAdapter(
            config=OpenAICompatibleLocalConfig(
                base_url=self.session.base_url,
                model_name=MODEL_NAME,
                expected_identity=self.identity,
            ),
            transport=_RequestTransport(self.session, request, self._exchange),
            bearer_token=self.session.token,
        )
        try:
            return await adapter.generate(request)
        except FinalEvaluatorSessionError:
            return _failure(
                StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
                "The S67 session is unavailable; no retry was performed.",
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            return _failure(
                StructuredGenerationFailureCode.RESPONSE_SCHEMA_ERROR,
                "The unmodified S67 response failed strict contract verification.",
            )


def _failure(code, message):
    return failed_structured_generation_result(
        provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
        code=code,
        message=message,
        retryable=False,
    )
