"""PostgreSQL integration coverage for durable workflow recovery and events."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from orchestwin.identity.application import AuthenticationStatus, LocalIdentityApplicationService
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.migrate import create_alembic_config
from orchestwin.projects.application import LocalProjectApplicationService
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence import SqlAlchemyProjectUnitOfWorkFactory
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.event_persistence import (
    SqlAlchemyWorkflowEventRepository,
    WorkflowEventAppendStatus,
)
from orchestwin.workflow.events import WorkflowEventType, create_workflow_event
from orchestwin.workflow.langgraph_checkpointer import (
    RunScopedLangGraphCheckpointer,
    SqlAlchemyLangGraphCheckpointStore,
)
from orchestwin.workflow.langgraph_graph import (
    WorkflowGraphStep,
    WorkflowGraphStepKind,
    build_governed_workflow_graph,
    create_workflow_gate_resume_command,
)
from orchestwin.workflow.recovery import WorkflowRecoveryService, WorkflowRecoveryStatus
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.run_persistence import (
    SqlAlchemyWorkflowRunRepository,
    WorkflowRunStoreStatus,
)
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage, create_workflow_run

pytestmark = pytest.mark.integration

RUN_ID = UUID("94000000-0000-4000-8000-000000000101")
GATE_ID = UUID("94000000-0000-4000-8000-000000000102")
DECISION_ID = UUID("94000000-0000-4000-8000-000000000103")
CHECKPOINT_IDS = (
    UUID("94000000-0000-4000-8000-000000000111"),
    UUID("94000000-0000-4000-8000-000000000112"),
    UUID("94000000-0000-4000-8000-000000000113"),
)
EVENT_IDS = (
    UUID("94000000-0000-4000-8000-000000000121"),
    UUID("94000000-0000-4000-8000-000000000122"),
    UUID("94000000-0000-4000-8000-000000000123"),
)
BASE_TIME = datetime(2026, 8, 28, 23, 40, tzinfo=UTC)


async def truncate_application_data(runtime) -> None:
    """Reset owner-scoped rows while preserving the migrated schema."""
    async with runtime.engine.begin() as connection:
        await connection.execute(text("TRUNCATE TABLE users CASCADE"))


async def mutation_is_rejected(runtime, statement: str, identifier: UUID) -> bool:
    """Return whether an append-only database row rejected direct mutation."""
    try:
        async with runtime.session_factory.begin() as session:
            await session.execute(text(statement), {"identifier": identifier})
    except DBAPIError:
        return True
    return False


async def create_owner_and_project(runtime):
    """Create two owners and one project through the public application services."""
    identity = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(runtime.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr(
                    "workflow-integration-jwt-secret-with-more-than-32-characters"
                ),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )
    projects = LocalProjectApplicationService(
        unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(runtime.session_factory)
    )
    owner_result = await identity.register(
        email="sprint-ten-owner@example.com",
        password="correct horse battery staple",
    )
    foreign_result = await identity.register(
        email="sprint-ten-foreign@example.com",
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
        display_name="Sprint 10 durable workflow fixture",
        mode=ProjectMode.GREENFIELD_GENERATION,
    )
    return owner, foreign, project


async def persist_interrupted_run(runtime, *, owner, project):
    """Persist application state, graph interrupts, and the first replay events."""
    draft = create_workflow_run(
        project_id=project.id,
        owner_user_id=owner.id,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        run_id=RUN_ID,
        created_at=BASE_TIME,
    )
    started = start_workflow_run(
        draft,
        occurred_at=BASE_TIME + timedelta(seconds=1),
    ).run
    started_checkpoint = create_workflow_checkpoint(
        started,
        created_at=BASE_TIME + timedelta(seconds=1),
        checkpoint_id=CHECKPOINT_IDS[0],
    )

    async with runtime.session_factory.begin() as session:
        runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner.id)
        events = SqlAlchemyWorkflowEventRepository(session, owner_user_id=owner.id)
        created = await runs.create(draft)
        assert created.status is WorkflowRunStoreStatus.CREATED
        saved_started = await runs.save_checkpoint(
            previous_run=draft,
            creation=started_checkpoint,
        )
        assert saved_started.status is WorkflowRunStoreStatus.UPDATED

        graph_store = SqlAlchemyLangGraphCheckpointStore(session)
        graph = build_governed_workflow_graph(
            checkpointer=RunScopedLangGraphCheckpointer(
                graph_store,
                run_id=RUN_ID,
                project_id=project.id,
                owner_user_id=owner.id,
            )
        )
        interrupted = await graph.ainvoke(
            {
                "run": started_checkpoint.run,
                "step": WorkflowGraphStep(
                    kind=WorkflowGraphStepKind.ADVANCE,
                    occurred_at=BASE_TIME + timedelta(seconds=2),
                    next_stage=WorkflowStage.BRIEF_APPROVAL,
                    pending_gate_id=GATE_ID,
                ),
                "trace": (),
            },
            config={"configurable": {"thread_id": str(RUN_ID)}},
        )
        pending_interrupt = interrupted["__interrupt__"][0]
        assert pending_interrupt.value["gate_id"] == str(GATE_ID)
        waiting_checkpoint = create_workflow_checkpoint(
            interrupted["run"],
            previous_checkpoint=started_checkpoint.checkpoint,
            created_at=BASE_TIME + timedelta(seconds=2),
            checkpoint_id=CHECKPOINT_IDS[1],
        )
        saved_waiting = await runs.save_checkpoint(
            previous_run=started_checkpoint.run,
            creation=waiting_checkpoint,
        )
        assert saved_waiting.status is WorkflowRunStoreStatus.UPDATED

        started_event = create_workflow_event(
            started_checkpoint.run,
            previous_run=draft,
            event_type=WorkflowEventType.RUN_STARTED,
            sequence_number=1,
            occurred_at=BASE_TIME + timedelta(seconds=1),
            event_id=EVENT_IDS[0],
        )
        waiting_event = create_workflow_event(
            waiting_checkpoint.run,
            previous_run=started_checkpoint.run,
            event_type=WorkflowEventType.WAITING_FOR_HUMAN,
            sequence_number=2,
            occurred_at=BASE_TIME + timedelta(seconds=2),
            event_id=EVENT_IDS[1],
        )
        assert (
            await events.append(started_event, expected_previous_sequence=0)
        ).status is WorkflowEventAppendStatus.APPENDED
        assert (
            await events.append(waiting_event, expected_previous_sequence=1)
        ).status is WorkflowEventAppendStatus.APPENDED

    return waiting_checkpoint, pending_interrupt.id


async def recover_and_resume(
    runtime,
    *,
    owner,
    project,
    waiting_checkpoint,
    interrupt_id: str,
):
    """Recreate the process, reconcile checkpoints, and resume the exact interrupt."""
    async with runtime.session_factory.begin() as session:
        runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner.id)
        events = SqlAlchemyWorkflowEventRepository(session, owner_user_id=owner.id)
        graph_store = SqlAlchemyLangGraphCheckpointStore(session)
        reader_graph = build_governed_workflow_graph(
            checkpointer=RunScopedLangGraphCheckpointer(
                graph_store,
                run_id=RUN_ID,
                project_id=project.id,
                owner_user_id=owner.id,
            )
        )
        recovery = WorkflowRecoveryService(runs, reader_graph.checkpointer)
        ready = await recovery.assess(run_id=RUN_ID)
        assert ready.status is WorkflowRecoveryStatus.READY
        assert ready.run == waiting_checkpoint.run
        assert ready.graph_config is not None

        recovered_graph = build_governed_workflow_graph(
            checkpointer=RunScopedLangGraphCheckpointer(
                graph_store,
                run_id=RUN_ID,
                project_id=project.id,
                owner_user_id=owner.id,
                authoritative_run=ready.run,
                authoritative_checkpoint_id=ready.graph_config["configurable"]["checkpoint_id"],
            )
        )
        resumed = await recovered_graph.ainvoke(
            create_workflow_gate_resume_command(
                interrupt_id=interrupt_id,
                gate_id=GATE_ID,
                decision_id=DECISION_ID,
                decision_applied=True,
                occurred_at=BASE_TIME + timedelta(seconds=3),
            ),
            config=ready.graph_config,
        )
        assert resumed["run"].status is WorkflowRunStatus.RUNNING
        resumed_checkpoint = create_workflow_checkpoint(
            resumed["run"],
            previous_checkpoint=waiting_checkpoint.checkpoint,
            created_at=BASE_TIME + timedelta(seconds=3),
            checkpoint_id=CHECKPOINT_IDS[2],
        )
        saved = await runs.save_checkpoint(
            previous_run=waiting_checkpoint.run,
            creation=resumed_checkpoint,
        )
        assert saved.status is WorkflowRunStoreStatus.UPDATED

        resumed_event = create_workflow_event(
            resumed_checkpoint.run,
            previous_run=waiting_checkpoint.run,
            event_type=WorkflowEventType.RESUMED,
            sequence_number=3,
            occurred_at=BASE_TIME + timedelta(seconds=3),
            event_id=EVENT_IDS[2],
            decision_id=DECISION_ID,
        )
        appended = await events.append(
            resumed_event,
            expected_previous_sequence=2,
        )
        assert appended.status is WorkflowEventAppendStatus.APPENDED

    return resumed_checkpoint


async def verify_owner_isolation_and_history(
    runtime,
    *,
    owner,
    foreign,
    project,
    resumed_checkpoint,
) -> None:
    """Verify durable history is complete for the owner and hidden cross-owner."""
    async with runtime.session_factory() as session:
        owner_runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=owner.id)
        owner_events = SqlAlchemyWorkflowEventRepository(session, owner_user_id=owner.id)
        assert await owner_runs.get_owned(run_id=RUN_ID) == resumed_checkpoint.run
        checkpoints = await owner_runs.list_checkpoints(run_id=RUN_ID)
        replay = await owner_events.list_after(run_id=RUN_ID, after_sequence=1)
        assert len(checkpoints) == 3
        assert [item.sequence_number for item in replay] == [2, 3]

    async with runtime.session_factory() as session:
        foreign_runs = SqlAlchemyWorkflowRunRepository(session, owner_user_id=foreign.id)
        foreign_events = SqlAlchemyWorkflowEventRepository(session, owner_user_id=foreign.id)
        foreign_graph = build_governed_workflow_graph(
            checkpointer=RunScopedLangGraphCheckpointer(
                SqlAlchemyLangGraphCheckpointStore(session),
                run_id=RUN_ID,
                project_id=project.id,
                owner_user_id=foreign.id,
            )
        )
        foreign_recovery = WorkflowRecoveryService(
            foreign_runs,
            foreign_graph.checkpointer,
        )
        assert await foreign_runs.get_owned(run_id=RUN_ID) is None
        assert await foreign_events.list_after(run_id=RUN_ID) == ()
        assert (
            await foreign_recovery.assess(run_id=RUN_ID)
        ).status is WorkflowRecoveryStatus.RUN_NOT_FOUND


async def run_integration_scenario() -> None:
    """Verify migrations, recovery, events, owner isolation, and append-only guards."""
    settings = load_database_settings(env_file=None)
    runtime = create_database_runtime(settings)
    try:
        await truncate_application_data(runtime)
        owner, foreign, project = await create_owner_and_project(runtime)
        waiting_checkpoint, interrupt_id = await persist_interrupted_run(
            runtime,
            owner=owner,
            project=project,
        )
        resumed_checkpoint = await recover_and_resume(
            runtime,
            owner=owner,
            project=project,
            waiting_checkpoint=waiting_checkpoint,
            interrupt_id=interrupt_id,
        )
        await verify_owner_isolation_and_history(
            runtime,
            owner=owner,
            foreign=foreign,
            project=project,
            resumed_checkpoint=resumed_checkpoint,
        )

        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE workflow_checkpoints SET state_hash = repeat('0', 64) "
                "WHERE id = :identifier"
            ),
            identifier=CHECKPOINT_IDS[0],
        )
        assert await mutation_is_rejected(
            runtime,
            statement=(
                "UPDATE workflow_events SET payload_hash = repeat('0', 64) WHERE id = :identifier"
            ),
            identifier=EVENT_IDS[0],
        )

        async with runtime.engine.connect() as connection:
            database_revision = await connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        scripts = ScriptDirectory.from_config(
            create_alembic_config(settings.url.get_secret_value())
        )
        current_head = scripts.get_current_head()
        assert current_head == "0025_workflow_events"
        assert database_revision == current_head
    finally:
        await truncate_application_data(runtime)
        await runtime.dispose()


def test_postgresql_workflow_recovery_and_event_history() -> None:
    """Verify the complete first Sprint 10 PostgreSQL workflow boundary."""
    asyncio.run(
        run_integration_scenario(),
        loop_factory=asyncio.SelectorEventLoop,
    )
