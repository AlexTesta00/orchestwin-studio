"""PostgreSQL journey for persisted synthetic evaluation workflow completion."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr

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
from orchestwin.evaluation.authorized_persistence_application import (
    PersistedAuthorizedIndependentUserTwinEvaluationService,
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
    SqlAlchemySyntheticEvaluationRepository,
)
from orchestwin.evaluation.validation import (
    EvaluationEvidenceKind,
    EvaluationEvidenceReference,
)
from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import (
    Argon2PasswordService,
)
from orchestwin.identity.persistence import (
    SqlAlchemyIdentityUnitOfWorkFactory,
)
from orchestwin.identity.tokens import (
    AccessTokenSettings,
    JwtAccessTokenService,
)
from orchestwin.persistence import (
    create_database_runtime,
    load_database_settings,
)
from orchestwin.projects.application import (
    LocalProjectApplicationService,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import (
    SqlAlchemyProjectUnitOfWorkFactory,
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
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import (
    WorkflowRunStatus,
    WorkflowStage,
    create_workflow_run,
)
from orchestwin.workflow.synthetic_evaluation_stage import (
    SyntheticEvaluationStageService,
)

pytestmark = pytest.mark.integration

WORKFLOW_RUN_ID = UUID("00000000-0000-4000-8000-000000091101")
EVALUATION_RUN_ID = UUID("00000000-0000-4000-8000-000000091102")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000091103")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000091104")
BUNDLE_ID = UUID("00000000-0000-4000-8000-000000091105")
TWIN_ID = UUID("00000000-0000-4000-8000-000000091106")

BASE_TIME = datetime(
    2026,
    9,
    10,
    19,
    0,
    tzinfo=UTC,
)

CONTENT = b"<!doctype html><button id='confirm'>Confirm reservation</button>"


async def _create_scope(runtime):
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=(SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory)),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr(
                    "c91-postgresql-integration-secret-with-more-than-32-characters"
                ),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )

    projects = LocalProjectApplicationService(
        unit_of_work_factory=(SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory))
    )

    owner_result = await identity.register(
        email="c91-stage-owner@example.com",
        password="correct horse battery staple",
    )

    foreign_result = await identity.register(
        email="c91-stage-foreign@example.com",
        password="another correct battery staple",
    )

    assert owner_result.status is AuthenticationStatus.AUTHENTICATED

    assert foreign_result.status is AuthenticationStatus.AUTHENTICATED

    assert owner_result.authenticated is not None
    assert foreign_result.authenticated is not None

    owner = owner_result.authenticated.user
    foreign = foreign_result.authenticated.user

    project = await projects.create(
        owner_user_id=owner.id,
        display_name="C91 synthetic evaluation fixture",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )

    return owner, foreign, project


def _workflow(owner, project):
    draft = create_workflow_run(
        project_id=project.id,
        owner_user_id=owner.id,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=WORKFLOW_RUN_ID,
        created_at=BASE_TIME,
    )

    started = start_workflow_run(
        draft,
        occurred_at=BASE_TIME + timedelta(seconds=1),
    )

    assert started.status is WorkflowTransitionStatus.APPLIED

    execution = replace(
        started.run,
        current_stage=WorkflowStage.EXECUTION,
        updated_at=BASE_TIME + timedelta(seconds=2),
    )

    entered = advance_workflow_run(
        execution,
        next_stage=WorkflowStage.SYNTHETIC_EVALUATION,
        occurred_at=BASE_TIME + timedelta(seconds=3),
    )

    assert entered.status is WorkflowTransitionStatus.APPLIED

    return entered.run


async def _build_evaluation(owner, project):
    digest = hashlib.sha256(CONTENT).hexdigest()

    reference = EvaluationArtifactReference(
        artifact_id=ARTIFACT_ID,
        version_number=1,
        kind=EvaluationArtifactKind.DOM_SNAPSHOT,
        media_type="text/html",
        sha256_digest=digest,
        size_bytes=len(CONTENT),
        storage_key=(f"sha256/{digest[:2]}/{digest}"),
        location="browser:c91-postgresql#confirm",
    )

    bundle = create_evaluation_artifact_bundle(
        project_id=project.id,
        workflow_run_id=WORKFLOW_RUN_ID,
        scenario=EvaluationScenario(
            id=SCENARIO_ID,
            name="Reservation confirmation",
            task=("Review whether the reservation confirmation action is explicit."),
            locale="en",
            expected_outcomes=("The confirmation action remains explicit.",),
        ),
        artifacts=(reference,),
        created_at=BASE_TIME + timedelta(seconds=4),
        bundle_id=BUNDLE_ID,
    )

    snapshot, profile_hash = canonical_profile_snapshot(
        {
            "name": "Reservation operator",
            "role": "Completes reservations",
            "goals": ["Confirm reservations without ambiguity"],
        }
    )

    twin = EvaluationUserTwinProfile(
        twin_id=TWIN_ID,
        version_number=1,
        name="Reservation operator",
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

    target = ApprovedUserTwinEvaluationTarget(
        twin=twin,
        evidence=(evidence,),
    )

    configuration = UserTwinEvaluatorConfiguration(
        evaluator_id="test.c91-postgresql",
        evaluator_version="1.0.0",
        model_config_ref="test-c91-model",
        prompt_version_ref="test-c91-prompt",
    )

    evaluator = FakeUserTwinEvaluator(
        configuration=configuration,
        templates_by_twin={
            TWIN_ID: (
                FakeSyntheticFindingTemplate(
                    finding_id="UTF-911",
                    artifact_kind=(EvaluationArtifactKind.DOM_SNAPSHOT),
                    location=("browser:c91-postgresql#confirm"),
                    summary=("The confirmation action should remain explicit."),
                    rationale=("The supplied project evidence requires an explicit action."),
                    criterion=(SyntheticFindingCriterion.ACTIONABILITY),
                    severity=(SyntheticFindingSeverity.MINOR),
                    epistemic_status=(SyntheticFindingEpistemicStatus.MODEL_INFERRED),
                    evidence_refs=("REQ-091",),
                    confidence=0.7,
                    recommended_action=("Preserve the explicit confirmation label."),
                    requires_human_validation=True,
                ),
            ),
        },
        summaries_by_twin={
            TWIN_ID: ("One simulated design hypothesis was generated."),
        },
        clock=lambda: BASE_TIME + timedelta(seconds=7),
    )

    moments = iter(
        (
            BASE_TIME + timedelta(seconds=6),
            BASE_TIME + timedelta(seconds=8),
        )
    )

    service = IndependentUserTwinEvaluationService(
        evaluator,
        identifier_provider=lambda: EVALUATION_RUN_ID,
        clock=lambda: next(moments),
    )

    run = await service.evaluate(
        owner_user_id=owner.id,
        artifact_bundle=bundle,
        targets=(target,),
    )

    return bundle, target, run


class ReturningAuthorizedEvaluationService:
    """Deterministic stand-in for the already-tested C89 boundary."""

    def __init__(self, run) -> None:
        self._run = run
        self.calls = 0

    async def evaluate(
        self,
        *,
        owner_user_id,
        artifact_bundle,
        targets,
        selected,
    ):
        self.calls += 1

        assert owner_user_id == self._run.owner_user_id

        assert artifact_bundle.project_id == self._run.project_id

        assert artifact_bundle.workflow_run_id == self._run.workflow_run_id

        assert tuple(targets)
        assert selected == ((ARTIFACT_ID, 1),)

        return self._run


def test_postgresql_persists_evaluation_and_checkpoints_revision_stage() -> None:
    async def scenario() -> None:
        settings = load_database_settings(env_file=None)

        runtime = create_database_runtime(settings)

        try:
            owner, foreign, project = await _create_scope(runtime)

            workflow = _workflow(owner, project)

            bundle, target, evaluation_run = await _build_evaluation(
                owner,
                project,
            )

            delegate = ReturningAuthorizedEvaluationService(evaluation_run)

            async with runtime.session_factory.begin() as session:
                workflow_repository = SqlAlchemyWorkflowRunRepository(
                    session,
                    owner_user_id=owner.id,
                )

                evaluation_repository = SqlAlchemySyntheticEvaluationRepository(
                    session,
                    owner_user_id=owner.id,
                )

                created = await workflow_repository.create(workflow)

                assert created.status is WorkflowRunStoreStatus.CREATED

                persisted_evaluation = PersistedAuthorizedIndependentUserTwinEvaluationService(
                    evaluation_service=delegate,
                    repository=evaluation_repository,
                )

                stage = SyntheticEvaluationStageService(
                    workflow_repository=workflow_repository,
                    evaluation_service=persisted_evaluation,
                )

                result = await stage.execute(
                    owner_user_id=owner.id,
                    project_id=project.id,
                    run_id=WORKFLOW_RUN_ID,
                    expected_state_version=(workflow.state_version),
                    artifact_bundle=bundle,
                    targets=(target,),
                    selected=((ARTIFACT_ID, 1),),
                )

                assert delegate.calls == 1

                assert result.evaluation_run == evaluation_run

                assert result.run.current_stage is WorkflowStage.REVISION_DECISION

                assert result.run.status is WorkflowRunStatus.RUNNING

                assert result.run.latest_evaluation_run_id == EVALUATION_RUN_ID

                assert result.run.state_version == workflow.state_version + 1

                assert result.run.checkpoint_sequence == 1

                references = tuple(
                    item
                    for item in result.run.artifact_references
                    if item.artifact_type == "SYNTHETIC_EVALUATION"
                )

                assert len(references) == 1

                assert references[0].artifact_id == EVALUATION_RUN_ID

                assert references[0].version_number == 1

                assert references[0].content_hash == evaluation_run.content_hash

            # New transaction proves the complete journey survived commit.
            async with runtime.session_factory() as session:
                workflow_repository = SqlAlchemyWorkflowRunRepository(
                    session,
                    owner_user_id=owner.id,
                )

                evaluation_repository = SqlAlchemySyntheticEvaluationRepository(
                    session,
                    owner_user_id=owner.id,
                )

                restored = await workflow_repository.get_owned(run_id=WORKFLOW_RUN_ID)

                assert restored is not None

                assert restored.current_stage is WorkflowStage.REVISION_DECISION

                assert restored.latest_evaluation_run_id == EVALUATION_RUN_ID

                checkpoints = await workflow_repository.list_checkpoints(run_id=WORKFLOW_RUN_ID)

                assert len(checkpoints) == 1

                assert checkpoints[0].state_version == restored.state_version

                stored_evaluation = await evaluation_repository.get_owned(run_id=EVALUATION_RUN_ID)

                assert stored_evaluation is not None

                assert stored_evaluation.content_hash == evaluation_run.content_hash

                assert stored_evaluation.workflow_run_id == WORKFLOW_RUN_ID

                assert (
                    await evaluation_repository.list_findings(run_id=EVALUATION_RUN_ID)
                    == evaluation_run.findings
                )

            # Owner isolation survives a fresh repository construction.
            async with runtime.session_factory() as session:
                foreign_workflows = SqlAlchemyWorkflowRunRepository(
                    session,
                    owner_user_id=foreign.id,
                )

                foreign_evaluations = SqlAlchemySyntheticEvaluationRepository(
                    session,
                    owner_user_id=foreign.id,
                )

                assert await foreign_workflows.get_owned(run_id=WORKFLOW_RUN_ID) is None

                assert await foreign_evaluations.get_owned(run_id=EVALUATION_RUN_ID) is None

                assert await foreign_evaluations.list_findings(run_id=EVALUATION_RUN_ID) == ()

        finally:
            await runtime.dispose()

    asyncio.run(
        scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
