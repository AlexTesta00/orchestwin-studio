"""Gate 6 approval for exact immutable Architecture Package versions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
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
from orchestwin.workflow.repository import HumanGateRepository


class ArchitectureGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 6."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    NEW_PACKAGE_REQUIRED = "NEW_PACKAGE_REQUIRED"
    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class ArchitectureGateDecisionStatus(StrEnum):
    """Stable outcomes of one Gate 6 owner decision."""

    APPLIED = "APPLIED"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


class ArchitectureWorkflowReadiness(StrEnum):
    """Derived readiness after the architecture and test-plan stage."""

    ARCHITECTURE_REQUIRED = "ARCHITECTURE_REQUIRED"
    ARCHITECTURE_APPROVAL_REQUIRED = "ARCHITECTURE_APPROVAL_REQUIRED"
    READY_FOR_IMPLEMENTATION = "READY_FOR_IMPLEMENTATION"


@dataclass(frozen=True, slots=True)
class ArchitectureGateSubmissionResult:
    """Typed result of submitting the current Architecture Package version."""

    status: ArchitectureGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[HumanGateEvent, ...] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class ArchitectureGateDecisionResult:
    """Typed result of applying one owner decision to Gate 6."""

    status: ArchitectureGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class ArchitectureReadinessResult:
    """Current Gate 6 readiness for one exact Architecture Package."""

    status: ArchitectureWorkflowReadiness
    version: ArchitecturePackageVersion | None = None
    gate: HumanGate | None = None


class CurrentArchitecturePackageRepository(Protocol):
    """Repository port for locking the current owned Architecture Package."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Lock project scope and return the current Architecture Package."""


class ArchitectureGateUnitOfWork(Protocol):
    """Transactional boundary for Gate 6 use cases."""

    packages: CurrentArchitecturePackageRepository
    gates: HumanGateRepository

    async def __aenter__(self) -> Self:
        """Enter the Gate 6 transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the Gate 6 transaction."""


class ArchitectureGateUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Gate 6 Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ArchitectureGateUnitOfWork:
        """Create one transactional boundary."""


Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""
    return datetime.now(UTC)


def architecture_artifact_reference(
    version: ArchitecturePackageVersion,
) -> GateArtifactReference:
    """Create the exact Gate 6 artifact reference."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=HumanGateType.ARCHITECTURE,
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def architecture_gate_is_currently_approved(
    gate: HumanGate | None,
    version: ArchitecturePackageVersion | None,
) -> bool:
    """Return whether Gate 6 approves the exact current version."""
    if gate is None or version is None:
        return False

    return (
        gate.status is HumanGateStatus.APPROVED
        and gate.artifact == architecture_artifact_reference(version)
    )


def architecture_readiness(
    *,
    version: ArchitecturePackageVersion | None,
    gate: HumanGate | None,
) -> ArchitectureWorkflowReadiness:
    """Derive implementation readiness without mutating approved artifacts."""
    if version is None:
        return ArchitectureWorkflowReadiness.ARCHITECTURE_REQUIRED

    if architecture_gate_is_currently_approved(gate, version):
        return ArchitectureWorkflowReadiness.READY_FOR_IMPLEMENTATION

    return ArchitectureWorkflowReadiness.ARCHITECTURE_APPROVAL_REQUIRED


class LocalArchitectureGateService:
    """Gate 6 use cases composed from explicit repository ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: ArchitectureGateUnitOfWorkFactory,
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        """Configure Gate 6 application dependencies."""
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureGateSubmissionResult:
        """Submit the exact current Architecture Package and test plan."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return ArchitectureGateSubmissionResult(
                    status=ArchitectureGateSubmissionStatus.PACKAGE_NOT_FOUND
                )

            artifact = architecture_artifact_reference(version)
            latest = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )

            if latest is not None and latest.artifact == artifact:
                return await self._submit_existing(
                    unit=unit,
                    gate=latest,
                    owner_user_id=owner_user_id,
                    occurred_at=timestamp,
                )

            stale_events: list[HumanGateEvent] = []

            if latest is not None:
                if latest.status in {
                    HumanGateStatus.CANCELLED,
                    HumanGateStatus.PAUSED_NEEDS_HUMAN,
                }:
                    return ArchitectureGateSubmissionResult(
                        status=ArchitectureGateSubmissionStatus.GATE_BLOCKED,
                        gate=latest,
                    )

                if latest.status is not HumanGateStatus.STALE:
                    stale_result = mark_human_gate_stale(
                        latest,
                        current_artifact=artifact,
                        occurred_at=timestamp,
                        event_id=self._event_id_factory(),
                    )

                    if stale_result.status is HumanGateTransitionStatus.REJECTED:
                        return ArchitectureGateSubmissionResult(
                            status=(ArchitectureGateSubmissionStatus.TRANSITION_REJECTED),
                            gate=latest,
                            issue=stale_result.issue,
                        )

                    if (
                        stale_result.status is HumanGateTransitionStatus.APPLIED
                        and stale_result.event is not None
                    ):
                        await unit.gates.save_transition(
                            previous_gate=latest,
                            updated_gate=stale_result.gate,
                            event=stale_result.event,
                        )
                        stale_events.append(stale_result.event)
                        latest = stale_result.gate

                next_iteration = latest.iteration + 1
                max_iterations = latest.max_iterations

                if next_iteration > max_iterations:
                    return ArchitectureGateSubmissionResult(
                        status=(ArchitectureGateSubmissionStatus.ITERATION_LIMIT_REACHED),
                        gate=latest,
                        events=tuple(stale_events),
                    )
            else:
                next_iteration = 1
                max_iterations = DEFAULT_GATE_ITERATION_LIMIT

            draft = create_human_gate(
                gate_id=self._gate_id_factory(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
                artifact=artifact,
                iteration=next_iteration,
                max_iterations=max_iterations,
                created_at=timestamp,
            )
            submitted = transition_human_gate(
                draft,
                action=HumanGateAction.SUBMIT,
                actor_user_id=owner_user_id,
                occurred_at=timestamp,
                event_id=self._event_id_factory(),
            )

            if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
                return ArchitectureGateSubmissionResult(
                    status=(ArchitectureGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=draft,
                    events=tuple(stale_events),
                    issue=submitted.issue,
                )

            persisted = await unit.gates.add_with_event(
                gate=submitted.gate,
                event=submitted.event,
            )

            return ArchitectureGateSubmissionResult(
                status=ArchitectureGateSubmissionStatus.SUBMITTED,
                gate=persisted,
                events=(
                    *stale_events,
                    submitted.event,
                ),
            )

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> ArchitectureGateDecisionResult:
        """Apply one owner decision to the exact current Gate 6."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return ArchitectureGateDecisionResult(
                    status=(ArchitectureGateDecisionStatus.PACKAGE_NOT_FOUND)
                )

            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )

            if gate is None:
                return ArchitectureGateDecisionResult(
                    status=ArchitectureGateDecisionStatus.GATE_NOT_FOUND
                )

            if action is HumanGateAction.SUBMIT:
                return ArchitectureGateDecisionResult(
                    status=ArchitectureGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=HumanGateIssueCode.INVALID_TRANSITION,
                )

            current_artifact = architecture_artifact_reference(version)

            if gate.artifact != current_artifact:
                stale_result = mark_human_gate_stale(
                    gate,
                    current_artifact=current_artifact,
                    occurred_at=timestamp,
                    event_id=self._event_id_factory(),
                )

                if (
                    stale_result.status is HumanGateTransitionStatus.APPLIED
                    and stale_result.event is not None
                ):
                    await unit.gates.save_transition(
                        previous_gate=gate,
                        updated_gate=stale_result.gate,
                        event=stale_result.event,
                    )

                    return ArchitectureGateDecisionResult(
                        status=ArchitectureGateDecisionStatus.ARTIFACT_STALE,
                        gate=stale_result.gate,
                        event=stale_result.event,
                    )

                if stale_result.status is HumanGateTransitionStatus.NO_CHANGE:
                    return ArchitectureGateDecisionResult(
                        status=ArchitectureGateDecisionStatus.ARTIFACT_STALE,
                        gate=gate,
                    )

                return ArchitectureGateDecisionResult(
                    status=ArchitectureGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=stale_result.issue,
                )

            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=owner_user_id,
                occurred_at=timestamp,
                reason=reason,
                event_id=self._event_id_factory(),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return ArchitectureGateDecisionResult(
                    status=ArchitectureGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return ArchitectureGateDecisionResult(
                status=ArchitectureGateDecisionStatus.APPLIED,
                gate=persisted,
                event=transition.event,
            )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitectureReadinessResult:
        """Return readiness for implementation after Gate 6."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )

        return ArchitectureReadinessResult(
            status=architecture_readiness(
                version=version,
                gate=gate,
            ),
            version=version,
            gate=gate,
        )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest owner-scoped Gate 6."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.ARCHITECTURE,
            )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only owner-scoped Gate 6 history."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_id=gate_id,
            )

    async def _submit_existing(
        self,
        *,
        unit: ArchitectureGateUnitOfWork,
        gate: HumanGate,
        owner_user_id: UUID,
        occurred_at: datetime,
    ) -> ArchitectureGateSubmissionResult:
        """Submit a draft or report the current artifact gate state."""
        if gate.status is HumanGateStatus.PENDING_APPROVAL:
            return ArchitectureGateSubmissionResult(
                status=ArchitectureGateSubmissionStatus.ALREADY_PENDING,
                gate=gate,
            )

        if gate.status is HumanGateStatus.APPROVED:
            return ArchitectureGateSubmissionResult(
                status=ArchitectureGateSubmissionStatus.ALREADY_APPROVED,
                gate=gate,
            )

        if gate.status is HumanGateStatus.DRAFT:
            transition = transition_human_gate(
                gate,
                action=HumanGateAction.SUBMIT,
                actor_user_id=owner_user_id,
                occurred_at=occurred_at,
                event_id=self._event_id_factory(),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return ArchitectureGateSubmissionResult(
                    status=(ArchitectureGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return ArchitectureGateSubmissionResult(
                status=ArchitectureGateSubmissionStatus.SUBMITTED,
                gate=persisted,
                events=(transition.event,),
            )

        if gate.status in {
            HumanGateStatus.PAUSED,
            HumanGateStatus.CANCELLED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            return ArchitectureGateSubmissionResult(
                status=ArchitectureGateSubmissionStatus.GATE_BLOCKED,
                gate=gate,
            )

        return ArchitectureGateSubmissionResult(
            status=(ArchitectureGateSubmissionStatus.NEW_PACKAGE_REQUIRED),
            gate=gate,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.utcoffset() is None:
            raise ValueError("architecture gate clock must be timezone-aware")

        return timestamp


__all__ = [
    "ArchitectureGateDecisionResult",
    "ArchitectureGateDecisionStatus",
    "ArchitectureGateSubmissionResult",
    "ArchitectureGateSubmissionStatus",
    "ArchitectureGateUnitOfWork",
    "ArchitectureGateUnitOfWorkFactory",
    "ArchitectureReadinessResult",
    "ArchitectureWorkflowReadiness",
    "CurrentArchitecturePackageRepository",
    "LocalArchitectureGateService",
    "architecture_artifact_reference",
    "architecture_gate_is_currently_approved",
    "architecture_readiness",
]
