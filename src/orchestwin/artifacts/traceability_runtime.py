"""SQLAlchemy-backed query composition for the cross-stage artifact graph."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.architecture_persistence import (
    SqlAlchemyArchitecturePackageRepository,
)
from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.traceability import (
    CrossStageArtifactGraph,
    build_cross_stage_artifact_graph,
)
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)


class SqlAlchemyArtifactGraphQueryService:
    """Derive one owner-scoped graph from the current immutable stage versions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> CrossStageArtifactGraph | None:
        """Return the current graph or no resource when Requirements do not exist."""
        async with self._session_factory() as session:
            requirements_repository = SqlAlchemyRequirementsSpecificationRepository(
                session,
                owner_user_id=owner_user_id,
            )
            design_repository = SqlAlchemyDesignPackageRepository(
                session,
                owner_user_id=owner_user_id,
            )
            architecture_repository = SqlAlchemyArchitecturePackageRepository(
                session,
                owner_user_id=owner_user_id,
            )
            requirements = await requirements_repository.current(project_id=project_id)

            if requirements is None:
                return None

            design = await design_repository.current(project_id=project_id)
            architecture = await architecture_repository.current(project_id=project_id)

            if design is None:
                architecture = None

            return build_cross_stage_artifact_graph(
                requirements,
                design,
                architecture,
            )


__all__ = ["SqlAlchemyArtifactGraphQueryService"]
