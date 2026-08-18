"""Tests for Project Definition application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID, uuid4

from orchestwin.projects.application import (
    LocalProjectApplicationService,
)
from orchestwin.projects.briefs import (
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    Project,
    ProjectMode,
)
from orchestwin.projects.repository import (
    BriefVersionCreationResult,
    BriefVersionCreationStatus,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")


class InMemoryProjectRepository:
    """Owner-scoped in-memory project repository."""

    def __init__(self) -> None:
        self.projects: dict[UUID, Project] = {}

    async def add(
        self,
        project: Project,
    ) -> Project:
        self.projects[project.id] = project
        return project

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        include_archived: bool = False,
    ) -> Project | None:
        project = self.projects.get(project_id)

        if (
            project is None
            or project.owner_user_id != owner_user_id
            or (project.is_archived and not include_archived)
        ):
            return None

        return project

    async def list_active_owned(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        return tuple(
            project
            for project in self.projects.values()
            if (project.owner_user_id == owner_user_id and not project.is_archived)
        )

    async def rename_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        project = await self.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if project is None:
            return None

        renamed = Project(
            id=project.id,
            owner_user_id=project.owner_user_id,
            display_name=display_name.strip(),
            mode=project.mode,
            current_brief_version=(project.current_brief_version),
            archived_at=project.archived_at,
            created_at=project.created_at,
            updated_at=datetime.now(UTC),
        )
        self.projects[project_id] = renamed

        return renamed

    async def archive_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        project = await self.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if project is None:
            return None

        archived = Project(
            id=project.id,
            owner_user_id=project.owner_user_id,
            display_name=project.display_name,
            mode=project.mode,
            current_brief_version=(project.current_brief_version),
            archived_at=datetime.now(UTC),
            created_at=project.created_at,
            updated_at=datetime.now(UTC),
        )
        self.projects[project_id] = archived

        return archived


class InMemoryBriefRepository:
    """In-memory immutable brief-version repository."""

    def __init__(
        self,
        projects: InMemoryProjectRepository,
    ) -> None:
        self._projects = projects
        self.versions: dict[
            UUID,
            list[ProjectBriefVersion],
        ] = {}

    async def create_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        created_by_user_id: UUID,
        brief,
    ) -> BriefVersionCreationResult:
        project = await self._projects.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if project is None:
            return BriefVersionCreationResult(status=(BriefVersionCreationStatus.PROJECT_NOT_FOUND))

        existing = self.versions.setdefault(
            project_id,
            [],
        )

        if existing and existing[-1].content_hash == brief.content_hash:
            return BriefVersionCreationResult(
                status=(BriefVersionCreationStatus.UNCHANGED),
                version=existing[-1],
            )

        version = ProjectBriefVersion(
            id=uuid4(),
            project_id=project_id,
            version_number=len(existing) + 1,
            schema_version=brief.SCHEMA_VERSION,
            brief=brief,
            content_hash=brief.content_hash,
            created_by_user_id=(created_by_user_id),
            created_at=datetime.now(UTC),
        )
        existing.append(version)

        return BriefVersionCreationResult(
            status=(BriefVersionCreationStatus.CREATED),
            version=version,
        )

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        project = await self._projects.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if project is None:
            return None

        versions = self.versions.get(
            project_id,
            [],
        )

        return versions[-1] if versions else None

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        versions = await self.list_owned_versions(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        return next(
            (version for version in versions if version.version_number == version_number),
            None,
        )

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        project = await self._projects.get_owned(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

        if project is None:
            return ()

        return tuple(
            self.versions.get(
                project_id,
                [],
            )
        )


class InMemoryProjectUnitOfWork:
    """Reusable in-memory project unit of work."""

    def __init__(
        self,
        projects: InMemoryProjectRepository,
        briefs: InMemoryBriefRepository,
    ) -> None:
        self.projects = projects
        self.briefs = briefs

    async def __aenter__(
        self,
    ) -> InMemoryProjectUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def build_service() -> LocalProjectApplicationService:
    """Create a project service with reusable in-memory adapters."""
    projects = InMemoryProjectRepository()
    briefs = InMemoryBriefRepository(projects)

    return LocalProjectApplicationService(
        unit_of_work_factory=lambda: InMemoryProjectUnitOfWork(
            projects,
            briefs,
        )
    )


def test_projects_are_isolated_by_owner() -> None:
    """Hide a project from every other user."""
    service = build_service()

    project = asyncio.run(
        service.create(
            owner_user_id=OWNER_ID,
            display_name="Project",
            mode=(ProjectMode.GREENFIELD_GENERATION),
        )
    )

    owner_result = asyncio.run(
        service.get(
            project_id=project.id,
            owner_user_id=OWNER_ID,
        )
    )
    other_result = asyncio.run(
        service.get(
            project_id=project.id,
            owner_user_id=OTHER_OWNER_ID,
        )
    )

    assert owner_result == project
    assert other_result is None


def test_brief_versions_are_created_and_reused() -> None:
    """Create version one and reuse identical content."""
    service = build_service()
    project = asyncio.run(
        service.create(
            owner_user_id=OWNER_ID,
            display_name="Project",
            mode=(ProjectMode.GREENFIELD_GENERATION),
        )
    )
    brief = create_project_brief(name="Project")

    first = asyncio.run(
        service.create_brief_version(
            project_id=project.id,
            owner_user_id=OWNER_ID,
            brief=brief,
        )
    )
    second = asyncio.run(
        service.create_brief_version(
            project_id=project.id,
            owner_user_id=OWNER_ID,
            brief=brief,
        )
    )

    assert first.status is (BriefVersionCreationStatus.CREATED)
    assert second.status is (BriefVersionCreationStatus.UNCHANGED)
    assert first.version == second.version
