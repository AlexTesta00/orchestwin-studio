"""Repository ports for clarification rounds and assumptions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from orchestwin.projects.clarification_state import (
    BriefAssumption,
)


class BriefAssumptionRepository(Protocol):
    """Owner-scoped persistence operations for brief assumptions."""

    async def add(
        self,
        assumption: BriefAssumption,
    ) -> BriefAssumption:
        """Persist a proposed assumption."""

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
    ) -> BriefAssumption | None:
        """Return an assumption through the project owner boundary."""

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[BriefAssumption, ...]:
        """Return assumptions in creation order."""

    async def accept_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str | None = None,
    ) -> BriefAssumption | None:
        """Accept an owner-scoped proposed assumption."""

    async def reject_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        assumption_id: UUID,
        decided_at: datetime,
        reason: str,
    ) -> BriefAssumption | None:
        """Reject an owner-scoped proposed assumption."""
