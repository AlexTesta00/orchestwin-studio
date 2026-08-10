"""Tests for immutable Project Brief version persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
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
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
    owned_project_for_update_statement,
)
from orchestwin.projects.persistence.models import (
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.projects.repository import (
    BriefVersionCreationStatus,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
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


def build_project_record(
    *,
    current_brief_version: int = 0,
) -> ProjectRecord:
    """Create one deterministic active project record."""
    return ProjectRecord(
        id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Project",
        mode=(ProjectMode.GREENFIELD_GENERATION.value),
        current_brief_version=(current_brief_version),
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


def test_project_lock_query_is_owner_scoped() -> None:
    """Serialize numbering only after validating ownership."""
    statement = owned_project_for_update_statement(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={
                "literal_binds": True,
            },
        )
    )

    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "FOR UPDATE" in sql


def test_first_brief_version_is_created_atomically() -> None:
    """Insert version one and update the project pointer."""
    project = build_project_record()
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=project)
    session.flush = AsyncMock()
    repository = SqlAlchemyProjectBriefRepository(
        session,
        clock=lambda: NOW,
        uuid_factory=lambda: VERSION_ID,
    )
    brief = create_project_brief(
        name="Project",
        goals=["Build a working system"],
        unknown_fields=[BriefField.BUDGET],
    )

    result = asyncio.run(
        repository.create_owned_version(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            created_by_user_id=OWNER_ID,
            brief=brief,
        )
    )

    assert result.status is (BriefVersionCreationStatus.CREATED)
    assert result.created is True
    assert result.version is not None
    assert result.version.version_number == 1
    assert result.version.content_hash == (brief.content_hash)
    assert project.current_brief_version == 1
    assert project.updated_at == NOW

    added = session.add.call_args.args[0]

    assert isinstance(
        added,
        ProjectBriefVersionRecord,
    )
    assert added.content == brief.to_snapshot()


def test_identical_current_brief_is_not_duplicated() -> None:
    """Return the immutable current version for identical content."""
    brief = create_project_brief(name="Project")
    project = build_project_record(current_brief_version=1)
    current = ProjectBriefVersionRecord(
        id=VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=brief.SCHEMA_VERSION,
        content=brief.to_snapshot(),
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(
        side_effect=[
            project,
            current,
        ]
    )
    session.flush = AsyncMock()
    repository = SqlAlchemyProjectBriefRepository(
        session,
        clock=lambda: NOW,
    )

    result = asyncio.run(
        repository.create_owned_version(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            created_by_user_id=OWNER_ID,
            brief=brief,
        )
    )

    assert result.status is (BriefVersionCreationStatus.UNCHANGED)
    assert result.created is False
    assert result.version is not None
    assert result.version.version_number == 1
    session.add.assert_not_called()
    session.flush.assert_not_awaited()


def test_other_owner_is_reported_as_project_not_found() -> None:
    """Avoid revealing whether another user's project exists."""
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=None)
    session.flush = AsyncMock()
    repository = SqlAlchemyProjectBriefRepository(session)

    result = asyncio.run(
        repository.create_owned_version(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            created_by_user_id=OWNER_ID,
            brief=create_project_brief(name="Project"),
        )
    )

    assert result.status is (BriefVersionCreationStatus.PROJECT_NOT_FOUND)
    assert result.version is None
    session.add.assert_not_called()


def test_brief_version_migration_installs_immutability_trigger() -> None:
    """Render the immutable table and trigger in offline SQL."""
    from io import StringIO

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

    assert "CREATE TABLE project_brief_versions" in generated_sql
    assert "trg_project_brief_versions_immutable" in generated_sql
    assert "reject_project_brief_version_mutation" in generated_sql
    assert "BEFORE UPDATE OR DELETE" in generated_sql


def test_brief_version_revision_follows_projects() -> None:
    """Keep the version table attached to project persistence."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0005_project_brief_versions")

    assert revision is not None
    assert revision.down_revision == ("0004_projects")
    assert len(scripts.get_heads()) == 1
