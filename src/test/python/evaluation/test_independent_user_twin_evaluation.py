"""Tests for independent evaluation of approved User Twin versions."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.application import (
    SYNTHETIC_RUN_DISCLAIMER,
    ApprovedUserTwinEvaluationTarget,
    IndependentUserTwinEvaluationService,
    SyntheticEvaluationError,
    SyntheticEvaluationIssueCode,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.evaluator import (
    EvaluationUserTwinProfile,
    FakeSyntheticFindingTemplate,
    FakeUserTwinEvaluator,
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

PROJECT_ID = UUID("00000000-0000-4000-8000-000000019001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000019002")
OWNER_ID = UUID("00000000-0000-4000-8000-000000019003")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000019004")
TWIN_A = UUID("00000000-0000-4000-8000-000000019010")
TWIN_B = UUID("00000000-0000-4000-8000-000000019009")
NOW = datetime(2026, 8, 30, 19, 0, tzinfo=UTC)


def _bundle():
    digest = "a" * 64
    return create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=UUID(int=19005),
            name="Review the reservation flow",
            task="Complete a reservation while preserving operational context.",
            locale="en",
            expected_outcomes=("The reservation can be completed without ambiguity.",),
        ),
        artifacts=(
            EvaluationArtifactReference(
                artifact_id=UUID(int=19006),
                version_number=2,
                kind=EvaluationArtifactKind.SCREENSHOT,
                media_type="image/png",
                sha256_digest=digest,
                size_bytes=100,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                location="screen:reservation",
            ),
        ),
        created_at=NOW,
        bundle_id=UUID(int=19007),
    )


def _profile(twin_id: UUID, status: UserTwinLifecycleStatus) -> EvaluationUserTwinProfile:
    snapshot, digest = canonical_profile_snapshot(
        {
            "name": f"Twin {twin_id.int}",
            "role": "Receptionist",
            "goals": ["Complete reservations accurately"],
        }
    )
    return EvaluationUserTwinProfile(
        twin_id=twin_id,
        version_number=1,
        name=f"Twin {twin_id.int}",
        lifecycle_status=status,
        content_hash=digest,
        snapshot_json=snapshot,
    )


def _evidence(reference_id: str) -> EvaluationEvidenceReference:
    return EvaluationEvidenceReference(
        reference_id=reference_id,
        kind=EvaluationEvidenceKind.PROJECT_ARTIFACT,
        content_hash="b" * 64,
        locator=f"requirements:{reference_id}",
    )


def _template(finding_id: str, evidence_ref: str) -> FakeSyntheticFindingTemplate:
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.SCREENSHOT,
        location="screen:reservation/action:confirm",
        summary="The confirmation action may be unclear under time pressure.",
        rationale="The supplied project requirement asks for a clear primary action.",
        criterion=SyntheticFindingCriterion.ACTIONABILITY,
        severity=SyntheticFindingSeverity.MODERATE,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(evidence_ref,),
        confidence=0.7,
        recommended_action="Use an explicit confirmation label and preserve the summary.",
        requires_human_validation=True,
    )


def _times() -> Iterator[datetime]:
    yield NOW
    yield NOW + timedelta(seconds=2)


def test_service_evaluates_approved_twins_independently_in_canonical_order() -> None:
    async def scenario() -> None:
        configuration = UserTwinEvaluatorConfiguration(
            evaluator_id="fake.user-twin-evaluator",
            evaluator_version="1.0.0",
            model_config_ref="fake-model-v1",
            prompt_version_ref="ut-eval-v1",
        )
        adapter = FakeUserTwinEvaluator(
            configuration=configuration,
            templates_by_twin={
                TWIN_A: (_template("UTF-191", "REQ-A"),),
                TWIN_B: (_template("UTF-192", "REQ-B"),),
            },
            summaries_by_twin={
                TWIN_A: "Twin A produced one simulated observation.",
                TWIN_B: "Twin B produced one simulated observation.",
            },
            clock=lambda: NOW + timedelta(seconds=1),
        )
        moments = _times()
        service = IndependentUserTwinEvaluationService(
            adapter,
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: next(moments),
        )
        target_a = ApprovedUserTwinEvaluationTarget(
            twin=_profile(TWIN_A, UserTwinLifecycleStatus.OWNER_APPROVED_UT),
            evidence=(_evidence("REQ-A"),),
        )
        target_b = ApprovedUserTwinEvaluationTarget(
            twin=_profile(TWIN_B, UserTwinLifecycleStatus.EMPIRICALLY_GROUNDED_UT),
            evidence=(_evidence("REQ-B"),),
        )

        result = await service.evaluate(
            owner_user_id=OWNER_ID,
            artifact_bundle=_bundle(),
            targets=(target_a, target_b),
        )

        assert [response.twin_id for response in result.twin_evaluations] == [TWIN_B, TWIN_A]
        assert [request.twin.twin_id for request in adapter.requests] == [TWIN_B, TWIN_A]
        assert [request.evidence[0].reference_id for request in adapter.requests] == [
            "REQ-B",
            "REQ-A",
        ]
        assert [finding.finding_id for finding in result.findings] == ["UTF-192", "UTF-191"]
        assert result.disclaimer == SYNTHETIC_RUN_DISCLAIMER
        assert result.to_snapshot()["aggregation"] == "NONE_INDEPENDENT_RESPONSES_PRESERVED"

    asyncio.run(scenario())


def test_target_rejects_a_profile_that_has_not_reached_owner_approval() -> None:
    with pytest.raises(SyntheticEvaluationError) as captured:
        ApprovedUserTwinEvaluationTarget(
            twin=_profile(TWIN_A, UserTwinLifecycleStatus.PROJECT_GROUNDED_UT),
            evidence=(_evidence("REQ-A"),),
        )

    assert captured.value.code is SyntheticEvaluationIssueCode.UNAPPROVED_TWIN


def test_service_rejects_duplicate_twin_versions_before_invoking_adapter() -> None:
    async def scenario() -> None:
        adapter = FakeUserTwinEvaluator(
            configuration=UserTwinEvaluatorConfiguration(
                evaluator_id="fake.user-twin-evaluator",
                evaluator_version="1.0.0",
                model_config_ref="fake-model-v1",
                prompt_version_ref="ut-eval-v1",
            ),
            templates_by_twin={},
            summaries_by_twin={},
            clock=lambda: NOW,
        )
        service = IndependentUserTwinEvaluationService(
            adapter,
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: NOW,
        )
        target = ApprovedUserTwinEvaluationTarget(
            twin=_profile(TWIN_A, UserTwinLifecycleStatus.OWNER_APPROVED_UT),
            evidence=(_evidence("REQ-A"),),
        )

        with pytest.raises(SyntheticEvaluationError) as captured:
            await service.evaluate(
                owner_user_id=OWNER_ID,
                artifact_bundle=_bundle(),
                targets=(target, target),
            )

        assert captured.value.code is SyntheticEvaluationIssueCode.DUPLICATE_TWIN
        assert adapter.requests == []

    asyncio.run(scenario())
