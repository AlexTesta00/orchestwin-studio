"""SQLAlchemy adapters for Agent Catalog and Team Selection."""

from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    SqlAlchemyTeamSelectionContextRepository,
)
from orchestwin.agents.persistence.team_gate import (
    SqlAlchemyAgentTeamUnitOfWork,
    SqlAlchemyAgentTeamUnitOfWorkFactory,
    SqlAlchemyEditableTeamProposalRepository,
)
from orchestwin.agents.persistence.unit_of_work import (
    SqlAlchemyTeamProposalUnitOfWork,
    SqlAlchemyTeamProposalUnitOfWorkFactory,
)

__all__ = [
    "SqlAlchemyAgentTeamUnitOfWork",
    "SqlAlchemyAgentTeamUnitOfWorkFactory",
    "SqlAlchemyEditableTeamProposalRepository",
    "SqlAlchemyTeamProposalUnitOfWork",
    "SqlAlchemyTeamProposalUnitOfWorkFactory",
    "SqlAlchemyTeamProposalVersionRepository",
    "SqlAlchemyTeamSelectionContextRepository",
    "TeamProposalVersionRecord",
]
