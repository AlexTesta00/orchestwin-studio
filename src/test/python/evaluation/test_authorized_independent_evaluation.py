"""Tests for independent runs routed through authorized artifact content."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.application import (
    SYNTHETIC_RUN_DISCLAIMER,
    ApprovedUserTwinEvaluationTarget,
)
from orchestwin.evaluation.artifact_content_resolution import (
    ArtifactContentAuthorizationError,
    ArtifactContentAuthorizationIssueCode,
    OwnerScopedArtifactContentResolver,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.authorized_content_application import (
    AuthorizedArtifactContentEvaluationService,
)
from orchestwin.evaluation.authorized_run_application import (
    AuthorizedIndependentUserTwinEvaluationService,
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
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

OWNER_ID = UUID("00000000-0000-4000-8000-000000085001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000085002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000085003")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000085004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000085005")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000085006")
TWIN_A = UUID("00000000-0000-4000-8000-000000085010")
TWIN_B = UUID("00000000-0000-4000-8000-000000085009")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000085011")

NOW = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)

CONTENT = b"<!doctype html><button id='confirm'>Confirm reservation</button>"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
ARTIFACT_CITATION = f"artifact:{ARTIFACT_ID}:v1"

CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="test.authorized-independent",
    evaluator_version="1.0.0",
    model_config_ref="deterministic-test-model",
    prompt_version_ref="verified-content-test-v1",
)


def _reference() -> EvaluationArtifactReference:
    return EvaluationArtifactReference(
        artifact_id=ARTIFACT_ID,
        version_number=1,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=DIGEST,
        size_bytes=len(CONTENT),
        storage_key=f"sha256/{DIGEST[:2]}/{DIGEST}",
        location="browser:reservation/final-dom",
    )


def _bundle():
    return create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=SCENARIO_ID,
            name="Reservation confirmation",
            task="Review the reservation confirmation interface.",
            locale="en",
            expected_outcomes=("The reservation action remains explicit.",),
        ),
        artifacts=(_reference(),),
        created_at=NOW,
    )


def _profile(twin_id: UUID) -> EvaluationUserTwinProfile:
    snapshot, digest = canonical_profile_snapshot(
        {
            "name": f"Reservation operator {twin_id.int}",
            "role": "Completes reservations",
            "goals": ["Confirm reservations without ambiguity"],
        }
    )

    return EvaluationUserTwinProfile(
        twin_id=twin_id,
        version_number=1,
        name=f"Reservation operator {twin_id.int}",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=digest,
        snapshot_json=snapshot,
    )


def _target(twin_id: UUID) -> ApprovedUserTwinEvaluationTarget:
    return ApprovedUserTwinEvaluationTarget(
        twin=_profile(twin_id),
        evidence=(),
    )


def _template(finding_id: str) -> FakeSyntheticFindingTemplate:
    return FakeSyntheticFindingTemplate(
        finding_id=finding_id,
        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        location="browser:reservation/final-dom#confirm",
        summary="The confirmation action should remain explicit.",
        rationale=("The supplied verified DOM contains the reservation action."),
        criterion=SyntheticFindingCriterion.ACTIONABILITY,
        severity=SyntheticFindingSeverity.MINOR,
        epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
        evidence_refs=(ARTIFACT_CITATION,),
        confidence=0.7,
        recommended_action="Preserve the explicit confirmation label.",
        requires_human_validation=True,
    )


class RecordingOwnedArtifactSource:
    def __init__(self, *, authorized_owner_id: UUID) -> None:
        self.authorized_owner_id = authorized_owner_id
        self.resolve_calls: list[tuple[UUID, UUID, UUID, UUID, int]] = []
        self.read_calls: list[tuple[str, int]] = []

    async def resolve_owned_artifact(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        workflow_run_id: UUID,
        artifact_id: UUID,
        version_number: int,
    ) -> EvaluationArtifactReference | None:
        self.resolve_calls.append(
            (
                owner_user_id,
                project_id,
                workflow_run_id,
                artifact_id,
                version_number,
            )
        )

        if owner_user_id != self.authorized_owner_id:
            return None

        return _reference()

    def read_content(
        self,
        storage_key: str,
        maximum_bytes: int,
    ) -> bytes:
        self.read_calls.append((storage_key, maximum_bytes))
        return CONTENT


class RecordingEvaluatorFactory:
    def __init__(self) -> None:
        self.contexts = []
        self.evaluators: list[FakeUserTwinEvaluator] = []

    def __call__(self, *, verified_content):
        self.contexts.append(verified_content)

        evaluator = FakeUserTwinEvaluator(
            configuration=CONFIGURATION,
            templates_by_twin={
                TWIN_A: (_template("UTF-851"),),
                TWIN_B: (_template("UTF-852"),),
            },
            summaries_by_twin={
                TWIN_A: "Twin A produced one simulated hypothesis.",
                TWIN_B: "Twin B produced one simulated hypothesis.",
            },
            clock=lambda: NOW + timedelta(seconds=1),
        )

        self.evaluators.append(evaluator)
        return evaluator


def _times() -> Iterator[datetime]:
    yield NOW
    yield NOW + timedelta(seconds=2)


def test_service_evaluates_each_twin_through_an_independent_authorized_context() -> None:
    async def scenario() -> None:
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
        )
        factory = RecordingEvaluatorFactory()

        authorized_evaluation = AuthorizedArtifactContentEvaluationService(
            resolver=OwnerScopedArtifactContentResolver(source),
            evaluator_factory=factory,
        )

        moments = _times()

        service = AuthorizedIndependentUserTwinEvaluationService(
            authorized_evaluation_service=authorized_evaluation,
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: next(moments),
        )

        result = await service.evaluate(
            owner_user_id=OWNER_ID,
            artifact_bundle=_bundle(),
            targets=(
                _target(TWIN_A),
                _target(TWIN_B),
            ),
            selected=((ARTIFACT_ID, 1),),
        )

        assert result.id == EVALUATION_RUN_ID
        assert result.owner_user_id == OWNER_ID
        assert result.project_id == PROJECT_ID
        assert result.workflow_run_id == WORKFLOW_RUN_ID
        assert result.evaluator == CONFIGURATION

        # Canonical twin order is preserved independently of caller order.
        assert [response.twin_id for response in result.twin_evaluations] == [TWIN_B, TWIN_A]

        # Each twin receives its own request-bound verified context/evaluator.
        assert len(factory.contexts) == 2
        assert factory.contexts[0] is not factory.contexts[1]
        assert len(factory.evaluators) == 2

        assert [evaluator.requests[0].twin.twin_id for evaluator in factory.evaluators] == [
            TWIN_B,
            TWIN_A,
        ]

        assert all(
            evaluator.requests[0].evidence[0].reference_id == ARTIFACT_CITATION
            for evaluator in factory.evaluators
        )

        # Authorization and content verification happen independently per request.
        assert len(source.resolve_calls) == 2
        assert len(source.read_calls) == 2

        assert [finding.finding_id for finding in result.findings] == [
            "UTF-852",
            "UTF-851",
        ]

        assert result.disclaimer == SYNTHETIC_RUN_DISCLAIMER
        assert result.to_snapshot()["aggregation"] == "NONE_INDEPENDENT_RESPONSES_PRESERVED"

    asyncio.run(scenario())


def test_unauthorized_owner_stops_before_any_evaluator_is_created() -> None:
    async def scenario() -> None:
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
        )
        factory = RecordingEvaluatorFactory()

        service = AuthorizedIndependentUserTwinEvaluationService(
            authorized_evaluation_service=(
                AuthorizedArtifactContentEvaluationService(
                    resolver=OwnerScopedArtifactContentResolver(source),
                    evaluator_factory=factory,
                )
            ),
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: NOW,
        )

        with pytest.raises(ArtifactContentAuthorizationError) as captured:
            await service.evaluate(
                owner_user_id=OTHER_OWNER_ID,
                artifact_bundle=_bundle(),
                targets=(_target(TWIN_A),),
                selected=((ARTIFACT_ID, 1),),
            )

        assert captured.value.code is ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED

        assert source.read_calls == []
        assert factory.contexts == []
        assert factory.evaluators == []

    asyncio.run(scenario())
