from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.design_discussion_persistence import SqlAlchemyDesignDiscussionRepository
from orchestwin.artifacts.design_evaluation_persistence import SqlAlchemyDesignEvaluationRepository
from orchestwin.artifacts.design_finding_validation_persistence import (
    SqlAlchemyFindingValidationRepository,
)
from orchestwin.knowledge.sources import KnowledgeFeedback, knowledge_feedback
from orchestwin.projects.persistence.insight_applications import (
    SqlAlchemyInsightApplicationRepository,
)

FEEDBACK_LIMIT: Final = 200


class SqlAlchemyKnowledgeFeedbackQueryService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> KnowledgeFeedback:
        async with self._session_factory() as session:
            runs = await SqlAlchemyDesignEvaluationRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id, limit=FEEDBACK_LIMIT)
            validations = await SqlAlchemyFindingValidationRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id)
            discussions = await SqlAlchemyDesignDiscussionRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id, limit=FEEDBACK_LIMIT)
            applications = await SqlAlchemyInsightApplicationRepository(
                session, owner_user_id=owner_user_id
            ).list(project_id=project_id, limit=FEEDBACK_LIMIT)
        return knowledge_feedback(
            runs=runs,
            validations=validations,
            discussions=discussions,
            applications=applications,
        )


__all__ = [
    "FEEDBACK_LIMIT",
    "SqlAlchemyKnowledgeFeedbackQueryService",
]
