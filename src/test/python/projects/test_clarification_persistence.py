"""Tests for clarification and assumption persistence adapters."""

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
from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.clarification import (
    CLARIFICATION_CATALOG_VERSION,
    clarification_question_for,
)
from orchestwin.projects.clarification_state import (
    BriefAssumptionSource,
    create_brief_assumption,
    create_clarification_round,
)
from orchestwin.projects.persistence.clarification import (
    SqlAlchemyBriefAssumptionRepository,
    SqlAlchemyClarificationRoundRepository,
    owned_assumption_statement,
    owned_round_statement,
    question_spec_from_snapshot,
    question_spec_to_snapshot,
)
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
    ClarificationRoundRecord,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
ROUND_ID = UUID("00000000-0000-4000-8000-000000000030")
ASSUMPTION_ID = UUID("00000000-0000-4000-8000-000000000040")
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


def test_round_query_is_project_and_owner_scoped() -> None:
    """Prevent identifier-only clarification-round lookup."""
    sql = compile_statement(
        owned_round_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            round_id=ROUND_ID,
        )
    )

    assert "clarification_rounds.id =" in sql
    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql


def test_assumption_query_is_project_and_owner_scoped() -> None:
    """Prevent cross-owner assumption lookup."""
    sql = compile_statement(
        owned_assumption_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            assumption_id=ASSUMPTION_ID,
        )
    )

    assert "brief_assumptions.id =" in sql
    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql


def test_question_snapshot_round_trips() -> None:
    """Preserve the exact question metadata presented to the owner."""
    question = clarification_question_for(BriefField.PROBLEM)

    snapshot = question_spec_to_snapshot(question)
    reconstructed = question_spec_from_snapshot(snapshot)

    assert reconstructed == question


def test_round_repository_adds_jsonb_snapshot() -> None:
    """Map an immutable round into one SQLAlchemy record."""
    round_state = create_clarification_round(
        round_id=ROUND_ID,
        project_id=PROJECT_ID,
        source_brief_version_number=1,
        round_number=1,
        catalog_version=(CLARIFICATION_CATALOG_VERSION),
        questions=[clarification_question_for(BriefField.PROBLEM)],
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyClarificationRoundRepository(session)

    persisted = asyncio.run(repository.add(round_state))

    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    record = session.add.call_args.args[0]

    assert isinstance(
        record,
        ClarificationRoundRecord,
    )
    assert record.questions == [question_spec_to_snapshot(round_state.questions[0])]
    assert persisted == round_state


def test_assumption_repository_adds_separate_record() -> None:
    """Persist an assumption outside the brief JSONB snapshot."""
    assumption = create_brief_assumption(
        assumption_id=ASSUMPTION_ID,
        project_id=PROJECT_ID,
        brief_version_number=1,
        field=BriefField.BUDGET,
        statement="The budget may be EUR 5,000.",
        source=(BriefAssumptionSource.OWNER_PROVIDED),
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyBriefAssumptionRepository(session)

    persisted = asyncio.run(repository.add(assumption))

    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    record = session.add.call_args.args[0]

    assert isinstance(
        record,
        BriefAssumptionRecord,
    )
    assert record.field_name == "budget"
    assert record.status == "PROPOSED"
    assert persisted == assumption


def test_migration_creates_rounds_assumptions_and_open_round_index() -> None:
    """Render the complete schema extension through offline SQL."""
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

    assert "CREATE TABLE clarification_rounds" in generated_sql
    assert "CREATE TABLE brief_assumptions" in generated_sql
    assert "uq_clarification_rounds_open_project" in generated_sql
    assert "0006_clarification_rounds_assumptions" in generated_sql
    assert "database-secret-must-not-leak-8472" not in generated_sql


def test_clarification_revision_follows_version_capacity() -> None:
    """Keep clarification persistence attached to immutable briefs."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0006_clarification_rounds_assumptions")

    assert revision is not None
    assert revision.down_revision == ("0005a_expand_alembic_version")
    assert len(scripts.get_heads()) == 1
