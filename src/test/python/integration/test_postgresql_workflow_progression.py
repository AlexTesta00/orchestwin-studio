"""PostgreSQL coverage for public LangGraph workflow progression commands."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr

from orchestwin.api.workflow_run_runtime import SqlAlchemyWorkflowRunApiService
from orchestwin.api.workflow_runs import (
    WorkflowRunAdvanceCommand,
    WorkflowRunApiStatus,
    WorkflowRunCreateCommand,
    WorkflowRunGateResumeCommand,
    WorkflowRunStartCommand,
)
from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateAction,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from orchestwin.workflow.langgraph_checkpointer import (
    RunScopedLangGraphCheckpointer,
    SqlAlchemyLangGraphCheckpointStore,
)
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from orchestwin.workflow.recovery import WorkflowRecoveryService, WorkflowRecoveryStatus
from orchestwin.workflow.run_persistence import SqlAlchemyWorkflowRunRepository
from orchestwin.workflow.runs import WorkflowStage

pytestmark = pytest.mark.integration

RUN_ID = UUID("95000000-0000-4000-8000-000000000101")
BRIEF_GATE_ID = UUID("95000000-0000-4000-8000-000000000102")
TEAM_GATE_ID = UUID("95000000-0000-4000-8000-000000000103")
BRIEF_ARTIFACT_ID = UUID("95000000-0000-4000-8000-000000000104")
TEAM_ARTIFACT_ID = UUID("95000000-0000-4000-8000-000000000105")
WRONG_DECISION_ID = UUID("95000000-0000-4000-8000-000000000199")


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def set(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


async def _create_owner_and_project(runtime):
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr(
                    "workflow-progression-integration-secret-more-than-32-characters"
                ),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )
    registered = await identity.register(
        email="workflow-progression-integration@example.com",
        password="correct horse battery staple progression",
    )
    assert registered.status is AuthenticationStatus.AUTHENTICATED
    assert registered.authenticated is not None
    owner = registered.authenticated.user

    projects = LocalProjectApplicationService(
        unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory)
    )
    project = await projects.create(
        owner_user_id=owner.id,
        display_name="Workflow progression PostgreSQL integration",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )
    return owner, project


async def _persist_pending_gate(
    runtime,
    *,
    owner_id: UUID,
    project_id: UUID,
    gate_id: UUID,
    gate_type: HumanGateType,
    artifact_id: UUID,
    artifact_hash: str,
    occurred_at: datetime,
):
    draft = create_human_gate(
        gate_id=gate_id,
        project_id=project_id,
        owner_user_id=owner_id,
        gate_type=gate_type,
        artifact=GateArtifactReference(
            project_id=project_id,
            gate_type=gate_type,
            artifact_id=artifact_id,
            version=1,
            content_hash=artifact_hash,
        ),
        created_at=occurred_at,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=owner_id,
        occurred_at=occurred_at,
    )
    assert submitted.status is HumanGateTransitionStatus.APPLIED
    assert submitted.event is not None
    async with runtime.session_factory.begin() as session:
        persisted = await SqlAlchemyHumanGateRepository(session).add_with_event(
            gate=submitted.gate,
            event=submitted.event,
        )
    assert persisted.status is HumanGateStatus.PENDING_APPROVAL
    return persisted


async def _approve_gate(
    runtime,
    *,
    owner_id: UUID,
    project_id: UUID,
    gate_type: HumanGateType,
    occurred_at: datetime,
):
    async with runtime.session_factory.begin() as session:
        repository = SqlAlchemyHumanGateRepository(session)
        gate = await repository.get_latest_owned_for_update(
            project_id=project_id,
            owner_user_id=owner_id,
            gate_type=gate_type,
        )
        assert gate is not None
        approved = transition_human_gate(
            gate,
            action=HumanGateAction.APPROVE,
            actor_user_id=owner_id,
            occurred_at=occurred_at,
        )
        assert approved.status is HumanGateTransitionStatus.APPLIED
        assert approved.event is not None
        persisted = await repository.save_transition(
            previous_gate=gate,
            updated_gate=approved.gate,
            event=approved.event,
        )
    assert persisted.status is HumanGateStatus.APPROVED
    return approved.event


async def _run_scenario() -> None:
    settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(settings)
    try:
        owner, project = await _create_owner_and_project(runtime)
        base = max(project.created_at, datetime.now(UTC)) + timedelta(seconds=1)
        clock = MutableClock(base)
        service = SqlAlchemyWorkflowRunApiService(
            runtime.session_factory,
            clock=clock,
        )

        created = await service.create_run(
            owner_user_id=owner.id,
            project_id=project.id,
            command=WorkflowRunCreateCommand(
                run_id=RUN_ID,
                project_mode=ProjectMode.GREENFIELD_GENERATION,
                created_at=project.created_at,
            ),
        )
        assert created.status is WorkflowRunApiStatus.RUN_CREATED

        clock.set(base + timedelta(seconds=1))
        started = await service.start_run(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunStartCommand(
                command_id=UUID(int=95101),
                project_id=project.id,
                expected_state_version=1,
                expected_checkpoint_sequence=0,
            ),
        )
        assert started.status is WorkflowRunApiStatus.COMMAND_APPLIED
        assert started.snapshot is not None
        assert started.snapshot["status"] == "RUNNING"
        assert started.snapshot["checkpoint_sequence"] == 1

        await _persist_pending_gate(
            runtime,
            owner_id=owner.id,
            project_id=project.id,
            gate_id=BRIEF_GATE_ID,
            gate_type=HumanGateType.PROJECT_BRIEF,
            artifact_id=BRIEF_ARTIFACT_ID,
            artifact_hash="a" * 64,
            occurred_at=base + timedelta(seconds=2),
        )

        clock.set(base + timedelta(seconds=3))
        waiting_brief = await service.advance_run(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunAdvanceCommand(
                command_id=UUID(int=95102),
                project_id=project.id,
                expected_state_version=2,
                expected_checkpoint_sequence=1,
                next_stage=WorkflowStage.BRIEF_APPROVAL,
                pending_gate_id=BRIEF_GATE_ID,
            ),
        )
        assert waiting_brief.status is WorkflowRunApiStatus.COMMAND_APPLIED
        assert waiting_brief.snapshot is not None
        assert waiting_brief.snapshot["status"] == "WAITING_FOR_HUMAN"

        clock.set(base + timedelta(seconds=4))
        denied_unapproved = await service.resume_after_gate(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunGateResumeCommand(
                project_id=project.id,
                expected_state_version=3,
                expected_checkpoint_sequence=2,
                gate_id=BRIEF_GATE_ID,
                decision_id=WRONG_DECISION_ID,
            ),
        )
        assert denied_unapproved.status is WorkflowRunApiStatus.AUTHORIZATION_REQUIRED

        brief_decision = await _approve_gate(
            runtime,
            owner_id=owner.id,
            project_id=project.id,
            gate_type=HumanGateType.PROJECT_BRIEF,
            occurred_at=base + timedelta(seconds=4),
        )

        clock.set(base + timedelta(seconds=5))
        resumed_brief = await service.resume_after_gate(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunGateResumeCommand(
                project_id=project.id,
                expected_state_version=3,
                expected_checkpoint_sequence=2,
                gate_id=BRIEF_GATE_ID,
                decision_id=brief_decision.id,
            ),
        )
        assert resumed_brief.status is WorkflowRunApiStatus.COMMAND_APPLIED

        clock.set(base + timedelta(seconds=6))
        team_selection = await service.advance_run(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunAdvanceCommand(
                command_id=UUID(int=95103),
                project_id=project.id,
                expected_state_version=4,
                expected_checkpoint_sequence=3,
                next_stage=WorkflowStage.TEAM_SELECTION,
                pending_gate_id=None,
            ),
        )
        assert team_selection.status is WorkflowRunApiStatus.COMMAND_APPLIED

        await _persist_pending_gate(
            runtime,
            owner_id=owner.id,
            project_id=project.id,
            gate_id=TEAM_GATE_ID,
            gate_type=HumanGateType.AGENT_TEAM,
            artifact_id=TEAM_ARTIFACT_ID,
            artifact_hash="b" * 64,
            occurred_at=base + timedelta(seconds=7),
        )

        clock.set(base + timedelta(seconds=8))
        waiting_team = await service.advance_run(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunAdvanceCommand(
                command_id=UUID(int=95104),
                project_id=project.id,
                expected_state_version=5,
                expected_checkpoint_sequence=4,
                next_stage=WorkflowStage.TEAM_APPROVAL,
                pending_gate_id=TEAM_GATE_ID,
            ),
        )
        assert waiting_team.status is WorkflowRunApiStatus.COMMAND_APPLIED

        team_decision = await _approve_gate(
            runtime,
            owner_id=owner.id,
            project_id=project.id,
            gate_type=HumanGateType.AGENT_TEAM,
            occurred_at=base + timedelta(seconds=9),
        )

        clock.set(base + timedelta(seconds=10))
        resumed_team = await service.resume_after_gate(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunGateResumeCommand(
                project_id=project.id,
                expected_state_version=6,
                expected_checkpoint_sequence=5,
                gate_id=TEAM_GATE_ID,
                decision_id=team_decision.id,
            ),
        )
        assert resumed_team.status is WorkflowRunApiStatus.COMMAND_APPLIED

        clock.set(base + timedelta(seconds=11))
        user_modeling = await service.advance_run(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            command=WorkflowRunAdvanceCommand(
                command_id=UUID(int=95105),
                project_id=project.id,
                expected_state_version=7,
                expected_checkpoint_sequence=6,
                next_stage=WorkflowStage.USER_MODELING,
                pending_gate_id=None,
            ),
        )
        assert user_modeling.status is WorkflowRunApiStatus.COMMAND_APPLIED
        assert user_modeling.snapshot is not None
        assert user_modeling.snapshot["current_stage"] == "USER_MODELING"
        assert user_modeling.snapshot["state_version"] == 8
        assert user_modeling.snapshot["checkpoint_sequence"] == 7

        checkpoints = await service.checkpoints(owner_user_id=owner.id, run_id=RUN_ID)
        events = await service.events(
            owner_user_id=owner.id,
            run_id=RUN_ID,
            after_sequence=0,
            limit=500,
        )
        assert len(checkpoints) == 7
        assert [event["event_type"] for event in events] == [
            "workflow.run.started",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.waiting_for_human",
            "workflow.checkpoint.created",
            "workflow.resumed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.waiting_for_human",
            "workflow.checkpoint.created",
            "workflow.resumed",
            "workflow.checkpoint.created",
            "workflow.stage.changed",
            "workflow.checkpoint.created",
        ]
        assert events[5]["payload"]["decision_id"] == str(brief_decision.id)
        assert events[12]["payload"]["decision_id"] == str(team_decision.id)

        async with runtime.session_factory() as session:
            runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner.id)
            checkpointer = RunScopedLangGraphCheckpointer(
                SqlAlchemyLangGraphCheckpointStore(runtime.session_factory),
                run_id=RUN_ID,
                project_id=project.id,
                owner_user_id=owner.id,
            )
            recovery = await WorkflowRecoveryService(runs, checkpointer).assess(run_id=RUN_ID)
        assert recovery.status is WorkflowRecoveryStatus.READY
        assert recovery.run is not None
        assert recovery.run.current_stage is WorkflowStage.USER_MODELING
    finally:
        await runtime.dispose()


def test_postgresql_public_progression_uses_langgraph_and_exact_gate_decisions() -> None:
    asyncio.run(_run_scenario(), loop_factory=asyncio.SelectorEventLoop)
