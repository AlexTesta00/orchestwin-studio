"""Replay calibration output through the production domain without output repair."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    UserTwinEvaluationRequest,
    UserTwinEvaluatorConfiguration,
)
from orchestwin.evaluation.model_evaluator import _input_payload, _response_from_payload
from orchestwin.evaluation.validation import EvaluationEvidenceKind, EvaluationEvidenceReference
from orchestwin.models.strict_evaluator_json import strict_json_object
from orchestwin.training.grounded_evaluator_curriculum import NOW
from orchestwin.twins.user_twins import UserTwinLifecycleStatus


def request_for(row):
    value = strict_json_object(row["messages"][1]["content"])["input"]
    snapshot, profile = value["artifact_bundle"], value["user_twin"]
    scenario = EvaluationScenario(
        **{
            **snapshot["scenario"],
            "id": UUID(snapshot["scenario"]["id"]),
            "expected_outcomes": tuple(snapshot["scenario"]["expected_outcomes"]),
        }
    )
    artifacts = tuple(
        EvaluationArtifactReference(
            **{
                **{k: v for k, v in item.items() if k != "modality"},
                "artifact_id": UUID(item["artifact_id"]),
                "kind": EvaluationArtifactKind(item["kind"]),
            }
        )
        for item in snapshot["artifacts"]
    )
    bundle = create_evaluation_artifact_bundle(
        project_id=UUID(snapshot["project_id"]),
        workflow_run_id=UUID(snapshot["workflow_run_id"]),
        scenario=scenario,
        artifacts=artifacts,
        created_at=datetime.fromisoformat(snapshot["created_at"]),
        bundle_id=UUID(snapshot["id"]),
    )
    if bundle.to_snapshot() != snapshot:
        raise ValueError("calibration artifact bundle changed")
    twin = EvaluationUserTwinProfile(
        **{
            **{k: v for k, v in profile.items() if k != "profile"},
            "twin_id": UUID(profile["twin_id"]),
            "lifecycle_status": UserTwinLifecycleStatus(profile["lifecycle_status"]),
        }
    )
    evidence = tuple(
        EvaluationEvidenceReference(**{**item, "kind": EvaluationEvidenceKind(item["kind"])})
        for item in value["evidence"]
    )
    request = UserTwinEvaluationRequest(
        UUID(value["evaluation_run_id"]),
        UUID(value["project_id"]),
        UUID(value["workflow_run_id"]),
        bundle,
        twin,
        evidence,
        NOW,
    )
    if _input_payload(request) != {
        key: item for key, item in value.items() if key != "verified_artifact_content"
    }:
        raise ValueError("calibration request changed")
    return request


def validate_domain_response(payload, row):
    return _response_from_payload(
        request=request_for(row),
        configuration=UserTwinEvaluatorConfiguration(
            "calibration-domain-validation", "1", "unchanged-raw-output", "calibration-v2"
        ),
        payload=payload,
        completed_at=NOW,
    )
