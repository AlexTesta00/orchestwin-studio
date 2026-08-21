"""Application-service composition for the FastAPI boundary."""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.persistence import (
    SqlAlchemyAgentTeamUnitOfWorkFactory,
    SqlAlchemyTeamProposalUnitOfWorkFactory,
)
from orchestwin.agents.proposals import (
    LocalTeamProposalApplicationService,
    TeamProposalApplicationService,
)
from orchestwin.agents.team_gate import (
    AgentTeamGateDecisionResult,
    AgentTeamGateSubmissionResult,
    LocalAgentTeamApprovalService,
    OwnerAgentRationale,
    ProjectWorkflowReadiness,
    TeamEditResult,
)
from orchestwin.api.architecture import (
    ArchitectureGateService,
    ArchitectureGenerationService,
    ArchitectureQueryService,
    ArchitectureRevisionService,
)
from orchestwin.api.design import (
    DesignGateService,
    DesignGenerationService,
    DesignQueryService,
    DesignRevisionService,
)
from orchestwin.identity.application import (
    IdentityApplicationService,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import (
    JwtAccessTokenService,
    load_access_token_settings,
)
from orchestwin.models.runtime import (
    create_team_proposal_port,
    load_team_proposal_runtime_settings,
)
from orchestwin.persistence import (
    DatabaseRuntime,
    create_database_runtime,
    load_database_settings,
)
from orchestwin.projects.application import (
    LocalProjectApplicationService,
    ProjectApplicationService,
)
from orchestwin.projects.architecture_runtime import build_architecture_services
from orchestwin.projects.brief_gate import (
    LocalProjectBriefGateService,
    ProjectBriefGateService,
)
from orchestwin.projects.clarification_application import (
    LocalProjectClarificationApplicationService,
    ProjectClarificationApplicationService,
)
from orchestwin.projects.design_runtime import build_design_services
from orchestwin.projects.persistence import (
    SqlAlchemyProjectBriefGateUnitOfWorkFactory,
    SqlAlchemyProjectClarificationUnitOfWorkFactory,
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.projects.requirements_application import (
    LocalRequirementsGenerationService,
)
from orchestwin.projects.requirements_gate import LocalRequirementsGateService
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
)
from orchestwin.projects.requirements_runtime import (
    SqlAlchemyRequirementsQueryService,
    build_requirements_services,
)
from orchestwin.workflow.gates import HumanGate, HumanGateAction, HumanGateEvent

DATABASE_URL_ENVIRONMENT = "ORCHESTWIN_DATABASE_URL"
JWT_SECRET_ENVIRONMENT = "ORCHESTWIN_AUTH_JWT_SECRET"


class AgentTeamApprovalService(Protocol):
    """Use cases exposed to the Agent Team API adapter."""

    async def edit_current(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        selected_agent_ids: Iterable[AgentIdentifier],
        owner_rationales: Iterable[OwnerAgentRationale] = (),
    ) -> TeamEditResult:
        """Create or reuse an owner-edited team version."""

    async def submit_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> AgentTeamGateSubmissionResult:
        """Submit the current team proposal to Gate 2."""

    async def decide_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> AgentTeamGateDecisionResult:
        """Apply one owner decision to Gate 2."""

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectWorkflowReadiness:
        """Return the derived project readiness."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the current owner-scoped Gate 2."""

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the Gate 2 append-only event history."""


@dataclass(slots=True)
class ApplicationRuntime:
    """Process-level adapters owned by one FastAPI application."""

    identity_service: IdentityApplicationService | None = None
    project_service: ProjectApplicationService | None = None
    clarification_service: ProjectClarificationApplicationService | None = None
    brief_gate_service: ProjectBriefGateService | None = None
    database_runtime: DatabaseRuntime | None = None
    team_proposal_service: TeamProposalApplicationService | None = None
    agent_team_service: AgentTeamApprovalService | None = None
    requirements_generation_service: LocalRequirementsGenerationService | None = None
    requirements_revision_service: LocalRequirementsRevisionService | None = None
    requirements_query_service: SqlAlchemyRequirementsQueryService | None = None
    requirements_gate_service: LocalRequirementsGateService | None = None
    design_generation_service: DesignGenerationService | None = None
    design_revision_service: DesignRevisionService | None = None
    design_query_service: DesignQueryService | None = None
    design_gate_service: DesignGateService | None = None
    architecture_generation_service: ArchitectureGenerationService | None = None
    architecture_revision_service: ArchitectureRevisionService | None = None
    architecture_query_service: ArchitectureQueryService | None = None
    architecture_gate_service: ArchitectureGateService | None = None

    async def close(self) -> None:
        """Dispose process-level resources."""
        if self.database_runtime is not None:
            await self.database_runtime.dispose()


def create_default_runtime() -> ApplicationRuntime:
    """Create persistence-backed services when configuration exists."""
    database_url = os.getenv(DATABASE_URL_ENVIRONMENT)
    jwt_secret = os.getenv(JWT_SECRET_ENVIRONMENT)

    if not database_url or not jwt_secret:
        return ApplicationRuntime()

    team_proposal_port = create_team_proposal_port(load_team_proposal_runtime_settings())
    database_runtime = create_database_runtime(load_database_settings())

    identity_service = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(database_runtime.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(load_access_token_settings()),
    )
    project_service = LocalProjectApplicationService(
        unit_of_work_factory=SqlAlchemyProjectUnitOfWorkFactory(database_runtime.session_factory)
    )
    clarification_service = LocalProjectClarificationApplicationService(
        unit_of_work_factory=SqlAlchemyProjectClarificationUnitOfWorkFactory(
            database_runtime.session_factory
        )
    )
    brief_gate_service = LocalProjectBriefGateService(
        unit_of_work_factory=SqlAlchemyProjectBriefGateUnitOfWorkFactory(
            database_runtime.session_factory
        )
    )
    team_proposal_service = LocalTeamProposalApplicationService(
        unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(
            database_runtime.session_factory
        ),
        proposal_port=team_proposal_port,
    )
    agent_team_service = LocalAgentTeamApprovalService(
        unit_of_work_factory=SqlAlchemyAgentTeamUnitOfWorkFactory(database_runtime.session_factory)
    )
    requirements = build_requirements_services(database_runtime.session_factory)
    design = build_design_services(database_runtime.session_factory)
    architecture = build_architecture_services(database_runtime.session_factory)

    return ApplicationRuntime(
        identity_service=identity_service,
        project_service=project_service,
        clarification_service=clarification_service,
        brief_gate_service=brief_gate_service,
        database_runtime=database_runtime,
        team_proposal_service=team_proposal_service,
        agent_team_service=agent_team_service,
        requirements_generation_service=requirements.generation,
        requirements_revision_service=requirements.revisions,
        requirements_query_service=requirements.queries,
        requirements_gate_service=requirements.gate,
        design_generation_service=design.generation,
        design_revision_service=design.revisions,
        design_query_service=design.queries,
        design_gate_service=design.gate,
        architecture_generation_service=architecture.generation,
        architecture_revision_service=architecture.revisions,
        architecture_query_service=architecture.queries,
        architecture_gate_service=architecture.gate,
    )
