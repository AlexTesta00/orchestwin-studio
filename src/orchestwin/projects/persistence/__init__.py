"""SQLAlchemy adapters for Project Definition."""

from orchestwin.projects.persistence.brief_gate import (
    SqlAlchemyCurrentProjectBriefRepository,
    SqlAlchemyProjectBriefGateUnitOfWork,
    SqlAlchemyProjectBriefGateUnitOfWorkFactory,
)
from orchestwin.projects.persistence.briefs import (
    SqlAlchemyProjectBriefRepository,
)
from orchestwin.projects.persistence.clarification import (
    SqlAlchemyBriefAssumptionRepository,
    SqlAlchemyClarificationRoundRepository,
)
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
    ClarificationRoundRecord,
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.projects.persistence.repositories import (
    SqlAlchemyProjectRepository,
)
from orchestwin.projects.persistence.unit_of_work import (
    SqlAlchemyProjectUnitOfWork,
    SqlAlchemyProjectUnitOfWorkFactory,
)

__all__ = [
    "BriefAssumptionRecord",
    "ClarificationRoundRecord",
    "ProjectBriefVersionRecord",
    "ProjectRecord",
    "SqlAlchemyBriefAssumptionRepository",
    "SqlAlchemyClarificationRoundRepository",
    "SqlAlchemyCurrentProjectBriefRepository",
    "SqlAlchemyProjectBriefGateUnitOfWork",
    "SqlAlchemyProjectBriefGateUnitOfWorkFactory",
    "SqlAlchemyProjectBriefRepository",
    "SqlAlchemyProjectRepository",
    "SqlAlchemyProjectUnitOfWork",
    "SqlAlchemyProjectUnitOfWorkFactory",
]
