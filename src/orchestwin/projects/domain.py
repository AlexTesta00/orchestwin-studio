"""Immutable project aggregate values and transitions."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProjectMode(StrEnum):
    """Supported top-level project intake modes."""

    GREENFIELD_GENERATION = "GREENFIELD_GENERATION"
    BROWNFIELD_ASSESSMENT = "BROWNFIELD_ASSESSMENT"


@dataclass(frozen=True, slots=True)
class Project:
    """Owner-scoped project aggregate state."""

    id: UUID
    owner_user_id: UUID
    display_name: str
    mode: ProjectMode
    current_brief_version: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None

    def __post_init__(self) -> None:
        """Protect project aggregate invariants."""
        if not self.display_name:
            raise ValueError("project display name is required")

        if self.display_name != (self.display_name.strip()):
            raise ValueError("project display name must be normalized")

        if len(self.display_name) > 120:
            raise ValueError("project display name exceeds 120 characters")

        if self.current_brief_version < 0:
            raise ValueError("current brief version must not be negative")

        timestamps = (
            self.created_at,
            self.updated_at,
            self.archived_at,
        )

        if any(timestamp is not None and timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("project timestamps must be timezone-aware")

        if self.updated_at < self.created_at:
            raise ValueError("project updated_at must not precede created_at")

        if self.archived_at is not None and self.archived_at < self.created_at:
            raise ValueError("project archived_at must not precede created_at")

    @property
    def is_archived(self) -> bool:
        """Return whether the project is archived."""
        return self.archived_at is not None


def normalize_project_name(
    display_name: str,
) -> str:
    """Normalize and validate a project display name."""
    normalized = " ".join(display_name.split())

    if not normalized:
        raise ValueError("project display name is required")

    if len(normalized) > 120:
        raise ValueError("project display name exceeds 120 characters")

    return normalized


def create_project(
    *,
    owner_user_id: UUID,
    display_name: str,
    mode: ProjectMode,
    project_id: UUID | None = None,
    created_at: datetime | None = None,
) -> Project:
    """Create one active project with no brief version."""
    timestamp = created_at or datetime.now(UTC)

    return Project(
        id=project_id or uuid4(),
        owner_user_id=owner_user_id,
        display_name=normalize_project_name(display_name),
        mode=mode,
        current_brief_version=0,
        created_at=timestamp,
        updated_at=timestamp,
    )


def rename_project(
    project: Project,
    *,
    display_name: str,
    updated_at: datetime | None = None,
) -> Project:
    """Return a renamed project without changing its mode."""
    timestamp = updated_at or datetime.now(UTC)

    if timestamp < project.updated_at:
        raise ValueError("project rename timestamp must not move backwards")

    return replace(
        project,
        display_name=normalize_project_name(display_name),
        updated_at=timestamp,
    )


def archive_project(
    project: Project,
    *,
    archived_at: datetime | None = None,
) -> Project:
    """Archive a project idempotently."""
    if project.archived_at is not None:
        return project

    timestamp = archived_at or datetime.now(UTC)

    if timestamp < project.updated_at:
        raise ValueError("project archive timestamp must not move backwards")

    return replace(
        project,
        archived_at=timestamp,
        updated_at=timestamp,
    )
