"""Tests for the provider-independent User Twin evaluator and fake adapter."""

from __future__ import annotations

import asyncio
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
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
    UserTwinEvaluationRequest,
    UserTwinEvaluatorConfiguration,
    canonical_profile_snapshot,
)
from orchestwin.evaluation.findings import (
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

PROJECT_ID = UUID("00000000-0000-4000-8000-000000018001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000018002")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000018003")
TWIN_ID = UUID("00000000-0000-4000-8000-000000018004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000018005")
NOW = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)


def _bundle():
    digest = "a" * 64
    return create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=UUID(int=18006),
            name="Review the disruption alert",
            task="Determine whether the alert supports an operational decision.",
            locale="en",
            expected_outcomes=("The alert explains its operational relevance.",),
        ),
        artifacts=(
            EvaluationArtifactReference(
                artifact_id=ARTIFACT_ID,
                version_number=2,
                kind=EvaluationArtifactKind.SCREENSHOT,
                media_type="image/png",
                sha256_digest=digest,
                size_bytes=200,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                location="screen:dashboard",
            ),
        ),
        created_at=NOW,
        bundle_id=UUID(int=18007),
    )


def _profile() -> EvaluationUserTwinProfile:
    snapshot, digest = canonical_profile_snapshot(
        {
            "name": "Control-room operator",
            "role": "Control-room operator",
            "goals": ["Resolve disruptions quickly"],
        }
    )
    return EvaluationUserTwinProfile(
        twin_id=TWIN_ID,
        version_number=3,
        name="Control-room operator",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=digest,
        snapshot_json=snapshot,
    )


def _evidence() -> EvaluationEvidenceReference:
    return EvaluationEvidenceReference(
        reference_id="REQ-NFR-012",
        kind=EvaluationEvidenceKind.PROJECT_ARTIFACT,
        content_hash="b" * 64,
        locator="requirements:nfr-012",
    )


def _adapter() -> FakeUserTwinEvaluator:
    configuration = UserTwinEvaluatorConfiguration(
        evaluator_id="fake.user-twin-evaluator",
        evaluator_version="1.0.0",
        model_config_ref="fake-model-v1",
        prompt_version_ref="ut-eval-v1",
    )
    template = FakeSyntheticFindingTemplate(
        finding_id="UTF-018",
        artifact_kind=EvaluationArtifactKind.SCREENSHOT,
        location="screen:dashboard/alert:delay",
        summary="The alert does not explain why the disruption matters.",
        rationale="The approved requirement asks for concise operational explanations.",
        criterion=SyntheticFindingCriterion.TRUST,
        severity=SyntheticFindingSeverity.MAJOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=("REQ-NFR-012",),
        confidence=0.75,
        recommended_action="Add a concise explanation of affected routes and passengers.",
        requires_human_validation=True,
    )
    return FakeUserTwinEvaluator(
        configuration=configuration,
        templates_by_twin={TWIN_ID: (template,)},
        summaries_by_twin={TWIN_ID: "One simulated trust issue requires human validation."},
        clock=lambda: NOW,
    )


def test_fake_evaluator_returns_deterministic_typed_simulated_feedback() -> None:
    async def scenario() -> None:
        evidence = _evidence()
        request = UserTwinEvaluationRequest(
            evaluation_run_id=EVALUATION_RUN_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_bundle=_bundle(),
            twin=_profile(),
            evidence=(evidence,),
            requested_at=NOW,
        )
        adapter = _adapter()

        first = await adapter.evaluate(request)
        second = await adapter.evaluate(request)

        assert first == second
        assert first.findings[0].twin_id == TWIN_ID
        assert first.findings[0].artifact_id == ARTIFACT_ID
        assert first.findings[0].model_config_ref == "fake-model-v1"
        assert first.disclaimer == SYNTHETIC_EVALUATION_DISCLAIMER
        assert first.to_snapshot()["is_simulated_feedback"] is True
        assert adapter.requests == [request, request]

    asyncio.run(scenario())


def test_request_rejects_artifact_bundles_from_another_workflow_scope() -> None:
    bundle = _bundle()

    with pytest.raises(ValueError, match="workflow run"):
        UserTwinEvaluationRequest(
            evaluation_run_id=EVALUATION_RUN_ID,
            project_id=PROJECT_ID,
            workflow_run_id=UUID(int=18999),
            artifact_bundle=bundle,
            twin=_profile(),
            evidence=(_evidence(),),
            requested_at=NOW,
        )


def test_fake_evaluator_rejects_unauthorized_evidence_references() -> None:
    async def scenario() -> None:
        request = UserTwinEvaluationRequest(
            evaluation_run_id=EVALUATION_RUN_ID,
            project_id=PROJECT_ID,
            workflow_run_id=WORKFLOW_RUN_ID,
            artifact_bundle=_bundle(),
            twin=_profile(),
            evidence=(),
            requested_at=NOW,
        )

        with pytest.raises(ValueError, match="unauthorized evidence"):
            await _adapter().evaluate(request)

    asyncio.run(scenario())
