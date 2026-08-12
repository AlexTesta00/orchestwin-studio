"""Repository ports for clarification rounds and assumptions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from orchestwin.projects.clarification_state import (
    BriefAssumption,
    ClarificationRound,
)


class ClarificationRoundRepository(Protocol):
    """Owner-scoped persistence operations for clarification rounds."""

    async def add(
        self,
        round_state: ClarificationRound,
    ) -> ClarificationRound:
        """Persist an open clarification round."""

    async def count_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> int:
        """Count clarification rounds for an owned project."""

    async def get_current_open_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ClarificationRound | None:
        """Return the current open round for an owned project."""

    async def get_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
    ) -> ClarificationRound | None:
        """Return one round through the project ownership boundary."""

    async def list_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ClarificationRound, ...]:
        """Return clarification-round history in sequence order."""

    async def complete_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        round_id: UUID,
        resulting_brief_version_number: int,
        answered_at: datetime,
    ) -> ClarificationRound | None:
        """Complete an open round through an owner-scoped row lock."""


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
