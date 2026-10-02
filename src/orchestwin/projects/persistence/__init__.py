"""SQLAlchemy adapters for Project Definition."""

from importlib import import_module

_EXPORT_MODULES = {
    "BriefAssumptionRecord": "models",
    "ProjectBriefVersionRecord": "models",
    "ProjectRecord": "models",
    "SqlAlchemyBriefAssumptionRepository": "clarification",
    "SqlAlchemyCurrentProjectBriefRepository": "brief_gate",
    "SqlAlchemyProjectBriefGateUnitOfWork": "brief_gate",
    "SqlAlchemyProjectBriefGateUnitOfWorkFactory": "brief_gate",
    "SqlAlchemyProjectBriefRepository": "briefs",
    "SqlAlchemyProjectClarificationUnitOfWork": "clarification_uow",
    "SqlAlchemyProjectClarificationUnitOfWorkFactory": "clarification_uow",
    "SqlAlchemyProjectRepository": "repositories",
    "SqlAlchemyProjectUnitOfWork": "unit_of_work",
    "SqlAlchemyProjectUnitOfWorkFactory": "unit_of_work",
}

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


def __getattr__(name):
    module = _EXPORT_MODULES.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module}"), name)
    globals()[name] = value
    return value
