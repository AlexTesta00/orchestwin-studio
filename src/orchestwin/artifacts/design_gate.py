"""Gate 5 approval for exact immutable Design Package versions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design_packages import (
    DesignPackageVersion,
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
from orchestwin.workflow.repository import HumanGateRepository


class DesignGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 5."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    PACKAGE_NOT_READY = "PACKAGE_NOT_READY"
    NEW_PACKAGE_REQUIRED = "NEW_PACKAGE_REQUIRED"
    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class DesignGateDecisionStatus(StrEnum):
    """Stable outcomes of one Gate 5 owner decision."""

    APPLIED = "APPLIED"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


class DesignWorkflowReadiness(StrEnum):
    """Derived readiness after the design stage."""

    DESIGN_REQUIRED = "DESIGN_REQUIRED"
    DESIGN_REVIEW_REQUIRED = "DESIGN_REVIEW_REQUIRED"
    DESIGN_APPROVAL_REQUIRED = "DESIGN_APPROVAL_REQUIRED"
    READY_FOR_ARCHITECTURE_PLANNING = "READY_FOR_ARCHITECTURE_PLANNING"


@dataclass(frozen=True, slots=True)
class DesignGateSubmissionResult:
    """Typed result of submitting the current Design Package version."""

    status: DesignGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[HumanGateEvent, ...] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class DesignGateDecisionResult:
    """Typed result of applying one owner decision to Gate 5."""

    status: DesignGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class DesignReadinessResult:
    """Current Gate 5 readiness for one exact Design Package."""

    status: DesignWorkflowReadiness
    version: DesignPackageVersion | None = None
    gate: HumanGate | None = None


class CurrentDesignPackageRepository(Protocol):
    """Repository port for locking the current owned Design Package."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignPackageVersion | None:
        """Lock project scope and return the current Design Package."""


class DesignGateUnitOfWork(Protocol):
    """Transactional boundary for Gate 5 use cases."""

    packages: CurrentDesignPackageRepository
    gates: HumanGateRepository

    async def __aenter__(self) -> Self:
        """Enter the Gate 5 transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the Gate 5 transaction."""


class DesignGateUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Gate 5 Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> DesignGateUnitOfWork:
        """Create one transactional boundary."""


Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""
    return datetime.now(UTC)


def design_artifact_reference(
    version: DesignPackageVersion,
) -> GateArtifactReference:
    """Create the exact Gate 5 artifact reference."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=HumanGateType.DESIGN,
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def design_gate_is_currently_approved(
    gate: HumanGate | None,
    version: DesignPackageVersion | None,
) -> bool:
    """Return whether Gate 5 approves the exact current version."""
    if gate is None or version is None:
        return False

    return gate.status is HumanGateStatus.APPROVED and gate.artifact == design_artifact_reference(
        version
    )


def design_readiness(
    *,
    version: DesignPackageVersion | None,
    gate: HumanGate | None,
) -> DesignWorkflowReadiness:
    """Derive design-stage readiness without mutating artifacts."""
    if version is None:
        return DesignWorkflowReadiness.DESIGN_REQUIRED

    if not version.package.ready_for_gate:
        return DesignWorkflowReadiness.DESIGN_REVIEW_REQUIRED

    if design_gate_is_currently_approved(gate, version):
        return DesignWorkflowReadiness.READY_FOR_ARCHITECTURE_PLANNING

    return DesignWorkflowReadiness.DESIGN_APPROVAL_REQUIRED


class LocalDesignGateService:
    """Gate 5 use cases composed from explicit repository ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: DesignGateUnitOfWorkFactory,
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        """Configure Gate 5 application dependencies."""
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignGateSubmissionResult:
        """Submit the exact current owner-selected and prototyped Design Package."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return DesignGateSubmissionResult(
                    status=DesignGateSubmissionStatus.PACKAGE_NOT_FOUND
                )

            if not version.package.ready_for_gate:
                return DesignGateSubmissionResult(
                    status=DesignGateSubmissionStatus.PACKAGE_NOT_READY
                )

            artifact = design_artifact_reference(version)
            latest = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
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
                    return DesignGateSubmissionResult(
                        status=DesignGateSubmissionStatus.GATE_BLOCKED,
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
                        return DesignGateSubmissionResult(
                            status=(DesignGateSubmissionStatus.TRANSITION_REJECTED),
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
                    return DesignGateSubmissionResult(
                        status=(DesignGateSubmissionStatus.ITERATION_LIMIT_REACHED),
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
                gate_type=HumanGateType.DESIGN,
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
                return DesignGateSubmissionResult(
                    status=(DesignGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=draft,
                    events=tuple(stale_events),
                    issue=submitted.issue,
                )

            persisted = await unit.gates.add_with_event(
                gate=submitted.gate,
                event=submitted.event,
            )

            return DesignGateSubmissionResult(
                status=DesignGateSubmissionStatus.SUBMITTED,
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
    ) -> DesignGateDecisionResult:
        """Apply one owner decision to the exact current Gate 5."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return DesignGateDecisionResult(status=(DesignGateDecisionStatus.PACKAGE_NOT_FOUND))

            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
            )

            if gate is None:
                return DesignGateDecisionResult(status=DesignGateDecisionStatus.GATE_NOT_FOUND)

            if action is HumanGateAction.SUBMIT:
                return DesignGateDecisionResult(
                    status=DesignGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=HumanGateIssueCode.INVALID_TRANSITION,
                )

            current_artifact = design_artifact_reference(version)

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

                    return DesignGateDecisionResult(
                        status=DesignGateDecisionStatus.ARTIFACT_STALE,
                        gate=stale_result.gate,
                        event=stale_result.event,
                    )

                if stale_result.status is HumanGateTransitionStatus.NO_CHANGE:
                    return DesignGateDecisionResult(
                        status=DesignGateDecisionStatus.ARTIFACT_STALE,
                        gate=gate,
                    )

                return DesignGateDecisionResult(
                    status=DesignGateDecisionStatus.REJECTED,
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
                return DesignGateDecisionResult(
                    status=DesignGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return DesignGateDecisionResult(
                status=DesignGateDecisionStatus.APPLIED,
                gate=persisted,
                event=transition.event,
            )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignReadinessResult:
        """Return readiness for architecture and test planning."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.packages.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
            )

        return DesignReadinessResult(
            status=design_readiness(
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
        """Return the latest owner-scoped Gate 5."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.DESIGN,
            )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only owner-scoped Gate 5 history."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_id=gate_id,
            )

    async def _submit_existing(
        self,
        *,
        unit: DesignGateUnitOfWork,
        gate: HumanGate,
        owner_user_id: UUID,
        occurred_at: datetime,
    ) -> DesignGateSubmissionResult:
        """Submit a draft or report the current artifact gate state."""
        if gate.status is HumanGateStatus.PENDING_APPROVAL:
            return DesignGateSubmissionResult(
                status=DesignGateSubmissionStatus.ALREADY_PENDING,
                gate=gate,
            )

        if gate.status is HumanGateStatus.APPROVED:
            return DesignGateSubmissionResult(
                status=DesignGateSubmissionStatus.ALREADY_APPROVED,
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
                return DesignGateSubmissionResult(
                    status=(DesignGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return DesignGateSubmissionResult(
                status=DesignGateSubmissionStatus.SUBMITTED,
                gate=persisted,
                events=(transition.event,),
            )

        if gate.status in {
            HumanGateStatus.PAUSED,
            HumanGateStatus.CANCELLED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            return DesignGateSubmissionResult(
                status=DesignGateSubmissionStatus.GATE_BLOCKED,
                gate=gate,
            )

        return DesignGateSubmissionResult(
            status=(DesignGateSubmissionStatus.NEW_PACKAGE_REQUIRED),
            gate=gate,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.utcoffset() is None:
            raise ValueError("design gate clock must be timezone-aware")

        return timestamp


__all__ = [
    "CurrentDesignPackageRepository",
    "DesignGateDecisionResult",
    "DesignGateDecisionStatus",
    "DesignGateSubmissionResult",
    "DesignGateSubmissionStatus",
    "DesignGateUnitOfWork",
    "DesignGateUnitOfWorkFactory",
    "DesignReadinessResult",
    "DesignWorkflowReadiness",
    "LocalDesignGateService",
    "design_artifact_reference",
    "design_gate_is_currently_approved",
    "design_readiness",
]
