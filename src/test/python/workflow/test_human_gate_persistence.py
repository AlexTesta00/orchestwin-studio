"""Tests for SQLAlchemy human-gate persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.persistence.migrate import (
    create_alembic_config,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGateAction,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)
from orchestwin.workflow.persistence.models import (
    HumanGateEventRecord,
    HumanGateRecord,
)
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
    latest_owned_gate_statement,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
GATE_ID = UUID("00000000-0000-4000-8000-000000000020")
EVENT_ID = UUID("00000000-0000-4000-8000-000000000021")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000000030")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)
TEST_DATABASE_URL = (
    "postgresql+psycopg://user:database-secret-must-not-leak-8472@localhost:5432/orchestwin"
)


def submitted_gate():
    """Create one deterministic submitted Project Brief gate."""
    draft = create_human_gate(
        gate_id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=(HumanGateType.PROJECT_BRIEF),
            artifact_id=ARTIFACT_ID,
            version=1,
            content_hash="a" * 64,
        ),
        created_at=NOW,
    )

    result = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW,
        event_id=EVENT_ID,
    )

    assert result.status is (HumanGateTransitionStatus.APPLIED)
    assert result.event is not None

    return (
        result.gate,
        result.event,
    )


def compile_statement(
    statement: object,
) -> str:
    """Compile a statement using PostgreSQL syntax."""
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={
                "literal_binds": True,
            },
        )
    )


def test_latest_gate_query_is_owner_scoped() -> None:
    """Prevent gate lookup through project ID alone."""
    sql = compile_statement(
        latest_owned_gate_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            gate_type=(HumanGateType.PROJECT_BRIEF),
        )
    )

    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "human_gates.gate_type =" in sql
    assert "ORDER BY human_gates.iteration DESC" in sql


def test_repository_adds_gate_and_first_event() -> None:
    """Persist gate state and its first append-only event."""
    gate, event = submitted_gate()
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyHumanGateRepository(session)

    persisted = asyncio.run(
        repository.add_with_event(
            gate=gate,
            event=event,
        )
    )

    assert session.add.call_count == 2
    session.flush.assert_awaited_once()

    records = [call.args[0] for call in (session.add.call_args_list)]

    assert any(
        isinstance(
            record,
            HumanGateRecord,
        )
        for record in records
    )
    assert any(
        isinstance(
            record,
            HumanGateEventRecord,
        )
        for record in records
    )
    assert persisted == gate


def test_migration_creates_gate_tables_and_append_only_trigger() -> None:
    """Render Gate 1 persistence and its audit protection."""
    output = StringIO()
    configuration = create_alembic_config(
        TEST_DATABASE_URL,
        output_buffer=output,
    )

    command.upgrade(
        configuration,
        "head",
        sql=True,
    )

    generated_sql = output.getvalue()

    assert "CREATE TABLE human_gates" in generated_sql
    assert "CREATE TABLE human_gate_events" in generated_sql
    assert "trg_human_gate_events_append_only" in generated_sql
    assert "reject_human_gate_event_mutation" in generated_sql
    assert "BEFORE UPDATE OR DELETE" in generated_sql
    assert "0007_project_brief_human_gates" in generated_sql
    assert "database-secret-must-not-leak-8472" not in generated_sql


def test_gate_revision_follows_clarification_persistence() -> None:
    """Attach Gate 1 persistence to the Sprint 03 clarification schema."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0007_project_brief_human_gates")

    assert revision is not None
    assert revision.down_revision == ("0006_clarification_rounds_assumptions")
    assert len(scripts.get_heads()) == 1
