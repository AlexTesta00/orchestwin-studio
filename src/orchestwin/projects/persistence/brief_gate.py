"""SQLAlchemy unit of work for Project Brief approval gates."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.persistence.unit_of_work import SqlAlchemyUnitOfWork, SqlAlchemyUnitOfWorkFactory
from orchestwin.projects.briefs import (
    ProjectBriefVersion,
)
from orchestwin.projects.persistence.briefs import (
    brief_record_to_domain,
)
from orchestwin.projects.persistence.models import (
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
)


def owned_project_for_gate_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    """Build the owner-scoped project lock used by Gate 1."""
    return (
        select(ProjectRecord)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        .with_for_update()
    )


class SqlAlchemyCurrentProjectBriefRepository:
    """Lock and load the current brief through project ownership."""

    def __init__(
        self,
        session: AsyncSession,
    ) -> None:
        self._session = session

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Lock the owned project and return its current brief."""
        project = await self._session.scalar(
            owned_project_for_gate_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if project is None or project.current_brief_version < 1:
            return None

        record = await self._session.scalar(
            select(ProjectBriefVersionRecord).where(
                ProjectBriefVersionRecord.project_id == project.id,
                ProjectBriefVersionRecord.version_number == project.current_brief_version,
            )
        )

        if record is None:
            raise RuntimeError("project current brief version is missing")

        return brief_record_to_domain(record)


class SqlAlchemyProjectBriefGateUnitOfWork(SqlAlchemyUnitOfWork):
    """One SQLAlchemy transaction for a Gate 1 use case."""

    @property
    def current_briefs(
        self,
    ) -> SqlAlchemyCurrentProjectBriefRepository:
        """Return the current-brief repository after entry."""
        if self._current_briefs is None:
            raise RuntimeError("Project Brief gate unit of work is not open")

        return self._current_briefs

    @property
    def gates(
        self,
    ) -> SqlAlchemyHumanGateRepository:
        """Return the gate repository after entry."""
        if self._gates is None:
            raise RuntimeError("Project Brief gate unit of work is not open")

        return self._gates

    def _bind(self, session: AsyncSession) -> None:
        self._current_briefs = SqlAlchemyCurrentProjectBriefRepository(session)
        self._gates = SqlAlchemyHumanGateRepository(session)

    def _release(self) -> None:
        self._current_briefs = None
        self._gates = None


class SqlAlchemyProjectBriefGateUnitOfWorkFactory(SqlAlchemyUnitOfWorkFactory):
    """Create a fresh Gate 1 unit of work per use case."""

    unit_of_work = SqlAlchemyProjectBriefGateUnitOfWork
