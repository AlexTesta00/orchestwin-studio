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
from orchestwin.workflow.gates import (
    DEFAULT_GATE_ITERATION_LIMIT,
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    mark_human_gate_stale,
    transition_human_gate,
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


class UserModelingGateService(Protocol):
    """Use cases exposed to the future Gate 3 API adapter."""

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> UserModelingGateSubmissionResult:
        """Submit the current User Modeling snapshot."""

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> UserModelingGateDecisionResult:
        """Apply an owner decision to Gate 3."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest Gate 3."""

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
        """Return the owner-scoped Gate 3 history."""


Clock = Callable[
    [],
    datetime,
]
UuidFactory = Callable[
    [],
    UUID,
]


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
    if gate is None or version is None:
        return False

    return (
        gate.status is HumanGateStatus.APPROVED
        and gate.artifact == user_modeling_artifact_reference(version)
    )


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

            artifact = user_modeling_artifact_reference(version)

            latest = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.USER_MODELING),
            )

            if latest is not None and latest.artifact == artifact:
                return await self._submit_existing(
                    unit=unit,
                    gate=latest,
                    owner_user_id=(owner_user_id),
                    occurred_at=timestamp,
                )

            stale_events: list[HumanGateEvent] = []

            if latest is not None:
                if latest.status in {
                    HumanGateStatus.CANCELLED,
                    HumanGateStatus.PAUSED_NEEDS_HUMAN,
                }:
                    return UserModelingGateSubmissionResult(
                        status=(UserModelingGateSubmissionStatus.GATE_BLOCKED),
                        gate=latest,
                    )

                if latest.status is not HumanGateStatus.STALE:
                    stale_result = mark_human_gate_stale(
                        latest,
                        current_artifact=(artifact),
                        occurred_at=(timestamp),
                        event_id=(self._event_id_factory()),
                    )

                    if stale_result.status is HumanGateTransitionStatus.REJECTED:
                        return UserModelingGateSubmissionResult(
                            status=(UserModelingGateSubmissionStatus.TRANSITION_REJECTED),
                            gate=latest,
                            issue=(stale_result.issue),
                        )

                    if (
                        stale_result.status is HumanGateTransitionStatus.APPLIED
                        and stale_result.event is not None
                    ):
                        await unit.gates.save_transition(
                            previous_gate=(latest),
                            updated_gate=(stale_result.gate),
                            event=(stale_result.event),
                        )

                        stale_events.append(stale_result.event)
                        latest = stale_result.gate

                next_iteration = latest.iteration + 1
                max_iterations = latest.max_iterations

                if next_iteration > max_iterations:
                    return UserModelingGateSubmissionResult(
                        status=(UserModelingGateSubmissionStatus.ITERATION_LIMIT_REACHED),
                        gate=latest,
                        events=tuple(stale_events),
                    )
            else:
                next_iteration = 1
                max_iterations = DEFAULT_GATE_ITERATION_LIMIT

            draft = create_human_gate(
                gate_id=(self._gate_id_factory()),
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.USER_MODELING),
                artifact=artifact,
                iteration=next_iteration,
                max_iterations=(max_iterations),
                created_at=timestamp,
            )

            submitted = transition_human_gate(
                draft,
                action=(HumanGateAction.SUBMIT),
                actor_user_id=(owner_user_id),
                occurred_at=(timestamp),
                event_id=(self._event_id_factory()),
            )

            if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
                return UserModelingGateSubmissionResult(
                    status=(UserModelingGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=draft,
                    events=tuple(stale_events),
                    issue=submitted.issue,
                )

            persisted = await unit.gates.add_with_event(
                gate=submitted.gate,
                event=submitted.event,
            )

            all_events = (
                *stale_events,
                submitted.event,
            )

            return UserModelingGateSubmissionResult(
                status=(UserModelingGateSubmissionStatus.SUBMITTED),
                gate=persisted,
                events=all_events,
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

            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.USER_MODELING),
            )

            if gate is None:
                return UserModelingGateDecisionResult(
                    status=(UserModelingGateDecisionStatus.GATE_NOT_FOUND)
                )

            if action is HumanGateAction.SUBMIT:
                return UserModelingGateDecisionResult(
                    status=(UserModelingGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=(HumanGateIssueCode.INVALID_TRANSITION),
                )

            current_artifact = user_modeling_artifact_reference(version)

            if gate.artifact != current_artifact:
                stale_result = mark_human_gate_stale(
                    gate,
                    current_artifact=(current_artifact),
                    occurred_at=(timestamp),
                    event_id=(self._event_id_factory()),
                )

                if (
                    stale_result.status is HumanGateTransitionStatus.APPLIED
                    and stale_result.event is not None
                ):
                    await unit.gates.save_transition(
                        previous_gate=gate,
                        updated_gate=(stale_result.gate),
                        event=(stale_result.event),
                    )

                    return UserModelingGateDecisionResult(
                        status=(UserModelingGateDecisionStatus.ARTIFACT_STALE),
                        gate=(stale_result.gate),
                        event=(stale_result.event),
                    )

                if stale_result.status is HumanGateTransitionStatus.NO_CHANGE:
                    return UserModelingGateDecisionResult(
                        status=(UserModelingGateDecisionStatus.ARTIFACT_STALE),
                        gate=gate,
                    )

                return UserModelingGateDecisionResult(
                    status=(UserModelingGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=(stale_result.issue),
                )

            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=(owner_user_id),
                occurred_at=timestamp,
                reason=reason,
                event_id=(self._event_id_factory()),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return UserModelingGateDecisionResult(
                    status=(UserModelingGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=(transition.issue),
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=(transition.gate),
                event=(transition.event),
            )

            return UserModelingGateDecisionResult(
                status=(UserModelingGateDecisionStatus.APPLIED),
                gate=persisted,
                event=(transition.event),
            )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest owner-scoped Gate 3."""
        async with self._unit_of_work_factory() as unit:
            return await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.USER_MODELING),
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
        async with self._unit_of_work_factory() as unit:
            return await unit.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_id=gate_id,
            )

    async def _submit_existing(
        self,
        *,
        unit: UserModelingGateUnitOfWork,
        gate: HumanGate,
        owner_user_id: UUID,
        occurred_at: datetime,
    ) -> UserModelingGateSubmissionResult:
        """Submit a draft or report the current snapshot's gate state."""
        if gate.status is HumanGateStatus.PENDING_APPROVAL:
            return UserModelingGateSubmissionResult(
                status=(UserModelingGateSubmissionStatus.ALREADY_PENDING),
                gate=gate,
            )

        if gate.status is HumanGateStatus.APPROVED:
            return UserModelingGateSubmissionResult(
                status=(UserModelingGateSubmissionStatus.ALREADY_APPROVED),
                gate=gate,
            )

        if gate.status is HumanGateStatus.DRAFT:
            transition = transition_human_gate(
                gate,
                action=(HumanGateAction.SUBMIT),
                actor_user_id=(owner_user_id),
                occurred_at=(occurred_at),
                event_id=(self._event_id_factory()),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return UserModelingGateSubmissionResult(
                    status=(UserModelingGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=gate,
                    issue=(transition.issue),
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=(transition.gate),
                event=(transition.event),
            )

            return UserModelingGateSubmissionResult(
                status=(UserModelingGateSubmissionStatus.SUBMITTED),
                gate=persisted,
                events=(transition.event,),
            )

        if gate.status in {
            HumanGateStatus.PAUSED,
            HumanGateStatus.CANCELLED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            return UserModelingGateSubmissionResult(
                status=(UserModelingGateSubmissionStatus.GATE_BLOCKED),
                gate=gate,
            )

        return UserModelingGateSubmissionResult(
            status=(UserModelingGateSubmissionStatus.NEW_SNAPSHOT_REQUIRED),
            gate=gate,
        )

    def _current_time(
        self,
    ) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.tzinfo is None:
            raise ValueError("User Modeling gate clock must be timezone-aware")

        return timestamp
