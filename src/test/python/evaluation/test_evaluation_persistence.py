"""Tests for append-only owner-scoped synthetic evaluation persistence."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.evaluation.application import (
    ApprovedUserTwinEvaluationTarget,
    IndependentUserTwinEvaluationService,
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
from orchestwin.evaluation.persistence import (
    InMemorySyntheticEvaluationRepository,
    SyntheticEvaluationStoreStatus,
    evaluation_run_record_to_domain,
    evaluation_run_to_record,
    synthetic_finding_record_to_domain,
    synthetic_finding_to_record,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

PROJECT_ID = UUID("00000000-0000-4000-8000-000000020001")
WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000020002")
OWNER_ID = UUID("00000000-0000-4000-8000-000000020003")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000020004")
TWIN_ID = UUID("00000000-0000-4000-8000-000000020005")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000020006")
NOW = datetime(2026, 8, 30, 20, 0, tzinfo=UTC)


def _times() -> Iterator[datetime]:
    yield NOW
    yield NOW + timedelta(seconds=2)


async def _evaluation_run():
    digest = "a" * 64
    bundle = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=UUID(int=20007),
            name="Review the final action",
            task="Determine whether the primary action is understandable.",
            locale="en",
            expected_outcomes=("The primary action is explicit.",),
        ),
        artifacts=(
            EvaluationArtifactReference(
                artifact_id=ARTIFACT_ID,
                version_number=2,
                kind=EvaluationArtifactKind.SCREENSHOT,
                media_type="image/png",
                sha256_digest=digest,
                size_bytes=100,
                storage_key=f"sha256/{digest[:2]}/{digest}",
                location="screen:final-review",
            ),
        ),
        created_at=NOW,
        bundle_id=UUID(int=20008),
    )
    snapshot, profile_hash = canonical_profile_snapshot(
        {"name": "Project owner", "role": "Project owner"}
    )
    twin = EvaluationUserTwinProfile(
        twin_id=TWIN_ID,
        version_number=2,
        name="Project owner",
        lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
        content_hash=profile_hash,
        snapshot_json=snapshot,
    )
    evidence = EvaluationEvidenceReference(
        reference_id="REQ-020",
        kind=EvaluationEvidenceKind.PROJECT_ARTIFACT,
        content_hash="b" * 64,
        locator="requirements:REQ-020",
    )
    configuration = UserTwinEvaluatorConfiguration(
        evaluator_id="fake.user-twin-evaluator",
        evaluator_version="1.0.0",
        model_config_ref="fake-model-v1",
        prompt_version_ref="ut-eval-v1",
    )
    adapter = FakeUserTwinEvaluator(
        configuration=configuration,
        templates_by_twin={
            TWIN_ID: (
                FakeSyntheticFindingTemplate(
                    finding_id="UTF-020",
                    artifact_kind=EvaluationArtifactKind.SCREENSHOT,
                    location="screen:final-review/action:approve",
                    summary="The final action label may be ambiguous.",
                    rationale="The supplied requirement calls for an explicit action.",
                    criterion=SyntheticFindingCriterion.ACTIONABILITY,
                    severity=SyntheticFindingSeverity.MODERATE,
                    epistemic_status=SyntheticFindingEpistemicStatus.MODEL_INFERRED,
                    evidence_refs=("REQ-020",),
                    confidence=0.7,
                    recommended_action="Label the action as Approve final output.",
                    requires_human_validation=True,
                ),
            )
        },
        summaries_by_twin={TWIN_ID: "One simulated actionability issue was identified."},
        clock=lambda: NOW + timedelta(seconds=1),
    )
    moments = _times()
    service = IndependentUserTwinEvaluationService(
        adapter,
        identifier_provider=lambda: EVALUATION_RUN_ID,
        clock=lambda: next(moments),
    )
    return await service.evaluate(
        owner_user_id=OWNER_ID,
        artifact_bundle=bundle,
        targets=(
            ApprovedUserTwinEvaluationTarget(
                twin=twin,
                evidence=(evidence,),
            ),
        ),
    )


def test_records_round_trip_run_projection_and_canonical_finding() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()
        stored = evaluation_run_record_to_domain(evaluation_run_to_record(run))
        finding = run.findings[0]
        restored_finding = synthetic_finding_record_to_domain(
            synthetic_finding_to_record(run, finding, sequence_number=1)
        )

        assert stored.id == run.id
        assert stored.content_hash == run.content_hash
        assert stored.response_count == 1
        assert stored.finding_count == 1
        assert restored_finding == finding

    asyncio.run(scenario())


def test_in_memory_repository_is_idempotent_and_owner_scoped() -> None:
    async def scenario() -> None:
        run = await _evaluation_run()
        repository = InMemorySyntheticEvaluationRepository(
            owner_user_id=OWNER_ID,
            workflow_run_projects={WORKFLOW_RUN_ID: PROJECT_ID},
        )

        created = await repository.append(run)
        repeated = await repository.append(run)

        assert created.status is SyntheticEvaluationStoreStatus.CREATED
        assert repeated.status is SyntheticEvaluationStoreStatus.ALREADY_PRESENT
        assert await repository.get_owned(run_id=run.id) == created.run
        assert await repository.list_findings(run_id=run.id) == run.findings

        foreign_repository = InMemorySyntheticEvaluationRepository(
            owner_user_id=UUID(int=20999),
            workflow_run_projects={WORKFLOW_RUN_ID: PROJECT_ID},
        )
        hidden = await foreign_repository.append(run)
        assert hidden.status is SyntheticEvaluationStoreStatus.WORKFLOW_RUN_NOT_FOUND
        assert await foreign_repository.get_owned(run_id=run.id) is None
        assert await foreign_repository.list_findings(run_id=run.id) == ()

    asyncio.run(scenario())
