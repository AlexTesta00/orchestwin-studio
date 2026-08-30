"""End-to-end deterministic tests for checkpointed workflow recovery and replay."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.event_persistence import InMemoryWorkflowEventRepository
from orchestwin.workflow.events import WorkflowEventType, create_workflow_event
from orchestwin.workflow.langgraph_checkpointer import (
    InMemoryLangGraphCheckpointStore,
    RunScopedLangGraphCheckpointer,
)
from orchestwin.workflow.langgraph_graph import (
    WorkflowGraphStep,
    WorkflowGraphStepKind,
    build_governed_workflow_graph,
    create_workflow_gate_resume_command,
)
from orchestwin.workflow.recovery import WorkflowRecoveryService, WorkflowRecoveryStatus
from orchestwin.workflow.routing import advance_workflow_run, start_workflow_run
from orchestwin.workflow.run_persistence import InMemoryWorkflowRunRepository
from orchestwin.workflow.runs import WorkflowRunStatus, WorkflowStage, create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010901")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010902")
RUN_ID = UUID("00000000-0000-4000-8000-000000010903")
GATE_ID = UUID("00000000-0000-4000-8000-000000010904")
DECISION_ID = UUID("00000000-0000-4000-8000-000000010905")
CHECKPOINT_IDS = (
    UUID("00000000-0000-4000-8000-000000010911"),
    UUID("00000000-0000-4000-8000-000000010912"),
    UUID("00000000-0000-4000-8000-000000010913"),
)
EVENT_IDS = (
    UUID("00000000-0000-4000-8000-000000010921"),
    UUID("00000000-0000-4000-8000-000000010922"),
    UUID("00000000-0000-4000-8000-000000010923"),
)
NOW = datetime(2026, 8, 28, 23, 30, tzinfo=UTC)


def test_checkpointed_graph_recovers_after_restart_and_replays_ordered_events() -> None:
    async def scenario() -> None:
        run_repository = InMemoryWorkflowRunRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        event_repository = InMemoryWorkflowEventRepository(
            owner_user_id=OWNER_ID,
            run_projects={RUN_ID: PROJECT_ID},
        )
        graph_store = InMemoryLangGraphCheckpointStore()
        draft = create_workflow_run(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            project_mode=ProjectMode.GREENFIELD_GENERATION,
            run_id=RUN_ID,
            created_at=NOW,
        )
        assert (await run_repository.create(draft)).run == draft

        started = start_workflow_run(
            draft,
            occurred_at=NOW + timedelta(seconds=1),
        ).run
        started_checkpoint = create_workflow_checkpoint(
            started,
            created_at=NOW + timedelta(seconds=1),
            checkpoint_id=CHECKPOINT_IDS[0],
        )
        assert (
            await run_repository.save_checkpoint(
                previous_run=draft,
                creation=started_checkpoint,
            )
        ).run == started_checkpoint.run

        writer = RunScopedLangGraphCheckpointer(
            graph_store,
            run_id=RUN_ID,
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
        writer_graph = build_governed_workflow_graph(checkpointer=writer)
        thread_config = {"configurable": {"thread_id": str(RUN_ID)}}
        interrupted = await writer_graph.ainvoke(
            {
                "run": started_checkpoint.run,
                "step": WorkflowGraphStep(
                    kind=WorkflowGraphStepKind.ADVANCE,
                    occurred_at=NOW + timedelta(seconds=2),
                    next_stage=WorkflowStage.BRIEF_APPROVAL,
                    pending_gate_id=GATE_ID,
                ),
                "trace": (),
            },
            config=thread_config,
        )
        waiting = interrupted["run"]
        pending_interrupt = interrupted["__interrupt__"][0]
        assert waiting.status is WorkflowRunStatus.WAITING_FOR_HUMAN
        assert pending_interrupt.value["gate_id"] == str(GATE_ID)

        waiting_checkpoint = create_workflow_checkpoint(
            waiting,
            previous_checkpoint=started_checkpoint.checkpoint,
            created_at=NOW + timedelta(seconds=2),
            checkpoint_id=CHECKPOINT_IDS[1],
        )
        assert (
            await run_repository.save_checkpoint(
                previous_run=started_checkpoint.run,
                creation=waiting_checkpoint,
            )
        ).run == waiting_checkpoint.run

        started_event = create_workflow_event(
            started_checkpoint.run,
            previous_run=draft,
            event_type=WorkflowEventType.RUN_STARTED,
            sequence_number=1,
            occurred_at=NOW + timedelta(seconds=1),
            event_id=EVENT_IDS[0],
        )
        waiting_event = create_workflow_event(
            waiting_checkpoint.run,
            previous_run=started_checkpoint.run,
            event_type=WorkflowEventType.WAITING_FOR_HUMAN,
            sequence_number=2,
            occurred_at=NOW + timedelta(seconds=2),
            event_id=EVENT_IDS[1],
        )
        assert (
            await event_repository.append(
                started_event,
                expected_previous_sequence=0,
            )
        ).event == started_event
        assert (
            await event_repository.append(
                waiting_event,
                expected_previous_sequence=1,
            )
        ).event == waiting_event

        reader = RunScopedLangGraphCheckpointer(
            graph_store,
            run_id=RUN_ID,
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
        reader_graph = build_governed_workflow_graph(checkpointer=reader)
        recovery = WorkflowRecoveryService(
            run_repository,
            reader_graph.checkpointer,
        )
        ready = await recovery.assess(run_id=RUN_ID)
        assert ready.status is WorkflowRecoveryStatus.READY
        assert ready.run == waiting_checkpoint.run
        assert ready.graph_config is not None

        recovering = RunScopedLangGraphCheckpointer(
            graph_store,
            run_id=RUN_ID,
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            authoritative_run=ready.run,
            authoritative_checkpoint_id=ready.graph_config["configurable"]["checkpoint_id"],
        )
        recovered_graph = build_governed_workflow_graph(checkpointer=recovering)
        resumed = await recovered_graph.ainvoke(
            create_workflow_gate_resume_command(
                interrupt_id=pending_interrupt.id,
                gate_id=GATE_ID,
                decision_id=DECISION_ID,
                decision_applied=True,
                occurred_at=NOW + timedelta(seconds=3),
            ),
            config=ready.graph_config,
        )
        assert resumed["run"].status is WorkflowRunStatus.RUNNING
        assert resumed["run"].checkpoint_sequence == 2

        resumed_checkpoint = create_workflow_checkpoint(
            resumed["run"],
            previous_checkpoint=waiting_checkpoint.checkpoint,
            created_at=NOW + timedelta(seconds=3),
            checkpoint_id=CHECKPOINT_IDS[2],
        )
        assert (
            await run_repository.save_checkpoint(
                previous_run=waiting_checkpoint.run,
                creation=resumed_checkpoint,
            )
        ).run == resumed_checkpoint.run
        resumed_event = create_workflow_event(
            resumed_checkpoint.run,
            previous_run=waiting_checkpoint.run,
            event_type=WorkflowEventType.RESUMED,
            sequence_number=3,
            occurred_at=NOW + timedelta(seconds=3),
            event_id=EVENT_IDS[2],
            decision_id=DECISION_ID,
        )
        assert (
            await event_repository.append(
                resumed_event,
                expected_previous_sequence=2,
            )
        ).event == resumed_event

        replay = await event_repository.list_after(
            run_id=RUN_ID,
            after_sequence=1,
        )
        assert replay == (waiting_event, resumed_event)
        assert [item.sequence_number for item in replay] == [2, 3]
        assert len(await run_repository.list_checkpoints(run_id=RUN_ID)) == 3

    asyncio.run(scenario())


def test_brownfield_route_remains_distinct_from_the_greenfield_gate_path() -> None:
    draft = create_workflow_run(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        project_mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        run_id=RUN_ID,
        created_at=NOW,
    )
    running = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
    source_ingestion = advance_workflow_run(
        running,
        next_stage=WorkflowStage.SOURCE_INGESTION,
        occurred_at=NOW + timedelta(seconds=2),
    )

    assert source_ingestion.run.current_stage is WorkflowStage.SOURCE_INGESTION
    assert source_ingestion.run.status is WorkflowRunStatus.RUNNING
