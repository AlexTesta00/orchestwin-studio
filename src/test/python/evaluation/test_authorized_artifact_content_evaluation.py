"""Application tests for authorized verified-content evaluator invocation."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from uuid import UUID

import pytest

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
from orchestwin.evaluation.evaluator import (
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
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

OWNER_ID = UUID("00000000-0000-4000-8000-000000084001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000084002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000084003")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000084004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000084005")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000084006")
TWIN_ID = UUID("00000000-0000-4000-8000-000000084007")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000084008")
NOW = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)

CONTENT = b"<!doctype html><button id='confirm'>Confirm reservation</button>"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
ARTIFACT_CITATION = f"artifact:{ARTIFACT_ID}:v1"

CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="test.authorized-content",
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


def _request() -> UserTwinEvaluationRequest:
    reference = _reference()

    profile_snapshot, profile_hash = canonical_profile_snapshot(
        {
            "name": "Reservation operator",
            "role": "Completes reservations",
            "goals": ["Confirm reservations without ambiguity"],
        }
    )

    bundle = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=SCENARIO_ID,
            name="Reservation confirmation",
            task="Review the reservation confirmation interface.",
            locale="en",
            expected_outcomes=("The primary reservation action is explicit.",),
        ),
        artifacts=(reference,),
        created_at=NOW,
    )

    return UserTwinEvaluationRequest(
        evaluation_run_id=EVALUATION_RUN_ID,
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        artifact_bundle=bundle,
        twin=EvaluationUserTwinProfile(
            twin_id=TWIN_ID,
            version_number=1,
            name="Reservation operator",
            lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
            content_hash=profile_hash,
            snapshot_json=profile_snapshot,
        ),
        evidence=(),
        requested_at=NOW,
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
                TWIN_ID: (
                    FakeSyntheticFindingTemplate(
                        finding_id="UTF-840",
                        artifact_kind=EvaluationArtifactKind.DOM_SNAPSHOT,
                        location="browser:reservation/final-dom#confirm",
                        summary="The confirmation action should remain explicit.",
                        rationale=(
                            "The supplied verified DOM contains the primary reservation action."
                        ),
                        criterion=SyntheticFindingCriterion.ACTIONABILITY,
                        severity=SyntheticFindingSeverity.MINOR,
                        epistemic_status=(SyntheticFindingEpistemicStatus.MODEL_INFERRED),
                        evidence_refs=(ARTIFACT_CITATION,),
                        confidence=0.7,
                        recommended_action=("Preserve an explicit confirmation label."),
                        requires_human_validation=True,
                    ),
                )
            },
            summaries_by_twin={TWIN_ID: "One simulated design hypothesis was produced."},
            clock=lambda: NOW,
        )

        self.evaluators.append(evaluator)
        return evaluator


def test_service_authorizes_content_before_creating_and_invoking_evaluator() -> None:
    async def scenario() -> None:
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
        )
        factory = RecordingEvaluatorFactory()

        service = AuthorizedArtifactContentEvaluationService(
            resolver=OwnerScopedArtifactContentResolver(source),
            evaluator_factory=factory,
        )

        request = _request()

        response = await service.evaluate(
            owner_user_id=OWNER_ID,
            request=request,
            selected=((ARTIFACT_ID, 1),),
        )

        assert source.resolve_calls == [
            (
                OWNER_ID,
                PROJECT_ID,
                WORKFLOW_RUN_ID,
                ARTIFACT_ID,
                1,
            )
        ]
        assert len(source.read_calls) == 1

        assert len(factory.contexts) == 1
        context = factory.contexts[0]

        assert context.to_snapshot()["bundle_content_hash"] == request.artifact_bundle.content_hash

        assert len(factory.evaluators) == 1
        assert len(factory.evaluators[0].requests) == 1

        evaluated_request = factory.evaluators[0].requests[0]

        assert evaluated_request is not request
        assert evaluated_request.evidence[0].reference_id == ARTIFACT_CITATION
        assert response.findings[0].evidence_refs == (ARTIFACT_CITATION,)

    asyncio.run(scenario())


def test_unauthorized_content_never_reaches_evaluator_factory() -> None:
    async def scenario() -> None:
        source = RecordingOwnedArtifactSource(
            authorized_owner_id=OWNER_ID,
        )
        factory = RecordingEvaluatorFactory()

        service = AuthorizedArtifactContentEvaluationService(
            resolver=OwnerScopedArtifactContentResolver(source),
            evaluator_factory=factory,
        )

        with pytest.raises(ArtifactContentAuthorizationError) as captured:
            await service.evaluate(
                owner_user_id=OTHER_OWNER_ID,
                request=_request(),
                selected=((ARTIFACT_ID, 1),),
            )

        assert captured.value.code is ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED

        assert source.read_calls == []
        assert factory.contexts == []
        assert factory.evaluators == []

    asyncio.run(scenario())
