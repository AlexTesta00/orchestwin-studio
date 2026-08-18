"""FastAPI boundary for User Modeling, User Twins, and Gate 3."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, Self
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from orchestwin.twins.application import (
    GroundedSnapshotGenerationResult,
    PersonaDecisionApplicationResult,
    PersonaOwnerDecision,
    PersonaProposalApplicationResult,
    UserModelingApplicationIssueCode,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ObservationValueKind,
    ProfileObservation,
)
from orchestwin.twins.lifecycle import (
    UserTwinOwnerApprovalStatus,
    effective_user_twin_lifecycle,
)
from orchestwin.twins.personas import (
    PersonaProfileVersion,
)
from orchestwin.twins.revision_application import (
    ProfileRevisionApplicationIssueCode,
    ProfileRevisionApplicationResult,
    ProfileRevisionDecision,
)
from orchestwin.twins.revisions import (
    UserTwinProfileDiff,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
    VersionedArtifactReference,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateType,
)

USER_MODELING_API_PREFIX = "/projects/{project_id}/user-modeling"


class ApiModel(BaseModel):
    """Strict base class for User Modeling API contracts."""

    model_config = ConfigDict(
        extra="forbid",
    )


class EvidenceReferencePayload(ApiModel):
    """HTTP representation of one evidence reference."""

    source_kind: EvidenceSourceKind
    source_id: str
    source_version: int | None = None
    content_hash: str | None = None
    locator: str | None = None
    summary: str | None = None

    @classmethod
    def from_domain(
        cls,
        reference: EvidenceReference,
    ) -> EvidenceReferencePayload:
        """Convert a domain evidence reference."""
        return cls(
            source_kind=reference.source_kind,
            source_id=reference.source_id,
            source_version=(reference.source_version),
            content_hash=(reference.content_hash),
            locator=reference.locator,
            summary=reference.summary,
        )

    def to_domain(
        self,
    ) -> EvidenceReference:
        """Convert an API evidence reference to domain."""
        return EvidenceReference(
            source_kind=self.source_kind,
            source_id=self.source_id,
            source_version=self.source_version,
            content_hash=self.content_hash,
            locator=self.locator,
            summary=self.summary,
        )


class ObservationValuePayload(ApiModel):
    """Typed value carried by a profile observation."""

    kind: ObservationValueKind
    text: str | None = None
    items: tuple[str, ...] = ()
    reason: str | None = None

    @classmethod
    def from_domain(
        cls,
        value: ObservationValue,
    ) -> ObservationValuePayload:
        """Convert a domain observation value."""
        return cls(
            kind=value.kind,
            text=value.text,
            items=value.items,
            reason=value.reason,
        )

    def to_domain(
        self,
    ) -> ObservationValue:
        """Convert the API value through domain validation."""
        return ObservationValue(
            kind=self.kind,
            text=self.text,
            items=self.items,
            reason=self.reason,
        )


class ProfileObservationPayload(ApiModel):
    """Inspectable epistemic profile observation."""

    observation_key: str
    value: ObservationValuePayload
    epistemic_status: EpistemicStatus
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    provenance: tuple[
        EvidenceReferencePayload,
        ...,
    ]
    human_validation: HumanValidationRequirement
    rationale: str | None = None

    @classmethod
    def from_domain(
        cls,
        observation: ProfileObservation,
    ) -> ProfileObservationPayload:
        """Convert one domain profile observation."""
        return cls(
            observation_key=(observation.observation_key),
            value=(ObservationValuePayload.from_domain(observation.value)),
            epistemic_status=(observation.epistemic_status),
            confidence=(observation.confidence.value),
            provenance=tuple(
                EvidenceReferencePayload.from_domain(reference)
                for reference in observation.provenance.references
            ),
            human_validation=(observation.human_validation),
            rationale=observation.rationale,
        )

    def to_domain(
        self,
    ) -> ProfileObservation:
        """Convert the API observation through domain invariants."""
        return ProfileObservation(
            observation_key=(self.observation_key),
            value=self.value.to_domain(),
            epistemic_status=(self.epistemic_status),
            confidence=ConfidenceScore(self.confidence),
            provenance=(
                ObservationProvenance.from_references(
                    tuple(reference.to_domain() for reference in self.provenance)
                )
            ),
            human_validation=(self.human_validation),
            rationale=self.rationale,
        )


class ArtifactReferencePayload(ApiModel):
    """Exact immutable artifact reference."""

    artifact_id: UUID
    version_number: int
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        reference: VersionedArtifactReference,
    ) -> ArtifactReferencePayload:
        """Convert one versioned domain reference."""
        return cls(
            artifact_id=reference.artifact_id,
            version_number=(reference.version_number),
            content_hash=(reference.content_hash),
        )


class PersonaProfilePayload(ApiModel):
    """Boundary representation of a persona profile."""

    name: str
    source: str
    kind: str
    confirmation_status: str
    rejection_reason: str | None = None
    observations: tuple[
        ProfileObservationPayload,
        ...,
    ]


class PersonaVersionPayload(ApiModel):
    """Immutable persona profile version."""

    id: UUID
    project_id: UUID
    persona_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    profile: PersonaProfilePayload

    @classmethod
    def from_domain(
        cls,
        version: PersonaProfileVersion,
    ) -> PersonaVersionPayload:
        """Convert a persona domain version."""
        profile = version.profile

        return cls(
            id=version.id,
            project_id=version.project_id,
            persona_id=version.persona_id,
            version_number=(version.version_number),
            based_on_version_number=(version.based_on_version_number),
            content_hash=version.content_hash,
            created_by_user_id=(version.created_by_user_id),
            created_at=version.created_at,
            profile=PersonaProfilePayload(
                name=profile.name,
                source=profile.source.value,
                kind=profile.kind.value,
                confirmation_status=(profile.confirmation_status.value),
                rejection_reason=(profile.rejection_reason),
                observations=tuple(
                    ProfileObservationPayload.from_domain(observation)
                    for observation in profile.observations
                ),
            ),
        )


class UserTwinProfilePayload(ApiModel):
    """Inspectable User Twin profile."""

    name: str
    persona_reference: dict[
        str,
        object,
    ]
    project_brief_reference: ArtifactReferencePayload
    agent_team_reference: ArtifactReferencePayload
    catalog_version: int
    catalog_content_hash: str
    validation_status: str
    observations: tuple[
        ProfileObservationPayload,
        ...,
    ]


class UserTwinVersionPayload(ApiModel):
    """Immutable User Twin profile version."""

    id: UUID
    project_id: UUID
    twin_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    profile: UserTwinProfilePayload

    @classmethod
    def from_domain(
        cls,
        version: UserTwinProfileVersion,
    ) -> UserTwinVersionPayload:
        """Convert one User Twin version."""
        profile = version.profile
        persona = profile.persona_reference

        return cls(
            id=version.id,
            project_id=version.project_id,
            twin_id=version.twin_id,
            version_number=(version.version_number),
            based_on_version_number=(version.based_on_version_number),
            content_hash=version.content_hash,
            created_by_user_id=(version.created_by_user_id),
            created_at=version.created_at,
            profile=UserTwinProfilePayload(
                name=profile.name,
                persona_reference={
                    "persona_id": (str(persona.persona_id)),
                    "version_number": (persona.version_number),
                    "content_hash": (persona.content_hash),
                    "source": (persona.source.value),
                    "kind": (persona.kind.value),
                    "confirmation_status": (persona.confirmation_status.value),
                },
                project_brief_reference=(
                    ArtifactReferencePayload.from_domain(profile.project_brief_reference)
                ),
                agent_team_reference=(
                    ArtifactReferencePayload.from_domain(profile.agent_team_reference)
                ),
                catalog_version=(profile.catalog_version),
                catalog_content_hash=(profile.catalog_content_hash),
                validation_status=(profile.validation_status.value),
                observations=tuple(
                    ProfileObservationPayload.from_domain(observation)
                    for observation in profile.observations
                ),
            ),
        )


class UserModelingSnapshotPayload(ApiModel):
    """Authoritative project User Modeling state."""

    project_id: UUID
    project_brief_reference: ArtifactReferencePayload
    agent_team_reference: ArtifactReferencePayload
    catalog_version: int
    catalog_content_hash: str
    persona_count: int
    twin_count: int
    persona_versions: tuple[
        PersonaVersionPayload,
        ...,
    ]
    twin_versions: tuple[
        UserTwinVersionPayload,
        ...,
    ]


class UserModelingSnapshotVersionPayload(ApiModel):
    """Immutable User Modeling snapshot version."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    snapshot: UserModelingSnapshotPayload

    @classmethod
    def from_domain(
        cls,
        version: UserModelingSnapshotVersion,
    ) -> UserModelingSnapshotVersionPayload:
        """Convert one authoritative snapshot."""
        snapshot = version.snapshot

        return cls(
            id=version.id,
            project_id=version.project_id,
            version_number=(version.version_number),
            based_on_version_number=(version.based_on_version_number),
            content_hash=version.content_hash,
            created_by_user_id=(version.created_by_user_id),
            created_at=version.created_at,
            snapshot=(
                UserModelingSnapshotPayload(
                    project_id=(snapshot.project_id),
                    project_brief_reference=(
                        ArtifactReferencePayload.from_domain(snapshot.project_brief_reference)
                    ),
                    agent_team_reference=(
                        ArtifactReferencePayload.from_domain(snapshot.agent_team_reference)
                    ),
                    catalog_version=(snapshot.catalog_version),
                    catalog_content_hash=(snapshot.catalog_content_hash),
                    persona_count=(snapshot.persona_count),
                    twin_count=(snapshot.twin_count),
                    persona_versions=tuple(
                        PersonaVersionPayload.from_domain(persona)
                        for persona in snapshot.persona_versions
                    ),
                    twin_versions=tuple(
                        UserTwinVersionPayload.from_domain(twin) for twin in snapshot.twin_versions
                    ),
                )
            ),
        )


class ProfileDiffOperationPayload(ApiModel):
    """One before/after observation replacement."""

    field: UserTwinField
    before: ProfileObservationPayload | None
    after: ProfileObservationPayload


class UserTwinProfileDiffPayload(ApiModel):
    """Reviewable persisted User Twin profile diff."""

    id: UUID
    project_id: UUID
    base_snapshot_version_id: UUID
    base_snapshot_version_number: int
    base_snapshot_content_hash: str
    twin_id: UUID
    base_twin_version_id: UUID
    base_twin_version_number: int
    base_twin_content_hash: str
    proposal_hash: str
    status: str
    operations: tuple[
        ProfileDiffOperationPayload,
        ...,
    ]
    created_by_user_id: UUID
    created_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_reason: str | None
    applied_snapshot_version_id: UUID | None

    @classmethod
    def from_domain(
        cls,
        diff: UserTwinProfileDiff,
    ) -> UserTwinProfileDiffPayload:
        """Convert one domain diff."""
        return cls(
            id=diff.id,
            project_id=diff.project_id,
            base_snapshot_version_id=(diff.base_snapshot_version_id),
            base_snapshot_version_number=(diff.base_snapshot_version_number),
            base_snapshot_content_hash=(diff.base_snapshot_content_hash),
            twin_id=diff.twin_id,
            base_twin_version_id=(diff.base_twin_version_id),
            base_twin_version_number=(diff.base_twin_version_number),
            base_twin_content_hash=(diff.base_twin_content_hash),
            proposal_hash=diff.proposal_hash,
            status=diff.status.value,
            operations=tuple(
                ProfileDiffOperationPayload(
                    field=operation.field,
                    before=(
                        None
                        if operation.before is None
                        else ProfileObservationPayload.from_domain(operation.before)
                    ),
                    after=(ProfileObservationPayload.from_domain(operation.after)),
                )
                for operation in diff.operations
            ),
            created_by_user_id=(diff.created_by_user_id),
            created_at=diff.created_at,
            decided_by_user_id=(diff.decided_by_user_id),
            decided_at=diff.decided_at,
            decision_reason=(diff.decision_reason),
            applied_snapshot_version_id=(diff.applied_snapshot_version_id),
        )


class GateArtifactPayload(ApiModel):
    """Exact artifact governed by a human gate."""

    project_id: UUID
    gate_type: HumanGateType
    artifact_id: UUID
    version: int
    content_hash: str

    @classmethod
    def from_domain(
        cls,
        artifact: GateArtifactReference,
    ) -> GateArtifactPayload:
        """Convert a gate artifact reference."""
        return cls(
            project_id=artifact.project_id,
            gate_type=artifact.gate_type,
            artifact_id=artifact.artifact_id,
            version=artifact.version,
            content_hash=(artifact.content_hash),
        )


class HumanGatePayload(ApiModel):
    """HTTP representation of Gate 3 state."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    gate_type: HumanGateType
    artifact: GateArtifactPayload
    iteration: int
    max_iterations: int
    status: HumanGateStatus
    created_at: datetime
    updated_at: datetime
    event_sequence: int

    @classmethod
    def from_domain(
        cls,
        gate: HumanGate,
    ) -> HumanGatePayload:
        """Convert one human gate."""
        return cls(
            id=gate.id,
            project_id=gate.project_id,
            owner_user_id=(gate.owner_user_id),
            gate_type=gate.gate_type,
            artifact=(GateArtifactPayload.from_domain(gate.artifact)),
            iteration=gate.iteration,
            max_iterations=(gate.max_iterations),
            status=gate.status,
            created_at=gate.created_at,
            updated_at=gate.updated_at,
            event_sequence=(gate.event_sequence),
        )


class HumanGateEventPayload(ApiModel):
    """Append-only Gate 3 event."""

    id: UUID
    gate_id: UUID
    sequence_number: int
    kind: str
    previous_status: HumanGateStatus
    resulting_status: HumanGateStatus
    artifact: GateArtifactPayload
    occurred_at: datetime
    actor_user_id: UUID | None
    reason: str | None

    @classmethod
    def from_domain(
        cls,
        event: HumanGateEvent,
    ) -> HumanGateEventPayload:
        """Convert one auditable gate event."""
        return cls(
            id=event.id,
            gate_id=event.gate_id,
            sequence_number=(event.sequence_number),
            kind=event.kind.value,
            previous_status=(event.previous_status),
            resulting_status=(event.resulting_status),
            artifact=(GateArtifactPayload.from_domain(event.artifact)),
            occurred_at=event.occurred_at,
            actor_user_id=(event.actor_user_id),
            reason=event.reason,
        )


class PersonaDecisionRequest(ApiModel):
    """Confirm or reject one proto-persona."""

    decision: PersonaOwnerDecision
    reason: str | None = None


class ProfileReplacementRequest(ApiModel):
    """One explicit epistemic User Twin replacement."""

    field: UserTwinField
    value: ObservationValuePayload
    epistemic_status: EpistemicStatus
    confidence: float = Field(
        ge=0.0,
        le=1.0,
    )
    provenance: tuple[
        EvidenceReferencePayload,
        ...,
    ]
    human_validation: HumanValidationRequirement
    rationale: str | None = None

    def to_domain(
        self,
    ) -> ProfileObservation:
        """Create the replacement domain observation."""
        return ProfileObservation(
            observation_key=(self.field.observation_key),
            value=self.value.to_domain(),
            epistemic_status=(self.epistemic_status),
            confidence=ConfidenceScore(self.confidence),
            provenance=(
                ObservationProvenance.from_references(
                    tuple(reference.to_domain() for reference in self.provenance)
                )
            ),
            human_validation=(self.human_validation),
            rationale=self.rationale,
        )


class ProfileRevisionProposalRequest(ApiModel):
    """Request an owner-reviewable User Twin diff."""

    replacements: tuple[
        ProfileReplacementRequest,
        ...,
    ]

    @model_validator(
        mode="after",
    )
    def validate_replacements(
        self,
    ) -> Self:
        """Reject empty and duplicate field replacements."""
        if not self.replacements:
            raise ValueError("at least one profile replacement is required")

        fields = tuple(replacement.field for replacement in self.replacements)

        if len(fields) != len(set(fields)):
            raise ValueError("profile replacement fields must be unique")

        return self

    def to_domain(
        self,
    ) -> Mapping[
        UserTwinField,
        ProfileObservation,
    ]:
        """Create the explicit domain replacement mapping."""
        return {replacement.field: (replacement.to_domain()) for replacement in self.replacements}


class ProfileRevisionDecisionRequest(ApiModel):
    """Approve or reject one proposed profile diff."""

    decision: ProfileRevisionDecision
    reason: str | None = None


class GateDecisionRequest(ApiModel):
    """Apply an owner action to Gate 3."""

    action: HumanGateAction
    reason: str | None = None

    @model_validator(
        mode="after",
    )
    def reject_submit_action(
        self,
    ) -> Self:
        """Keep submission on its dedicated endpoint."""
        if self.action is HumanGateAction.SUBMIT:
            raise ValueError("SUBMIT must use the Gate 3 submission endpoint")

        return self


class PersonaProposalCommandPayload(ApiModel):
    """Result of proposing initial personas."""

    status: str
    issue: str | None
    candidate_issue: str | None
    proposal_issue: str | None
    versions: tuple[
        PersonaVersionPayload,
        ...,
    ]


class PersonaDecisionCommandPayload(ApiModel):
    """Result of one owner persona decision."""

    status: str
    issue: str | None
    decision_issue: str | None
    version: PersonaVersionPayload | None


class SnapshotGenerationCommandPayload(ApiModel):
    """Result of grounded User Twin generation."""

    status: str
    issue: str | None
    proposal_issue: str | None
    snapshot_version: UserModelingSnapshotVersionPayload | None
    twin_versions: tuple[
        UserTwinVersionPayload,
        ...,
    ]


class ProfileRevisionCommandPayload(ApiModel):
    """Result of proposing or deciding a profile revision."""

    status: str
    issue: str | None
    proposal_issue: str | None
    diff: UserTwinProfileDiffPayload | None
    twin_version: UserTwinVersionPayload | None
    snapshot_version: UserModelingSnapshotVersionPayload | None


class GateApiOutcome(StrEnum):
    """API-normalized outcomes supplied by the C13 Gate 3 adapter."""

    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    NOT_FOUND = "NOT_FOUND"
    STALE = "STALE"
    REJECTED = "REJECTED"


@dataclass(
    frozen=True,
    slots=True,
)
class GateApiResult:
    """Small API-facing adapter contract for Gate 3."""

    outcome: GateApiOutcome
    gate: HumanGate | None = None
    events: tuple[
        HumanGateEvent,
        ...,
    ] = ()
    issue: str | None = None


class GateCommandPayload(ApiModel):
    """Normalized Gate 3 command response."""

    outcome: GateApiOutcome
    gate: HumanGatePayload | None
    events: tuple[
        HumanGateEventPayload,
        ...,
    ]
    issue: str | None


class EffectiveTwinLifecyclePayload(ApiModel):
    """Persisted versus effective User Twin lifecycle."""

    twin_id: UUID
    version_number: int
    persisted_status: str
    effective_status: str


class UserModelingReadinessPayload(ApiModel):
    """Readiness for the Requirements/DoD stage."""

    snapshot_exists: bool
    snapshot_version_id: UUID | None
    snapshot_version_number: int | None
    snapshot_content_hash: str | None
    gate_exists: bool
    gate_id: UUID | None
    gate_status: HumanGateStatus | None
    approved_current_snapshot: bool
    workflow_state: str
    twins: tuple[
        EffectiveTwinLifecyclePayload,
        ...,
    ]


class UserModelingCommandPort(Protocol):
    """Application commands exposed by C09."""

    async def propose_personas(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersonaProposalApplicationResult:
        """Propose project personas."""

    async def decide_persona(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        persona_id: UUID,
        decision: PersonaOwnerDecision,
        reason: str | None = None,
    ) -> PersonaDecisionApplicationResult:
        """Apply an owner persona decision."""

    async def generate_grounded_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GroundedSnapshotGenerationResult:
        """Generate project-grounded User Twins."""


class UserTwinRevisionPort(Protocol):
    """Profile revision commands exposed by C10."""

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        twin_id: UUID,
        replacements: Mapping[
            UserTwinField,
            ProfileObservation,
        ],
    ) -> ProfileRevisionApplicationResult:
        """Propose an explicit profile diff."""

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ProfileRevisionDecision,
        reason: str | None = None,
    ) -> ProfileRevisionApplicationResult:
        """Approve or reject one profile diff."""


class UserModelingGateApiPort(Protocol):
    """API-facing Gate 3 command adapter.

    C13 adapts the concrete C11 Gate 3 service to this small boundary.
    """

    async def submit(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GateApiResult:
        """Submit the exact current User Modeling snapshot."""

    async def decide(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> GateApiResult:
        """Apply an owner Gate 3 action."""

    async def current_gate(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> HumanGate | None:
        """Read current Gate 3."""

    async def gate_events(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Read current Gate 3 event history."""


class UserModelingQueryPort(Protocol):
    """Owner-scoped User Modeling read boundary."""

    async def current_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Return the current authoritative snapshot."""

    async def snapshot_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[
        UserModelingSnapshotVersion,
        ...,
    ]:
        """Return immutable snapshot history."""

    async def get_diff(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
    ) -> UserTwinProfileDiff | None:
        """Return one owner-scoped profile diff."""


OwnerUserIdDependency = Callable[
    ...,
    UUID,
]


@dataclass(
    frozen=True,
    slots=True,
)
class UserModelingApiDependencies:
    """Explicit dependencies required by the User Modeling router."""

    commands: UserModelingCommandPort
    revisions: UserTwinRevisionPort
    gates: UserModelingGateApiPort
    queries: UserModelingQueryPort
    owner_user_id_dependency: OwnerUserIdDependency


def create_user_modeling_router(
    dependencies: UserModelingApiDependencies,
) -> APIRouter:
    """Create the User Modeling router without global service state."""
    router = APIRouter(
        prefix=USER_MODELING_API_PREFIX,
        tags=["user-modeling"],
    )

    owner_user_id_dependency = Depends(dependencies.owner_user_id_dependency)

    @router.post(
        "/personas/proposals",
        response_model=(PersonaProposalCommandPayload),
    )
    async def propose_personas(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> PersonaProposalCommandPayload:
        """Propose one-to-four project personas."""
        result = await dependencies.commands.propose_personas(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        _raise_for_user_modeling_issue(result.issue)

        return _persona_proposal_payload(result)

    @router.post(
        "/personas/{persona_id}/decision",
        response_model=(PersonaDecisionCommandPayload),
    )
    async def decide_persona(
        project_id: UUID,
        persona_id: UUID,
        request: PersonaDecisionRequest,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> PersonaDecisionCommandPayload:
        """Confirm or reject one proto-persona."""
        result = await dependencies.commands.decide_persona(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            persona_id=persona_id,
            decision=request.decision,
            reason=request.reason,
        )

        _raise_for_user_modeling_issue(result.issue)

        return _persona_decision_payload(result)

    @router.post(
        "/snapshots/generate",
        response_model=(SnapshotGenerationCommandPayload),
    )
    async def generate_snapshot(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> SnapshotGenerationCommandPayload:
        """Generate project-grounded User Twins and snapshot."""
        result = await dependencies.commands.generate_grounded_snapshot(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        _raise_for_user_modeling_issue(result.issue)

        return _snapshot_generation_payload(result)

    @router.get(
        "/snapshots/current",
        response_model=(UserModelingSnapshotVersionPayload),
    )
    async def current_snapshot(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> UserModelingSnapshotVersionPayload:
        """Return the current authoritative User Modeling snapshot."""
        version = await dependencies.queries.current_snapshot(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        if version is None:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail={"code": ("USER_MODELING_SNAPSHOT_NOT_FOUND")},
            )

        return UserModelingSnapshotVersionPayload.from_domain(version)

    @router.get(
        "/snapshots",
        response_model=tuple[
            UserModelingSnapshotVersionPayload,
            ...,
        ],
    )
    async def snapshot_history(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> tuple[
        UserModelingSnapshotVersionPayload,
        ...,
    ]:
        """Return immutable User Modeling snapshot history."""
        history = await dependencies.queries.snapshot_history(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        return tuple(UserModelingSnapshotVersionPayload.from_domain(version) for version in history)

    @router.post(
        "/twins/{twin_id}/revisions",
        response_model=(ProfileRevisionCommandPayload),
    )
    async def propose_revision(
        project_id: UUID,
        twin_id: UUID,
        request: (ProfileRevisionProposalRequest),
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> ProfileRevisionCommandPayload:
        """Create an owner-reviewable User Twin profile diff."""
        try:
            replacements = request.to_domain()
        except ValueError as error:
            raise HTTPException(
                status_code=(status.HTTP_422_UNPROCESSABLE_CONTENT),
                detail={
                    "code": ("INVALID_PROFILE_REPLACEMENT"),
                    "message": str(error),
                },
            ) from error

        result = await dependencies.revisions.propose_revision(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            twin_id=twin_id,
            replacements=replacements,
        )

        _raise_for_revision_issue(result.issue)

        return _revision_payload(result)

    @router.post(
        "/revisions/{diff_id}/decision",
        response_model=(ProfileRevisionCommandPayload),
    )
    async def decide_revision(
        project_id: UUID,
        diff_id: UUID,
        request: (ProfileRevisionDecisionRequest),
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> ProfileRevisionCommandPayload:
        """Approve or reject one profile diff."""
        result = await dependencies.revisions.decide_revision(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            diff_id=diff_id,
            decision=request.decision,
            reason=request.reason,
        )

        _raise_for_revision_issue(result.issue)

        return _revision_payload(result)

    @router.get(
        "/revisions/{diff_id}",
        response_model=(UserTwinProfileDiffPayload),
    )
    async def get_revision(
        project_id: UUID,
        diff_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> UserTwinProfileDiffPayload:
        """Return one persisted owner-scoped profile diff."""
        diff = await dependencies.queries.get_diff(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            diff_id=diff_id,
        )

        if diff is None:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail={"code": ("PROFILE_DIFF_NOT_FOUND")},
            )

        return UserTwinProfileDiffPayload.from_domain(diff)

    @router.post(
        "/gate/submit",
        response_model=GateCommandPayload,
    )
    async def submit_gate_three(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> GateCommandPayload:
        """Submit the exact current snapshot to Gate 3."""
        result = await dependencies.gates.submit(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        _raise_for_gate_outcome(result)

        return _gate_command_payload(result)

    @router.post(
        "/gate/decision",
        response_model=GateCommandPayload,
    )
    async def decide_gate_three(
        project_id: UUID,
        request: GateDecisionRequest,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> GateCommandPayload:
        """Apply an owner decision to Gate 3."""
        result = await dependencies.gates.decide(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            action=request.action,
            reason=request.reason,
        )

        _raise_for_gate_outcome(result)

        return _gate_command_payload(result)

    @router.get(
        "/gate",
        response_model=HumanGatePayload,
    )
    async def current_gate_three(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> HumanGatePayload:
        """Return the latest owner-scoped Gate 3."""
        gate = await dependencies.gates.current_gate(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        if gate is None:
            raise HTTPException(
                status_code=(status.HTTP_404_NOT_FOUND),
                detail={"code": ("USER_MODELING_GATE_NOT_FOUND")},
            )

        return HumanGatePayload.from_domain(gate)

    @router.get(
        "/gate/events",
        response_model=tuple[
            HumanGateEventPayload,
            ...,
        ],
    )
    async def gate_three_events(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> tuple[
        HumanGateEventPayload,
        ...,
    ]:
        """Return append-only Gate 3 event history."""
        events = await dependencies.gates.gate_events(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        return tuple(HumanGateEventPayload.from_domain(event) for event in events)

    @router.get(
        "/readiness",
        response_model=(UserModelingReadinessPayload),
    )
    async def readiness(
        project_id: UUID,
        owner_user_id: UUID = (owner_user_id_dependency),
    ) -> UserModelingReadinessPayload:
        """Expose effective Gate 3 and User Twin lifecycle state."""
        snapshot = await dependencies.queries.current_snapshot(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        gate = await dependencies.gates.current_gate(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        return _readiness_payload(
            snapshot=snapshot,
            gate=gate,
        )

    return router


def _persona_proposal_payload(
    result: PersonaProposalApplicationResult,
) -> PersonaProposalCommandPayload:
    """Convert a C09 persona proposal result."""
    return PersonaProposalCommandPayload(
        status=result.status.value,
        issue=_enum_value(result.issue),
        candidate_issue=_enum_value(result.candidate_issue),
        proposal_issue=_enum_value(result.proposal_issue),
        versions=tuple(PersonaVersionPayload.from_domain(version) for version in result.versions),
    )


def _persona_decision_payload(
    result: PersonaDecisionApplicationResult,
) -> PersonaDecisionCommandPayload:
    """Convert one C09 persona decision result."""
    return PersonaDecisionCommandPayload(
        status=result.status.value,
        issue=_enum_value(result.issue),
        decision_issue=_enum_value(result.decision_issue),
        version=(
            None if result.version is None else PersonaVersionPayload.from_domain(result.version)
        ),
    )


def _snapshot_generation_payload(
    result: GroundedSnapshotGenerationResult,
) -> SnapshotGenerationCommandPayload:
    """Convert grounded snapshot generation output."""
    return SnapshotGenerationCommandPayload(
        status=result.status.value,
        issue=_enum_value(result.issue),
        proposal_issue=_enum_value(result.proposal_issue),
        snapshot_version=(
            None
            if result.snapshot_version is None
            else UserModelingSnapshotVersionPayload.from_domain(result.snapshot_version)
        ),
        twin_versions=tuple(
            UserTwinVersionPayload.from_domain(version) for version in result.twin_versions
        ),
    )


def _revision_payload(
    result: ProfileRevisionApplicationResult,
) -> ProfileRevisionCommandPayload:
    """Convert a C10 revision result."""
    return ProfileRevisionCommandPayload(
        status=result.status.value,
        issue=_enum_value(result.issue),
        proposal_issue=_enum_value(result.proposal_issue),
        diff=(None if result.diff is None else UserTwinProfileDiffPayload.from_domain(result.diff)),
        twin_version=(
            None
            if result.twin_version is None
            else UserTwinVersionPayload.from_domain(result.twin_version)
        ),
        snapshot_version=(
            None
            if result.snapshot_version is None
            else UserModelingSnapshotVersionPayload.from_domain(result.snapshot_version)
        ),
    )


def _gate_command_payload(
    result: GateApiResult,
) -> GateCommandPayload:
    """Convert the normalized C11 Gate 3 adapter output."""
    return GateCommandPayload(
        outcome=result.outcome,
        gate=(None if result.gate is None else HumanGatePayload.from_domain(result.gate)),
        events=tuple(HumanGateEventPayload.from_domain(event) for event in result.events),
        issue=result.issue,
    )


def _readiness_payload(
    *,
    snapshot: (UserModelingSnapshotVersion | None),
    gate: HumanGate | None,
) -> UserModelingReadinessPayload:
    """Derive HTTP readiness without mutating User Twin profiles."""
    if snapshot is None:
        return UserModelingReadinessPayload(
            snapshot_exists=False,
            snapshot_version_id=None,
            snapshot_version_number=None,
            snapshot_content_hash=None,
            gate_exists=gate is not None,
            gate_id=(None if gate is None else gate.id),
            gate_status=(None if gate is None else gate.status),
            approved_current_snapshot=False,
            workflow_state=("USER_MODELING_REQUIRED"),
            twins=(),
        )

    expected_artifact = GateArtifactReference(
        project_id=snapshot.project_id,
        gate_type=(HumanGateType.USER_MODELING),
        artifact_id=snapshot.id,
        version=snapshot.version_number,
        content_hash=(snapshot.content_hash),
    )

    approved = (
        gate is not None
        and gate.gate_type is HumanGateType.USER_MODELING
        and gate.status is HumanGateStatus.APPROVED
        and gate.artifact == expected_artifact
    )

    owner_approval = (
        UserTwinOwnerApprovalStatus.APPROVED
        if approved
        else UserTwinOwnerApprovalStatus.NOT_APPROVED
    )

    twins = tuple(
        EffectiveTwinLifecyclePayload(
            twin_id=version.twin_id,
            version_number=(version.version_number),
            persisted_status=(version.profile.validation_status.value),
            effective_status=(
                effective_user_twin_lifecycle(
                    version.profile,
                    owner_approval=(owner_approval),
                ).value
            ),
        )
        for version in snapshot.snapshot.twin_versions
    )

    return UserModelingReadinessPayload(
        snapshot_exists=True,
        snapshot_version_id=(snapshot.id),
        snapshot_version_number=(snapshot.version_number),
        snapshot_content_hash=(snapshot.content_hash),
        gate_exists=gate is not None,
        gate_id=(None if gate is None else gate.id),
        gate_status=(None if gate is None else gate.status),
        approved_current_snapshot=(approved),
        workflow_state=(
            "READY_FOR_REQUIREMENTS_DEFINITION" if approved else "USER_MODELING_REVIEW_REQUIRED"
        ),
        twins=twins,
    )


def _raise_for_user_modeling_issue(
    issue: (UserModelingApplicationIssueCode | None),
) -> None:
    """Translate expected C09 failures to HTTP semantics."""
    if issue is None:
        return

    not_found = {
        (UserModelingApplicationIssueCode.PROJECT_NOT_FOUND),
        (UserModelingApplicationIssueCode.PERSONA_NOT_FOUND),
    }

    raise HTTPException(
        status_code=(status.HTTP_404_NOT_FOUND if issue in not_found else status.HTTP_409_CONFLICT),
        detail={
            "code": issue.value,
        },
    )


def _raise_for_revision_issue(
    issue: (ProfileRevisionApplicationIssueCode | None),
) -> None:
    """Translate expected C10 failures to HTTP semantics."""
    if issue is None:
        return

    not_found = {
        (ProfileRevisionApplicationIssueCode.SNAPSHOT_NOT_FOUND),
        (ProfileRevisionApplicationIssueCode.TWIN_NOT_FOUND),
        (ProfileRevisionApplicationIssueCode.DIFF_NOT_FOUND),
    }

    raise HTTPException(
        status_code=(status.HTTP_404_NOT_FOUND if issue in not_found else status.HTTP_409_CONFLICT),
        detail={
            "code": issue.value,
        },
    )


def _raise_for_gate_outcome(
    result: GateApiResult,
) -> None:
    """Translate normalized Gate 3 failures."""
    if result.outcome in {
        GateApiOutcome.APPLIED,
        GateApiOutcome.NO_CHANGE,
    }:
        return

    raise HTTPException(
        status_code=(
            status.HTTP_404_NOT_FOUND
            if result.outcome is GateApiOutcome.NOT_FOUND
            else status.HTTP_409_CONFLICT
        ),
        detail={"code": (result.issue or result.outcome.value)},
    )


def _enum_value(
    value: object | None,
) -> str | None:
    """Return a stable enum value for API responses."""
    if value is None:
        return None

    enum_value = getattr(
        value,
        "value",
        None,
    )

    if isinstance(
        enum_value,
        str,
    ):
        return enum_value

    return str(value)


__all__ = [
    "GateApiOutcome",
    "GateApiResult",
    "UserModelingApiDependencies",
    "UserModelingGateApiPort",
    "UserModelingQueryPort",
    "create_user_modeling_router",
]
