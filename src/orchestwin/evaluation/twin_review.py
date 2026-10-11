from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from uuid import UUID

from orchestwin.artifacts.design_evaluation import anchor_element, anchor_finding
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationRequest,
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
    user_twin_evaluation_response_hash,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)


def _normalized(value: object, *, maximum: int) -> str:
    text = " ".join(str(value).split())
    return text[:maximum].rstrip() if len(text) > maximum else text


def bind_twin_review(
    request: UserTwinEvaluationRequest,
    output,
    *,
    configuration: UserTwinEvaluatorConfiguration,
    anchors: Mapping[str, str],
    artifact_id: UUID,
    artifact_version: int,
    scoped: bool,
    clock: Callable[[], datetime],
) -> UserTwinEvaluationResponse:
    if output.unable_to_assess and output.findings:
        raise ValueError("a twin that cannot assess the design must not report findings")
    twin = request.twin
    artifact_reference = f"artifact:{artifact_id}:v{artifact_version}"
    findings = tuple(
        anchor_finding(
            create_synthetic_finding(
                finding_id=f"UTF-{index:03d}",
                twin_id=twin.twin_id,
                twin_version=twin.version_number,
                artifact_id=artifact_id,
                artifact_version=artifact_version,
                location=_normalized(anchors[item.anchor], maximum=500),
                summary=_normalized(item.concern, maximum=1000),
                rationale=_normalized(item.grounds, maximum=4000),
                criterion=SyntheticFindingCriterion(item.quality_criterion),
                severity=SyntheticFindingSeverity(item.severity),
                epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
                evidence_refs=tuple(
                    sorted(
                        {
                            artifact_reference,
                            *(
                                f"user-twin:{twin.twin_id}:v{twin.version_number}#{key}"
                                for key in item.profile_keys
                            ),
                        }
                    )
                ),
                confidence=round(float(item.self_confidence), 2),
                recommended_action=_normalized(item.recommended_action, maximum=2000),
                requires_human_validation=True,
                model_config_ref=configuration.model_config_ref,
                prompt_version_ref=configuration.prompt_version_ref,
            ),
            item.anchor,
            anchor_element(item.anchor) if scoped else None,
        )
        for index, item in enumerate(output.findings, 1)
    )
    gaps = sorted({_normalized(item, maximum=1000) for item in output.evidence_gaps})
    if output.unable_to_assess and not gaps:
        raise ValueError("a twin that cannot assess the design must explain the gap")
    summary = _normalized(output.assessment, maximum=4000)
    return UserTwinEvaluationResponse(
        evaluation_run_id=request.evaluation_run_id,
        artifact_bundle_id=request.artifact_bundle.id,
        artifact_bundle_hash=request.artifact_bundle.content_hash,
        twin_id=twin.twin_id,
        twin_version=twin.version_number,
        evaluator=configuration,
        findings=findings,
        summary=summary,
        evidence_gaps=tuple(gaps),
        completed_at=clock(),
        content_hash=user_twin_evaluation_response_hash(
            evaluation_run_id=request.evaluation_run_id,
            artifact_bundle_id=request.artifact_bundle.id,
            artifact_bundle_hash=request.artifact_bundle.content_hash,
            twin_id=twin.twin_id,
            twin_version=twin.version_number,
            evaluator=configuration,
            findings=findings,
            summary=summary,
            evidence_gaps=tuple(gaps),
        ),
    )


__all__ = ["bind_twin_review"]
