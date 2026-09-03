"""Tests for User Twin evaluation through the structured model gateway."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    SYNTHETIC_EVALUATION_DISCLAIMER,
    EvaluationUserTwinProfile,
    UserTwinEvaluationRequest,
    UserTwinEvaluatorConfiguration,
    canonical_profile_snapshot,
)
from orchestwin.evaluation.model_evaluator import (
    USER_TWIN_MODEL_EVALUATION_TASK_ID,
    ModelGatewayEvaluationError,
    ModelGatewayEvaluationErrorCode,
    ModelGatewayUserTwinEvaluator,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
)
from orchestwin.models.structured_generation import (
    ModelRuntimeIdentity,
    StructuredGenerationFailureCode,
    StructuredGenerationFinishReason,
    StructuredGenerationProviderKind,
    StructuredGenerationRequest,
    StructuredGenerationResult,
    StructuredGenerationUsage,
    create_structured_generation_success,
    failed_structured_generation_result,
    successful_structured_generation_result,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

PROJECT_ID = UUID("00000000-0000-4000-8000-000000126001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000126002")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000126003")
TWIN_ID = UUID("00000000-0000-4000-8000-000000126004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000126005")
REQUEST_ID = UUID("00000000-0000-4000-8000-000000126006")
NOW = datetime(2026, 10, 16, 13, 0, tzinfo=UTC)


def _identity(*, adapter_id: str = "ut-evaluator-adapter-v1") -> ModelRuntimeIdentity:
    return ModelRuntimeIdentity(
        provider_id="local-openai-compatible",
        runtime_id="local-evaluator-runtime-v1",
        base_model_repository="example/selected-small-instruct",
        base_model_revision="a" * 40,
        tokenizer_revision="b" * 40,
        configuration_sha256="c" * 64,
        adapter_id=adapter_id,
        adapter_sha256="d" * 64,
    )


def _bundle():
    digest = "e" * 64
    return create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=UUID("00000000-0000-4000-8000-000000126007"),
            name="Correct a validation error",
            task="Recover from an invalid value without losing entered data.",
            locale="en",
            expected_outcomes=("The interface gives actionable recovery guidance.",),
        ),
        artifacts=(
            EvaluationArtifactReference(
                artifact_id=ARTIFACT_ID,
                version_number=3,
                kind=EvaluationArtifactKind.SCREENSHOT,
                media_type="image/png",
                sha256_digest=digest,
                size_bytes=400,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                location="screen:booking-form",
            ),
        ),
        created_at=NOW,
        bundle_id=UUID("00000000-0000-4000-8000-000000126008"),
    )


def _profile() -> EvaluationUserTwinProfile:
    snapshot, digest = canonical_profile_snapshot(
        {
            "name": "Operations coordinator",
            "role": "Coordinates a time-sensitive workflow",
            "operational_constraints": ["Limited recovery time"],
        }
    )
    return EvaluationUserTwinProfile(
        twin_id=TWIN_ID,
        version_number=2,
        name="Operations coordinator",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=digest,
        snapshot_json=snapshot,
    )


def _evidence() -> EvaluationEvidenceReference:
    return EvaluationEvidenceReference(
        reference_id="REQ-NFR-012",
        kind=EvaluationEvidenceKind.PROJECT_ARTIFACT,
        content_hash="f" * 64,
        locator="requirements:nfr-012",
    )


def _request() -> UserTwinEvaluationRequest:
    return UserTwinEvaluationRequest(
        evaluation_run_id=EVALUATION_RUN_ID,
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        artifact_bundle=_bundle(),
        twin=_profile(),
        evidence=(_evidence(),),
        requested_at=NOW,
    )


def _valid_payload() -> dict[str, object]:
    return {
        "overall_summary": "One simulated actionability issue requires human validation.",
        "findings": [
            {
                "finding_id": "UTF-126",
                "artifact_id": str(ARTIFACT_ID),
                "artifact_version": 3,
                "location": "screen:booking-form/field:arrival-date",
                "summary": "The recovery instruction is not visible near the invalid field.",
                "rationale": "The supplied requirement asks for actionable recovery guidance.",
                "criterion": "actionability",
                "severity": "major",
                "epistemic_status": "MODEL_INFERRED",
                "evidence_refs": ["REQ-NFR-012"],
                "confidence": 0.71,
                "recommended_action": "Add an inline error and retain keyboard focus.",
                "requires_human_validation": True,
            }
        ],
        "evidence_gaps": [],
        "abstained": False,
    }


@dataclass
class _Port:
    identity: ModelRuntimeIdentity
    payload: dict[str, object] | None = None
    failure_code: StructuredGenerationFailureCode | None = None
    request: StructuredGenerationRequest | None = None

    async def generate(self, request: StructuredGenerationRequest) -> StructuredGenerationResult:
        self.request = request
        if self.failure_code is not None:
            return failed_structured_generation_result(
                provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
                code=self.failure_code,
                message="The local structured endpoint is unavailable.",
                retryable=True,
            )
        success = create_structured_generation_success(
            payload=self.payload or {},
            actual_identity=self.identity,
            usage=StructuredGenerationUsage(300, 120, 45),
            finish_reason=StructuredGenerationFinishReason.STOP,
            provider_request_id="local-request-126",
        )
        return successful_structured_generation_result(
            provider_kind=StructuredGenerationProviderKind.OPENAI_COMPATIBLE_LOCAL,
            success=success,
        )


def _evaluator(port: _Port, identity: ModelRuntimeIdentity | None = None):
    selected_identity = identity or port.identity
    return ModelGatewayUserTwinEvaluator(
        configuration=UserTwinEvaluatorConfiguration(
            evaluator_id="model-gateway-user-twin-evaluator",
            evaluator_version="1.0.0",
            model_config_ref=selected_identity.content_hash,
            prompt_version_ref="ut-eval-v6",
        ),
        model_identity=selected_identity,
        generation_port=port,
        request_id_factory=lambda: REQUEST_ID,
        clock=lambda: NOW,
    )


def test_model_gateway_evaluator_builds_and_validates_exact_structured_feedback() -> None:
    identity = _identity()
    port = _Port(identity=identity, payload=_valid_payload())
    evaluator = _evaluator(port)

    response = asyncio.run(evaluator.evaluate(_request()))

    assert response.findings[0].model_config_ref == identity.content_hash
    assert response.findings[0].prompt_version_ref == "ut-eval-v6"
    assert response.findings[0].evidence_refs == ("REQ-NFR-012",)
    assert response.disclaimer == SYNTHETIC_EVALUATION_DISCLAIMER
    assert port.request is not None
    assert port.request.task_id == USER_TWIN_MODEL_EVALUATION_TASK_ID
    assert port.request.expected_identity == identity
    assert port.request.allowed_evidence_refs == ("REQ-NFR-012",)
    input_payload = json.loads(port.request.input_payload_json)
    assert input_payload["user_twin"]["profile"]["role"].startswith("Coordinates")
    assert evaluator.traces[0].runtime_identity.adapter_id == "ut-evaluator-adapter-v1"
    assert evaluator.traces[0].input_tokens == 300


def test_model_gateway_evaluator_rejects_unknown_evidence_and_artifacts() -> None:
    unknown_evidence = _valid_payload()
    unknown_evidence["findings"][0]["evidence_refs"] = ["UNKNOWN"]
    with pytest.raises(ModelGatewayEvaluationError) as evidence_error:
        asyncio.run(_evaluator(_Port(_identity(), unknown_evidence)).evaluate(_request()))
    assert evidence_error.value.code is ModelGatewayEvaluationErrorCode.INVALID_FINDING

    unknown_artifact = _valid_payload()
    unknown_artifact["findings"][0]["artifact_id"] = str(UUID(int=999))
    with pytest.raises(ModelGatewayEvaluationError) as artifact_error:
        asyncio.run(_evaluator(_Port(_identity(), unknown_artifact)).evaluate(_request()))
    assert artifact_error.value.code is ModelGatewayEvaluationErrorCode.INVALID_FINDING


def test_model_gateway_evaluator_preserves_explicit_abstention() -> None:
    payload = {
        "overall_summary": "The supplied artifact is insufficient for a grounded evaluation.",
        "findings": [],
        "evidence_gaps": ["A task-completion state is missing."],
        "abstained": True,
    }

    response = asyncio.run(_evaluator(_Port(_identity(), payload)).evaluate(_request()))

    assert response.findings == ()
    assert response.evidence_gaps == ("A task-completion state is missing.",)


def test_invalid_abstention_and_provider_failure_remain_explicit() -> None:
    invalid = {
        "overall_summary": "Insufficient evidence.",
        "findings": [],
        "evidence_gaps": [],
        "abstained": True,
    }
    with pytest.raises(ModelGatewayEvaluationError) as invalid_error:
        asyncio.run(_evaluator(_Port(_identity(), invalid)).evaluate(_request()))
    assert invalid_error.value.code is ModelGatewayEvaluationErrorCode.INVALID_PAYLOAD

    failing_port = _Port(
        identity=_identity(),
        failure_code=StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE,
    )
    with pytest.raises(ModelGatewayEvaluationError) as provider_error:
        asyncio.run(_evaluator(failing_port).evaluate(_request()))
    assert provider_error.value.code is ModelGatewayEvaluationErrorCode.GENERATION_FAILED
    assert (
        provider_error.value.provider_failure_code
        is StructuredGenerationFailureCode.PROVIDER_UNAVAILABLE
    )


def test_configuration_and_returned_identity_cannot_drift() -> None:
    identity = _identity()
    with pytest.raises(ModelGatewayEvaluationError) as configuration_error:
        ModelGatewayUserTwinEvaluator(
            configuration=UserTwinEvaluatorConfiguration(
                evaluator_id="model-gateway-user-twin-evaluator",
                evaluator_version="1.0.0",
                model_config_ref="0" * 64,
                prompt_version_ref="ut-eval-v6",
            ),
            model_identity=identity,
            generation_port=_Port(identity, _valid_payload()),
            request_id_factory=lambda: REQUEST_ID,
            clock=lambda: NOW,
        )
    assert configuration_error.value.code is ModelGatewayEvaluationErrorCode.CONFIGURATION_MISMATCH

    different_identity = _identity(adapter_id="different-adapter")
    port = _Port(identity=different_identity, payload=_valid_payload())
    with pytest.raises(ModelGatewayEvaluationError) as identity_error:
        asyncio.run(_evaluator(port, identity).evaluate(_request()))
    assert identity_error.value.code is ModelGatewayEvaluationErrorCode.IDENTITY_MISMATCH
