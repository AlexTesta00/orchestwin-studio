"""Application services for governed User Modeling generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
)
from orchestwin.models.user_modeling import (
    PersonaProposalRequest,
    ProposedPersonaProfile,
    ProposedUserTwinProfile,
    UserModelingProposalIssueCode,
    UserModelingProposalPort,
    UserModelingProposalStatus,
    UserTwinProposalRequest,
)
from orchestwin.projects.brief_gate import (
    project_brief_gate_is_currently_approved,
)
from orchestwin.projects.briefs import (
    ProjectBriefVersion,
)
from orchestwin.twins.persistence.repositories import (
    VersionAppendStatus,
)
from orchestwin.twins.persistence.uow import (
    UserModelingUnitOfWork,
)
from orchestwin.twins.persona_candidates import (
    PersonaCandidateDerivationStatus,
    PersonaCandidateIssueCode,
    ProjectPersonaCandidate,
    derive_project_persona_candidates,
)
from orchestwin.twins.personas import (
    PersonaConfirmationStatus,
    PersonaDecisionIssueCode,
    PersonaDecisionStatus,
    PersonaField,
    PersonaProfileVersion,
    confirm_proto_persona,
    reject_proto_persona,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    UserTwinProfileVersion,
    VersionedArtifactReference,
    create_user_modeling_snapshot,
)
from orchestwin.workflow.gates import (
    HumanGate,
)


class UserModelingApplicationStatus(StrEnum):
    """Stable high-level outcomes of User Modeling commands."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class UserModelingApplicationIssueCode(StrEnum):
    """Expected application-level reasons an operation cannot continue."""

    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    BRIEF_APPROVAL_REQUIRED = "BRIEF_APPROVAL_REQUIRED"
    TEAM_PROPOSAL_REQUIRED = "TEAM_PROPOSAL_REQUIRED"
    TEAM_APPROVAL_REQUIRED = "TEAM_APPROVAL_REQUIRED"

    PERSONAS_ALREADY_EXIST = "PERSONAS_ALREADY_EXIST"
    CANDIDATE_DERIVATION_REJECTED = "CANDIDATE_DERIVATION_REJECTED"
    PROPOSAL_REJECTED = "PROPOSAL_REJECTED"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"

    PERSONA_NOT_FOUND = "PERSONA_NOT_FOUND"
    PERSONA_DECISION_REJECTED = "PERSONA_DECISION_REJECTED"
    PERSONAS_REQUIRED = "PERSONAS_REQUIRED"
    PERSONA_CONFIRMATION_REQUIRED = "PERSONA_CONFIRMATION_REQUIRED"

    SNAPSHOT_ALREADY_EXISTS = "SNAPSHOT_ALREADY_EXISTS"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class PersonaOwnerDecision(StrEnum):
    """Initial owner decision for a system-proposed proto-persona."""

    CONFIRM = "CONFIRM"
    REJECT = "REJECT"


@dataclass(
    frozen=True,
    slots=True,
)
class UserModelingContextFingerprint:
    """Stable fingerprint of the governed inputs used for generation."""

    brief_version_id: UUID
    brief_version_number: int
    brief_content_hash: str

    team_reference: VersionedArtifactReference | None
    approved_team_reference: VersionedArtifactReference | None

    catalog_version: int | None
    catalog_content_hash: str | None


@dataclass(
    frozen=True,
    slots=True,
)
class GovernedUserModelingContext:
    """Current governed inputs required by User Modeling."""

    project_id: UUID

    brief_version: ProjectBriefVersion
    brief_gate: HumanGate

    team_reference: VersionedArtifactReference | None
    approved_team_reference: VersionedArtifactReference | None

    catalog_version: int | None
    catalog_content_hash: str | None

    def __post_init__(self) -> None:
        """Protect basic consistency of the supplied context."""
        if self.brief_version.project_id != self.project_id:
            raise ValueError("User Modeling brief must belong to the context project")

        if self.team_reference is None:
            if (
                self.approved_team_reference is not None
                or self.catalog_version is not None
                or self.catalog_content_hash is not None
            ):
                raise ValueError("missing team context cannot contain approval or catalog metadata")

            return

        if self.catalog_version is None or self.catalog_content_hash is None:
            raise ValueError("team context requires catalog version and hash")

        if (
            isinstance(
                self.catalog_version,
                bool,
            )
            or self.catalog_version < 1
        ):
            raise ValueError("catalog version must be positive")

        if not _is_sha256_digest(self.catalog_content_hash):
            raise ValueError("catalog content hash must be a lowercase SHA-256 digest")

    @property
    def brief_reference(
        self,
    ) -> VersionedArtifactReference:
        """Return the exact Project Brief reference."""
        return VersionedArtifactReference(
            artifact_id=(self.brief_version.id),
            version_number=(self.brief_version.version_number),
            content_hash=(self.brief_version.content_hash),
        )

    @property
    def fingerprint(
        self,
    ) -> UserModelingContextFingerprint:
        """Return the context identity used for stale-result checks."""
        return UserModelingContextFingerprint(
            brief_version_id=(self.brief_version.id),
            brief_version_number=(self.brief_version.version_number),
            brief_content_hash=(self.brief_version.content_hash),
            team_reference=(self.team_reference),
            approved_team_reference=(self.approved_team_reference),
            catalog_version=(self.catalog_version),
            catalog_content_hash=(self.catalog_content_hash),
        )


class UserModelingGovernancePort(Protocol):
    """Owner-scoped boundary exposing the current governed project state."""

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedUserModelingContext | None:
        """Load the latest Brief, Gate 1, team, Gate 2, and catalog."""


class UserModelingUnitOfWorkFactory(Protocol):
    """Create one owner-scoped User Modeling Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> UserModelingUnitOfWork:
        """Create a transactional boundary."""


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaProposalApplicationResult:
    """Result of generating and persisting initial proto-personas."""

    status: UserModelingApplicationStatus

    versions: tuple[
        PersonaProfileVersion,
        ...,
    ] = ()

    issue: UserModelingApplicationIssueCode | None = None

    candidate_issue: PersonaCandidateIssueCode | None = None

    proposal_issue: UserModelingProposalIssueCode | None = None

    persistence_status: VersionAppendStatus | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class PersonaDecisionApplicationResult:
    """Result of applying an initial owner persona decision."""

    status: UserModelingApplicationStatus

    version: PersonaProfileVersion | None = None

    issue: UserModelingApplicationIssueCode | None = None

    decision_issue: PersonaDecisionIssueCode | None = None

    persistence_status: VersionAppendStatus | None = None


@dataclass(
    frozen=True,
    slots=True,
)
class GroundedSnapshotGenerationResult:
    """Result of creating project-grounded User Twins and their snapshot."""

    status: UserModelingApplicationStatus

    snapshot_version: UserModelingSnapshotVersion | None = None

    twin_versions: tuple[
        UserTwinProfileVersion,
        ...,
    ] = ()

    issue: UserModelingApplicationIssueCode | None = None

    proposal_issue: UserModelingProposalIssueCode | None = None

    persistence_status: VersionAppendStatus | None = None


class LocalUserModelingApplicationService:
    """Coordinate governed proposal, confirmation, and snapshot creation."""

    def __init__(
        self,
        *,
        governance: UserModelingGovernancePort,
        proposals: UserModelingProposalPort,
        uow_factory: UserModelingUnitOfWorkFactory,
        uuid_factory: Callable[
            [],
            UUID,
        ] = uuid4,
        clock: Callable[
            [],
            datetime,
        ]
        | None = None,
    ) -> None:
        """Configure explicit application dependencies."""
        self._governance = governance
        self._proposals = proposals
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock if clock is not None else _utc_now

    async def propose_personas(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersonaProposalApplicationResult:
        """Generate initial proto-personas from the current governed Brief."""
        context = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        governance_issue = _governance_issue(context)

        if governance_issue is not None:
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=governance_issue,
            )

        if context is None:
            raise RuntimeError("ready governance context cannot be None")

        if await self._project_has_personas(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        ):
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.PERSONAS_ALREADY_EXIST),
            )

        candidate_result = derive_project_persona_candidates(
            brief_version=(context.brief_version),
            brief_gate=(context.brief_gate),
        )

        if candidate_result.status is not PersonaCandidateDerivationStatus.DERIVED:
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.CANDIDATE_DERIVATION_REJECTED),
                candidate_issue=(candidate_result.issue),
            )

        proposal_result = await self._proposals.propose_personas(
            PersonaProposalRequest(
                project_id=project_id,
                candidates=(candidate_result.candidates),
            )
        )

        if proposal_result.status is not UserModelingProposalStatus.PROPOSED:
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.PROPOSAL_REJECTED),
                proposal_issue=(proposal_result.issue),
            )

        if not _persona_proposals_match_candidates(
            candidates=(candidate_result.candidates),
            proposals=(proposal_result.proposals),
        ):
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.INVALID_PROPOSAL),
            )

        if not await self._context_is_unchanged(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            previous=context,
        ):
            return PersonaProposalApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.CONTEXT_CHANGED),
            )

        async with self._uow_factory(owner_user_id=(owner_user_id)) as uow:
            existing = await uow.personas.list_current(project_id=(project_id))

            if existing:
                return PersonaProposalApplicationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.PERSONAS_ALREADY_EXIST),
                )

            created_at = _aware_timestamp(self._clock())

            versions = tuple(
                self._initial_persona_version(
                    project_id=project_id,
                    owner_user_id=(owner_user_id),
                    proposal=proposal,
                    created_at=created_at,
                )
                for proposal in proposal_result.proposals
            )

            for version in versions:
                append_status = await uow.personas.append(version)

                if append_status is not VersionAppendStatus.APPENDED:
                    return PersonaProposalApplicationResult(
                        status=(UserModelingApplicationStatus.REJECTED),
                        issue=(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED),
                        persistence_status=(append_status),
                    )

            await uow.commit()

        return PersonaProposalApplicationResult(
            status=(UserModelingApplicationStatus.CREATED),
            versions=versions,
        )

    async def decide_persona(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        persona_id: UUID,
        decision: PersonaOwnerDecision,
        reason: str | None = None,
    ) -> PersonaDecisionApplicationResult:
        """Confirm or reject one pending proto-persona immutably."""
        context = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        governance_issue = _governance_issue(context)

        if governance_issue is not None:
            return PersonaDecisionApplicationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=governance_issue,
            )

        async with self._uow_factory(owner_user_id=(owner_user_id)) as uow:
            current = await uow.personas.current(
                project_id=project_id,
                persona_id=persona_id,
            )

            if current is None:
                return PersonaDecisionApplicationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.PERSONA_NOT_FOUND),
                )

            if decision is PersonaOwnerDecision.CONFIRM:
                domain_result = confirm_proto_persona(current.profile)
            else:
                domain_result = reject_proto_persona(
                    current.profile,
                    reason=(reason if reason is not None else ""),
                )

            if domain_result.status is PersonaDecisionStatus.REJECTED:
                return PersonaDecisionApplicationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    version=current,
                    issue=(UserModelingApplicationIssueCode.PERSONA_DECISION_REJECTED),
                    decision_issue=(domain_result.issue),
                )

            if domain_result.status is PersonaDecisionStatus.NO_CHANGE:
                return PersonaDecisionApplicationResult(
                    status=(UserModelingApplicationStatus.NO_CHANGE),
                    version=current,
                )

            next_version = PersonaProfileVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                persona_id=(current.persona_id),
                version_number=(current.version_number + 1),
                based_on_version_number=(current.version_number),
                profile=(domain_result.profile),
                content_hash=(domain_result.profile.content_hash),
                created_by_user_id=(owner_user_id),
                created_at=(_aware_timestamp(self._clock())),
            )

            append_status = await uow.personas.append(next_version)

            if append_status is not VersionAppendStatus.APPENDED:
                return PersonaDecisionApplicationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED),
                    persistence_status=(append_status),
                )

            await uow.commit()

        return PersonaDecisionApplicationResult(
            status=(UserModelingApplicationStatus.APPLIED),
            version=next_version,
        )

    async def generate_grounded_snapshot(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GroundedSnapshotGenerationResult:
        """Generate User Twins only from decided personas and current Gate 2."""
        context = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        governance_issue = _governance_issue(context)

        if governance_issue is not None:
            return GroundedSnapshotGenerationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=governance_issue,
            )

        if context is None:
            raise RuntimeError("ready governance context cannot be None")

        team_reference = _require_team_reference(context)

        async with self._uow_factory(owner_user_id=(owner_user_id)) as uow:
            current_snapshot = await uow.snapshots.current(project_id=project_id)

            if current_snapshot is not None:
                return GroundedSnapshotGenerationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.SNAPSHOT_ALREADY_EXISTS),
                )

            persona_versions = await uow.personas.list_current(project_id=(project_id))

        (
            persona_issue,
            confirmed_personas,
        ) = _select_confirmed_personas(persona_versions)

        if persona_issue is not None:
            return GroundedSnapshotGenerationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=persona_issue,
            )

        persona_fingerprint = _persona_set_fingerprint(persona_versions)

        proposal_result = await self._proposals.propose_user_twins(
            UserTwinProposalRequest(
                project_id=project_id,
                persona_versions=(confirmed_personas),
                project_brief_reference=(context.brief_reference),
                agent_team_reference=(team_reference),
                catalog_version=(_require_catalog_version(context)),
                catalog_content_hash=(_require_catalog_hash(context)),
            )
        )

        if proposal_result.status is not UserModelingProposalStatus.PROPOSED:
            return GroundedSnapshotGenerationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.PROPOSAL_REJECTED),
                proposal_issue=(proposal_result.issue),
            )

        if not _twin_proposals_match_personas(
            personas=(confirmed_personas),
            proposals=(proposal_result.proposals),
            context=context,
        ):
            return GroundedSnapshotGenerationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.INVALID_PROPOSAL),
            )

        if not await self._context_is_unchanged(
            owner_user_id=(owner_user_id),
            project_id=project_id,
            previous=context,
        ):
            return GroundedSnapshotGenerationResult(
                status=(UserModelingApplicationStatus.REJECTED),
                issue=(UserModelingApplicationIssueCode.CONTEXT_CHANGED),
            )

        async with self._uow_factory(owner_user_id=(owner_user_id)) as uow:
            current_snapshot = await uow.snapshots.current(project_id=project_id)

            if current_snapshot is not None:
                return GroundedSnapshotGenerationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.CONTEXT_CHANGED),
                )

            refreshed_personas = await uow.personas.list_current(project_id=(project_id))

            if _persona_set_fingerprint(refreshed_personas) != persona_fingerprint:
                return GroundedSnapshotGenerationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.CONTEXT_CHANGED),
                )

            (
                refreshed_issue,
                refreshed_confirmed,
            ) = _select_confirmed_personas(refreshed_personas)

            if refreshed_issue is not None:
                return GroundedSnapshotGenerationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.CONTEXT_CHANGED),
                )

            created_at = _aware_timestamp(self._clock())

            twin_versions = tuple(
                self._initial_twin_version(
                    project_id=project_id,
                    owner_user_id=(owner_user_id),
                    proposal=proposal,
                    created_at=created_at,
                )
                for proposal in proposal_result.proposals
            )

            for twin_version in twin_versions:
                append_status = await uow.twins.append(twin_version)

                if append_status is not VersionAppendStatus.APPENDED:
                    return GroundedSnapshotGenerationResult(
                        status=(UserModelingApplicationStatus.REJECTED),
                        issue=(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED),
                        persistence_status=(append_status),
                    )

            snapshot = create_user_modeling_snapshot(
                project_id=project_id,
                project_brief_reference=(context.brief_reference),
                agent_team_reference=(team_reference),
                catalog_version=(_require_catalog_version(context)),
                catalog_content_hash=(_require_catalog_hash(context)),
                persona_versions=(refreshed_confirmed),
                twin_versions=(twin_versions),
            )

            snapshot_version = UserModelingSnapshotVersion(
                id=self._uuid_factory(),
                project_id=project_id,
                version_number=1,
                based_on_version_number=None,
                snapshot=snapshot,
                content_hash=(snapshot.content_hash),
                created_by_user_id=(owner_user_id),
                created_at=created_at,
            )

            snapshot_append_status = await uow.snapshots.append(snapshot_version)

            if snapshot_append_status is not VersionAppendStatus.APPENDED:
                return GroundedSnapshotGenerationResult(
                    status=(UserModelingApplicationStatus.REJECTED),
                    issue=(UserModelingApplicationIssueCode.PERSISTENCE_REJECTED),
                    persistence_status=(snapshot_append_status),
                )

            await uow.commit()

        return GroundedSnapshotGenerationResult(
            status=(UserModelingApplicationStatus.CREATED),
            snapshot_version=(snapshot_version),
            twin_versions=(twin_versions),
        )

    async def _project_has_personas(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> bool:
        """Check persona existence without holding a provider-call transaction."""
        async with self._uow_factory(owner_user_id=(owner_user_id)) as uow:
            versions = await uow.personas.list_current(project_id=project_id)

        return bool(versions)

    async def _context_is_unchanged(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        previous: GovernedUserModelingContext,
    ) -> bool:
        """Reject provider output when governed inputs changed in flight."""
        current = await self._governance.load_current(
            owner_user_id=(owner_user_id),
            project_id=project_id,
        )

        return (
            current is not None
            and _governance_issue(current) is None
            and current.fingerprint == previous.fingerprint
        )

    def _initial_persona_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        proposal: ProposedPersonaProfile,
        created_at: datetime,
    ) -> PersonaProfileVersion:
        """Assign stable identity to one initial proposed persona."""
        persona_id = self._uuid_factory()

        return PersonaProfileVersion(
            id=self._uuid_factory(),
            project_id=project_id,
            persona_id=persona_id,
            version_number=1,
            based_on_version_number=None,
            profile=proposal.profile,
            content_hash=(proposal.profile.content_hash),
            created_by_user_id=(owner_user_id),
            created_at=created_at,
        )

    def _initial_twin_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        proposal: ProposedUserTwinProfile,
        created_at: datetime,
    ) -> UserTwinProfileVersion:
        """Assign stable identity to one initial grounded User Twin."""
        twin_id = self._uuid_factory()

        return UserTwinProfileVersion(
            id=self._uuid_factory(),
            project_id=project_id,
            twin_id=twin_id,
            version_number=1,
            based_on_version_number=None,
            profile=proposal.profile,
            content_hash=(proposal.profile.content_hash),
            created_by_user_id=(owner_user_id),
            created_at=created_at,
        )


def _governance_issue(
    context: (GovernedUserModelingContext | None),
) -> UserModelingApplicationIssueCode | None:
    """Return the first governance blocker for User Modeling."""
    if context is None:
        return UserModelingApplicationIssueCode.PROJECT_NOT_FOUND

    if not (
        project_brief_gate_is_currently_approved(
            context.brief_gate,
            context.brief_version,
        )
    ):
        return UserModelingApplicationIssueCode.BRIEF_APPROVAL_REQUIRED

    if context.team_reference is None:
        return UserModelingApplicationIssueCode.TEAM_PROPOSAL_REQUIRED

    if context.approved_team_reference != context.team_reference:
        return UserModelingApplicationIssueCode.TEAM_APPROVAL_REQUIRED

    if (
        context.catalog_version != AGENT_CATALOG_VERSION
        or context.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
    ):
        return UserModelingApplicationIssueCode.TEAM_APPROVAL_REQUIRED

    return None


def _persona_proposals_match_candidates(
    *,
    candidates: tuple[
        ProjectPersonaCandidate,
        ...,
    ],
    proposals: tuple[
        ProposedPersonaProfile,
        ...,
    ],
) -> bool:
    """Validate exact candidate coverage without trusting provider output."""
    if len(candidates) != len(proposals):
        return False

    for (
        candidate,
        proposal,
    ) in zip(
        candidates,
        proposals,
        strict=True,
    ):
        if (
            proposal.candidate_ordinal != candidate.ordinal
            or proposal.candidate_content_hash != candidate.content_hash
        ):
            return False

        role = proposal.profile.observation_for(PersonaField.ROLE)

        if role != candidate.role_observation:
            return False

    return True


def _twin_proposals_match_personas(
    *,
    personas: tuple[
        PersonaProfileVersion,
        ...,
    ],
    proposals: tuple[
        ProposedUserTwinProfile,
        ...,
    ],
    context: GovernedUserModelingContext,
) -> bool:
    """Validate complete one-to-one twin coverage and exact grounding."""
    if len(personas) != len(proposals):
        return False

    team_reference = context.team_reference

    if team_reference is None:
        return False

    expected = {
        persona.persona_id: (
            persona.version_number,
            persona.content_hash,
        )
        for persona in personas
    }

    seen: set[UUID] = set()

    for proposal in proposals:
        if proposal.persona_id in seen:
            return False

        expected_persona = expected.get(proposal.persona_id)

        if expected_persona is None:
            return False

        if expected_persona != (
            proposal.persona_version_number,
            proposal.persona_content_hash,
        ):
            return False

        profile = proposal.profile

        if (
            profile.project_brief_reference != context.brief_reference
            or profile.agent_team_reference != team_reference
            or profile.catalog_version != context.catalog_version
            or profile.catalog_content_hash != context.catalog_content_hash
            or profile.validation_status is not UserTwinLifecycleStatus.PROJECT_GROUNDED_UT
        ):
            return False

        seen.add(proposal.persona_id)

    return seen == set(expected)


def _select_confirmed_personas(
    versions: tuple[
        PersonaProfileVersion,
        ...,
    ],
) -> tuple[
    UserModelingApplicationIssueCode | None,
    tuple[
        PersonaProfileVersion,
        ...,
    ],
]:
    """Exclude rejected personas while requiring decisions on all others."""
    if not versions:
        return (
            UserModelingApplicationIssueCode.PERSONAS_REQUIRED,
            (),
        )

    if any(
        version.profile.confirmation_status is PersonaConfirmationStatus.PENDING_CONFIRMATION
        for version in versions
    ):
        return (
            UserModelingApplicationIssueCode.PERSONA_CONFIRMATION_REQUIRED,
            (),
        )

    confirmed = tuple(
        version
        for version in versions
        if (version.profile.confirmation_status is PersonaConfirmationStatus.CONFIRMED)
    )

    if not confirmed:
        return (
            UserModelingApplicationIssueCode.PERSONAS_REQUIRED,
            (),
        )

    return (
        None,
        confirmed,
    )


def _persona_set_fingerprint(
    versions: tuple[
        PersonaProfileVersion,
        ...,
    ],
) -> tuple[
    tuple[
        UUID,
        UUID,
        int,
        str,
    ],
    ...,
]:
    """Fingerprint current persona revisions for provider stale checks."""
    return tuple(
        (
            version.id,
            version.persona_id,
            version.version_number,
            version.content_hash,
        )
        for version in versions
    )


def _require_team_reference(
    context: GovernedUserModelingContext,
) -> VersionedArtifactReference:
    """Return a ready team reference or expose an internal contract breach."""
    if context.team_reference is None:
        raise RuntimeError("ready User Modeling context requires a team reference")

    return context.team_reference


def _require_catalog_version(
    context: GovernedUserModelingContext,
) -> int:
    """Return ready catalog version metadata."""
    if context.catalog_version is None:
        raise RuntimeError("ready User Modeling context requires a catalog version")

    return context.catalog_version


def _require_catalog_hash(
    context: GovernedUserModelingContext,
) -> str:
    """Return ready catalog hash metadata."""
    if context.catalog_content_hash is None:
        raise RuntimeError("ready User Modeling context requires a catalog hash")

    return context.catalog_content_hash


def _aware_timestamp(
    value: datetime,
) -> datetime:
    """Require application clocks to return timezone-aware values."""
    if value.utcoffset() is None:
        raise ValueError("User Modeling clock must return timezone-aware timestamps")

    return value


def _is_sha256_digest(
    value: str,
) -> bool:
    """Return whether text is a lowercase SHA-256 digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _utc_now() -> datetime:
    """Return the current UTC timestamp."""
    return datetime.now(UTC)
