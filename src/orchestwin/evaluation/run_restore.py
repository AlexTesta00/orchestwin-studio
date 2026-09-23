from datetime import datetime
from uuid import UUID

from orchestwin.evaluation.application import SyntheticEvaluationRun, SyntheticEvaluationRunStatus
from orchestwin.evaluation.evaluator import (
    UserTwinEvaluationResponse,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)


def synthetic_finding_from_snapshot(payload):
    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not all(
        isinstance(reference, str) for reference in evidence_refs
    ):
        raise ValueError("synthetic finding snapshot evidence references are invalid")
    requires_human_validation = payload.get("requires_human_validation")
    if not isinstance(requires_human_validation, bool):
        raise ValueError("synthetic finding snapshot validation flag is invalid")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int | float):
        raise ValueError("synthetic finding snapshot confidence is invalid")
    finding = create_synthetic_finding(
        finding_id=str(payload["finding_id"]),
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(str(payload["twin_version"])),
        artifact_id=UUID(str(payload["artifact_id"])),
        artifact_version=int(str(payload["artifact_version"])),
        location=str(payload["location"]),
        summary=str(payload["summary"]),
        rationale=str(payload["rationale"]),
        criterion=SyntheticFindingCriterion(str(payload["criterion"])),
        severity=SyntheticFindingSeverity(str(payload["severity"])),
        epistemic_status=SyntheticFindingEpistemicStatus(str(payload["epistemic_status"])),
        evidence_refs=tuple(evidence_refs),
        confidence=float(confidence),
        recommended_action=str(payload["recommended_action"]),
        requires_human_validation=requires_human_validation,
        model_config_ref=str(payload["model_config_ref"]),
        prompt_version_ref=str(payload["prompt_version_ref"]),
    )
    if finding.content_hash != payload.get("content_hash"):
        raise ValueError("synthetic finding snapshot content hash is inconsistent")
    return finding


def evaluator_configuration_from_snapshot(payload):
    return UserTwinEvaluatorConfiguration(
        evaluator_id=str(payload["evaluator_id"]),
        evaluator_version=str(payload["evaluator_version"]),
        model_config_ref=str(payload["model_config_ref"]),
        prompt_version_ref=str(payload["prompt_version_ref"]),
    )


def user_twin_evaluation_response_from_snapshot(payload):
    gaps = payload.get("evidence_gaps")
    if not isinstance(gaps, list) or not all(isinstance(item, str) for item in gaps):
        raise ValueError("evaluation response snapshot evidence gaps are invalid")
    return UserTwinEvaluationResponse(
        evaluation_run_id=UUID(str(payload["evaluation_run_id"])),
        artifact_bundle_id=UUID(str(payload["artifact_bundle_id"])),
        artifact_bundle_hash=str(payload["artifact_bundle_hash"]),
        twin_id=UUID(str(payload["twin_id"])),
        twin_version=int(str(payload["twin_version"])),
        evaluator=evaluator_configuration_from_snapshot(payload["evaluator"]),
        findings=tuple(synthetic_finding_from_snapshot(item) for item in payload["findings"]),
        summary=str(payload["summary"]),
        evidence_gaps=tuple(gaps),
        completed_at=datetime.fromisoformat(str(payload["completed_at"])),
        content_hash=str(payload["content_hash"]),
    )


def synthetic_evaluation_run_from_snapshot(payload):
    return SyntheticEvaluationRun(
        id=UUID(str(payload["id"])),
        project_id=UUID(str(payload["project_id"])),
        workflow_run_id=UUID(str(payload["workflow_run_id"])),
        owner_user_id=UUID(str(payload["owner_user_id"])),
        artifact_bundle_id=UUID(str(payload["artifact_bundle_id"])),
        artifact_bundle_hash=str(payload["artifact_bundle_hash"]),
        evaluator=evaluator_configuration_from_snapshot(payload["evaluator"]),
        status=SyntheticEvaluationRunStatus(str(payload["status"])),
        twin_evaluations=tuple(
            user_twin_evaluation_response_from_snapshot(item)
            for item in payload["twin_evaluations"]
        ),
        started_at=datetime.fromisoformat(str(payload["started_at"])),
        completed_at=datetime.fromisoformat(str(payload["completed_at"])),
        content_hash=str(payload["content_hash"]),
    )
