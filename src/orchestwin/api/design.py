"""FastAPI boundary for Design Exploration and Gate 5."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, JsonValue

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.clarification import HumanGateEventResponse, HumanGateResponse
from orchestwin.artifacts.design import (
    DesignApproach,
    DesignCritiqueKind,
)
from orchestwin.artifacts.design_gate import (
    DesignGateDecisionResult,
    DesignGateDecisionStatus,
    DesignGateSubmissionResult,
    DesignGateSubmissionStatus,
    DesignReadinessResult,
    DesignWorkflowReadiness,
)
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
)
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    DesignRevisionApplicationIssueCode,
    DesignRevisionResult,
    DesignRevisionStatus,
)
from orchestwin.artifacts.design_revisions import (
    DesignArtifactKind,
    DesignChangeKind,
    DesignPackageDiff,
    DesignPackageDiffStatus,
    DesignRevisionDecision,
    DesignRevisionIssueCode,
)
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
)
from orchestwin.artifacts.references import ArtifactKind
from orchestwin.identity.domain import UserAccount
from orchestwin.models.design import DesignProposalIssueCode
from orchestwin.projects.design_application import (
    DesignGenerationIssueCode,
    DesignGenerationResult,
    DesignGenerationStatus,
    DesignVersionAppendStatus,
)
from orchestwin.twins.epistemics import (
    EpistemicStatus,
    EvidenceSourceKind,
    HumanValidationRequirement,
)
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
)

DESIGN_API_PREFIX = "/projects/{project_id}/design"


class ApiModel(BaseModel):
    """Strict base model for Design API contracts."""

    model_config = ConfigDict(extra="forbid")


class VersionedArtifactReferencePayload(ApiModel):
    """Exact identity, version, and hash of one governed artifact."""

    kind: ArtifactKind
    artifact_id: UUID
    version_number: int
    content_hash: str


class UserTwinVersionReferencePayload(ApiModel):
    """Exact approved User Twin version used by design artifacts."""

    twin_id: UUID
    version_number: int
    content_hash: str
    name: str


class DesignCatalogPayload(ApiModel):
    """Fixed-catalog metadata used by the Design Package."""

    version: int
    content_hash: str


class DesignGroundingPayload(ApiModel):
    """Exact approved inputs and traceability indexes used by design."""

    requirements_reference: VersionedArtifactReferencePayload
    agent_team_reference: VersionedArtifactReferencePayload
    user_modeling_reference: VersionedArtifactReferencePayload
    catalog: DesignCatalogPayload
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReferencePayload, ...]


class DesignWorkflowPayload(ApiModel):
    """One ordered and traceable workflow inside a Design Alternative."""

    id: UUID
    code: str
    title: str
    steps: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]


class DesignAlternativePayload(ApiModel):
    """One inspectable design direction."""

    id: UUID
    code: str
    approach: DesignApproach
    title: str
    summary: str
    rationale: str
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReferencePayload, ...]
    workflows: tuple[DesignWorkflowPayload, ...]
    information_architecture: tuple[str, ...]
    accessibility_considerations: tuple[str, ...]
    security_considerations: tuple[str, ...]
    advantages: tuple[str, ...]
    trade_offs: tuple[str, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]


class EvidenceReferencePayload(ApiModel):
    """Inspectable provenance reference supporting synthetic feedback."""

    source_kind: EvidenceSourceKind
    source_id: str
    source_version: int | None = None
    content_hash: str | None = None
    locator: str | None = None
    summary: str | None = None


class SyntheticDesignCritiquePayload(ApiModel):
    """Explicitly synthetic and human-validation-required User Twin critique."""

    id: UUID
    code: str
    kind: DesignCritiqueKind
    design_alternative_id: UUID
    user_twin_reference: UserTwinVersionReferencePayload
    strengths: tuple[str, ...]
    concerns: tuple[str, ...]
    unmet_needs: tuple[str, ...]
    accessibility_observations: tuple[str, ...]
    trust_concerns: tuple[str, ...]
    questions: tuple[str, ...]
    suggested_changes: tuple[str, ...]
    provenance: tuple[EvidenceReferencePayload, ...]
    confidence: float
    epistemic_status: EpistemicStatus
    human_validation: HumanValidationRequirement
    rationale: str


class PrototypeElementPayload(ApiModel):
    """One trusted declarative prototype element."""

    id: UUID
    code: str
    kind: PrototypeElementKind
    content: str
    accessible_name: str | None = None
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    field_name: str | None = None
    required: bool
    options: tuple[str, ...]


class PrototypeScreenPayload(ApiModel):
    """One traceable screen in the trusted prototype."""

    id: UUID
    code: str
    title: str
    state: PrototypeScreenState
    elements: tuple[PrototypeElementPayload, ...]
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]


class PrototypeTransitionPayload(ApiModel):
    """One declared navigation transition between prototype screens."""

    id: UUID
    code: str
    source_screen_id: UUID
    trigger_element_id: UUID
    target_screen_id: UUID
    outcome: str


class DeclarativePrototypePayload(ApiModel):
    """Data-only prototype rendered through trusted frontend components."""

    id: UUID
    code: str
    title: str
    design_alternative_id: UUID
    entry_screen_id: UUID
    screens: tuple[PrototypeScreenPayload, ...]
    transitions: tuple[PrototypeTransitionPayload, ...]
    supported_viewports: tuple[PrototypeViewport, ...]


class DesignConcernPayload(ApiModel):
    """One reviewable concern linked to requirements and alternatives."""

    id: UUID
    code: str
    summary: str
    mitigation: str
    requirement_ids: tuple[UUID, ...]
    design_alternative_ids: tuple[UUID, ...]


class DesignPackagePayload(ApiModel):
    """Complete typed Design Package HTTP representation."""

    schema_version: int
    project_id: UUID
    grounding: DesignGroundingPayload
    alternatives: tuple[DesignAlternativePayload, ...]
    critiques: tuple[SyntheticDesignCritiquePayload, ...]
    recommended_alternative_id: UUID | None
    owner_selected_alternative_id: UUID | None
    prototype: DeclarativePrototypePayload | None
    concerns: tuple[DesignConcernPayload, ...]
    open_questions: tuple[str, ...]

    @classmethod
    def from_domain(
        cls,
        package: DesignExplorationPackage,
    ) -> DesignPackagePayload:
        """Map one complete domain package through its canonical snapshot."""
        return cls.model_validate(package.to_snapshot())

    def to_domain(self) -> DesignExplorationPackage:
        """Convert this complete payload through canonical domain validation."""
        return design_package_from_snapshot(self.model_dump(mode="json"))


class DesignPackageVersionPayload(ApiModel):
    """One immutable Design Package version exposed by the API."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    package: DesignPackagePayload
    created_by_user_id: UUID
    created_at: datetime
    ready_for_gate: bool

    @classmethod
    def from_domain(
        cls,
        version: DesignPackageVersion,
    ) -> DesignPackageVersionPayload:
        """Map one immutable Design Package version."""
        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            package=DesignPackagePayload.from_domain(version.package),
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at,
            ready_for_gate=version.package.ready_for_gate,
        )


class DesignChangePayload(ApiModel):
    """One explicit before/after change inside an owner revision."""

    kind: DesignChangeKind
    artifact_kind: DesignArtifactKind
    artifact_id: UUID
    before: dict[str, JsonValue] | None
    after: dict[str, JsonValue] | None


class DesignPackageDiffPayload(ApiModel):
    """One immutable owner-reviewable Design Package diff."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_package: DesignPackagePayload
    proposal_hash: str
    changes: tuple[DesignChangePayload, ...]
    status: DesignPackageDiffStatus
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    applied_version_id: UUID | None
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        diff: DesignPackageDiff,
    ) -> DesignPackageDiffPayload:
        """Map one complete Design Package diff."""
        snapshot = diff.to_snapshot()

        return cls(
            **snapshot,
            content_hash=diff.content_hash,
        )


class DesignGenerationPayload(ApiModel):
    """Typed result returned after deterministic design generation."""

    status: DesignGenerationStatus
    version: DesignPackageVersionPayload | None = None
    issue: DesignGenerationIssueCode | None = None
    proposal_issue: DesignProposalIssueCode | None = None
    persistence_status: DesignVersionAppendStatus | None = None

    @classmethod
    def from_domain(
        cls,
        result: DesignGenerationResult,
    ) -> DesignGenerationPayload:
        """Map one governed generation result."""
        return cls(
            status=result.status,
            version=(
                None
                if result.version is None
                else DesignPackageVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            proposal_issue=result.proposal_issue,
            persistence_status=result.persistence_status,
        )


class DesignRevisionPayload(ApiModel):
    """Typed result returned after a revision proposal or decision."""

    status: DesignRevisionStatus
    diff: DesignPackageDiffPayload | None = None
    version: DesignPackageVersionPayload | None = None
    issue: DesignRevisionApplicationIssueCode | None = None
    domain_issue: DesignRevisionIssueCode | None = None
    diff_persistence_status: DesignDiffPersistenceStatus | None = None
    version_persistence_status: DesignVersionAppendStatus | None = None

    @classmethod
    def from_domain(
        cls,
        result: DesignRevisionResult,
    ) -> DesignRevisionPayload:
        """Map one owner revision result."""
        return cls(
            status=result.status,
            diff=(
                None if result.diff is None else DesignPackageDiffPayload.from_domain(result.diff)
            ),
            version=(
                None
                if result.version is None
                else DesignPackageVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            domain_issue=result.domain_issue,
            diff_persistence_status=result.diff_persistence_status,
            version_persistence_status=result.version_persistence_status,
        )


class DesignRevisionRequest(ApiModel):
    """Complete proposed replacement for the current Design Package."""

    package: DesignPackagePayload


class DesignRevisionDecisionRequest(ApiModel):
    """Explicit owner decision for one Design Package diff."""

    decision: DesignRevisionDecision
    reason: str | None = None


class DesignGateDecisionRequest(ApiModel):
    """Explicit owner action for Gate 5."""

    action: HumanGateAction
    reason: str | None = None


class DesignGateSubmissionPayload(ApiModel):
    """Typed Gate 5 submission outcome."""

    status: DesignGateSubmissionStatus
    gate: HumanGateResponse | None = None
    events: tuple[HumanGateEventResponse, ...] = ()
    issue: HumanGateIssueCode | None = None

    @classmethod
    def from_domain(
        cls,
        result: DesignGateSubmissionResult,
    ) -> DesignGateSubmissionPayload:
        """Map one Gate 5 submission result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
            issue=result.issue,
        )


class DesignGateDecisionPayload(ApiModel):
    """Typed Gate 5 decision outcome."""

    status: DesignGateDecisionStatus
    gate: HumanGateResponse | None = None
    event: HumanGateEventResponse | None = None
    issue: HumanGateIssueCode | None = None

    @classmethod
    def from_domain(
        cls,
        result: DesignGateDecisionResult,
    ) -> DesignGateDecisionPayload:
        """Map one Gate 5 decision result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            event=_event_response(result.event),
            issue=result.issue,
        )


class DesignReadinessPayload(ApiModel):
    """Derived readiness for architecture and test planning."""

    status: DesignWorkflowReadiness
    version: DesignPackageVersionPayload | None = None
    gate: HumanGateResponse | None = None
    has_package: bool
    package_ready_for_gate: bool
    approved_current_package: bool

    @classmethod
    def from_domain(
        cls,
        result: DesignReadinessResult,
    ) -> DesignReadinessPayload:
        """Map readiness while making exact approval visible."""
        version = result.version
        gate = result.gate
        approved = (
            version is not None
            and gate is not None
            and gate.status is HumanGateStatus.APPROVED
            and gate.artifact.artifact_id == version.id
            and gate.artifact.version == version.version_number
            and gate.artifact.content_hash == version.content_hash
        )

        return cls(
            status=result.status,
            version=(None if version is None else DesignPackageVersionPayload.from_domain(version)),
            gate=_gate_response(gate),
            has_package=version is not None,
            package_ready_for_gate=(version is not None and version.package.ready_for_gate),
            approved_current_package=approved,
        )


class DesignGenerationService(Protocol):
    """Governed design generation used by the API."""

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignGenerationResult:
        """Generate the initial Design Package."""


class DesignRevisionService(Protocol):
    """Owner-controlled Design Package revisions used by the API."""

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_package: DesignExplorationPackage,
    ) -> DesignRevisionResult:
        """Propose one complete Design Package replacement."""

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: DesignRevisionDecision,
        reason: str | None = None,
    ) -> DesignRevisionResult:
        """Approve or reject one Design Package diff."""


class DesignQueryService(Protocol):
    """Owner-scoped Design Package queries used by the API."""

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> DesignPackageVersion | None:
        """Return the current Design Package version."""

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[DesignPackageVersion, ...]:
        """Return immutable Design Package history."""

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> DesignPackageDiff | None:
        """Return one exact Design Package diff."""

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[DesignPackageDiff, ...]:
        """Return Design Package diff history."""


class DesignGateService(Protocol):
    """Gate 5 commands and queries used by the API."""

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignGateSubmissionResult:
        """Submit the exact current Design Package."""

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> DesignGateDecisionResult:
        """Apply one owner Gate 5 decision."""

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignReadinessResult:
        """Return current Design readiness."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the current Gate 5."""

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return Gate 5 event history."""


def _state_service[Service](
    request: Request,
    *,
    attribute: str,
    unavailable_detail: str,
) -> Service:
    """Read one explicitly configured application service."""
    service = getattr(request.app.state, attribute, None)

    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=unavailable_detail,
        )

    return service


def design_generation_service_dependency(
    request: Request,
) -> DesignGenerationService:
    """Return the configured design generation service."""
    return _state_service(
        request,
        attribute="design_generation_service",
        unavailable_detail="design_generation_service_unavailable",
    )


def design_revision_service_dependency(
    request: Request,
) -> DesignRevisionService:
    """Return the configured design revision service."""
    return _state_service(
        request,
        attribute="design_revision_service",
        unavailable_detail="design_revision_service_unavailable",
    )


def design_query_service_dependency(
    request: Request,
) -> DesignQueryService:
    """Return the configured design query service."""
    return _state_service(
        request,
        attribute="design_query_service",
        unavailable_detail="design_query_service_unavailable",
    )


def design_gate_service_dependency(
    request: Request,
) -> DesignGateService:
    """Return the configured Design Gate 5 service."""
    return _state_service(
        request,
        attribute="design_gate_service",
        unavailable_detail="design_gate_service_unavailable",
    )


def create_design_router() -> APIRouter:
    """Create the owner-scoped Design Exploration and Gate 5 router."""
    router = APIRouter(prefix=DESIGN_API_PREFIX, tags=["design"])

    @router.post(
        "/proposals",
        response_model=DesignGenerationPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="generateDesignPackage",
    )
    async def generate_design_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGenerationService,
            Depends(design_generation_service_dependency),
        ],
    ) -> DesignGenerationPayload:
        result = await service.generate(
            owner_user_id=user.id,
            project_id=project_id,
        )
        _raise_generation_failure(result)

        return DesignGenerationPayload.from_domain(result)

    @router.get(
        "/current",
        response_model=DesignPackageVersionPayload,
        operation_id="getCurrentDesignPackage",
    )
    async def current_design_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignQueryService,
            Depends(design_query_service_dependency),
        ],
    ) -> DesignPackageVersionPayload:
        version = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if version is None:
            raise _not_found("DESIGN_PACKAGE_NOT_FOUND")

        return DesignPackageVersionPayload.from_domain(version)

    @router.get(
        "",
        response_model=tuple[DesignPackageVersionPayload, ...],
        operation_id="listDesignPackages",
    )
    async def design_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignQueryService,
            Depends(design_query_service_dependency),
        ],
    ) -> tuple[DesignPackageVersionPayload, ...]:
        versions = await service.history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(DesignPackageVersionPayload.from_domain(version) for version in versions)

    @router.post(
        "/revisions",
        response_model=DesignRevisionPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="proposeDesignRevision",
    )
    async def propose_revision_endpoint(
        project_id: UUID,
        payload: DesignRevisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignRevisionService,
            Depends(design_revision_service_dependency),
        ],
    ) -> DesignRevisionPayload:
        if payload.package.project_id != project_id:
            raise _unprocessable("DESIGN_PROJECT_MISMATCH")

        try:
            proposed = payload.package.to_domain()
        except (TypeError, ValueError) as error:
            raise _unprocessable("INVALID_DESIGN_PACKAGE") from error

        result = await service.propose_revision(
            owner_user_id=user.id,
            project_id=project_id,
            proposed_package=proposed,
        )
        _raise_revision_failure(result)

        return DesignRevisionPayload.from_domain(result)

    @router.get(
        "/revisions",
        response_model=tuple[DesignPackageDiffPayload, ...],
        operation_id="listDesignRevisions",
    )
    async def revision_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignQueryService,
            Depends(design_query_service_dependency),
        ],
    ) -> tuple[DesignPackageDiffPayload, ...]:
        diffs = await service.diff_history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(DesignPackageDiffPayload.from_domain(diff) for diff in diffs)

    @router.get(
        "/revisions/{diff_id}",
        response_model=DesignPackageDiffPayload,
        operation_id="getDesignRevision",
    )
    async def get_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignQueryService,
            Depends(design_query_service_dependency),
        ],
    ) -> DesignPackageDiffPayload:
        diff = await service.get_diff(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
        )

        if diff is None:
            raise _not_found("DESIGN_DIFF_NOT_FOUND")

        return DesignPackageDiffPayload.from_domain(diff)

    @router.post(
        "/revisions/{diff_id}/decision",
        response_model=DesignRevisionPayload,
        operation_id="decideDesignRevision",
    )
    async def decide_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        payload: DesignRevisionDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignRevisionService,
            Depends(design_revision_service_dependency),
        ],
    ) -> DesignRevisionPayload:
        result = await service.decide_revision(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        _raise_revision_failure(result)

        return DesignRevisionPayload.from_domain(result)

    @router.post(
        "/gate/submit",
        response_model=DesignGateSubmissionPayload,
        operation_id="submitDesignGate",
    )
    async def submit_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGateService,
            Depends(design_gate_service_dependency),
        ],
    ) -> DesignGateSubmissionPayload:
        result = await service.submit(
            project_id=project_id,
            owner_user_id=user.id,
        )
        _raise_gate_submission_failure(result)

        return DesignGateSubmissionPayload.from_domain(result)

    @router.post(
        "/gate/decision",
        response_model=DesignGateDecisionPayload,
        operation_id="decideDesignGate",
    )
    async def decide_gate_endpoint(
        project_id: UUID,
        payload: DesignGateDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGateService,
            Depends(design_gate_service_dependency),
        ],
    ) -> DesignGateDecisionPayload:
        result = await service.decide(
            project_id=project_id,
            owner_user_id=user.id,
            action=payload.action,
            reason=payload.reason,
        )
        _raise_gate_decision_failure(result)

        return DesignGateDecisionPayload.from_domain(result)

    @router.get(
        "/gate",
        response_model=HumanGateResponse,
        operation_id="getCurrentDesignGate",
    )
    async def current_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGateService,
            Depends(design_gate_service_dependency),
        ],
    ) -> HumanGateResponse:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("DESIGN_GATE_NOT_FOUND")

        return HumanGateResponse.from_domain(gate)

    @router.get(
        "/gate/events",
        response_model=tuple[HumanGateEventResponse, ...],
        operation_id="listDesignGateEvents",
    )
    async def gate_events_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGateService,
            Depends(design_gate_service_dependency),
        ],
    ) -> tuple[HumanGateEventResponse, ...]:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("DESIGN_GATE_NOT_FOUND")

        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate.id,
        )

        return tuple(HumanGateEventResponse.from_domain(event) for event in events)

    @router.get(
        "/readiness",
        response_model=DesignReadinessPayload,
        operation_id="getDesignReadiness",
    )
    async def readiness_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            DesignGateService,
            Depends(design_gate_service_dependency),
        ],
    ) -> DesignReadinessPayload:
        result = await service.readiness(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return DesignReadinessPayload.from_domain(result)

    return router


def _gate_response(gate: HumanGate | None) -> HumanGateResponse | None:
    """Map an optional human gate."""
    return None if gate is None else HumanGateResponse.from_domain(gate)


def _event_response(
    event: HumanGateEvent | None,
) -> HumanGateEventResponse | None:
    """Map an optional human-gate event."""
    return None if event is None else HumanGateEventResponse.from_domain(event)


def _raise_generation_failure(result: DesignGenerationResult) -> None:
    """Translate expected design-generation failures into HTTP semantics."""
    if result.status is DesignGenerationStatus.CREATED:
        return

    if result.issue is DesignGenerationIssueCode.PROJECT_NOT_FOUND:
        raise _not_found("PROJECT_NOT_FOUND")

    raise _conflict(
        result.issue.value if result.issue is not None else "DESIGN_GENERATION_REJECTED"
    )


def _raise_revision_failure(result: DesignRevisionResult) -> None:
    """Translate expected owner-revision failures into HTTP semantics."""
    if result.status in {
        DesignRevisionStatus.CREATED,
        DesignRevisionStatus.APPLIED,
    }:
        return

    if result.issue in {
        DesignRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
        DesignRevisionApplicationIssueCode.DIFF_NOT_FOUND,
    }:
        raise _not_found(result.issue.value)

    code = (
        result.domain_issue.value
        if result.domain_issue is not None
        else (result.issue.value if result.issue is not None else "DESIGN_REVISION_REJECTED")
    )
    raise _conflict(code)


def _raise_gate_submission_failure(
    result: DesignGateSubmissionResult,
) -> None:
    """Translate expected Gate 5 submission failures."""
    if result.status in {
        DesignGateSubmissionStatus.SUBMITTED,
        DesignGateSubmissionStatus.ALREADY_PENDING,
        DesignGateSubmissionStatus.ALREADY_APPROVED,
    }:
        return

    if result.status is DesignGateSubmissionStatus.PACKAGE_NOT_FOUND:
        raise _not_found("DESIGN_PACKAGE_NOT_FOUND")

    raise _conflict(result.status.value)


def _raise_gate_decision_failure(
    result: DesignGateDecisionResult,
) -> None:
    """Translate expected Gate 5 decision failures."""
    if result.status is DesignGateDecisionStatus.APPLIED:
        return

    if result.status in {
        DesignGateDecisionStatus.GATE_NOT_FOUND,
        DesignGateDecisionStatus.PACKAGE_NOT_FOUND,
    }:
        raise _not_found(result.status.value)

    raise _conflict(result.issue.value if result.issue is not None else result.status.value)


def _not_found(code: str) -> HTTPException:
    """Return one non-disclosing owner-scoped lookup error."""
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code},
    )


def _conflict(code: str) -> HTTPException:
    """Return one typed state or governance conflict."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code},
    )


def _unprocessable(code: str) -> HTTPException:
    """Return one typed invalid-input response."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": code},
    )


__all__ = [
    "DESIGN_API_PREFIX",
    "DesignGenerationPayload",
    "DesignPackageDiffPayload",
    "DesignPackagePayload",
    "DesignPackageVersionPayload",
    "DesignQueryService",
    "DesignReadinessPayload",
    "DesignRevisionPayload",
    "create_design_router",
]
