"""Bind one persisted synthetic evaluation to its durable workflow stage."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

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
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
)
from orchestwin.twins.user_twins import (
    UserTwinLifecycleStatus,
)
from orchestwin.workflow.routing import (
    WorkflowTransitionStatus,
    advance_workflow_run,
    start_workflow_run,
)
from orchestwin.workflow.run_persistence import (
    InMemoryWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import (
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)
from orchestwin.workflow.synthetic_evaluation_stage import (
    SyntheticEvaluationStageError,
    SyntheticEvaluationStageIssueCode,
    SyntheticEvaluationStageService,
)


class RecordingPersistedEvaluationService:
    def __init__(self, evaluation_run) -> None:
        self.evaluation_run = evaluation_run
        self.calls = []

    async def evaluate(
        self,
        *,
        owner_user_id,
        artifact_bundle,
        targets,
        selected,
    ):
        self.calls.append(
            {
                "owner_user_id": owner_user_id,
                "artifact_bundle": artifact_bundle,
                "targets": tuple(targets),
                "selected": selected,
            }
        )

        return self.evaluation_run


def _workflow_at_synthetic_evaluation(evaluation_run):
    created_at = evaluation_run.started_at - timedelta(seconds=10)

    draft = create_workflow_run(
        project_id=evaluation_run.project_id,
        owner_user_id=evaluation_run.owner_user_id,
        project_mode=(evaluation_run_to_project_mode()),
        run_id=evaluation_run.workflow_run_id,
        created_at=created_at,
    )

    started = start_workflow_run(
        draft,
        occurred_at=created_at + timedelta(seconds=1),
    )

    assert started.status is WorkflowTransitionStatus.APPLIED

    execution = replace(
        started.run,
        current_stage=WorkflowStage.EXECUTION,
        updated_at=created_at + timedelta(seconds=2),
    )

    entered = advance_workflow_run(
        execution,
        next_stage=WorkflowStage.SYNTHETIC_EVALUATION,
        occurred_at=created_at + timedelta(seconds=3),
    )

    assert entered.status is WorkflowTransitionStatus.APPLIED

    return entered.run


def evaluation_run_to_project_mode():
    from orchestwin.projects.domain import ProjectMode

    return ProjectMode.GREENFIELD_GENERATION


EVALUATION_PROJECT_ID = UUID("00000000-0000-4000-8000-000000091001")
EVALUATION_WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000091002")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000091003")
EVALUATION_TWIN_ID = UUID("00000000-0000-4000-8000-000000091004")
EVALUATION_ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000091005")
EVALUATION_SCENARIO_ID = UUID("00000000-0000-4000-8000-000000091006")
EVALUATION_BUNDLE_ID = UUID("00000000-0000-4000-8000-000000091007")

EVALUATION_NOW = datetime(
    2026,
    9,
    10,
    18,
    0,
    tzinfo=UTC,
)


async def _evaluation_run():
    digest = "a" * 64

    bundle = create_evaluation_artifact_bundle(
        project_id=EVALUATION_PROJECT_ID,
        workflow_run_id=EVALUATION_WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=EVALUATION_SCENARIO_ID,
            name="Review final action",
            task=("Determine whether the primary action is understandable."),
            locale="en",
            expected_outcomes=("The primary action is explicit.",),
        ),
        artifacts=(
            EvaluationArtifactReference(
                artifact_id=EVALUATION_ARTIFACT_ID,
                version_number=1,
                kind=EvaluationArtifactKind.SCREENSHOT,
                media_type="image/png",
                sha256_digest=digest,
                size_bytes=100,
                storage_key=(f"sha256/{digest[:2]}/{digest}"),
                location="screen:c91/final-review",
            ),
        ),
        created_at=EVALUATION_NOW,
        bundle_id=EVALUATION_BUNDLE_ID,
    )

    snapshot, profile_hash = canonical_profile_snapshot(
        {
            "name": "C91 project owner",
            "role": "Project owner",
        }
    )

    twin = EvaluationUserTwinProfile(
        twin_id=EVALUATION_TWIN_ID,
        version_number=1,
        name="C91 project owner",
        lifecycle_status=(UserTwinLifecycleStatus.OWNER_APPROVED_UT),
        content_hash=profile_hash,
        snapshot_json=snapshot,
    )

    evidence = EvaluationEvidenceReference(
        reference_id="REQ-091",
        kind=EvaluationEvidenceKind.PROJECT_ARTIFACT,
        content_hash="b" * 64,
        locator="requirements:REQ-091",
    )

    configuration = UserTwinEvaluatorConfiguration(
        evaluator_id="test.c91-evaluator",
        evaluator_version="1.0.0",
        model_config_ref="test-c91-model",
        prompt_version_ref="test-c91-prompt",
    )

    evaluator = FakeUserTwinEvaluator(
        configuration=configuration,
        templates_by_twin={
            EVALUATION_TWIN_ID: (
                FakeSyntheticFindingTemplate(
                    finding_id="UTF-091",
                    artifact_kind=(EvaluationArtifactKind.SCREENSHOT),
                    location=("screen:c91/final-review#action"),
                    summary=("The primary action should remain explicit."),
                    rationale=("The supplied project evidence requires an explicit action."),
                    criterion=(SyntheticFindingCriterion.ACTIONABILITY),
                    severity=(SyntheticFindingSeverity.MINOR),
                    epistemic_status=(SyntheticFindingEpistemicStatus.MODEL_INFERRED),
                    evidence_refs=("REQ-091",),
                    confidence=0.7,
                    recommended_action=("Preserve an explicit action label."),
                    requires_human_validation=True,
                ),
            ),
        },
        summaries_by_twin={
            EVALUATION_TWIN_ID: ("One simulated design hypothesis was produced."),
        },
        clock=lambda: EVALUATION_NOW + timedelta(seconds=1),
    )

    moments = iter(
        (
            EVALUATION_NOW,
            EVALUATION_NOW + timedelta(seconds=2),
        )
    )

    service = IndependentUserTwinEvaluationService(
        evaluator,
        identifier_provider=lambda: EVALUATION_RUN_ID,
        clock=lambda: next(moments),
    )

    return await service.evaluate(
        owner_user_id=UUID("00000000-0000-4000-8000-000000091008"),
        artifact_bundle=bundle,
        targets=(
            ApprovedUserTwinEvaluationTarget(
                twin=twin,
                evidence=(evidence,),
            ),
        ),
    )


def _bundle_stub(evaluation_run):
    return SimpleNamespace(
        id=evaluation_run.artifact_bundle_id,
        content_hash=evaluation_run.artifact_bundle_hash,
        project_id=evaluation_run.project_id,
        workflow_run_id=evaluation_run.workflow_run_id,
    )


def test_stage_binds_persisted_evaluation_and_advances_to_revision() -> None:
    async def scenario() -> None:
        evaluation_run = await _evaluation_run()

        workflow = _workflow_at_synthetic_evaluation(evaluation_run)

        repository = InMemoryWorkflowRunRepository(
            owner_user_id=workflow.owner_user_id,
            project_ids=frozenset({workflow.project_id}),
        )

        created = await repository.create(workflow)

        assert created.status is WorkflowRunStoreStatus.CREATED

        delegate = RecordingPersistedEvaluationService(evaluation_run)

        service = SyntheticEvaluationStageService(
            workflow_repository=repository,
            evaluation_service=delegate,
        )

        result = await service.execute(
            owner_user_id=workflow.owner_user_id,
            project_id=workflow.project_id,
            run_id=workflow.id,
            expected_state_version=(workflow.state_version),
            artifact_bundle=(_bundle_stub(evaluation_run)),
            targets=(),
            selected=(),
        )

        assert result.evaluation_run == evaluation_run

        assert result.run.current_stage is WorkflowStage.REVISION_DECISION

        assert result.run.status is WorkflowRunStatus.RUNNING

        assert result.run.latest_evaluation_run_id == evaluation_run.id

        assert result.run.state_version == workflow.state_version + 1

        assert result.run.checkpoint_sequence == 1

        evaluation_references = tuple(
            reference
            for reference in result.run.artifact_references
            if reference.artifact_type == "SYNTHETIC_EVALUATION"
        )

        assert len(evaluation_references) == 1

        reference = evaluation_references[0]

        assert reference.artifact_id == evaluation_run.id
        assert reference.version_number == 1

        assert reference.content_hash == evaluation_run.content_hash

        stored = await repository.get_owned(run_id=workflow.id)

        assert stored == result.run

        checkpoints = await repository.list_checkpoints(run_id=workflow.id)

        assert len(checkpoints) == 1

        assert checkpoints[0].state_version == result.run.state_version

        assert len(delegate.calls) == 1

    asyncio.run(scenario())


def test_wrong_stage_stops_before_evaluation() -> None:
    async def scenario() -> None:
        evaluation_run = await _evaluation_run()

        workflow = _workflow_at_synthetic_evaluation(evaluation_run)

        workflow = replace(
            workflow,
            current_stage=WorkflowStage.EXECUTION,
        )

        repository = InMemoryWorkflowRunRepository(
            owner_user_id=workflow.owner_user_id,
            project_ids=frozenset({workflow.project_id}),
        )

        assert (await repository.create(workflow)).status is WorkflowRunStoreStatus.CREATED

        delegate = RecordingPersistedEvaluationService(evaluation_run)

        service = SyntheticEvaluationStageService(
            workflow_repository=repository,
            evaluation_service=delegate,
        )

        with pytest.raises(SyntheticEvaluationStageError) as captured:
            await service.execute(
                owner_user_id=workflow.owner_user_id,
                project_id=workflow.project_id,
                run_id=workflow.id,
                expected_state_version=(workflow.state_version),
                artifact_bundle=(_bundle_stub(evaluation_run)),
                targets=(),
                selected=(),
            )

        assert captured.value.code is (SyntheticEvaluationStageIssueCode.WRONG_STAGE)

        assert delegate.calls == []

    asyncio.run(scenario())


def test_stale_state_and_wrong_bundle_scope_fail_before_evaluation() -> None:
    async def scenario() -> None:
        evaluation_run = await _evaluation_run()

        workflow = _workflow_at_synthetic_evaluation(evaluation_run)

        repository = InMemoryWorkflowRunRepository(
            owner_user_id=workflow.owner_user_id,
            project_ids=frozenset({workflow.project_id}),
        )

        assert (await repository.create(workflow)).status is WorkflowRunStoreStatus.CREATED

        delegate = RecordingPersistedEvaluationService(evaluation_run)

        service = SyntheticEvaluationStageService(
            workflow_repository=repository,
            evaluation_service=delegate,
        )

        with pytest.raises(SyntheticEvaluationStageError) as stale:
            await service.execute(
                owner_user_id=workflow.owner_user_id,
                project_id=workflow.project_id,
                run_id=workflow.id,
                expected_state_version=(workflow.state_version + 1),
                artifact_bundle=(_bundle_stub(evaluation_run)),
                targets=(),
                selected=(),
            )

        assert stale.value.code is (SyntheticEvaluationStageIssueCode.STATE_VERSION_CONFLICT)

        wrong_bundle = SimpleNamespace(
            project_id=workflow.project_id,
            workflow_run_id=uuid4(),
        )

        with pytest.raises(SyntheticEvaluationStageError) as scope:
            await service.execute(
                owner_user_id=workflow.owner_user_id,
                project_id=workflow.project_id,
                run_id=workflow.id,
                expected_state_version=(workflow.state_version),
                artifact_bundle=wrong_bundle,
                targets=(),
                selected=(),
            )

        assert scope.value.code is (SyntheticEvaluationStageIssueCode.EVALUATION_SCOPE_MISMATCH)

        assert delegate.calls == []

    asyncio.run(scenario())
