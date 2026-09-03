"""User Twin evaluator adapter backed by provider-independent structured generation."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.evaluation.evaluator import (
    SYNTHETIC_EVALUATION_DISCLAIMER,
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.evaluation.validation import (
    SyntheticFindingValidationContext,
    validate_synthetic_finding,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationPort,
    StructuredGenerationResult,
    StructuredGenerationStatus,
    StructuredJsonSchema,
    create_structured_generation_request,
    create_structured_json_schema,
)
from orchestwin.projects.requirements_primitives import normalize_required_text

USER_TWIN_MODEL_EVALUATION_TASK_ID: Final = "user-twin-evaluation-v1"
_MAX_SUMMARY_LENGTH: Final = 4_000
_MAX_GAP_LENGTH: Final = 1_000
_MAX_FINDINGS: Final = 100


class ModelGatewayEvaluationErrorCode(StrEnum):
    """Stable reasons why model-backed User Twin evaluation could not complete."""

    CONFIGURATION_MISMATCH = "CONFIGURATION_MISMATCH"
    GENERATION_FAILED = "GENERATION_FAILED"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    INVALID_PAYLOAD = "INVALID_PAYLOAD"
    INVALID_FINDING = "INVALID_FINDING"


class ModelGatewayEvaluationError(RuntimeError):
    """Typed application-boundary error without provider SDK details."""

    def __init__(
        self,
        code: ModelGatewayEvaluationErrorCode,
        message: str,
        *,
        provider_failure_code: StructuredGenerationFailureCode | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.provider_failure_code = provider_failure_code


@dataclass(frozen=True, slots=True)
class ModelGatewayEvaluationTrace:
    """Inspectable exact request, result, and model identity evidence."""

    evaluation_run_id: UUID
    twin_id: UUID
    request_sha256: str
    result_sha256: str
    runtime_identity: ModelRuntimeIdentity
    input_tokens: int
    output_tokens: int
    latency_milliseconds: int

    def to_snapshot(self) -> dict[str, object]:
        return {
            "evaluation_run_id": str(self.evaluation_run_id),
            "twin_id": str(self.twin_id),
            "request_sha256": self.request_sha256,
            "result_sha256": self.result_sha256,
            "runtime_identity": self.runtime_identity.to_snapshot(),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_milliseconds": self.latency_milliseconds,
        }


class ModelGatewayUserTwinEvaluator:
    """Convert exact evaluation context into validated structured model feedback."""

    def __init__(
        self,
        *,
        configuration: UserTwinEvaluatorConfiguration,
        model_identity: ModelRuntimeIdentity,
        generation_port: StructuredGenerationPort,
        request_id_factory: Callable[[], UUID],
        clock: Callable[[], datetime],
        max_output_tokens: int = 2_048,
        timeout_seconds: int = 120,
    ) -> None:
        if configuration.model_config_ref != model_identity.content_hash:
            raise ModelGatewayEvaluationError(
                ModelGatewayEvaluationErrorCode.CONFIGURATION_MISMATCH,
                "Evaluator model reference must equal the exact runtime identity digest.",
            )
        if max_output_tokens < 1 or timeout_seconds < 1:
            raise ValueError("model evaluator limits must be positive")
        self._configuration = configuration
        self._model_identity = model_identity
        self._generation_port = generation_port
        self._request_id_factory = request_id_factory
        self._clock = clock
        self._max_output_tokens = max_output_tokens
        self._timeout_seconds = timeout_seconds
        self.traces: list[ModelGatewayEvaluationTrace] = []

    @property
    def configuration(self) -> UserTwinEvaluatorConfiguration:
        return self._configuration

    @property
    def output_schema(self) -> StructuredJsonSchema:
        return create_structured_json_schema(
            schema_id="orchestwin-user-twin-evaluation",
            version_number=1,
            schema_payload=_output_schema_payload(),
        )

    async def evaluate(
        self,
        request: UserTwinEvaluationRequest,
    ) -> UserTwinEvaluationResponse:
        generation_request = create_structured_generation_request(
            request_id=self._request_id_factory(),
            task_id=USER_TWIN_MODEL_EVALUATION_TASK_ID,
            expected_identity=self._model_identity,
            output_schema=self.output_schema,
            system_instruction=_system_instruction(),
            input_payload=_input_payload(request),
            allowed_evidence_refs=tuple(reference.reference_id for reference in request.evidence),
            prompt_version_ref=self.configuration.prompt_version_ref,
            temperature=0.0,
            max_output_tokens=self._max_output_tokens,
            timeout_seconds=self._timeout_seconds,
        )
        result = await self._generation_port.generate(generation_request)
        success = _require_success(result)
        if success.actual_identity != self._model_identity:
            raise ModelGatewayEvaluationError(
                ModelGatewayEvaluationErrorCode.IDENTITY_MISMATCH,
                "Structured generation returned a different runtime identity.",
            )
        try:
            payload = json.loads(success.payload_json)
            response = _response_from_payload(
                request=request,
                configuration=self.configuration,
                payload=payload,
                completed_at=self._clock(),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise ModelGatewayEvaluationError(
                ModelGatewayEvaluationErrorCode.INVALID_PAYLOAD,
                "Model-backed User Twin evaluation returned an invalid payload.",
            ) from error
        self.traces.append(
            ModelGatewayEvaluationTrace(
                evaluation_run_id=request.evaluation_run_id,
                twin_id=request.twin.twin_id,
                request_sha256=generation_request.content_hash,
                result_sha256=result.content_hash,
                runtime_identity=success.actual_identity,
                input_tokens=success.usage.input_tokens,
                output_tokens=success.usage.output_tokens,
                latency_milliseconds=success.usage.latency_milliseconds,
            )
        )
        return response


def _require_success(result: StructuredGenerationResult):
    if result.status is StructuredGenerationStatus.SUCCEEDED and result.success is not None:
        return result.success
    failure = result.failure
    raise ModelGatewayEvaluationError(
        ModelGatewayEvaluationErrorCode.GENERATION_FAILED,
        (
            "Structured generation failed without a typed provider error."
            if failure is None
            else failure.message
        ),
        provider_failure_code=None if failure is None else failure.code,
    )


def _response_from_payload(
    *,
    request: UserTwinEvaluationRequest,
    configuration: UserTwinEvaluatorConfiguration,
    payload: object,
    completed_at: datetime,
) -> UserTwinEvaluationResponse:
    if not isinstance(payload, dict):
        raise ValueError("evaluation output must be a JSON object")
    findings_value = payload.get("findings")
    if not isinstance(findings_value, list) or len(findings_value) > _MAX_FINDINGS:
        raise ValueError("evaluation findings must be a bounded list")
    abstained = _required_boolean(payload, "abstained")
    evidence_gaps = tuple(sorted(_string_list(payload, "evidence_gaps", _MAX_GAP_LENGTH)))
    if abstained and (findings_value or not evidence_gaps):
        raise ValueError("abstention requires no findings and at least one evidence gap")
    findings = tuple(
        sorted(
            (
                _finding_from_payload(
                    request=request,
                    configuration=configuration,
                    payload=value,
                )
                for value in findings_value
            ),
            key=lambda item: item.finding_id,
        )
    )
    if len({finding.finding_id for finding in findings}) != len(findings):
        raise ValueError("evaluation finding IDs must be unique")
    summary = _required_normalized_string(
        payload,
        "overall_summary",
        maximum_length=_MAX_SUMMARY_LENGTH,
    )
    return UserTwinEvaluationResponse(
        evaluation_run_id=request.evaluation_run_id,
        artifact_bundle_id=request.artifact_bundle.id,
        artifact_bundle_hash=request.artifact_bundle.content_hash,
        twin_id=request.twin.twin_id,
        twin_version=request.twin.version_number,
        evaluator=configuration,
        findings=findings,
        summary=summary,
        evidence_gaps=evidence_gaps,
        completed_at=completed_at,
        content_hash=user_twin_evaluation_response_hash(
            evaluation_run_id=request.evaluation_run_id,
            artifact_bundle_id=request.artifact_bundle.id,
            artifact_bundle_hash=request.artifact_bundle.content_hash,
            twin_id=request.twin.twin_id,
            twin_version=request.twin.version_number,
            evaluator=configuration,
            findings=findings,
            summary=summary,
            evidence_gaps=evidence_gaps,
        ),
    )


def _finding_from_payload(
    *,
    request: UserTwinEvaluationRequest,
    configuration: UserTwinEvaluatorConfiguration,
    payload: object,
) -> SyntheticFinding:
    if not isinstance(payload, dict):
        raise ValueError("evaluation finding must be a JSON object")
    artifact_id = UUID(_required_string(payload, "artifact_id"))
    artifact_version = _required_integer(payload, "artifact_version")
    artifact = next(
        (
            item
            for item in request.artifact_bundle.artifacts
            if item.artifact_id == artifact_id and item.version_number == artifact_version
        ),
        None,
    )
    if artifact is None:
        raise ModelGatewayEvaluationError(
            ModelGatewayEvaluationErrorCode.INVALID_FINDING,
            "Model output referenced an artifact outside the authorized bundle.",
        )
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("evaluation finding confidence must be numeric")
    finding = create_synthetic_finding(
        finding_id=_required_string(payload, "finding_id"),
        twin_id=request.twin.twin_id,
        twin_version=request.twin.version_number,
        artifact_id=artifact.artifact_id,
        artifact_version=artifact.version_number,
        location=_required_string(payload, "location"),
        summary=_required_string(payload, "summary"),
        rationale=_required_string(payload, "rationale"),
        criterion=SyntheticFindingCriterion(_required_string(payload, "criterion")),
        severity=SyntheticFindingSeverity(_required_string(payload, "severity")),
        epistemic_status=SyntheticFindingEpistemicStatus(
            _required_string(payload, "epistemic_status")
        ),
        evidence_refs=tuple(sorted(_string_list(payload, "evidence_refs", 512))),
        confidence=float(confidence),
        recommended_action=_required_string(payload, "recommended_action"),
        requires_human_validation=_required_boolean(
            payload,
            "requires_human_validation",
        ),
        model_config_ref=configuration.model_config_ref,
        prompt_version_ref=configuration.prompt_version_ref,
    )
    report = validate_synthetic_finding(
        finding,
        SyntheticFindingValidationContext(
            twin_id=request.twin.twin_id,
            twin_version=request.twin.version_number,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.version_number,
            evidence=request.evidence,
        ),
    )
    if not report.is_valid:
        raise ModelGatewayEvaluationError(
            ModelGatewayEvaluationErrorCode.INVALID_FINDING,
            "Model output failed deterministic finding provenance validation.",
        )
    return finding


def _input_payload(request: UserTwinEvaluationRequest) -> dict[str, object]:
    return {
        "evaluation_run_id": str(request.evaluation_run_id),
        "project_id": str(request.project_id),
        "workflow_run_id": str(request.workflow_run_id),
        "artifact_bundle": request.artifact_bundle.to_snapshot(),
        "user_twin": {
            **request.twin.to_snapshot(),
            "profile": json.loads(request.twin.snapshot_json),
        },
        "evidence": [reference.to_snapshot() for reference in request.evidence],
        "rubric": [item.value for item in SyntheticFindingCriterion],
        "required_disclaimer": SYNTHETIC_EVALUATION_DISCLAIMER,
    }


def _system_instruction() -> str:
    return (
        "You are a User Twin used within an Agentic User-Centered Design workflow. "
        "Evaluate only the supplied artifact bundle from the represented role. "
        "Use only supplied evidence references. Mark unsupported hypotheses as "
        "UNSUPPORTED_ASSUMPTION, require human validation for model-inferred claims, "
        "and abstain when evidence or artifacts are insufficient. Do not predict real-user "
        "behavior. Return only the required structured schema. The output is simulated "
        "feedback and a design hypothesis, not empirical evidence."
    )


def _output_schema_payload() -> dict[str, object]:
    finding = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "finding_id",
            "artifact_id",
            "artifact_version",
            "location",
            "summary",
            "rationale",
            "criterion",
            "severity",
            "epistemic_status",
            "evidence_refs",
            "confidence",
            "recommended_action",
            "requires_human_validation",
        ],
        "properties": {
            "finding_id": {"type": "string"},
            "artifact_id": {"type": "string", "format": "uuid"},
            "artifact_version": {"type": "integer", "minimum": 1},
            "location": {"type": "string"},
            "summary": {"type": "string"},
            "rationale": {"type": "string"},
            "criterion": {"enum": [item.value for item in SyntheticFindingCriterion]},
            "severity": {"enum": [item.value for item in SyntheticFindingSeverity]},
            "epistemic_status": {"enum": [item.value for item in SyntheticFindingEpistemicStatus]},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "recommended_action": {"type": "string"},
            "requires_human_validation": {"type": "boolean"},
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["overall_summary", "findings", "evidence_gaps", "abstained"],
        "properties": {
            "overall_summary": {"type": "string"},
            "findings": {
                "type": "array",
                "maxItems": _MAX_FINDINGS,
                "items": finding,
            },
            "evidence_gaps": {"type": "array", "items": {"type": "string"}},
            "abstained": {"type": "boolean"},
        },
    }


def _required_string(values: dict[str, object], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str):
        raise ValueError(f"evaluation output {key} must be a string")
    return value


def _required_normalized_string(
    values: dict[str, object],
    key: str,
    *,
    maximum_length: int,
) -> str:
    value = _required_string(values, key)
    normalized = normalize_required_text(
        value,
        label=f"evaluation output {key}",
        maximum_length=maximum_length,
    )
    if normalized != value:
        raise ValueError(f"evaluation output {key} must be normalized")
    return value


def _required_integer(values: dict[str, object], key: str) -> int:
    value = values.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"evaluation output {key} must be a positive integer")
    return value


def _required_boolean(values: dict[str, object], key: str) -> bool:
    value = values.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"evaluation output {key} must be a boolean")
    return value


def _string_list(
    values: dict[str, object],
    key: str,
    maximum_length: int,
) -> tuple[str, ...]:
    value = values.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"evaluation output {key} must be a string list")
    result: list[str] = []
    for item in value:
        normalized = normalize_required_text(
            item,
            label=f"evaluation output {key} item",
            maximum_length=maximum_length,
        )
        if normalized != item:
            raise ValueError(f"evaluation output {key} items must be normalized")
        result.append(item)
    if len(result) != len(set(result)):
        raise ValueError(f"evaluation output {key} items must be unique")
    return tuple(result)
