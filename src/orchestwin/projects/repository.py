"""Project Definition repository ports."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from orchestwin.projects.domain import Project


class ProjectRepository(Protocol):
    """Owner-scoped project persistence operations."""

    async def add(
        self,
        project: Project,
    ) -> Project:
        """Persist a project."""

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        include_archived: bool = False,
    ) -> Project | None:
        """Return one project only for its owner."""

    async def list_active_owned(
        self,
        *,
        owner_user_id: UUID,
    ) -> tuple[Project, ...]:
        """Return active projects belonging to one owner."""

    async def rename_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        display_name: str,
    ) -> Project | None:
        """Rename an active project belonging to one owner."""

    async def archive_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> Project | None:
        """Archive an active project belonging to one owner."""
