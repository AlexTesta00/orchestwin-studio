"""Application services for User Modeling human approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.twins.lifecycle import (
    UserTwinOwnerApprovalStatus,
    effective_user_twin_lifecycle,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinLifecycleStatus,
    VersionedArtifactReference,
)
from orchestwin.workflow.gate_flow import (
    Clock,
    GateOutcomes,
    UuidFactory,
    current_time,
    decide_current,
    gate_history,
    gate_is_currently_approved,
    latest_gate,
    submit_artifact,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateType,
)
from orchestwin.workflow.repository import (
    HumanGateRepository,
)


@dataclass(frozen=True, slots=True)
class PersonaApprovalReference:
    """Exact PersonaProfileVersion included in a Gate 3 snapshot."""

    persona_id: UUID
    version_id: UUID
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class UserTwinApprovalReference:
    """Exact UserTwinProfileVersion included in a Gate 3 snapshot."""

    twin_id: UUID
    version_id: UUID
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class UserModelingApprovalManifest:
    """Human-readable exact contents governed by Gate 3."""

    project_id: UUID

    snapshot_version_id: UUID
    snapshot_version_number: int
    snapshot_content_hash: str

    project_brief_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference

    persona_versions: tuple[
        PersonaApprovalReference,
        ...,
    ]
    twin_versions: tuple[
        UserTwinApprovalReference,
        ...,
    ]


@dataclass(frozen=True, slots=True)
class EffectiveUserTwinApprovalState:
    """Effective lifecycle of one twin under the current Gate 3."""

    twin_id: UUID
    twin_version_id: UUID
    twin_version_number: int
    persisted_status: UserTwinLifecycleStatus
    effective_status: UserTwinLifecycleStatus


@dataclass(frozen=True, slots=True)
class UserModelingApprovalState:
    """Current Gate 3 approval state for one exact snapshot."""

    manifest: UserModelingApprovalManifest
    approved: bool
    twins: tuple[
        EffectiveUserTwinApprovalState,
        ...,
    ]


class CurrentUserModelingSnapshotRepository(Protocol):
    """Repository port for locking the current owned User Modeling snapshot."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Lock project scope and return the current modeling snapshot."""


class UserModelingGateUnitOfWork(Protocol):
    """Transactional boundary for Gate 3 use cases."""

    @property
    def current_snapshots(
        self,
    ) -> CurrentUserModelingSnapshotRepository:
        """Return the current User Modeling snapshot repository."""

    @property
    def gates(
        self,
    ) -> HumanGateRepository:
        """Return the shared human-gate repository."""

    async def __aenter__(
        self,
    ) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: (type[BaseException] | None),
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


UserModelingGateUnitOfWorkFactory = Callable[
    [],
    UserModelingGateUnitOfWork,
]


class UserModelingGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 3."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"

    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    NEW_SNAPSHOT_REQUIRED = "NEW_SNAPSHOT_REQUIRED"

    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class UserModelingGateDecisionStatus(StrEnum):
    """Stable outcomes of a Gate 3 owner decision."""

    APPLIED = "APPLIED"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class UserModelingGateSubmissionResult:
    """Typed result of submitting the current modeling snapshot."""

    status: UserModelingGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[
        HumanGateEvent,
        ...,
    ] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class UserModelingGateDecisionResult:
    """Typed result of applying an owner decision to Gate 3."""

    status: UserModelingGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""
    return datetime.now(UTC)


def user_modeling_artifact_reference(
    version: UserModelingSnapshotVersion,
) -> GateArtifactReference:
    """Create the exact Gate 3 artifact reference."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=(HumanGateType.USER_MODELING),
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def user_modeling_gate_is_currently_approved(
    gate: HumanGate | None,
    version: (UserModelingSnapshotVersion | None),
) -> bool:
    """Return whether Gate 3 approves the exact current snapshot."""
    return gate_is_currently_approved(gate, version, user_modeling_artifact_reference)


def user_modeling_approval_manifest(
    version: UserModelingSnapshotVersion,
) -> UserModelingApprovalManifest:
    """Expose every exact version governed by Gate 3."""
    snapshot = version.snapshot

    persona_versions = tuple(
        PersonaApprovalReference(
            persona_id=(persona.persona_id),
            version_id=persona.id,
            version_number=(persona.version_number),
            content_hash=(persona.content_hash),
        )
        for persona in snapshot.persona_versions
    )

    twin_versions = tuple(
        UserTwinApprovalReference(
            twin_id=twin.twin_id,
            version_id=twin.id,
            version_number=(twin.version_number),
            content_hash=(twin.content_hash),
        )
        for twin in snapshot.twin_versions
    )

    return UserModelingApprovalManifest(
        project_id=version.project_id,
        snapshot_version_id=version.id,
        snapshot_version_number=(version.version_number),
        snapshot_content_hash=(version.content_hash),
        project_brief_reference=(snapshot.project_brief_reference),
        agent_team_reference=(snapshot.agent_team_reference),
        persona_versions=(persona_versions),
        twin_versions=(twin_versions),
    )


def user_modeling_approval_state(
    *,
    version: UserModelingSnapshotVersion,
    gate: HumanGate | None,
) -> UserModelingApprovalState:
    """Derive owner-approved twin lifecycle without mutating profiles."""
    approved = user_modeling_gate_is_currently_approved(
        gate,
        version,
    )

    owner_approval = (
        UserTwinOwnerApprovalStatus.APPROVED
        if approved
        else UserTwinOwnerApprovalStatus.NOT_APPROVED
    )

    twins = tuple(
        EffectiveUserTwinApprovalState(
            twin_id=twin.twin_id,
            twin_version_id=twin.id,
            twin_version_number=(twin.version_number),
            persisted_status=(twin.profile.validation_status),
            effective_status=(
                effective_user_twin_lifecycle(
                    twin.profile,
                    owner_approval=(owner_approval),
                )
            ),
        )
        for twin in version.snapshot.twin_versions
    )

    return UserModelingApprovalState(
        manifest=(user_modeling_approval_manifest(version)),
        approved=approved,
        twins=twins,
    )


_OUTCOMES = GateOutcomes(
    submission=UserModelingGateSubmissionResult,
    submission_status=UserModelingGateSubmissionStatus,
    new_artifact_required=UserModelingGateSubmissionStatus.NEW_SNAPSHOT_REQUIRED,
    decision=UserModelingGateDecisionResult,
    decision_status=UserModelingGateDecisionStatus,
)


class LocalUserModelingGateService:
    """Gate 3 approval use cases composed from explicit ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: (UserModelingGateUnitOfWorkFactory),
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        """Configure Gate 3 application dependencies."""
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> UserModelingGateSubmissionResult:
        """Submit the exact current User Modeling snapshot."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            version = await unit.current_snapshots.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if version is None:
                return UserModelingGateSubmissionResult(
                    status=(UserModelingGateSubmissionStatus.SNAPSHOT_NOT_FOUND)
                )

            return await submit_artifact(
                unit.gates,
                user_modeling_artifact_reference(version),
                project_id=project_id,
                owner_user_id=owner_user_id,
                occurred_at=timestamp,
                gate_id_factory=self._gate_id_factory,
                event_id_factory=self._event_id_factory,
                outcomes=_OUTCOMES,
            )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> UserModelingGateDecisionResult:
        """Apply one owner decision to the exact current Gate 3."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            version = await unit.current_snapshots.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if version is None:
                return UserModelingGateDecisionResult(
                    status=(UserModelingGateDecisionStatus.SNAPSHOT_NOT_FOUND)
                )

            return await decide_current(
                unit.gates,
                user_modeling_artifact_reference(version),
                project_id=project_id,
                owner_user_id=owner_user_id,
                action=action,
                reason=reason,
                occurred_at=timestamp,
                event_id_factory=self._event_id_factory,
                outcomes=_OUTCOMES,
            )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest owner-scoped Gate 3."""
        return await latest_gate(
            self._unit_of_work_factory(),
            HumanGateType.USER_MODELING,
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[
        HumanGateEvent,
        ...,
    ]:
        """Return append-only owner-scoped Gate 3 history."""
        return await gate_history(
            self._unit_of_work_factory(),
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_id=gate_id,
        )

    def _current_time(
        self,
    ) -> datetime:
        """Return and validate the injected application clock."""
        return current_time(self._clock, "User Modeling gate clock must be timezone-aware")
