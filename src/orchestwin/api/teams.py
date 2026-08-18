"""HTTP contracts for the agent catalog, team proposals, and Gate 2."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentCapability,
    AgentCatalogEntry,
    AgentCatalogKind,
    AgentIdentifier,
    AgentSelectionPolicy,
    all_agent_catalog_entries,
)
from orchestwin.agents.proposals import (
    TeamProposalApplicationResult,
    TeamProposalApplicationService,
    TeamProposalApplicationStatus,
    TeamProposalRevisionKind,
    TeamProposalVersion,
)
from orchestwin.agents.selection_rules import (
    RuleEvidence,
    TeamRoleConstraint,
    TeamRoleConstraintKind,
    TeamSelectionIssue,
    TeamSelectionIssueCode,
    TeamSelectionReason,
    TeamSelectionReasonCode,
)
from orchestwin.agents.team_gate import (
    AgentTeamGateDecisionResult,
    AgentTeamGateDecisionStatus,
    AgentTeamGateSubmissionResult,
    AgentTeamGateSubmissionStatus,
    OwnerAgentRationale,
    ProjectWorkflowReadiness,
    TeamEditIssue,
    TeamEditIssueCode,
    TeamEditResult,
    TeamEditStatus,
    create_owner_agent_rationale,
)
from orchestwin.api.auth import (
    current_user_dependency,
)
from orchestwin.api.clarification import (
    HumanGateEventResponse,
    HumanGateResponse,
)
from orchestwin.api.services import (
    AgentTeamApprovalService,
)
from orchestwin.identity.domain import (
    UserAccount,
)
from orchestwin.models.team_proposals import (
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
)
from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
)


class AgentCatalogEntryResponse(BaseModel):
    """Public representation of one fixed-catalog agent."""

    model_config = ConfigDict(frozen=True)

    agent_id: AgentIdentifier
    catalog_version: int
    kind: AgentCatalogKind
    selection_policy: AgentSelectionPolicy
    capabilities: tuple[
        AgentCapability,
        ...,
    ]
    supported_project_modes: tuple[
        ProjectMode,
        ...,
    ]
    name_key: str
    description_key: str
    is_always_present: bool

    @classmethod
    def from_domain(
        cls,
        entry: AgentCatalogEntry,
    ) -> AgentCatalogEntryResponse:
        """Map one fixed-catalog entry into the API contract."""
        return cls(
            agent_id=entry.agent_id,
            catalog_version=entry.catalog_version,
            kind=entry.kind,
            selection_policy=entry.selection_policy,
            capabilities=entry.capabilities,
            supported_project_modes=tuple(
                sorted(
                    entry.supported_project_modes,
                    key=lambda mode: mode.value,
                )
            ),
            name_key=entry.name_key,
            description_key=(entry.description_key),
            is_always_present=(entry.is_always_present),
        )


class AgentCatalogResponse(BaseModel):
    """Versioned fixed-agent catalog."""

    model_config = ConfigDict(frozen=True)

    catalog_version: int
    content_hash: str
    agents: tuple[
        AgentCatalogEntryResponse,
        ...,
    ]


class RuleEvidenceResponse(BaseModel):
    """Fields and normalized terms activating a deterministic rule."""

    model_config = ConfigDict(frozen=True)

    fields: tuple[
        BriefField,
        ...,
    ]
    terms: tuple[str, ...]

    @classmethod
    def from_domain(
        cls,
        evidence: RuleEvidence,
    ) -> RuleEvidenceResponse:
        """Map deterministic rule evidence."""
        return cls(
            fields=evidence.fields,
            terms=evidence.terms,
        )


class TeamSelectionReasonResponse(BaseModel):
    """One deterministic explanation for a role constraint."""

    model_config = ConfigDict(frozen=True)

    code: TeamSelectionReasonCode
    evidence: RuleEvidenceResponse

    @classmethod
    def from_domain(
        cls,
        reason: TeamSelectionReason,
    ) -> TeamSelectionReasonResponse:
        """Map one selection reason."""
        return cls(
            code=reason.code,
            evidence=RuleEvidenceResponse.from_domain(reason.evidence),
        )


class TeamRoleConstraintResponse(BaseModel):
    """Deterministic participation constraint for one role."""

    model_config = ConfigDict(frozen=True)

    agent_id: AgentIdentifier
    kind: TeamRoleConstraintKind
    owner_editable: bool
    reasons: tuple[
        TeamSelectionReasonResponse,
        ...,
    ]

    @classmethod
    def from_domain(
        cls,
        constraint: TeamRoleConstraint,
    ) -> TeamRoleConstraintResponse:
        """Map one deterministic role constraint."""
        return cls(
            agent_id=constraint.agent_id,
            kind=constraint.kind,
            owner_editable=(constraint.owner_editable),
            reasons=tuple(
                TeamSelectionReasonResponse.from_domain(reason) for reason in constraint.reasons
            ),
        )


class TeamSelectionIssueResponse(BaseModel):
    """One deterministic contradiction blocking a team proposal."""

    model_config = ConfigDict(frozen=True)

    code: TeamSelectionIssueCode
    agent_id: AgentIdentifier
    mandatory_reasons: tuple[
        TeamSelectionReasonResponse,
        ...,
    ]
    impossible_reasons: tuple[
        TeamSelectionReasonResponse,
        ...,
    ]

    @classmethod
    def from_domain(
        cls,
        issue: TeamSelectionIssue,
    ) -> TeamSelectionIssueResponse:
        """Map one team-selection issue."""
        return cls(
            code=issue.code,
            agent_id=issue.agent_id,
            mandatory_reasons=tuple(
                TeamSelectionReasonResponse.from_domain(reason)
                for reason in issue.mandatory_reasons
            ),
            impossible_reasons=tuple(
                TeamSelectionReasonResponse.from_domain(reason)
                for reason in issue.impossible_reasons
            ),
        )


class TeamProposalJustificationResponse(BaseModel):
    """Typed rationale for including one team member."""

    model_config = ConfigDict(frozen=True)

    kind: TeamProposalJustificationKind
    code: str
    evidence_fields: tuple[
        BriefField,
        ...,
    ]
    evidence_terms: tuple[str, ...]
    statement: str | None

    @classmethod
    def from_domain(
        cls,
        justification: TeamProposalJustification,
    ) -> TeamProposalJustificationResponse:
        """Map one team-member justification."""
        return cls(
            kind=justification.kind,
            code=justification.code,
            evidence_fields=(justification.evidence_fields),
            evidence_terms=(justification.evidence_terms),
            statement=justification.statement,
        )


class ProposedTeamMemberResponse(BaseModel):
    """One selected agent and its provenance."""

    model_config = ConfigDict(frozen=True)

    agent_id: AgentIdentifier
    source: TeamProposalMemberSource
    justifications: tuple[
        TeamProposalJustificationResponse,
        ...,
    ]

    @classmethod
    def from_domain(
        cls,
        member: ProposedTeamMember,
    ) -> ProposedTeamMemberResponse:
        """Map one proposed team member."""
        return cls(
            agent_id=member.agent_id,
            source=member.source,
            justifications=tuple(
                TeamProposalJustificationResponse.from_domain(justification)
                for justification in member.justifications
            ),
        )


class TeamProposalVersionResponse(BaseModel):
    """One immutable persisted team-proposal version."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    version_number: int
    revision_kind: TeamProposalRevisionKind
    based_on_version_number: int | None

    schema_version: int
    provider_kind: TeamProposalProviderKind
    provider_id: str
    provider_version: int

    project_mode: ProjectMode
    brief_version_id: UUID
    brief_version_number: int
    brief_content_hash: str

    catalog_version: int
    catalog_content_hash: str
    constraints_content_hash: str
    content_hash: str

    selected_agent_ids: tuple[
        AgentIdentifier,
        ...,
    ]
    role_constraints: tuple[
        TeamRoleConstraintResponse,
        ...,
    ]
    constraint_issues: tuple[
        TeamSelectionIssueResponse,
        ...,
    ]
    members: tuple[
        ProposedTeamMemberResponse,
        ...,
    ]

    created_by_user_id: UUID
    created_at: datetime

    @classmethod
    def from_domain(
        cls,
        version: TeamProposalVersion,
    ) -> TeamProposalVersionResponse:
        """Map an immutable proposal version into the API contract."""
        proposal = version.proposal

        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=(version.version_number),
            revision_kind=(version.revision_kind),
            based_on_version_number=(version.based_on_version_number),
            schema_version=(proposal.schema_version),
            provider_kind=(proposal.provider_kind),
            provider_id=proposal.provider_id,
            provider_version=(proposal.provider_version),
            project_mode=(proposal.project_mode),
            brief_version_id=(proposal.brief_version_id),
            brief_version_number=(proposal.brief_version_number),
            brief_content_hash=(proposal.brief_content_hash),
            catalog_version=(proposal.catalog_version),
            catalog_content_hash=(proposal.catalog_content_hash),
            constraints_content_hash=(proposal.constraints.content_hash),
            content_hash=(version.content_hash),
            selected_agent_ids=(proposal.selected_agent_ids),
            role_constraints=tuple(
                TeamRoleConstraintResponse.from_domain(constraint)
                for constraint in proposal.constraints.role_constraints
            ),
            constraint_issues=tuple(
                TeamSelectionIssueResponse.from_domain(issue)
                for issue in proposal.constraints.issues
            ),
            members=tuple(
                ProposedTeamMemberResponse.from_domain(member) for member in proposal.members
            ),
            created_by_user_id=(version.created_by_user_id),
            created_at=version.created_at,
        )


class TeamProposalGenerationResponse(BaseModel):
    """Result of generating and persisting a team proposal."""

    model_config = ConfigDict(frozen=True)

    status: TeamProposalApplicationStatus
    version: TeamProposalVersionResponse | None
    issues: tuple[
        TeamSelectionIssueResponse,
        ...,
    ]


class OwnerAgentRationaleRequest(BaseModel):
    """Owner rationale for adding one optional catalog agent."""

    model_config = ConfigDict(extra="forbid")

    agent_id: AgentIdentifier
    statement: str = Field(
        min_length=1,
        max_length=2000,
    )

    @field_validator("statement")
    @classmethod
    def normalize_statement(
        cls,
        value: str,
    ) -> str:
        """Normalize an owner rationale before domain conversion."""
        normalized = " ".join(value.split())

        if not normalized:
            raise ValueError("owner rationale must not be empty")

        return normalized

    def to_domain(
        self,
    ) -> OwnerAgentRationale:
        """Create the normalized owner-rationale value."""
        return create_owner_agent_rationale(
            agent_id=self.agent_id,
            statement=self.statement,
        )


class TeamProposalEditRequest(BaseModel):
    """Complete owner-selected team membership."""

    model_config = ConfigDict(extra="forbid")

    selected_agent_ids: list[AgentIdentifier] = Field(
        min_length=1,
        max_length=17,
    )
    owner_rationales: list[OwnerAgentRationaleRequest] = Field(
        default_factory=list,
        max_length=17,
    )


class TeamEditIssueResponse(BaseModel):
    """One validation issue in an owner-selected team."""

    model_config = ConfigDict(frozen=True)

    code: TeamEditIssueCode
    agent_id: AgentIdentifier

    @classmethod
    def from_domain(
        cls,
        issue: TeamEditIssue,
    ) -> TeamEditIssueResponse:
        """Map one owner-edit issue."""
        return cls(
            code=issue.code,
            agent_id=issue.agent_id,
        )


class TeamEditResponse(BaseModel):
    """Result of editing the current team proposal."""

    model_config = ConfigDict(frozen=True)

    status: TeamEditStatus
    version: TeamProposalVersionResponse | None
    issues: tuple[
        TeamEditIssueResponse,
        ...,
    ]
    events: tuple[
        HumanGateEventResponse,
        ...,
    ]


class AgentTeamGateSubmissionResponse(BaseModel):
    """Result of submitting the current team to Gate 2."""

    model_config = ConfigDict(frozen=True)

    status: AgentTeamGateSubmissionStatus
    gate: HumanGateResponse | None
    events: tuple[
        HumanGateEventResponse,
        ...,
    ]
    issue: HumanGateIssueCode | None


class AgentTeamGateDecisionRequest(BaseModel):
    """Owner decision for the current Agent Team gate."""

    model_config = ConfigDict(extra="forbid")

    action: Literal[
        HumanGateAction.APPROVE,
        HumanGateAction.REJECT,
        HumanGateAction.REQUEST_REVISION,
        HumanGateAction.PAUSE,
        HumanGateAction.RESUME,
        HumanGateAction.CANCEL,
    ]
    reason: str | None = Field(
        default=None,
        max_length=2000,
    )


class AgentTeamGateDecisionResponse(BaseModel):
    """Result of one Gate 2 owner decision."""

    model_config = ConfigDict(frozen=True)

    status: AgentTeamGateDecisionStatus
    gate: HumanGateResponse | None
    event: HumanGateEventResponse | None
    issue: HumanGateIssueCode | None


class ProjectReadinessResponse(BaseModel):
    """Derived readiness for the future main workflow."""

    model_config = ConfigDict(frozen=True)

    status: ProjectWorkflowReadiness


def team_proposal_service_dependency(
    request: Request,
) -> TeamProposalApplicationService:
    """Return the configured team-proposal application service."""
    service = getattr(
        request.app.state,
        "team_proposal_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="team_proposal_service_unavailable",
        )

    return service


def agent_team_service_dependency(
    request: Request,
) -> AgentTeamApprovalService:
    """Return the configured Agent Team approval service."""
    service = getattr(
        request.app.state,
        "agent_team_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=(status.HTTP_503_SERVICE_UNAVAILABLE),
            detail="agent_team_service_unavailable",
        )

    return service


def _proposal_version_response(
    version: TeamProposalVersion | None,
) -> TeamProposalVersionResponse | None:
    """Map an optional team-proposal version."""
    if version is None:
        return None

    return TeamProposalVersionResponse.from_domain(version)


def _gate_response(
    gate: HumanGate | None,
) -> HumanGateResponse | None:
    """Map an optional human gate."""
    if gate is None:
        return None

    return HumanGateResponse.from_domain(gate)


def _event_response(
    event: HumanGateEvent | None,
) -> HumanGateEventResponse | None:
    """Map an optional gate event."""
    if event is None:
        return None

    return HumanGateEventResponse.from_domain(event)


def _generation_response(
    result: TeamProposalApplicationResult,
) -> TeamProposalGenerationResponse:
    """Map one proposal-generation result."""
    return TeamProposalGenerationResponse(
        status=result.status,
        version=_proposal_version_response(result.version),
        issues=tuple(TeamSelectionIssueResponse.from_domain(issue) for issue in result.issues),
    )


def _edit_response(
    result: TeamEditResult,
) -> TeamEditResponse:
    """Map one owner-edit result."""
    return TeamEditResponse(
        status=result.status,
        version=_proposal_version_response(result.version),
        issues=tuple(TeamEditIssueResponse.from_domain(issue) for issue in result.issues),
        events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
    )


def _gate_submission_response(
    result: AgentTeamGateSubmissionResult,
) -> AgentTeamGateSubmissionResponse:
    """Map one Gate 2 submission result."""
    return AgentTeamGateSubmissionResponse(
        status=result.status,
        gate=_gate_response(result.gate),
        events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
        issue=result.issue,
    )


def _gate_decision_response(
    result: AgentTeamGateDecisionResult,
) -> AgentTeamGateDecisionResponse:
    """Map one Gate 2 decision result."""
    return AgentTeamGateDecisionResponse(
        status=result.status,
        gate=_gate_response(result.gate),
        event=_event_response(result.event),
        issue=result.issue,
    )


def create_team_router() -> APIRouter:
    """Create authenticated agent-catalog, proposal, and Gate 2 routes."""
    router = APIRouter(
        tags=[
            "agent-teams",
        ]
    )

    @router.get(
        "/agent-catalog",
        response_model=AgentCatalogResponse,
        operation_id="getAgentCatalog",
        dependencies=[
            Depends(current_user_dependency),
        ],
    )
    async def agent_catalog_endpoint() -> AgentCatalogResponse:
        """Return the complete fixed and versioned agent catalog."""
        return AgentCatalogResponse(
            catalog_version=(AGENT_CATALOG_VERSION),
            content_hash=(AGENT_CATALOG_CONTENT_HASH),
            agents=tuple(
                AgentCatalogEntryResponse.from_domain(entry)
                for entry in all_agent_catalog_entries()
            ),
        )

    @router.post(
        "/projects/{project_id}/team-proposals",
        response_model=(TeamProposalGenerationResponse),
        status_code=status.HTTP_201_CREATED,
        operation_id="generateProjectTeamProposal",
    )
    async def generate_team_proposal_endpoint(
        project_id: UUID,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            TeamProposalApplicationService,
            Depends(team_proposal_service_dependency),
        ],
    ) -> TeamProposalGenerationResponse:
        """Generate and persist the current typed team proposal."""
        result = await service.generate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if result.status in {
            TeamProposalApplicationStatus.PROJECT_NOT_FOUND,
            TeamProposalApplicationStatus.BRIEF_NOT_FOUND,
        }:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail=("team_proposal_context_not_found"),
            )

        if result.status is TeamProposalApplicationStatus.INVALID_PROPOSAL:
            raise HTTPException(
                status_code=(status.HTTP_502_BAD_GATEWAY),
                detail="invalid_team_proposal",
            )

        if result.status is TeamProposalApplicationStatus.UNCHANGED:
            response.status_code = status.HTTP_200_OK

        if result.status in {
            TeamProposalApplicationStatus.BRIEF_NOT_APPROVED,
            TeamProposalApplicationStatus.BLOCKED_BY_CONSTRAINTS,
            TeamProposalApplicationStatus.CONTEXT_CHANGED,
        }:
            response.status_code = status.HTTP_409_CONFLICT

        return _generation_response(result)

    @router.get(
        "/projects/{project_id}/team-proposals",
        response_model=list[TeamProposalVersionResponse],
        operation_id="listProjectTeamProposals",
    )
    async def team_proposal_history_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            TeamProposalApplicationService,
            Depends(team_proposal_service_dependency),
        ],
    ) -> list[TeamProposalVersionResponse]:
        """Return immutable proposal history."""
        versions = await service.history(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return [TeamProposalVersionResponse.from_domain(version) for version in versions]

    @router.get(
        "/projects/{project_id}/team-proposals/current",
        response_model=(TeamProposalVersionResponse),
        operation_id="getCurrentProjectTeamProposal",
    )
    async def current_team_proposal_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            TeamProposalApplicationService,
            Depends(team_proposal_service_dependency),
        ],
    ) -> TeamProposalVersionResponse:
        """Return the latest owner-scoped team proposal."""
        version = await service.current(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if version is None:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="team_proposal_not_found",
            )

        return TeamProposalVersionResponse.from_domain(version)

    @router.patch(
        "/projects/{project_id}/team-proposals/current",
        response_model=TeamEditResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="editCurrentProjectTeamProposal",
    )
    async def edit_team_proposal_endpoint(
        project_id: UUID,
        payload: TeamProposalEditRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> TeamEditResponse:
        """Create an immutable owner-edited proposal version."""
        try:
            rationales = tuple(rationale.to_domain() for rationale in payload.owner_rationales)
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_owner_rationale",
            ) from error

        result = await service.edit_current(
            project_id=project_id,
            owner_user_id=user.id,
            selected_agent_ids=tuple(payload.selected_agent_ids),
            owner_rationales=rationales,
        )

        if result.status in {
            TeamEditStatus.PROJECT_NOT_FOUND,
            TeamEditStatus.BRIEF_NOT_FOUND,
            TeamEditStatus.PROPOSAL_NOT_FOUND,
        }:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="team_proposal_not_found",
            )

        if result.status is TeamEditStatus.REJECTED:
            response.status_code = status.HTTP_422_UNPROCESSABLE_CONTENT

        if result.status in {
            TeamEditStatus.BRIEF_NOT_APPROVED,
            TeamEditStatus.PROPOSAL_STALE,
            TeamEditStatus.CONTEXT_CHANGED,
        }:
            response.status_code = status.HTTP_409_CONFLICT

        if result.status is TeamEditStatus.UNCHANGED:
            response.status_code = status.HTTP_200_OK

        return _edit_response(result)

    @router.post(
        "/projects/{project_id}/gates/agent-team/submit",
        response_model=(AgentTeamGateSubmissionResponse),
        status_code=status.HTTP_201_CREATED,
        operation_id="submitAgentTeamGate",
    )
    async def submit_agent_team_gate_endpoint(
        project_id: UUID,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> AgentTeamGateSubmissionResponse:
        """Submit the current team proposal to Gate 2."""
        result = await service.submit_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if result.status in {
            AgentTeamGateSubmissionStatus.PROJECT_NOT_FOUND,
            AgentTeamGateSubmissionStatus.BRIEF_NOT_FOUND,
            AgentTeamGateSubmissionStatus.PROPOSAL_NOT_FOUND,
        }:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="agent_team_gate_context_not_found",
            )

        if result.status in {
            AgentTeamGateSubmissionStatus.ALREADY_PENDING,
            AgentTeamGateSubmissionStatus.ALREADY_APPROVED,
        }:
            response.status_code = status.HTTP_200_OK

        if result.status in {
            AgentTeamGateSubmissionStatus.BRIEF_NOT_APPROVED,
            AgentTeamGateSubmissionStatus.PROPOSAL_STALE,
            AgentTeamGateSubmissionStatus.NEW_PROPOSAL_REQUIRED,
            AgentTeamGateSubmissionStatus.GATE_BLOCKED,
            AgentTeamGateSubmissionStatus.ITERATION_LIMIT_REACHED,
            AgentTeamGateSubmissionStatus.TRANSITION_REJECTED,
        }:
            response.status_code = status.HTTP_409_CONFLICT

        return _gate_submission_response(result)

    @router.get(
        "/projects/{project_id}/gates/agent-team/current",
        response_model=HumanGateResponse,
        operation_id="getCurrentAgentTeamGate",
    )
    async def current_agent_team_gate_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> HumanGateResponse:
        """Return the latest owner-scoped Gate 2."""
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="agent_team_gate_not_found",
            )

        return HumanGateResponse.from_domain(gate)

    @router.get(
        ("/projects/{project_id}/gates/agent-team/{gate_id}/events"),
        response_model=list[HumanGateEventResponse],
        operation_id="listAgentTeamGateEvents",
    )
    async def agent_team_gate_events_endpoint(
        project_id: UUID,
        gate_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> list[HumanGateEventResponse]:
        """Return the Gate 2 append-only audit history."""
        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate_id,
        )

        return [HumanGateEventResponse.from_domain(event) for event in events]

    @router.post(
        "/projects/{project_id}/gates/agent-team/decisions",
        response_model=(AgentTeamGateDecisionResponse),
        operation_id="decideAgentTeamGate",
    )
    async def decide_agent_team_gate_endpoint(
        project_id: UUID,
        payload: AgentTeamGateDecisionRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> AgentTeamGateDecisionResponse:
        """Apply one explicit owner decision to Gate 2."""
        result = await service.decide_gate(
            project_id=project_id,
            owner_user_id=user.id,
            action=HumanGateAction(payload.action),
            reason=payload.reason,
        )

        if result.status in {
            AgentTeamGateDecisionStatus.PROJECT_NOT_FOUND,
            AgentTeamGateDecisionStatus.BRIEF_NOT_FOUND,
            AgentTeamGateDecisionStatus.PROPOSAL_NOT_FOUND,
            AgentTeamGateDecisionStatus.GATE_NOT_FOUND,
        }:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="agent_team_gate_not_found",
            )

        if result.status is not AgentTeamGateDecisionStatus.APPLIED:
            response.status_code = status.HTTP_409_CONFLICT

        return _gate_decision_response(result)

    @router.get(
        "/projects/{project_id}/readiness",
        response_model=ProjectReadinessResponse,
        operation_id="getProjectWorkflowReadiness",
    )
    async def project_readiness_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            AgentTeamApprovalService,
            Depends(agent_team_service_dependency),
        ],
    ) -> ProjectReadinessResponse:
        """Return readiness without starting the main workflow."""
        readiness = await service.readiness(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if readiness is ProjectWorkflowReadiness.PROJECT_NOT_FOUND:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail="project_not_found",
            )

        return ProjectReadinessResponse(status=readiness)

    return router
