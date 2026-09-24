"""Real concurrency regression for the GUI's overlapping gate reads."""

import asyncio
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from orchestwin.persistence import create_database_runtime
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import SqlAlchemyHumanGateRepository
from src.test.python.integration.test_proposal_evidence_postgres import (
    _persist_pending_gate,
    database,
    run,
    seed,
)

__all__ = ["database"]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("ORCHESTWIN_PROPOSAL_EVIDENCE_TEST_DATABASE_URL"),
        reason="explicit isolated PostgreSQL configuration required",
    ),
]


def test_gate_read_cannot_invert_project_then_gate_lock_order(database):
    async def scenario():
        runtime = create_database_runtime(database)
        try:
            owner, project = await seed(runtime, SimpleNamespace(project_id=uuid4()))
            await _persist_pending_gate(
                runtime,
                owner_id=owner,
                project_id=project,
                gate_id=uuid4(),
                gate_type=HumanGateType.AGENT_TEAM,
                artifact_id=uuid4(),
                artifact_hash="a" * 64,
                occurred_at=datetime.now(UTC),
            )
            project_locked = asyncio.Event()
            reader_started = asyncio.Event()

            async def command():
                async with runtime.session_factory.begin() as session:
                    await session.scalar(
                        select(ProjectRecord.id)
                        .where(ProjectRecord.id == project)
                        .with_for_update()
                    )
                    project_locked.set()
                    await reader_started.wait()
                    # Allow the competing reader to reach its first row lock.
                    await asyncio.sleep(0.2)
                    gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                        project_id=project, owner_user_id=owner, gate_type=HumanGateType.AGENT_TEAM
                    )
                    assert gate is not None

            async def reader():
                await project_locked.wait()
                async with runtime.session_factory.begin() as session:
                    reader_started.set()
                    gate = await SqlAlchemyHumanGateRepository(session).get_latest_owned_for_update(
                        project_id=project, owner_user_id=owner, gate_type=HumanGateType.AGENT_TEAM
                    )
                    assert gate is not None

            await asyncio.wait_for(asyncio.gather(command(), reader()), timeout=5)
        finally:
            await runtime.dispose()

    run(scenario())
