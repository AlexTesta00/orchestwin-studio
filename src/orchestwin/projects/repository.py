"""Project Definition repository ports and typed results."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from orchestwin.projects.briefs import (
    ProjectBrief,
    ProjectBriefVersion,
)
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


class BriefVersionCreationStatus(StrEnum):
    """Stable outcomes of brief-version creation."""

    CREATED = "created"
    UNCHANGED = "unchanged"
    PROJECT_NOT_FOUND = "project_not_found"


class BriefVersionCreationResult:
    """Typed result for immutable brief-version creation."""

    __slots__ = (
        "status",
        "version",
    )

    def __init__(
        self,
        *,
        status: BriefVersionCreationStatus,
        version: ProjectBriefVersion | None = None,
    ) -> None:
        has_version = version is not None

        if (status is BriefVersionCreationStatus.PROJECT_NOT_FOUND) == has_version:
            raise ValueError("project-not-found must not contain a version")

        self.status = status
        self.version = version

    @property
    def created(self) -> bool:
        """Return whether a new immutable row was inserted."""
        return self.status is BriefVersionCreationStatus.CREATED


class ProjectBriefRepository(Protocol):
    """Owner-scoped immutable Project Brief persistence."""

    async def create_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        created_by_user_id: UUID,
        brief: ProjectBrief,
    ) -> BriefVersionCreationResult:
        """Create or reuse the current immutable brief version."""

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current brief version for an owned project."""

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        """Return the immutable version history."""
