"""HTTP contracts for Project Brief clarification and Gate 1."""

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

from orchestwin.api.auth import (
    current_user_dependency,
)
from orchestwin.api.projects import (
    ProjectBriefVersionResponse,
)
from orchestwin.identity.domain import (
    UserAccount,
)
from orchestwin.projects.brief_gate import (
    ProjectBriefGateDecisionResult,
    ProjectBriefGateDecisionStatus,
    ProjectBriefGateService,
    ProjectBriefGateSubmissionResult,
    ProjectBriefGateSubmissionStatus,
)
from orchestwin.projects.briefs import (
    BriefField,
)
from orchestwin.projects.clarification_application import (
    BriefAssumptionCreationResult,
    BriefAssumptionCreationStatus,
    BriefAssumptionDecisionResult,
    BriefAssumptionDecisionStatus,
    ProjectClarificationApplicationService,
)
from orchestwin.projects.clarification_state import (
    BriefAssumption,
    BriefAssumptionSource,
    BriefAssumptionStatus,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateEventKind,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateType,
)


class BriefAssumptionCreateRequest(BaseModel):
    """Create an explicit assumption separate from the brief."""

    model_config = ConfigDict(extra="forbid")

    field: BriefField
    statement: str = Field(
        min_length=1,
        max_length=2000,
    )


class BriefAssumptionDecisionRequest(BaseModel):
    """Optional rationale for accepting an assumption."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(
        default=None,
        max_length=2000,
    )

    @field_validator("reason")
    @classmethod
    def normalize_optional_reason(
        cls,
        value: str | None,
    ) -> str | None:
        """Normalize an optional assumption-decision rationale."""
        if value is None:
            return None

        normalized = " ".join(value.split())

        if not normalized:
            raise ValueError("assumption decision reason must not be empty")

        return normalized


class BriefAssumptionRejectRequest(BaseModel):
    """Required rationale for rejecting an assumption."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(
        min_length=1,
        max_length=2000,
    )

    @field_validator("reason")
    @classmethod
    def normalize_reason(
        cls,
        value: str,
    ) -> str:
        """Normalize a required assumption-rejection rationale."""
        normalized = " ".join(value.split())

        if not normalized:
            raise ValueError("assumption rejection reason must not be empty")

        return normalized


class BriefAssumptionResponse(BaseModel):
    """Public representation of one separate assumption."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    brief_version_number: int
    field: BriefField
    statement: str
    source: BriefAssumptionSource
    status: BriefAssumptionStatus
    created_by_user_id: UUID
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None

    @classmethod
    def from_domain(
        cls,
        assumption: BriefAssumption,
    ) -> BriefAssumptionResponse:
        """Map one assumption into the API contract."""
        return cls(
            id=assumption.id,
            project_id=assumption.project_id,
            brief_version_number=(assumption.brief_version_number),
            field=assumption.field,
            statement=assumption.statement,
            source=assumption.source,
            status=assumption.status,
            created_by_user_id=(assumption.created_by_user_id),
            created_at=assumption.created_at,
            decided_by_user_id=(assumption.decided_by_user_id),
            decided_at=assumption.decided_at,
            decision_reason=assumption.decision_reason,
        )


class BriefAssumptionCreationResponse(BaseModel):
    """Result of creating an assumption."""

    model_config = ConfigDict(frozen=True)

    status: BriefAssumptionCreationStatus
    assumption: BriefAssumptionResponse | None


class BriefAssumptionDecisionResponse(BaseModel):
    """Result of accepting or rejecting an assumption."""

    model_config = ConfigDict(frozen=True)

    status: BriefAssumptionDecisionStatus
    assumption: BriefAssumptionResponse | None
    brief_version: ProjectBriefVersionResponse | None


class GateArtifactResponse(BaseModel):
    """Exact artifact reference governed by a human gate."""

    model_config = ConfigDict(frozen=True)

    project_id: UUID
    gate_type: HumanGateType
    artifact_id: UUID
    version: int
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        artifact: GateArtifactReference,
    ) -> GateArtifactResponse:
        """Map one gate artifact reference."""
        return cls(
            project_id=artifact.project_id,
            gate_type=artifact.gate_type,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            content_hash=artifact.content_hash,
        )


class HumanGateResponse(BaseModel):
    """Current state of one human-gate iteration."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    gate_type: HumanGateType
    artifact: GateArtifactResponse
    iteration: int
    max_iterations: int
    status: HumanGateStatus
    created_at: datetime
    updated_at: datetime
    event_sequence: int
    resume_status: HumanGateStatus | None

    @classmethod
    def from_domain(
        cls,
        gate: HumanGate,
    ) -> HumanGateResponse:
        """Map one human gate into the API contract."""
        return cls(
            id=gate.id,
            project_id=gate.project_id,
            owner_user_id=gate.owner_user_id,
            gate_type=gate.gate_type,
            artifact=GateArtifactResponse.from_domain(gate.artifact),
            iteration=gate.iteration,
            max_iterations=gate.max_iterations,
            status=gate.status,
            created_at=gate.created_at,
            updated_at=gate.updated_at,
            event_sequence=gate.event_sequence,
            resume_status=gate.resume_status,
        )


class HumanGateEventResponse(BaseModel):
    """Append-only human-gate audit event."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    gate_id: UUID
    sequence_number: int
    kind: HumanGateEventKind
    previous_status: HumanGateStatus
    resulting_status: HumanGateStatus
    artifact: GateArtifactResponse
    occurred_at: datetime
    actor_user_id: UUID | None
    reason: str | None

    @classmethod
    def from_domain(
        cls,
        event: HumanGateEvent,
    ) -> HumanGateEventResponse:
        """Map one gate event into the API contract."""
        return cls(
            id=event.id,
            gate_id=event.gate_id,
            sequence_number=event.sequence_number,
            kind=event.kind,
            previous_status=event.previous_status,
            resulting_status=event.resulting_status,
            artifact=GateArtifactResponse.from_domain(event.artifact),
            occurred_at=event.occurred_at,
            actor_user_id=event.actor_user_id,
            reason=event.reason,
        )


class ProjectBriefGateSubmissionResponse(BaseModel):
    """Result of submitting the current brief to Gate 1."""

    model_config = ConfigDict(frozen=True)

    status: ProjectBriefGateSubmissionStatus
    gate: HumanGateResponse | None
    events: tuple[HumanGateEventResponse, ...]
    missing_fields: tuple[BriefField, ...]
    issue: HumanGateIssueCode | None


class ProjectBriefGateDecisionRequest(BaseModel):
    """Owner decision for the current Project Brief gate."""

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


class ProjectBriefGateDecisionResponse(BaseModel):
    """Result of one Gate 1 owner decision."""

    model_config = ConfigDict(frozen=True)

    status: ProjectBriefGateDecisionStatus
    gate: HumanGateResponse | None
    event: HumanGateEventResponse | None
    issue: HumanGateIssueCode | None


def clarification_service_dependency(
    request: Request,
) -> ProjectClarificationApplicationService:
    """Return the configured clarification application service."""
    service = getattr(
        request.app.state,
        "clarification_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="clarification_service_unavailable",
        )

    return service


def brief_gate_service_dependency(
    request: Request,
) -> ProjectBriefGateService:
    """Return the configured Project Brief gate service."""
    service = getattr(
        request.app.state,
        "brief_gate_service",
        None,
    )

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="brief_gate_service_unavailable",
        )

    return service


def _assumption_response(
    assumption: BriefAssumption | None,
) -> BriefAssumptionResponse | None:
    """Map an optional assumption."""
    if assumption is None:
        return None

    return BriefAssumptionResponse.from_domain(assumption)


def _brief_version_response(
    version,
) -> ProjectBriefVersionResponse | None:
    """Map an optional Project Brief version."""
    if version is None:
        return None

    return ProjectBriefVersionResponse.from_domain(version)


def _gate_response(
    gate: HumanGate | None,
) -> HumanGateResponse | None:
    """Map an optional human gate."""
    if gate is None:
        return None

    return HumanGateResponse.from_domain(gate)


def _gate_event_response(
    event: HumanGateEvent | None,
) -> HumanGateEventResponse | None:
    """Map an optional gate event."""
    if event is None:
        return None

    return HumanGateEventResponse.from_domain(event)


def _assumption_creation_response(
    result: BriefAssumptionCreationResult,
) -> BriefAssumptionCreationResponse:
    """Map an assumption-creation result."""
    return BriefAssumptionCreationResponse(
        status=result.status,
        assumption=_assumption_response(result.assumption),
    )


def _assumption_decision_response(
    result: BriefAssumptionDecisionResult,
) -> BriefAssumptionDecisionResponse:
    """Map an assumption-decision result."""
    return BriefAssumptionDecisionResponse(
        status=result.status,
        assumption=_assumption_response(result.assumption),
        brief_version=_brief_version_response(result.version),
    )


def _brief_gate_submission_response(
    result: ProjectBriefGateSubmissionResult,
) -> ProjectBriefGateSubmissionResponse:
    """Map a Gate 1 submission result."""
    return ProjectBriefGateSubmissionResponse(
        status=result.status,
        gate=_gate_response(result.gate),
        events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
        missing_fields=result.missing_fields,
        issue=result.issue,
    )


def _brief_gate_decision_response(
    result: ProjectBriefGateDecisionResult,
) -> ProjectBriefGateDecisionResponse:
    """Map a Gate 1 decision result."""
    return ProjectBriefGateDecisionResponse(
        status=result.status,
        gate=_gate_response(result.gate),
        event=_gate_event_response(result.event),
        issue=result.issue,
    )


def create_clarification_router() -> APIRouter:
    """Create owner-scoped clarification, assumption, and Gate 1 routes."""
    router = APIRouter(
        prefix="/projects",
        tags=[
            "project-clarification",
        ],
    )

    @router.get(
        "/{project_id}/brief-assumptions",
        response_model=list[BriefAssumptionResponse],
        operation_id="listProjectBriefAssumptions",
    )
    async def list_assumptions_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectClarificationApplicationService,
            Depends(clarification_service_dependency),
        ],
    ) -> list[BriefAssumptionResponse]:
        assumptions = await service.assumptions(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return [BriefAssumptionResponse.from_domain(assumption) for assumption in assumptions]

    @router.post(
        "/{project_id}/brief-assumptions",
        response_model=BriefAssumptionCreationResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="createProjectBriefAssumption",
    )
    async def create_assumption_endpoint(
        project_id: UUID,
        payload: BriefAssumptionCreateRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectClarificationApplicationService,
            Depends(clarification_service_dependency),
        ],
    ) -> BriefAssumptionCreationResponse:
        try:
            result = await service.create_assumption(
                project_id=project_id,
                owner_user_id=user.id,
                field=payload.field,
                statement=payload.statement,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_brief_assumption",
            ) from error

        if result.status is BriefAssumptionCreationStatus.BRIEF_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project_brief_not_found",
            )

        if result.status is BriefAssumptionCreationStatus.FIELD_ALREADY_PROVIDED:
            response.status_code = status.HTTP_409_CONFLICT

        return _assumption_creation_response(result)

    @router.post(
        "/{project_id}/brief-assumptions/{assumption_id}/accept",
        response_model=BriefAssumptionDecisionResponse,
        operation_id="acceptProjectBriefAssumption",
    )
    async def accept_assumption_endpoint(
        project_id: UUID,
        assumption_id: UUID,
        payload: BriefAssumptionDecisionRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectClarificationApplicationService,
            Depends(clarification_service_dependency),
        ],
    ) -> BriefAssumptionDecisionResponse:
        try:
            result = await service.accept_assumption(
                project_id=project_id,
                owner_user_id=user.id,
                assumption_id=assumption_id,
                reason=payload.reason,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_assumption_acceptance",
            ) from error

        if result.status is BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="brief_assumption_not_found",
            )

        if result.status is not BriefAssumptionDecisionStatus.ACCEPTED:
            response.status_code = status.HTTP_409_CONFLICT

        return _assumption_decision_response(result)

    @router.post(
        "/{project_id}/brief-assumptions/{assumption_id}/reject",
        response_model=BriefAssumptionDecisionResponse,
        operation_id="rejectProjectBriefAssumption",
    )
    async def reject_assumption_endpoint(
        project_id: UUID,
        assumption_id: UUID,
        payload: BriefAssumptionRejectRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectClarificationApplicationService,
            Depends(clarification_service_dependency),
        ],
    ) -> BriefAssumptionDecisionResponse:
        try:
            result = await service.reject_assumption(
                project_id=project_id,
                owner_user_id=user.id,
                assumption_id=assumption_id,
                reason=payload.reason,
            )
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail="invalid_assumption_rejection",
            ) from error

        if result.status is BriefAssumptionDecisionStatus.ASSUMPTION_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="brief_assumption_not_found",
            )

        if result.status is not BriefAssumptionDecisionStatus.REJECTED:
            response.status_code = status.HTTP_409_CONFLICT

        return _assumption_decision_response(result)

    @router.post(
        "/{project_id}/gates/project-brief/submit",
        response_model=ProjectBriefGateSubmissionResponse,
        status_code=status.HTTP_201_CREATED,
        operation_id="submitProjectBriefGate",
    )
    async def submit_brief_gate_endpoint(
        project_id: UUID,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectBriefGateService,
            Depends(brief_gate_service_dependency),
        ],
    ) -> ProjectBriefGateSubmissionResponse:
        result = await service.submit(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if result.status is ProjectBriefGateSubmissionStatus.BRIEF_NOT_FOUND:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project_brief_not_found",
            )

        if result.status in {
            ProjectBriefGateSubmissionStatus.ALREADY_PENDING,
            ProjectBriefGateSubmissionStatus.ALREADY_APPROVED,
        }:
            response.status_code = status.HTTP_200_OK

        if result.status in {
            ProjectBriefGateSubmissionStatus.BRIEF_INCOMPLETE,
            ProjectBriefGateSubmissionStatus.NEW_BRIEF_REQUIRED,
            ProjectBriefGateSubmissionStatus.GATE_BLOCKED,
            ProjectBriefGateSubmissionStatus.ITERATION_LIMIT_REACHED,
            ProjectBriefGateSubmissionStatus.TRANSITION_REJECTED,
        }:
            response.status_code = status.HTTP_409_CONFLICT

        return _brief_gate_submission_response(result)

    @router.get(
        "/{project_id}/gates/project-brief/current",
        response_model=HumanGateResponse,
        operation_id="getCurrentProjectBriefGate",
    )
    async def current_brief_gate_endpoint(
        project_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectBriefGateService,
            Depends(brief_gate_service_dependency),
        ],
    ) -> HumanGateResponse:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project_brief_gate_not_found",
            )

        return HumanGateResponse.from_domain(gate)

    @router.get(
        "/{project_id}/gates/project-brief/{gate_id}/events",
        response_model=list[HumanGateEventResponse],
        operation_id="listProjectBriefGateEvents",
    )
    async def brief_gate_events_endpoint(
        project_id: UUID,
        gate_id: UUID,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectBriefGateService,
            Depends(brief_gate_service_dependency),
        ],
    ) -> list[HumanGateEventResponse]:
        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate_id,
        )

        return [HumanGateEventResponse.from_domain(event) for event in events]

    @router.post(
        "/{project_id}/gates/project-brief/decisions",
        response_model=ProjectBriefGateDecisionResponse,
        operation_id="decideProjectBriefGate",
    )
    async def decide_brief_gate_endpoint(
        project_id: UUID,
        payload: ProjectBriefGateDecisionRequest,
        response: Response,
        user: Annotated[
            UserAccount,
            Depends(current_user_dependency),
        ],
        service: Annotated[
            ProjectBriefGateService,
            Depends(brief_gate_service_dependency),
        ],
    ) -> ProjectBriefGateDecisionResponse:
        result = await service.decide(
            project_id=project_id,
            owner_user_id=user.id,
            action=HumanGateAction(payload.action),
            reason=payload.reason,
        )

        if result.status in {
            ProjectBriefGateDecisionStatus.GATE_NOT_FOUND,
            ProjectBriefGateDecisionStatus.BRIEF_NOT_FOUND,
        }:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="project_brief_gate_not_found",
            )

        if result.status is not ProjectBriefGateDecisionStatus.APPLIED:
            response.status_code = status.HTTP_409_CONFLICT

        return _brief_gate_decision_response(result)

    return router
