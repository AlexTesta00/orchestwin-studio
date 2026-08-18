"""Tests for immutable project aggregate transitions."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from orchestwin.projects.domain import (
    ProjectMode,
    archive_project,
    create_project,
    rename_project,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
CREATED_AT = datetime(
    2026,
    8,
    10,
    12,
    0,
    tzinfo=UTC,
)


def test_create_project_normalizes_name_and_preserves_mode() -> None:
    """Create one owner-scoped project with no brief version."""
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="  Hotel   Management  ",
        mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=CREATED_AT,
    )

    assert project.display_name == ("Hotel Management")
    assert project.mode is (ProjectMode.GREENFIELD_GENERATION)
    assert project.current_brief_version == 0
    assert project.is_archived is False


def test_rename_returns_new_project_without_changing_mode() -> None:
    """Rename through a pure aggregate transition."""
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Initial name",
        mode=ProjectMode.BROWNFIELD_ASSESSMENT,
        created_at=CREATED_AT,
    )

    renamed = rename_project(
        project,
        display_name=" Revised   name ",
        updated_at=(CREATED_AT + timedelta(minutes=1)),
    )

    assert renamed is not project
    assert project.display_name == "Initial name"
    assert renamed.display_name == "Revised name"
    assert renamed.mode is (ProjectMode.BROWNFIELD_ASSESSMENT)


def test_archive_is_idempotent() -> None:
    """Archive once and preserve the first archive timestamp."""
    project = create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Project",
        mode=ProjectMode.GREENFIELD_GENERATION,
        created_at=CREATED_AT,
    )
    archived_at = CREATED_AT + timedelta(minutes=1)

    archived = archive_project(
        project,
        archived_at=archived_at,
    )
    archived_again = archive_project(
        archived,
        archived_at=(archived_at + timedelta(minutes=1)),
    )

    assert archived.is_archived is True
    assert archived.archived_at == archived_at
    assert archived_again == archived
