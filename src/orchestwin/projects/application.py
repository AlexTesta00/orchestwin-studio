"""Project Definition application services."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from orchestwin.projects.briefs import (
    ProjectBrief,
    ProjectBriefVersion,
)
from orchestwin.projects.domain import (
    Project,
    ProjectMode,
    create_project,
)
from orchestwin.projects.repository import (
    BriefVersionCreationResult,
    ProjectBriefRepository,
    ProjectRepository,
)


class ProjectUnitOfWork(Protocol):
    """Transactional repository boundary for Project Definition."""

    @property
    def projects(self) -> ProjectRepository:
        """Return the project repository."""

    @property
    def briefs(self) -> ProjectBriefRepository:
        """Return the Project Brief repository."""

    async def __aenter__(self) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


ProjectUnitOfWorkFactory = Callable[
    [],
    ProjectUnitOfWork,
]


class ProjectApplicationService(Protocol):
    """Use cases exposed to the Project API adapter."""

    async def create(
        self,
        *,
        owner_user_id: UUID,
        display_name: str,
        mode: ProjectMode,
    ) -> Project:
        """Create a project."""

    async def list_active(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        """List active projects."""

    async def get(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Return an active owned project."""

    async def rename(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        """Rename an active owned project."""

    async def archive(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Archive an active owned project."""

    async def create_brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        brief: ProjectBrief,
    ) -> BriefVersionCreationResult:
        """Create or reuse a brief version."""

    async def current_brief(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current brief version."""

    async def brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        """Return one brief version."""

    async def brief_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        """Return the immutable version history."""


class LocalProjectApplicationService:
    """Project use cases composed from explicit repository ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ProjectUnitOfWorkFactory,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create(
        self,
        *,
        owner_user_id: UUID,
        display_name: str,
        mode: ProjectMode,
    ) -> Project:
        """Create one project for the authenticated owner."""
        project = create_project(
            owner_user_id=owner_user_id,
            display_name=display_name,
            mode=mode,
        )

        async with self._unit_of_work_factory() as unit:
            return await unit.projects.add(project)

    async def list_active(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        """List active projects belonging to one owner."""
        async with self._unit_of_work_factory() as unit:
            return await unit.projects.list_active_owned(owner_user_id=owner_user_id)

    async def get(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Return an active project through its ownership boundary."""
        async with self._unit_of_work_factory() as unit:
            return await unit.projects.get_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

    async def rename(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        """Rename an active owned project."""
        async with self._unit_of_work_factory() as unit:
            return await unit.projects.rename_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                display_name=display_name,
            )

    async def archive(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Archive an active owned project."""
        async with self._unit_of_work_factory() as unit:
            return await unit.projects.archive_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

    async def create_brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        brief: ProjectBrief,
    ) -> BriefVersionCreationResult:
        """Create or reuse the current immutable brief snapshot."""
        async with self._unit_of_work_factory() as unit:
            return await unit.briefs.create_owned_version(
                project_id=project_id,
                owner_user_id=owner_user_id,
                created_by_user_id=owner_user_id,
                brief=brief,
            )

    async def current_brief(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current brief of an active owned project."""
        async with self._unit_of_work_factory() as unit:
            return await unit.briefs.get_current_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

    async def brief_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        """Return one immutable brief version."""
        async with self._unit_of_work_factory() as unit:
            return await unit.briefs.get_owned_version(
                project_id=project_id,
                owner_user_id=owner_user_id,
                version_number=version_number,
            )

    async def brief_history(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        """Return the complete immutable version history."""
        async with self._unit_of_work_factory() as unit:
            return await unit.briefs.list_owned_versions(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
