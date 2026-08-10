"""SQLAlchemy project repository implementation."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.domain import (
    Project,
    archive_project,
    rename_project,
)
from orchestwin.projects.persistence.models import (
    ProjectRecord,
)


def project_record_to_domain(
    record: ProjectRecord,
) -> Project:
    """Translate a project record into an immutable aggregate."""
    return Project(
        id=record.id,
        owner_user_id=record.owner_user_id,
        display_name=record.display_name,
        mode=record.project_mode,
        current_brief_version=(record.current_brief_version),
        archived_at=record.archived_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def owned_project_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
    include_archived: bool = False,
) -> Select[tuple[ProjectRecord]]:
    """Build the canonical owner-scoped project query."""
    statement = select(ProjectRecord).where(
        ProjectRecord.id == project_id,
        ProjectRecord.owner_user_id == owner_user_id,
    )

    if not include_archived:
        statement = statement.where(ProjectRecord.archived_at.is_(None))

    return statement


def active_projects_statement(
    *,
    owner_user_id: UUID,
) -> Select[tuple[ProjectRecord]]:
    """Build the canonical active-project list query."""
    return (
        select(ProjectRecord)
        .where(
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        .order_by(
            ProjectRecord.created_at.desc(),
            ProjectRecord.id,
        )
    )


class SqlAlchemyProjectRepository:
    """Owner-scoped SQLAlchemy project repository."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def add(
        self,
        project: Project,
    ) -> Project:
        """Add a project to the current transaction."""
        record = ProjectRecord(
            id=project.id,
            owner_user_id=project.owner_user_id,
            display_name=project.display_name,
            mode=project.mode.value,
            current_brief_version=(project.current_brief_version),
            archived_at=project.archived_at,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

        self._session.add(record)
        await self._session.flush()

        return project_record_to_domain(record)

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        include_archived: bool = False,
    ) -> Project | None:
        """Return a project only when the owner matches."""
        record = await self._session.scalar(
            owned_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
                include_archived=include_archived,
            )
        )

        if record is None:
            return None

        return project_record_to_domain(record)

    async def list_active_owned(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        """Return active projects belonging to one owner."""
        result = await self._session.scalars(active_projects_statement(owner_user_id=owner_user_id))

        return tuple(project_record_to_domain(record) for record in result.all())

    async def rename_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        """Rename an active project under a row lock."""
        record = await self._session.scalar(
            owned_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).with_for_update()
        )

        if record is None:
            return None

        renamed = rename_project(
            project_record_to_domain(record),
            display_name=display_name,
            updated_at=datetime.now(UTC),
        )

        record.display_name = renamed.display_name
        record.updated_at = renamed.updated_at
        await self._session.flush()

        return project_record_to_domain(record)

    async def archive_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Archive an active project under a row lock."""
        record = await self._session.scalar(
            owned_project_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            ).with_for_update()
        )

        if record is None:
            return None

        archived = archive_project(
            project_record_to_domain(record),
            archived_at=datetime.now(UTC),
        )

        record.archived_at = archived.archived_at
        record.updated_at = archived.updated_at
        await self._session.flush()

        return project_record_to_domain(record)
