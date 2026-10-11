"""SQLAlchemy unit of work for versioned team proposals."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    SqlAlchemyTeamSelectionContextRepository,
)
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceBindings
from orchestwin.persistence.unit_of_work import SqlAlchemyUnitOfWork, SqlAlchemyUnitOfWorkFactory


class SqlAlchemyTeamProposalUnitOfWork(SqlAlchemyUnitOfWork):
    """One SQLAlchemy transaction for team-proposal use cases."""

    @property
    def contexts(
        self,
    ) -> SqlAlchemyTeamSelectionContextRepository:
        """Return the context repository after entry."""
        if self._contexts is None:
            raise RuntimeError("team-proposal unit of work is not open")

        return self._contexts

    @property
    def proposals(
        self,
    ) -> SqlAlchemyTeamProposalVersionRepository:
        """Return the proposal repository after entry."""
        if self._proposals is None:
            raise RuntimeError("team-proposal unit of work is not open")

        return self._proposals

    def _bind(self, session: AsyncSession) -> None:
        self._contexts = SqlAlchemyTeamSelectionContextRepository(session)
        self._proposals = SqlAlchemyTeamProposalVersionRepository(session)
        self.proposal_evidence = SqlAlchemyProposalEvidenceBindings(session)

    def _release(self) -> None:
        self._contexts = None
        self._proposals = None


class SqlAlchemyTeamProposalUnitOfWorkFactory(SqlAlchemyUnitOfWorkFactory):
    """Create a fresh proposal unit of work per use case."""

    unit_of_work = SqlAlchemyTeamProposalUnitOfWork
