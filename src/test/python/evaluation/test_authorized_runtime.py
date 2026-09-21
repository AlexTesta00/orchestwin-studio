"""Runtime composition for the authorized final User Twin evaluator."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
)
from orchestwin.evaluation.artifact_content_registry import (
    ArtifactContentRegistryStoreStatus,
    AuthorizedEvaluationArtifactRecord,
    InMemoryAuthorizedEvaluationArtifactRegistry,
)
from orchestwin.evaluation.artifact_content_resolution import (
    ArtifactContentAuthorizationError,
    ArtifactContentAuthorizationIssueCode,
)
from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)
from orchestwin.evaluation.authorized_runtime import (
    build_authorized_independent_evaluation_service,
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
from orchestwin.twins.user_twins import (
    UserTwinLifecycleStatus,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000089001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000089002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000089003")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000089004")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000089005")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000089006")
TWIN_ID = UUID("00000000-0000-4000-8000-000000089007")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000089008")

NOW = datetime(2026, 9, 10, 17, 0, tzinfo=UTC)

CONTENT = b"<!doctype html><button id='confirm'>Confirm reservation</button>"

DIGEST = hashlib.sha256(CONTENT).hexdigest()

ARTIFACT_CITATION = f"artifact:{ARTIFACT_ID}:v1"

CONFIGURATION = UserTwinEvaluatorConfiguration(
    evaluator_id="test.final-runtime-composition",
    evaluator_version="1.0.0",
    model_config_ref="test-final-adapter",
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
        storage_key=(f"sha256/{DIGEST[:2]}/{DIGEST}"),
        location="browser:runtime/final-dom",
    )


def _bundle():
    return create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=SCENARIO_ID,
            name="Reservation confirmation",
            task=("Review the reservation confirmation interface."),
            locale="en",
            expected_outcomes=("The confirmation action is explicit.",),
        ),
        artifacts=(_reference(),),
        created_at=NOW,
    )


def _profile() -> EvaluationUserTwinProfile:
    snapshot, digest = canonical_profile_snapshot(
        {
            "name": "Reservation operator",
            "role": "Completes reservations",
            "goals": ["Confirm reservations without ambiguity"],
        }
    )

    return EvaluationUserTwinProfile(
        twin_id=TWIN_ID,
        version_number=1,
        name="Reservation operator",
        lifecycle_status=(UserTwinLifecycleStatus.OWNER_APPROVED_UT),
        content_hash=digest,
        snapshot_json=snapshot,
    )


def _target() -> ApprovedUserTwinEvaluationTarget:
    return ApprovedUserTwinEvaluationTarget(
        twin=_profile(),
        evidence=(),
    )


def _template() -> FakeSyntheticFindingTemplate:
    return FakeSyntheticFindingTemplate(
        finding_id="UTF-891",
        artifact_kind=(EvaluationArtifactKind.DOM_SNAPSHOT),
        location=("browser:runtime/final-dom#confirm"),
        summary=("The confirmation action should remain explicit."),
        rationale=("The verified DOM supplies an explicit reservation confirmation action."),
        criterion=(SyntheticFindingCriterion.ACTIONABILITY),
        severity=SyntheticFindingSeverity.MINOR,
        epistemic_status=(SyntheticFindingEpistemicStatus.MODEL_INFERRED),
        evidence_refs=(ARTIFACT_CITATION,),
        confidence=0.7,
        recommended_action=("Preserve the explicit confirmation label."),
        requires_human_validation=True,
    )


class RecordingFinalEvaluatorRuntime:
    """Test double for FinalEvaluatorRuntime.create_evaluator."""

    def __init__(self) -> None:
        self.contexts = []
        self.evaluators = []

    def create_evaluator(
        self,
        *,
        verified_content,
    ):
        self.contexts.append(verified_content)

        evaluator = FakeUserTwinEvaluator(
            configuration=CONFIGURATION,
            templates_by_twin={
                TWIN_ID: (_template(),),
            },
            summaries_by_twin={
                TWIN_ID: ("One simulated design hypothesis was generated."),
            },
            clock=lambda: NOW + timedelta(seconds=1),
        )

        self.evaluators.append(evaluator)

        return evaluator


class RecordingReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def __call__(
        self,
        storage_key: str,
        maximum_bytes: int,
    ) -> bytes:
        self.calls.append(
            (
                storage_key,
                maximum_bytes,
            )
        )

        return CONTENT


def _times() -> Iterator[datetime]:
    yield NOW
    yield NOW + timedelta(seconds=2)


def test_runtime_composes_registry_authorization_with_final_factory() -> None:
    async def scenario() -> None:
        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        status = await registry.append(
            AuthorizedEvaluationArtifactRecord(
                owner_user_id=OWNER_ID,
                project_id=PROJECT_ID,
                workflow_run_id=WORKFLOW_RUN_ID,
                reference=_reference(),
            )
        )

        assert status is ArtifactContentRegistryStoreStatus.CREATED

        reader = RecordingReader()
        runtime = RecordingFinalEvaluatorRuntime()
        moments = _times()

        service = build_authorized_independent_evaluation_service(
            registry=registry,
            read_content=reader,
            final_evaluator_runtime=runtime,
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: next(moments),
        )

        assert service is not None

        result = await service.evaluate(
            owner_user_id=OWNER_ID,
            artifact_bundle=_bundle(),
            targets=(_target(),),
            selected=((ARTIFACT_ID, 1),),
        )

        assert result.id == EVALUATION_RUN_ID
        assert result.owner_user_id == OWNER_ID
        assert result.project_id == PROJECT_ID
        assert result.workflow_run_id == WORKFLOW_RUN_ID
        assert result.evaluator == CONFIGURATION

        assert len(runtime.contexts) == 1
        assert len(runtime.evaluators) == 1

        prepared_request = runtime.evaluators[0].requests[0]

        assert prepared_request.evidence[0].reference_id == ARTIFACT_CITATION

        assert len(reader.calls) == 1

        assert [finding.finding_id for finding in result.findings] == ["UTF-891"]

        context = runtime.contexts[0].to_snapshot()

        assert context["bundle_content_hash"] == result.artifact_bundle_hash

        assert context["items"][0]["data"] == CONTENT.decode("utf-8")

    asyncio.run(scenario())


def test_wrong_owner_stops_before_read_or_final_factory() -> None:
    async def scenario() -> None:
        registry = InMemoryAuthorizedEvaluationArtifactRegistry()

        await registry.append(
            AuthorizedEvaluationArtifactRecord(
                owner_user_id=OWNER_ID,
                project_id=PROJECT_ID,
                workflow_run_id=WORKFLOW_RUN_ID,
                reference=_reference(),
            )
        )

        reader = RecordingReader()
        runtime = RecordingFinalEvaluatorRuntime()

        service = build_authorized_independent_evaluation_service(
            registry=registry,
            read_content=reader,
            final_evaluator_runtime=runtime,
            identifier_provider=lambda: EVALUATION_RUN_ID,
            clock=lambda: NOW,
        )

        assert service is not None

        with pytest.raises(ArtifactContentAuthorizationError) as captured:
            await service.evaluate(
                owner_user_id=OTHER_OWNER_ID,
                artifact_bundle=_bundle(),
                targets=(_target(),),
                selected=((ARTIFACT_ID, 1),),
            )

        assert captured.value.code is ArtifactContentAuthorizationIssueCode.ARTIFACT_NOT_AUTHORIZED

        assert reader.calls == []
        assert runtime.contexts == []
        assert runtime.evaluators == []

    asyncio.run(scenario())


def test_disabled_final_runtime_exposes_no_evaluation_service() -> None:
    registry = InMemoryAuthorizedEvaluationArtifactRegistry()

    reader = RecordingReader()

    service = build_authorized_independent_evaluation_service(
        registry=registry,
        read_content=reader,
        final_evaluator_runtime=None,
        identifier_provider=lambda: EVALUATION_RUN_ID,
        clock=lambda: NOW,
    )

    assert service is None
    assert reader.calls == []
