"""Tests for owner-scoped LangGraph checkpoint storage and recovery."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from langgraph.checkpoint.base import Checkpoint

from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.checkpoints import create_workflow_checkpoint
from orchestwin.workflow.langgraph_checkpointer import (
    InMemoryLangGraphCheckpointStore,
    RunScopedLangGraphCheckpointer,
)
from orchestwin.workflow.recovery import (
    WorkflowRecoveryService,
    WorkflowRecoveryStatus,
)
from orchestwin.workflow.routing import start_workflow_run
from orchestwin.workflow.run_persistence import InMemoryWorkflowRunRepository
from orchestwin.workflow.runs import create_workflow_run

PROJECT_ID = UUID("00000000-0000-4000-8000-000000010601")
OWNER_ID = UUID("00000000-0000-4000-8000-000000010602")
RUN_ID = UUID("00000000-0000-4000-8000-000000010603")
APPLICATION_CHECKPOINT_ID = UUID("00000000-0000-4000-8000-000000010604")
NOW = datetime(2026, 8, 28, 23, 0, tzinfo=UTC)


def graph_checkpoint(
    checkpoint_id: str,
    *,
    value: int,
    run=None,
) -> Checkpoint:
    channel_values = {"value": value}
    if run is not None:
        channel_values["run"] = run
    return Checkpoint(
        v=1,
        id=checkpoint_id,
        ts=(NOW + timedelta(seconds=value)).isoformat(),
        channel_values=channel_values,
        channel_versions={"value": value},
        versions_seen={},
        updated_channels=["value"],
    )


def checkpointer(store: InMemoryLangGraphCheckpointStore) -> RunScopedLangGraphCheckpointer:
    return RunScopedLangGraphCheckpointer(
        store,
        run_id=RUN_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )


def test_async_checkpointer_round_trips_lineage_metadata_and_pending_writes() -> None:
    async def scenario() -> None:
        store = InMemoryLangGraphCheckpointStore()
        saver = checkpointer(store)
        root_config = {
            "configurable": {
                "thread_id": str(RUN_ID),
                "checkpoint_ns": "",
            }
        }
        first_config = await saver.aput(
            root_config,
            graph_checkpoint("00000000-0000-6000-8000-000000000001", value=1),
            {"source": "input", "step": -1, "case": "root"},
            {"value": 1},
        )
        await saver.aput_writes(
            first_config,
            (("value", 2), ("diagnostic", "temporary")),
            task_id="task-1",
            task_path="apply_step",
        )
        second_config = await saver.aput(
            first_config,
            graph_checkpoint("00000000-0000-6000-8000-000000000002", value=2),
            {"source": "loop", "step": 0, "case": "child"},
            {"value": 2},
        )

        latest = await saver.aget_tuple(root_config)
        first = await saver.aget_tuple(first_config)
        filtered = [
            item
            async for item in saver.alist(
                root_config,
                filter={"case": "child"},
                limit=1,
            )
        ]

        assert latest is not None
        assert latest.config == second_config
        assert latest.parent_config == first_config
        assert latest.checkpoint["channel_values"] == {"value": 2}
        assert first is not None
        assert first.pending_writes == [
            ("task-1", "value", 2),
            ("task-1", "diagnostic", "temporary"),
        ]
        assert [item.config for item in filtered] == [second_config]

    asyncio.run(scenario())


def test_checkpointer_rejects_cross_run_thread_ids() -> None:
    async def scenario() -> None:
        saver = checkpointer(InMemoryLangGraphCheckpointStore())
        foreign_config = {
            "configurable": {
                "thread_id": "00000000-0000-4000-8000-000000010699",
                "checkpoint_ns": "",
            }
        }

        try:
            await saver.aget_tuple(foreign_config)
        except ValueError as error:
            assert "thread id" in str(error)
        else:
            raise AssertionError("cross-run checkpoint access must be rejected")

    asyncio.run(scenario())


def test_recovery_requires_matching_application_and_graph_checkpoints() -> None:
    async def scenario() -> None:
        run_repository = InMemoryWorkflowRunRepository(
            owner_user_id=OWNER_ID,
            project_ids=frozenset({PROJECT_ID}),
        )
        draft = create_workflow_run(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            project_mode=ProjectMode.GREENFIELD_GENERATION,
            run_id=RUN_ID,
            created_at=NOW,
        )
        assert (await run_repository.create(draft)).run == draft
        started = start_workflow_run(draft, occurred_at=NOW + timedelta(seconds=1)).run
        creation = create_workflow_checkpoint(
            started,
            created_at=NOW + timedelta(seconds=2),
            checkpoint_id=APPLICATION_CHECKPOINT_ID,
        )
        assert (
            await run_repository.save_checkpoint(previous_run=draft, creation=creation)
        ).run == creation.run

        graph_store = InMemoryLangGraphCheckpointStore()
        saver = checkpointer(graph_store)
        recovery = WorkflowRecoveryService(run_repository, saver)
        missing = await recovery.assess(run_id=RUN_ID)
        await saver.aput(
            {
                "configurable": {
                    "thread_id": str(RUN_ID),
                    "checkpoint_ns": "",
                }
            },
            graph_checkpoint(
                "00000000-0000-6000-8000-000000000003",
                value=3,
                run=started,
            ),
            {"source": "loop", "step": 1},
            {"value": 3},
        )
        ready = await recovery.assess(run_id=RUN_ID)

        assert missing.status is WorkflowRecoveryStatus.GRAPH_CHECKPOINT_MISSING
        assert ready.status is WorkflowRecoveryStatus.READY
        assert ready.run == creation.run
        assert ready.graph_config is not None
        assert ready.graph_config["configurable"]["thread_id"] == str(RUN_ID)

        recovering_saver = RunScopedLangGraphCheckpointer(
            graph_store,
            run_id=RUN_ID,
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            authoritative_run=ready.run,
            authoritative_checkpoint_id=ready.graph_config["configurable"]["checkpoint_id"],
        )
        reconciled = await recovering_saver.aget_tuple(ready.graph_config)
        assert reconciled is not None
        assert reconciled.checkpoint["channel_values"]["run"] == creation.run

    asyncio.run(scenario())
