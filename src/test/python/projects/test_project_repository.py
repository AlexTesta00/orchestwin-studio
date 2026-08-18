"""Tests for owner-scoped project persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.persistence.migrate import (
    create_alembic_config,
)
from orchestwin.projects.domain import (
    ProjectMode,
    create_project,
)
from orchestwin.projects.persistence.models import (
    ProjectRecord,
)
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
    active_projects_statement,
    owned_project_statement,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(
    2026,
    8,
    10,
    12,
    0,
    tzinfo=UTC,
)
TEST_DATABASE_URL = (
    "postgresql+psycopg://user:database-secret-must-not-leak-8472@localhost:5432/orchestwin"
)


def compile_statement(statement: object) -> str:
    """Compile a statement using PostgreSQL syntax."""
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={
                "literal_binds": True,
            },
        )
    )


def test_owned_project_query_requires_project_and_owner() -> None:
    """Prevent identifier-only project lookups."""
    sql = compile_statement(
        owned_project_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql


def test_active_project_list_is_owner_scoped() -> None:
    """List active projects for exactly one owner."""
    sql = compile_statement(active_projects_statement(owner_user_id=OTHER_OWNER_ID))

    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "ORDER BY projects.created_at DESC" in sql


def test_repository_adds_project_record() -> None:
    """Map the immutable project into one ORM record."""
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Project",
        mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=NOW,
    )
    session = Mock(spec=AsyncSession)
    session.flush = AsyncMock()
    repository = SqlAlchemyProjectRepository(session)

    persisted = asyncio.run(repository.add(project))

    session.add.assert_called_once()
    assert persisted == project


def test_repository_maps_owned_record_to_domain() -> None:
    """Return an immutable aggregate for the matching owner."""
    record = ProjectRecord(
        id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Project",
        mode=(ProjectMode.BROWNFIELD_ASSESSMENT.value),
        current_brief_version=0,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=record)
    repository = SqlAlchemyProjectRepository(session)

    loaded = asyncio.run(
        repository.get_owned(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert loaded is not None
    assert loaded.owner_user_id == OWNER_ID
    assert loaded.mode is (ProjectMode.BROWNFIELD_ASSESSMENT)


def test_project_revision_follows_auth_sessions() -> None:
    """Attach project persistence to the identity schema."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0004_projects")

    assert revision is not None
    assert revision.down_revision == ("0003_auth_sessions")
    assert len(scripts.get_heads()) == 1
