"""FastAPI boundary for Architecture Planning, Test Plans, and Gate 6."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, JsonValue

from orchestwin.api.auth import current_user_dependency
from orchestwin.api.clarification import HumanGateEventResponse, HumanGateResponse
from orchestwin.artifacts.architecture import (
    ApiMethod,
    ArchitectureComponentKind,
    ArchitectureConnectionKind,
    ArchitectureStyle,
)
from orchestwin.artifacts.architecture_gate import (
    ArchitectureGateDecisionResult,
    ArchitectureGateDecisionStatus,
    ArchitectureGateSubmissionResult,
    ArchitectureGateSubmissionStatus,
    ArchitectureReadinessResult,
    ArchitectureWorkflowReadiness,
)
from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
)
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureDiffPersistenceStatus,
    ArchitectureRevisionApplicationIssueCode,
    ArchitectureRevisionResult,
    ArchitectureRevisionStatus,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitectureArtifactKind,
    ArchitectureChangeKind,
    ArchitecturePackageDiff,
    ArchitecturePackageDiffStatus,
    ArchitectureRevisionDecision,
    ArchitectureRevisionIssueCode,
)
from orchestwin.artifacts.architecture_serialization import (
    architecture_package_from_snapshot,
)
from orchestwin.artifacts.references import ArtifactKind
from orchestwin.artifacts.test_plans import (
    TestAutomation,
    TestEnvironmentKind,
    TestLevel,
    TestPriority,
)
from orchestwin.identity.domain import UserAccount
from orchestwin.models.architecture import ArchitectureProposalIssueCode
from orchestwin.projects.architecture_application import (
    ArchitectureGenerationIssueCode,
    ArchitectureGenerationResult,
    ArchitectureGenerationStatus,
    ArchitectureVersionAppendStatus,
)
from orchestwin.projects.requirements_quality import RiskImpact, RiskLikelihood
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateType,
)

ARCHITECTURE_API_PREFIX = "/projects/{project_id}/architecture"


class ApiModel(BaseModel):
    """Strict base model for Architecture API contracts."""

    model_config = ConfigDict(extra="forbid")


class VersionedArtifactReferencePayload(ApiModel):
    """Exact identity, version, and hash of one governed artifact."""

    kind: ArtifactKind
    artifact_id: UUID
    version_number: int
    content_hash: str


class UserTwinVersionReferencePayload(ApiModel):
    """Exact approved User Twin version inherited by architecture planning."""

    twin_id: UUID
    version_number: int
    content_hash: str
    name: str


class ArchitectureCatalogPayload(ApiModel):
    """Fixed-catalog metadata inherited from the approved workflow."""

    version: int
    content_hash: str


class ArchitectureGroundingPayload(ApiModel):
    """Exact approved Design Package and inherited planning context."""

    project_id: UUID
    design_package_reference: VersionedArtifactReferencePayload
    requirements_reference: VersionedArtifactReferencePayload
    agent_team_reference: VersionedArtifactReferencePayload
    user_modeling_reference: VersionedArtifactReferencePayload
    catalog: ArchitectureCatalogPayload
    owner_selected_alternative_id: UUID
    prototype_id: UUID
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReferencePayload, ...]


class ArchitectureComponentPayload(ApiModel):
    """One bounded generated-project component."""

    id: UUID
    code: str
    name: str
    kind: ArchitectureComponentKind
    responsibility: str
    technology: str
    interfaces: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    assumptions: tuple[str, ...]


class ArchitectureConnectionPayload(ApiModel):
    """One explicit component dependency or data-flow relation."""

    id: UUID
    code: str
    source_component_id: UUID
    target_component_id: UUID
    kind: ArchitectureConnectionKind
    description: str
    data_flows: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]


class ArchitectureDecisionPayload(ApiModel):
    """One ADR-ready architecture decision."""

    id: UUID
    code: str
    title: str
    context: str
    decision: str
    consequences: tuple[str, ...]
    alternatives_considered: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]


class ArchitectureDataEntityPayload(ApiModel):
    """One logical data entity and owning component."""

    id: UUID
    code: str
    name: str
    description: str
    fields: tuple[str, ...]
    owning_component_id: UUID
    requirement_ids: tuple[UUID, ...]


class ArchitectureApiOperationPayload(ApiModel):
    """One planned generated-project API operation."""

    id: UUID
    code: str
    method: ApiMethod
    path: str
    summary: str
    owning_component_id: UUID
    request_schema: str | None
    response_schema: str
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]


class ArchitectureRiskPayload(ApiModel):
    """One explicit architecture risk with mitigation and traceability."""

    id: UUID
    code: str
    summary: str
    likelihood: RiskLikelihood
    impact: RiskImpact
    mitigation: str
    component_ids: tuple[UUID, ...]
    requirement_ids: tuple[UUID, ...]


class SoftwareArchitecturePayload(ApiModel):
    """Complete generated-project software architecture specification."""

    id: UUID
    code: str
    title: str
    style: ArchitectureStyle
    summary: str
    selected_design_alternative_id: UUID
    prototype_id: UUID
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    components: tuple[ArchitectureComponentPayload, ...]
    connections: tuple[ArchitectureConnectionPayload, ...]
    decisions: tuple[ArchitectureDecisionPayload, ...]
    data_entities: tuple[ArchitectureDataEntityPayload, ...]
    api_operations: tuple[ArchitectureApiOperationPayload, ...]
    risks: tuple[ArchitectureRiskPayload, ...]
    quality_attributes: tuple[str, ...]
    deployment_view: tuple[str, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]


class TestEnvironmentPayload(ApiModel):
    """One declared environment needed by planned tests."""

    id: UUID
    code: str
    name: str
    kind: TestEnvironmentKind
    description: str
    configuration: tuple[str, ...]


class PlannedTestCasePayload(ApiModel):
    """One traceable generated-project test or review activity."""

    id: UUID
    code: str
    title: str
    objective: str
    level: TestLevel
    automation: TestAutomation
    priority: TestPriority
    preconditions: tuple[str, ...]
    steps: tuple[str, ...]
    expected_results: tuple[str, ...]
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    architecture_component_ids: tuple[UUID, ...]
    design_alternative_ids: tuple[UUID, ...]
    environment_ids: tuple[UUID, ...]


class QualityGatePayload(ApiModel):
    """One deterministic completion condition over planned tests."""

    id: UUID
    code: str
    title: str
    criterion: str
    required_test_case_ids: tuple[UUID, ...]
    minimum_pass_rate: int
    blocking: bool


class TestPlanPayload(ApiModel):
    """Complete traceable test strategy for the proposed architecture."""

    id: UUID
    code: str
    title: str
    strategy: str
    architecture_id: UUID
    selected_design_alternative_id: UUID
    requirement_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    architecture_component_ids: tuple[UUID, ...]
    environments: tuple[TestEnvironmentPayload, ...]
    test_cases: tuple[PlannedTestCasePayload, ...]
    quality_gates: tuple[QualityGatePayload, ...]
    fixtures: tuple[str, ...]
    assumptions: tuple[str, ...]
    open_questions: tuple[str, ...]


class ArchitecturePackagePayload(ApiModel):
    """Complete typed Architecture Package HTTP representation."""

    schema_version: int
    project_id: UUID
    grounding: ArchitectureGroundingPayload
    architecture: SoftwareArchitecturePayload
    test_plan: TestPlanPayload
    open_questions: tuple[str, ...]

    @classmethod
    def from_domain(
        cls,
        package: ArchitecturePlanningPackage,
    ) -> ArchitecturePackagePayload:
        """Map one complete domain package through its canonical snapshot."""
        return cls.model_validate(package.to_snapshot())

    def to_domain(self) -> ArchitecturePlanningPackage:
        """Convert this complete payload through canonical domain validation."""
        return architecture_package_from_snapshot(self.model_dump(mode="json"))


class ArchitecturePackageVersionPayload(ApiModel):
    """One immutable Architecture Package version exposed by the API."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    package: ArchitecturePackagePayload
    created_by_user_id: UUID
    created_at: datetime

    @classmethod
    def from_domain(
        cls,
        version: ArchitecturePackageVersion,
    ) -> ArchitecturePackageVersionPayload:
        """Map one immutable Architecture Package version."""
        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=version.version_number,
            based_on_version_number=version.based_on_version_number,
            content_hash=version.content_hash,
            package=ArchitecturePackagePayload.from_domain(version.package),
            created_by_user_id=version.created_by_user_id,
            created_at=version.created_at,
        )


class ArchitectureChangePayload(ApiModel):
    """One explicit before/after replacement inside an owner revision."""

    kind: ArchitectureChangeKind
    artifact_kind: ArchitectureArtifactKind
    artifact_id: UUID
    before: dict[str, JsonValue]
    after: dict[str, JsonValue]


class ArchitecturePackageDiffPayload(ApiModel):
    """One immutable owner-reviewable Architecture Package diff."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_package: ArchitecturePackagePayload
    proposal_hash: str
    changes: tuple[ArchitectureChangePayload, ...]
    status: ArchitecturePackageDiffStatus
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    applied_version_id: UUID | None
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        diff: ArchitecturePackageDiff,
    ) -> ArchitecturePackageDiffPayload:
        """Map one complete Architecture Package diff."""
        return cls(
            **diff.to_snapshot(),
            content_hash=diff.content_hash,
        )


class ArchitectureGenerationPayload(ApiModel):
    """Typed result returned after deterministic architecture generation."""

    status: ArchitectureGenerationStatus
    version: ArchitecturePackageVersionPayload | None = None
    issue: ArchitectureGenerationIssueCode | None = None
    proposal_issue: ArchitectureProposalIssueCode | None = None
    persistence_status: ArchitectureVersionAppendStatus | None = None

    @classmethod
    def from_domain(
        cls,
        result: ArchitectureGenerationResult,
    ) -> ArchitectureGenerationPayload:
        """Map one governed architecture-generation result."""
        return cls(
            status=result.status,
            version=(
                None
                if result.version is None
                else ArchitecturePackageVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            proposal_issue=result.proposal_issue,
            persistence_status=result.persistence_status,
        )


class ArchitectureRevisionPayload(ApiModel):
    """Typed result returned after a revision proposal or decision."""

    status: ArchitectureRevisionStatus
    diff: ArchitecturePackageDiffPayload | None = None
    version: ArchitecturePackageVersionPayload | None = None
    issue: ArchitectureRevisionApplicationIssueCode | None = None
    domain_issue: ArchitectureRevisionIssueCode | None = None
    diff_persistence_status: ArchitectureDiffPersistenceStatus | None = None
    version_persistence_status: ArchitectureVersionAppendStatus | None = None

    @classmethod
    def from_domain(
        cls,
        result: ArchitectureRevisionResult,
    ) -> ArchitectureRevisionPayload:
        """Map one owner revision result."""
        return cls(
            status=result.status,
            diff=(
                None
                if result.diff is None
                else ArchitecturePackageDiffPayload.from_domain(result.diff)
            ),
            version=(
                None
                if result.version is None
                else ArchitecturePackageVersionPayload.from_domain(result.version)
            ),
            issue=result.issue,
            domain_issue=result.domain_issue,
            diff_persistence_status=result.diff_persistence_status,
            version_persistence_status=result.version_persistence_status,
        )


class ArchitectureRevisionRequest(ApiModel):
    """Complete proposed replacement for the current Architecture Package."""

    package: ArchitecturePackagePayload


class ArchitectureRevisionDecisionRequest(ApiModel):
    """Explicit owner decision for one Architecture Package diff."""

    decision: ArchitectureRevisionDecision
    reason: str | None = None


class ArchitectureGateDecisionRequest(ApiModel):
    """Explicit owner action for Gate 6."""

    action: HumanGateAction
    reason: str | None = None


class ArchitectureGateSubmissionPayload(ApiModel):
    """Typed Gate 6 submission outcome."""

    status: ArchitectureGateSubmissionStatus
    gate: HumanGateResponse | None = None
    events: tuple[HumanGateEventResponse, ...] = ()
    issue: HumanGateIssueCode | None = None

    @classmethod
    def from_domain(
        cls,
        result: ArchitectureGateSubmissionResult,
    ) -> ArchitectureGateSubmissionPayload:
        """Map one Gate 6 submission result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            events=tuple(HumanGateEventResponse.from_domain(event) for event in result.events),
            issue=result.issue,
        )


class ArchitectureGateDecisionPayload(ApiModel):
    """Typed Gate 6 decision outcome."""

    status: ArchitectureGateDecisionStatus
    gate: HumanGateResponse | None = None
    event: HumanGateEventResponse | None = None
    issue: HumanGateIssueCode | None = None

    @classmethod
    def from_domain(
        cls,
        result: ArchitectureGateDecisionResult,
    ) -> ArchitectureGateDecisionPayload:
        """Map one Gate 6 decision result."""
        return cls(
            status=result.status,
            gate=_gate_response(result.gate),
            event=_event_response(result.event),
            issue=result.issue,
        )


class ArchitectureReadinessPayload(ApiModel):
    """Derived readiness for implementation after Gate 6."""

    status: ArchitectureWorkflowReadiness
    version: ArchitecturePackageVersionPayload | None = None
    gate: HumanGateResponse | None = None
    has_package: bool
    approved_current_package: bool

    @classmethod
    def from_domain(
        cls,
        result: ArchitectureReadinessResult,
    ) -> ArchitectureReadinessPayload:
        """Map readiness while making exact Gate 6 approval visible."""
        version = result.version
        gate = result.gate
        approved = (
            version is not None
            and gate is not None
            and gate.gate_type is HumanGateType.ARCHITECTURE
            and gate.status is HumanGateStatus.APPROVED
            and gate.artifact.artifact_id == version.id
            and gate.artifact.version == version.version_number
            and gate.artifact.content_hash == version.content_hash
        )

        return cls(
            status=result.status,
            version=(
                None if version is None else ArchitecturePackageVersionPayload.from_domain(version)
            ),
            gate=_gate_response(gate),
            has_package=version is not None,
            approved_current_package=approved,
        )


class ArchitectureGenerationService(Protocol):
    """Governed architecture generation used by the API."""

    async def generate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitectureGenerationResult:
        """Generate the initial Architecture Package."""


class ArchitectureRevisionService(Protocol):
    """Owner-controlled Architecture Package revisions used by the API."""

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        proposed_package: ArchitecturePlanningPackage,
    ) -> ArchitectureRevisionResult:
        """Propose one complete Architecture Package replacement."""

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ArchitectureRevisionDecision,
        reason: str | None = None,
    ) -> ArchitectureRevisionResult:
        """Approve or reject one Architecture Package diff."""


class ArchitectureQueryService(Protocol):
    """Owner-scoped Architecture Package queries used by the API."""

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Return the current Architecture Package version."""

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageVersion, ...]:
        """Return immutable Architecture Package history."""

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return one exact Architecture Package diff."""

    async def diff_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageDiff, ...]:
        """Return Architecture Package diff history."""


class ArchitectureGateService(Protocol):
    """Gate 6 commands and queries used by the API."""

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureGateSubmissionResult:
        """Submit the exact current Architecture Package."""

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> ArchitectureGateDecisionResult:
        """Apply one owner Gate 6 decision."""

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureReadinessResult:
        """Return current Architecture readiness."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the current Gate 6."""

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return Gate 6 event history."""


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


def architecture_generation_service_dependency(
    request: Request,
) -> ArchitectureGenerationService:
    """Return the configured architecture generation service."""
    return _state_service(
        request,
        attribute="architecture_generation_service",
        unavailable_detail="architecture_generation_service_unavailable",
    )


def architecture_revision_service_dependency(
    request: Request,
) -> ArchitectureRevisionService:
    """Return the configured architecture revision service."""
    return _state_service(
        request,
        attribute="architecture_revision_service",
        unavailable_detail="architecture_revision_service_unavailable",
    )


def architecture_query_service_dependency(
    request: Request,
) -> ArchitectureQueryService:
    """Return the configured architecture query service."""
    return _state_service(
        request,
        attribute="architecture_query_service",
        unavailable_detail="architecture_query_service_unavailable",
    )


def architecture_gate_service_dependency(
    request: Request,
) -> ArchitectureGateService:
    """Return the configured Architecture Gate 6 service."""
    return _state_service(
        request,
        attribute="architecture_gate_service",
        unavailable_detail="architecture_gate_service_unavailable",
    )


def create_architecture_router() -> APIRouter:
    """Create the owner-scoped Architecture Planning and Gate 6 router."""
    router = APIRouter(prefix=ARCHITECTURE_API_PREFIX, tags=["architecture"])

    @router.post(
        "/proposals",
        response_model=ArchitectureGenerationPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="generateArchitecturePackage",
    )
    async def generate_architecture_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGenerationService,
            Depends(architecture_generation_service_dependency),
        ],
    ) -> ArchitectureGenerationPayload:
        result = await service.generate(
            owner_user_id=user.id,
            project_id=project_id,
        )
        _raise_generation_failure(result)

        return ArchitectureGenerationPayload.from_domain(result)

    @router.get(
        "/current",
        response_model=ArchitecturePackageVersionPayload,
        operation_id="getCurrentArchitecturePackage",
    )
    async def current_architecture_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureQueryService,
            Depends(architecture_query_service_dependency),
        ],
    ) -> ArchitecturePackageVersionPayload:
        version = await service.current(
            owner_user_id=user.id,
            project_id=project_id,
        )

        if version is None:
            raise _not_found("ARCHITECTURE_PACKAGE_NOT_FOUND")

        return ArchitecturePackageVersionPayload.from_domain(version)

    @router.get(
        "",
        response_model=tuple[ArchitecturePackageVersionPayload, ...],
        operation_id="listArchitecturePackages",
    )
    async def architecture_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureQueryService,
            Depends(architecture_query_service_dependency),
        ],
    ) -> tuple[ArchitecturePackageVersionPayload, ...]:
        versions = await service.history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(ArchitecturePackageVersionPayload.from_domain(version) for version in versions)

    @router.post(
        "/revisions",
        response_model=ArchitectureRevisionPayload,
        status_code=status.HTTP_201_CREATED,
        operation_id="proposeArchitectureRevision",
    )
    async def propose_revision_endpoint(
        project_id: UUID,
        payload: ArchitectureRevisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureRevisionService,
            Depends(architecture_revision_service_dependency),
        ],
    ) -> ArchitectureRevisionPayload:
        if payload.package.project_id != project_id:
            raise _unprocessable("ARCHITECTURE_PROJECT_MISMATCH")

        try:
            proposed = payload.package.to_domain()
        except (TypeError, ValueError) as error:
            raise _unprocessable("INVALID_ARCHITECTURE_PACKAGE") from error

        result = await service.propose_revision(
            owner_user_id=user.id,
            project_id=project_id,
            proposed_package=proposed,
        )
        _raise_revision_failure(result)

        return ArchitectureRevisionPayload.from_domain(result)

    @router.get(
        "/revisions",
        response_model=tuple[ArchitecturePackageDiffPayload, ...],
        operation_id="listArchitectureRevisions",
    )
    async def revision_history_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureQueryService,
            Depends(architecture_query_service_dependency),
        ],
    ) -> tuple[ArchitecturePackageDiffPayload, ...]:
        diffs = await service.diff_history(
            owner_user_id=user.id,
            project_id=project_id,
        )

        return tuple(ArchitecturePackageDiffPayload.from_domain(diff) for diff in diffs)

    @router.get(
        "/revisions/{diff_id}",
        response_model=ArchitecturePackageDiffPayload,
        operation_id="getArchitectureRevision",
    )
    async def get_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureQueryService,
            Depends(architecture_query_service_dependency),
        ],
    ) -> ArchitecturePackageDiffPayload:
        diff = await service.get_diff(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
        )

        if diff is None:
            raise _not_found("ARCHITECTURE_DIFF_NOT_FOUND")

        return ArchitecturePackageDiffPayload.from_domain(diff)

    @router.post(
        "/revisions/{diff_id}/decision",
        response_model=ArchitectureRevisionPayload,
        operation_id="decideArchitectureRevision",
    )
    async def decide_revision_endpoint(
        project_id: UUID,
        diff_id: UUID,
        payload: ArchitectureRevisionDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureRevisionService,
            Depends(architecture_revision_service_dependency),
        ],
    ) -> ArchitectureRevisionPayload:
        result = await service.decide_revision(
            owner_user_id=user.id,
            project_id=project_id,
            diff_id=diff_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        _raise_revision_failure(result)

        return ArchitectureRevisionPayload.from_domain(result)

    @router.post(
        "/gate/submit",
        response_model=ArchitectureGateSubmissionPayload,
        operation_id="submitArchitectureGate",
    )
    async def submit_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGateService,
            Depends(architecture_gate_service_dependency),
        ],
    ) -> ArchitectureGateSubmissionPayload:
        result = await service.submit(
            project_id=project_id,
            owner_user_id=user.id,
        )
        _raise_gate_submission_failure(result)

        return ArchitectureGateSubmissionPayload.from_domain(result)

    @router.post(
        "/gate/decision",
        response_model=ArchitectureGateDecisionPayload,
        operation_id="decideArchitectureGate",
    )
    async def decide_gate_endpoint(
        project_id: UUID,
        payload: ArchitectureGateDecisionRequest,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGateService,
            Depends(architecture_gate_service_dependency),
        ],
    ) -> ArchitectureGateDecisionPayload:
        result = await service.decide(
            project_id=project_id,
            owner_user_id=user.id,
            action=payload.action,
            reason=payload.reason,
        )
        _raise_gate_decision_failure(result)

        return ArchitectureGateDecisionPayload.from_domain(result)

    @router.get(
        "/gate",
        response_model=HumanGateResponse,
        operation_id="getCurrentArchitectureGate",
    )
    async def current_gate_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGateService,
            Depends(architecture_gate_service_dependency),
        ],
    ) -> HumanGateResponse:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("ARCHITECTURE_GATE_NOT_FOUND")

        return HumanGateResponse.from_domain(gate)

    @router.get(
        "/gate/events",
        response_model=tuple[HumanGateEventResponse, ...],
        operation_id="listArchitectureGateEvents",
    )
    async def gate_events_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGateService,
            Depends(architecture_gate_service_dependency),
        ],
    ) -> tuple[HumanGateEventResponse, ...]:
        gate = await service.current_gate(
            project_id=project_id,
            owner_user_id=user.id,
        )

        if gate is None:
            raise _not_found("ARCHITECTURE_GATE_NOT_FOUND")

        events = await service.gate_events(
            project_id=project_id,
            owner_user_id=user.id,
            gate_id=gate.id,
        )

        return tuple(HumanGateEventResponse.from_domain(event) for event in events)

    @router.get(
        "/readiness",
        response_model=ArchitectureReadinessPayload,
        operation_id="getArchitectureReadiness",
    )
    async def readiness_endpoint(
        project_id: UUID,
        user: Annotated[UserAccount, Depends(current_user_dependency)],
        service: Annotated[
            ArchitectureGateService,
            Depends(architecture_gate_service_dependency),
        ],
    ) -> ArchitectureReadinessPayload:
        result = await service.readiness(
            project_id=project_id,
            owner_user_id=user.id,
        )

        return ArchitectureReadinessPayload.from_domain(result)

    return router


def _gate_response(gate: HumanGate | None) -> HumanGateResponse | None:
    """Map an optional human gate."""
    return None if gate is None else HumanGateResponse.from_domain(gate)


def _event_response(
    event: HumanGateEvent | None,
) -> HumanGateEventResponse | None:
    """Map an optional human-gate event."""
    return None if event is None else HumanGateEventResponse.from_domain(event)


def _raise_generation_failure(result: ArchitectureGenerationResult) -> None:
    """Translate expected architecture-generation failures into HTTP semantics."""
    if result.status is ArchitectureGenerationStatus.CREATED:
        return

    if result.issue is ArchitectureGenerationIssueCode.PROJECT_NOT_FOUND:
        raise _not_found("PROJECT_NOT_FOUND")

    raise _conflict(
        result.issue.value if result.issue is not None else "ARCHITECTURE_GENERATION_REJECTED"
    )


def _raise_revision_failure(result: ArchitectureRevisionResult) -> None:
    """Translate expected owner-revision failures into HTTP semantics."""
    if result.status in {
        ArchitectureRevisionStatus.CREATED,
        ArchitectureRevisionStatus.APPLIED,
    }:
        return

    if result.issue in {
        ArchitectureRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
        ArchitectureRevisionApplicationIssueCode.DIFF_NOT_FOUND,
    }:
        raise _not_found(result.issue.value)

    code = (
        result.domain_issue.value
        if result.domain_issue is not None
        else (result.issue.value if result.issue is not None else "ARCHITECTURE_REVISION_REJECTED")
    )
    raise _conflict(code)


def _raise_gate_submission_failure(
    result: ArchitectureGateSubmissionResult,
) -> None:
    """Translate expected Gate 6 submission failures."""
    if result.status in {
        ArchitectureGateSubmissionStatus.SUBMITTED,
        ArchitectureGateSubmissionStatus.ALREADY_PENDING,
        ArchitectureGateSubmissionStatus.ALREADY_APPROVED,
    }:
        return

    if result.status is ArchitectureGateSubmissionStatus.PACKAGE_NOT_FOUND:
        raise _not_found("ARCHITECTURE_PACKAGE_NOT_FOUND")

    raise _conflict(result.status.value)


def _raise_gate_decision_failure(
    result: ArchitectureGateDecisionResult,
) -> None:
    """Translate expected Gate 6 decision failures."""
    if result.status is ArchitectureGateDecisionStatus.APPLIED:
        return

    if result.status in {
        ArchitectureGateDecisionStatus.GATE_NOT_FOUND,
        ArchitectureGateDecisionStatus.PACKAGE_NOT_FOUND,
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
    "ARCHITECTURE_API_PREFIX",
    "ArchitectureGenerationPayload",
    "ArchitecturePackageDiffPayload",
    "ArchitecturePackagePayload",
    "ArchitecturePackageVersionPayload",
    "ArchitectureQueryService",
    "ArchitectureReadinessPayload",
    "ArchitectureRevisionPayload",
    "create_architecture_router",
]
