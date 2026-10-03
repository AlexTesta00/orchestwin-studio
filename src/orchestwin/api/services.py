"""Application-service composition for the FastAPI boundary."""

from __future__ import annotations

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
from orchestwin.agents.realignment_persistence import build_team_realignment_service
from orchestwin.agents.realignment_service import TeamRealignmentService
from orchestwin.agents.team_gate import (
    AgentTeamGateDecisionResult,
    AgentTeamGateSubmissionResult,
    LocalAgentTeamApprovalService,
    OwnerAgentRationale,
    ProjectWorkflowReadiness,
    TeamEditResult,
)
from orchestwin.api.artifact_why import WhyQueryService
from orchestwin.api.artifacts import ArtifactGraphQueryService
from orchestwin.api.design import (
    DesignGateService,
    DesignGenerationService,
    DesignQueryService,
    DesignRevisionService,
)
from orchestwin.api.human_validation import HumanValidationService
from orchestwin.api.runtime_configuration import load_runtime_connection_settings
from orchestwin.api.sections import build_sections_service
from orchestwin.api.training import SqlAlchemyTrainingApiService, TrainingApiService
from orchestwin.artifacts.human_validation_runtime import SqlAlchemyHumanValidationService
from orchestwin.artifacts.traceability_runtime import SqlAlchemyArtifactGraphQueryService
from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.config import (
    ApplicationSettings,
    ModelRuntimeMode,
    RuntimeEnvironment,
    load_settings,
)
from orchestwin.evaluation.final_runtime import FinalEvaluatorRuntime, build_final_evaluator_runtime
from orchestwin.evaluation.local_runtime import LocalEvaluatorRuntime
from orchestwin.identity.application import (
    IdentityApplicationService,
    LocalIdentityApplicationService,
)
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import SqlAlchemyIdentityUnitOfWorkFactory
from orchestwin.identity.tokens import JwtAccessTokenService
from orchestwin.knowledge.diagram_service import ProjectDiagramService
from orchestwin.knowledge.export import KnowledgeSourceLoader
from orchestwin.knowledge.feedback_runtime import SqlAlchemyKnowledgeFeedbackQueryService
from orchestwin.knowledge.package_service import (
    KnowledgePackageService,
    SqlAlchemyKnowledgePackageStore,
)
from orchestwin.knowledge.project_import_service import ProjectImportService
from orchestwin.knowledge.research_evidence import SqlAlchemyKnowledgeEvidenceQueryService
from orchestwin.knowledge.twin_import_service import TwinImportService
from orchestwin.knowledge.twin_import_sources import SqlAlchemyTwinImportCandidateQuery
from orchestwin.models.proposal_evidence_persistence import SqlAlchemyProposalEvidenceStore
from orchestwin.models.real_runtime import (
    RealModelRuntime,
    RealModelRuntimeError,
    build_real_model_runtime,
)
from orchestwin.models.runtime import (
    create_team_proposal_port,
    load_team_proposal_runtime_settings,
)
from orchestwin.persistence import DatabaseRuntime, create_database_runtime
from orchestwin.projects import design_runtime
from orchestwin.projects.application import (
    LocalProjectApplicationService,
    ProjectApplicationService,
)
from orchestwin.projects.brief_gate import (
    LocalProjectBriefGateService,
    ProjectBriefGateService,
)
from orchestwin.projects.clarification_application import (
    LocalProjectClarificationApplicationService,
    ProjectClarificationApplicationService,
)
from orchestwin.projects.code_change_state import SqlAlchemyProjectStateQueryService
from orchestwin.projects.design_realignment_service import DesignRealignmentService
from orchestwin.projects.design_runtime import build_design_services
from orchestwin.projects.persistence import (
    SqlAlchemyProjectBriefGateUnitOfWorkFactory,
    SqlAlchemyProjectClarificationUnitOfWorkFactory,
    SqlAlchemyProjectUnitOfWorkFactory,
)
from orchestwin.projects.requirements_application import (
    LocalRequirementsGenerationService,
)
from orchestwin.projects.requirements_change_application import LocalRequirementsChangeService
from orchestwin.projects.requirements_gate import LocalRequirementsGateService
from orchestwin.projects.requirements_realignment_service import (
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
)
from orchestwin.projects.requirements_runtime import (
    ManagedRequirementsUnitOfWorkFactory,
    SqlAlchemyRequirementsQueryService,
    build_requirements_services,
)
from orchestwin.projects.sections_service import SectionsService
from orchestwin.training.adapter_artifacts import ContentAddressedAdapterRegistry
from orchestwin.twins.archetypes import ArchetypeService
from orchestwin.twins.realignment_service import UserModelingRealignmentService
from orchestwin.twins.runtime import (
    ManagedUserModelingUnitOfWorkFactory,
    SqlAlchemyUserModelingGovernanceAdapter,
    UserModelingServices,
    build_archetype_service,
    build_user_modeling_services,
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

    final_evaluator_runtime: FinalEvaluatorRuntime | LocalEvaluatorRuntime | None = None
    real_model_runtime: RealModelRuntime | None = None
    proposal_evidence_store: SqlAlchemyProposalEvidenceStore | None = None
    identity_service: IdentityApplicationService | None = None
    project_service: ProjectApplicationService | None = None
    clarification_service: ProjectClarificationApplicationService | None = None
    brief_gate_service: ProjectBriefGateService | None = None
    database_runtime: DatabaseRuntime | None = None
    team_proposal_service: TeamProposalApplicationService | None = None
    agent_team_service: AgentTeamApprovalService | None = None
    user_modeling_services: UserModelingServices | None = None
    archetype_service: ArchetypeService | None = None
    requirements_generation_service: LocalRequirementsGenerationService | None = None
    requirements_revision_service: LocalRequirementsRevisionService | None = None
    requirements_query_service: SqlAlchemyRequirementsQueryService | None = None
    requirements_gate_service: LocalRequirementsGateService | None = None
    requirements_change_service: LocalRequirementsChangeService | None = None
    design_generation_service: DesignGenerationService | None = None
    design_revision_service: DesignRevisionService | None = None
    design_query_service: DesignQueryService | None = None
    design_gate_service: DesignGateService | None = None
    artifact_graph_query_service: ArtifactGraphQueryService | None = None
    why_query_service: WhyQueryService | None = None
    human_validation_service: HumanValidationService | None = None
    project_diagram_service: ProjectDiagramService | None = None
    knowledge_package_service: KnowledgePackageService | None = None
    twin_import_service: TwinImportService | None = None
    user_modeling_realignment_service: UserModelingRealignmentService | None = None
    requirements_realignment_service: RequirementsRealignmentService | None = None
    design_realignment_service: DesignRealignmentService | None = None
    sections_service: SectionsService | None = None
    team_realignment_service: TeamRealignmentService | None = None
    project_import_service: ProjectImportService | None = None
    training_api_service: TrainingApiService | None = None

    async def close(self) -> None:
        """Dispose process-level resources."""
        closing = getattr(self.real_model_runtime, "close", None)
        try:
            if closing is not None:
                await closing()
        finally:
            if self.database_runtime is not None:
                await self.database_runtime.dispose()


def create_default_runtime(
    settings: ApplicationSettings | None = None,
) -> ApplicationRuntime:
    """Compose services from validated process/dotenv credentials, not os.getenv alone."""
    connection_settings = load_runtime_connection_settings()
    resolved_settings = settings if settings is not None else load_settings()

    real_required = resolved_settings.model_runtime_mode is ModelRuntimeMode.REAL_REQUIRED
    if not real_required and resolved_settings.model_runtime_config_file is not None:
        raise RealModelRuntimeError("REAL_MODEL_MODE_REQUIRED_FOR_CONFIGURATION")
    if resolved_settings.environment is RuntimeEnvironment.PRODUCTION and not real_required:
        raise RealModelRuntimeError("PRODUCTION_REQUIRES_REAL_MODEL_RUNTIME")

    if connection_settings is None:
        if real_required:
            raise RealModelRuntimeError("REAL_MODEL_RUNTIME_REQUIRES_DATABASE_AND_AUTH")
        return ApplicationRuntime()

    real_models = (
        build_real_model_runtime(resolved_settings.model_runtime_config_file)
        if real_required
        else None
    )
    final_evaluator = (
        real_models.final_evaluator if real_models is not None else build_final_evaluator_runtime()
    )
    team_proposal_port = (
        real_models.team
        if real_models is not None
        else create_team_proposal_port(load_team_proposal_runtime_settings())
    )
    database_runtime = create_database_runtime(connection_settings.database)

    identity_service = LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(database_runtime.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(connection_settings.access_tokens),
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
    proposal_evidence_store = SqlAlchemyProposalEvidenceStore(database_runtime.session_factory)
    team_proposal_service = LocalTeamProposalApplicationService(
        proposal_evidence_store=proposal_evidence_store,
        unit_of_work_factory=SqlAlchemyTeamProposalUnitOfWorkFactory(
            database_runtime.session_factory
        ),
        proposal_port=team_proposal_port,
    )
    agent_team_service = LocalAgentTeamApprovalService(
        unit_of_work_factory=SqlAlchemyAgentTeamUnitOfWorkFactory(database_runtime.session_factory)
    )
    user_modeling = build_user_modeling_services(
        database_runtime.session_factory,
        **({"proposal_runtime": real_models.user_modeling} if real_models is not None else {}),
    )
    requirements = build_requirements_services(
        database_runtime.session_factory,
        **({"proposal_runtime": real_models.requirements} if real_models is not None else {}),
    )
    design = build_design_services(
        database_runtime.session_factory,
        **({"proposal_runtime": real_models.design} if real_models is not None else {}),
    )
    artifact_graph_query_service = SqlAlchemyArtifactGraphQueryService(
        database_runtime.session_factory
    )
    why_query_service = SqlAlchemyWhyQueryService(database_runtime.session_factory)
    human_validation_service = SqlAlchemyHumanValidationService(
        database_runtime.session_factory, why_query_service=why_query_service
    )
    project_diagram_service = ProjectDiagramService(
        project_service=project_service,
        requirements_query_service=requirements.queries,
        design_query_service=design.queries,
    )
    project_import_service = ProjectImportService(session_factory=database_runtime.session_factory)
    knowledge_package_service = KnowledgePackageService(
        source_loader=KnowledgeSourceLoader(
            project_service=project_service,
            brief_gate_service=brief_gate_service,
            team_proposal_service=team_proposal_service,
            agent_team_service=agent_team_service,
            user_modeling_services=user_modeling,
            requirements_query_service=requirements.queries,
            requirements_gate_service=requirements.gate,
            design_query_service=design.queries,
            design_gate_service=design.gate,
            feedback_query_service=SqlAlchemyKnowledgeFeedbackQueryService(
                database_runtime.session_factory
            ),
            state_query_service=SqlAlchemyProjectStateQueryService(
                database_runtime.session_factory
            ),
            evidence_query_service=SqlAlchemyKnowledgeEvidenceQueryService(
                database_runtime.session_factory
            ),
            validation_query_service=human_validation_service,
            import_origin_query_service=project_import_service,
        ),
        store=SqlAlchemyKnowledgePackageStore(database_runtime.session_factory),
    )
    twin_import_service = TwinImportService(
        governance=SqlAlchemyUserModelingGovernanceAdapter(database_runtime.session_factory),
        uow_factory=ManagedUserModelingUnitOfWorkFactory(database_runtime.session_factory),
        project_service=project_service,
        user_modeling_queries=user_modeling.queries,
        user_modeling_gates=user_modeling.gates,
        candidates=SqlAlchemyTwinImportCandidateQuery(database_runtime.session_factory),
    )
    team_realignment_service = build_team_realignment_service(database_runtime.session_factory)
    user_modeling_realignment_service = UserModelingRealignmentService(
        governance=SqlAlchemyUserModelingGovernanceAdapter(database_runtime.session_factory),
        team_queries=agent_team_service,
        uow_factory=ManagedUserModelingUnitOfWorkFactory(database_runtime.session_factory),
    )
    requirements_realignment_service = RequirementsRealignmentService(
        uow_factory=ManagedRequirementsUnitOfWorkFactory(database_runtime.session_factory),
        user_modeling_queries=user_modeling.queries,
        user_modeling_gates=user_modeling.gates,
        user_modeling_context=user_modeling_realignment_service,
    )
    design_realignment_service = DesignRealignmentService(
        uow_factory=design_runtime.ManagedDesignUnitOfWorkFactory(database_runtime.session_factory),
        requirements_queries=requirements.queries,
        requirements_gates=requirements.gate,
    )
    sections_service = build_sections_service(
        team_realignment_service=team_realignment_service,
        agent_team_service=agent_team_service,
        database_runtime=database_runtime,
        user_modeling_services=user_modeling,
        user_modeling_realignment_service=user_modeling_realignment_service,
        requirements_realignment_service=requirements_realignment_service,
        requirements_gate_service=requirements.gate,
        design_realignment_service=design_realignment_service,
        design_gate_service=design.gate,
        real_model_runtime=real_models,
        proposal_evidence_store=proposal_evidence_store,
    )

    return ApplicationRuntime(
        real_model_runtime=real_models,
        final_evaluator_runtime=final_evaluator,
        proposal_evidence_store=proposal_evidence_store,
        identity_service=identity_service,
        project_service=project_service,
        clarification_service=clarification_service,
        brief_gate_service=brief_gate_service,
        database_runtime=database_runtime,
        team_proposal_service=team_proposal_service,
        agent_team_service=agent_team_service,
        user_modeling_services=user_modeling,
        requirements_generation_service=requirements.generation,
        archetype_service=build_archetype_service(database_runtime.session_factory),
        requirements_revision_service=requirements.revisions,
        requirements_query_service=requirements.queries,
        requirements_gate_service=requirements.gate,
        requirements_change_service=requirements.changes,
        design_generation_service=design.generation,
        design_revision_service=design.revisions,
        design_query_service=design.queries,
        design_gate_service=design.gate,
        artifact_graph_query_service=artifact_graph_query_service,
        why_query_service=why_query_service,
        human_validation_service=human_validation_service,
        project_diagram_service=project_diagram_service,
        knowledge_package_service=knowledge_package_service,
        twin_import_service=twin_import_service,
        user_modeling_realignment_service=user_modeling_realignment_service,
        requirements_realignment_service=requirements_realignment_service,
        design_realignment_service=design_realignment_service,
        sections_service=sections_service,
        team_realignment_service=team_realignment_service,
        project_import_service=project_import_service,
        training_api_service=SqlAlchemyTrainingApiService(
            session_factory=database_runtime.session_factory,
            adapter_registry=ContentAddressedAdapterRegistry(
                resolved_settings.training_adapter_registry_root
            ),
        ),
    )
