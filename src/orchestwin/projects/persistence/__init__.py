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
)
from orchestwin.projects.persistence.clarification_uow import (
    SqlAlchemyProjectClarificationUnitOfWork,
    SqlAlchemyProjectClarificationUnitOfWorkFactory,
)
from orchestwin.projects.persistence.models import (
    BriefAssumptionRecord,
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
    "ProjectBriefVersionRecord",
    "ProjectRecord",
    "SqlAlchemyBriefAssumptionRepository",
    "SqlAlchemyCurrentProjectBriefRepository",
    "SqlAlchemyProjectBriefGateUnitOfWork",
    "SqlAlchemyProjectBriefGateUnitOfWorkFactory",
    "SqlAlchemyProjectBriefRepository",
    "SqlAlchemyProjectClarificationUnitOfWork",
    "SqlAlchemyProjectClarificationUnitOfWorkFactory",
    "SqlAlchemyProjectRepository",
    "SqlAlchemyProjectUnitOfWork",
    "SqlAlchemyProjectUnitOfWorkFactory",
]
