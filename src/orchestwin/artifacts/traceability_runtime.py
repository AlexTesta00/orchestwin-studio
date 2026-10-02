"""SQLAlchemy-backed query composition for the cross-stage artifact graph."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.design_persistence import SqlAlchemyDesignPackageRepository
from orchestwin.artifacts.traceability import (
    CrossStageArtifactGraph,
    build_cross_stage_artifact_graph,
    grounded_design,
)
from orchestwin.projects.persistence.research_evidence import SqlAlchemyResearchEvidenceRepository
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.user_modeling_gate import user_modeling_gate_is_currently_approved
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.repositories import (
    gate_record_to_domain,
    latest_owned_gate_statement,
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
            requirements = await requirements_repository.current(project_id=project_id)

            if requirements is None:
                return None

            design = await design_repository.current(project_id=project_id)
            evidence_repository = SqlAlchemyResearchEvidenceRepository(
                session, owner_user_id=owner_user_id
            )
            evidence = await evidence_repository.dossier(project_id)
            modeling = None
            if evidence.get("evidence"):
                modeling = await SqlAlchemyUserModelingSnapshotRepository(
                    session, owner_user_id=owner_user_id
                ).current(project_id=project_id)
                gate_record = await session.scalar(
                    latest_owned_gate_statement(
                        project_id=project_id,
                        owner_user_id=owner_user_id,
                        gate_type=HumanGateType.USER_MODELING,
                    )
                )
                gate = None if gate_record is None else gate_record_to_domain(gate_record)
                if not user_modeling_gate_is_currently_approved(gate, modeling):
                    modeling = None
            return build_cross_stage_artifact_graph(
                requirements,
                grounded_design(requirements, design),
                research_evidence=evidence,
                evidence_twins=() if modeling is None else modeling.snapshot.twin_versions,
            )


__all__ = ["SqlAlchemyArtifactGraphQueryService"]
