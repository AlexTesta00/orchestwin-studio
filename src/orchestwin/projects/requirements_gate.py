from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
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


class RequirementsGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 4."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    SPECIFICATION_NOT_FOUND = "SPECIFICATION_NOT_FOUND"
    NEW_SPECIFICATION_REQUIRED = "NEW_SPECIFICATION_REQUIRED"
    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class RequirementsGateDecisionStatus(StrEnum):
    """Stable outcomes of one Gate 4 owner decision."""

    APPLIED = "APPLIED"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    SPECIFICATION_NOT_FOUND = "SPECIFICATION_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


class RequirementsWorkflowReadiness(StrEnum):
    """Derived readiness after the requirements stage."""

    REQUIREMENTS_REQUIRED = "REQUIREMENTS_REQUIRED"
    REQUIREMENTS_APPROVAL_REQUIRED = "REQUIREMENTS_APPROVAL_REQUIRED"
    READY_FOR_DESIGN_EXPLORATION = "READY_FOR_DESIGN_EXPLORATION"


@dataclass(frozen=True, slots=True)
class RequirementsGateSubmissionResult:
    """Typed result of submitting the current requirements version."""

    status: RequirementsGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[HumanGateEvent, ...] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class RequirementsGateDecisionResult:
    """Typed result of applying one owner decision to Gate 4."""

    status: RequirementsGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class RequirementsReadinessResult:
    """Current Gate 4 readiness for one exact specification."""

    status: RequirementsWorkflowReadiness
    version: RequirementsSpecificationVersion | None = None
    gate: HumanGate | None = None


class CurrentRequirementsSpecificationRepository(Protocol):
    """Repository port for locking the current owned specification."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        """Lock project scope and return the current specification."""


class RequirementsGateUnitOfWork(Protocol):
    """Transactional boundary for Gate 4 use cases."""

    specifications: CurrentRequirementsSpecificationRepository
    gates: HumanGateRepository

    async def __aenter__(self) -> Self:
        """Enter the Gate 4 transaction."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the Gate 4 transaction."""


class RequirementsGateUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Gate 4 Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> RequirementsGateUnitOfWork:
        """Create one transactional boundary."""


Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return current timezone-aware UTC time."""
    return datetime.now(UTC)


def requirements_artifact_reference(
    version: RequirementsSpecificationVersion,
) -> GateArtifactReference:
    """Create the exact Gate 4 artifact reference."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def requirements_gate_is_currently_approved(
    gate: HumanGate | None,
    version: RequirementsSpecificationVersion | None,
) -> bool:
    """Return whether Gate 4 approves the exact current version."""
    if gate is None or version is None:
        return False

    return (
        gate.status is HumanGateStatus.APPROVED
        and gate.artifact == requirements_artifact_reference(version)
    )


def requirements_readiness(
    *,
    version: RequirementsSpecificationVersion | None,
    gate: HumanGate | None,
) -> RequirementsWorkflowReadiness:
    """Derive requirements-stage readiness without mutating artifacts."""
    if version is None:
        return RequirementsWorkflowReadiness.REQUIREMENTS_REQUIRED

    if requirements_gate_is_currently_approved(gate, version):
        return RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION

    return RequirementsWorkflowReadiness.REQUIREMENTS_APPROVAL_REQUIRED


class LocalRequirementsGateService:
    """Gate 4 use cases composed from explicit repository ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: RequirementsGateUnitOfWorkFactory,
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        """Configure Gate 4 application dependencies."""
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsGateSubmissionResult:
        """Submit the exact current requirements specification."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.specifications.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return RequirementsGateSubmissionResult(
                    status=(RequirementsGateSubmissionStatus.SPECIFICATION_NOT_FOUND)
                )

            artifact = requirements_artifact_reference(version)
            latest = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.REQUIREMENTS,
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
                    return RequirementsGateSubmissionResult(
                        status=RequirementsGateSubmissionStatus.GATE_BLOCKED,
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
                        return RequirementsGateSubmissionResult(
                            status=(RequirementsGateSubmissionStatus.TRANSITION_REJECTED),
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
                    return RequirementsGateSubmissionResult(
                        status=(RequirementsGateSubmissionStatus.ITERATION_LIMIT_REACHED),
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
                gate_type=HumanGateType.REQUIREMENTS,
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
                return RequirementsGateSubmissionResult(
                    status=(RequirementsGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=draft,
                    events=tuple(stale_events),
                    issue=submitted.issue,
                )

            persisted = await unit.gates.add_with_event(
                gate=submitted.gate,
                event=submitted.event,
            )

            return RequirementsGateSubmissionResult(
                status=RequirementsGateSubmissionStatus.SUBMITTED,
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
    ) -> RequirementsGateDecisionResult:
        """Apply one owner decision to the exact current Gate 4."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.specifications.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return RequirementsGateDecisionResult(
                    status=(RequirementsGateDecisionStatus.SPECIFICATION_NOT_FOUND)
                )

            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.REQUIREMENTS,
            )

            if gate is None:
                return RequirementsGateDecisionResult(
                    status=RequirementsGateDecisionStatus.GATE_NOT_FOUND
                )

            if action is HumanGateAction.SUBMIT:
                return RequirementsGateDecisionResult(
                    status=RequirementsGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=HumanGateIssueCode.INVALID_TRANSITION,
                )

            current_artifact = requirements_artifact_reference(version)

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

                    return RequirementsGateDecisionResult(
                        status=RequirementsGateDecisionStatus.ARTIFACT_STALE,
                        gate=stale_result.gate,
                        event=stale_result.event,
                    )

                if stale_result.status is HumanGateTransitionStatus.NO_CHANGE:
                    return RequirementsGateDecisionResult(
                        status=RequirementsGateDecisionStatus.ARTIFACT_STALE,
                        gate=gate,
                    )

                return RequirementsGateDecisionResult(
                    status=RequirementsGateDecisionStatus.REJECTED,
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
                return RequirementsGateDecisionResult(
                    status=RequirementsGateDecisionStatus.REJECTED,
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return RequirementsGateDecisionResult(
                status=RequirementsGateDecisionStatus.APPLIED,
                gate=persisted,
                event=transition.event,
            )

    async def readiness(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsReadinessResult:
        """Return readiness for design exploration."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            version = await unit.specifications.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.REQUIREMENTS,
            )

        return RequirementsReadinessResult(
            status=requirements_readiness(
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
        """Return the latest owner-scoped Gate 4."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=HumanGateType.REQUIREMENTS,
            )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only owner-scoped Gate 4 history."""
        async with self._unit_of_work_factory(owner_user_id=owner_user_id) as unit:
            return await unit.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_id=gate_id,
            )

    async def _submit_existing(
        self,
        *,
        unit: RequirementsGateUnitOfWork,
        gate: HumanGate,
        owner_user_id: UUID,
        occurred_at: datetime,
    ) -> RequirementsGateSubmissionResult:
        """Submit a draft or report the current artifact gate state."""
        if gate.status is HumanGateStatus.PENDING_APPROVAL:
            return RequirementsGateSubmissionResult(
                status=RequirementsGateSubmissionStatus.ALREADY_PENDING,
                gate=gate,
            )

        if gate.status is HumanGateStatus.APPROVED:
            return RequirementsGateSubmissionResult(
                status=RequirementsGateSubmissionStatus.ALREADY_APPROVED,
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
                return RequirementsGateSubmissionResult(
                    status=(RequirementsGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=transition.gate,
                event=transition.event,
            )

            return RequirementsGateSubmissionResult(
                status=RequirementsGateSubmissionStatus.SUBMITTED,
                gate=persisted,
                events=(transition.event,),
            )

        if gate.status in {
            HumanGateStatus.PAUSED,
            HumanGateStatus.CANCELLED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            return RequirementsGateSubmissionResult(
                status=RequirementsGateSubmissionStatus.GATE_BLOCKED,
                gate=gate,
            )

        return RequirementsGateSubmissionResult(
            status=(RequirementsGateSubmissionStatus.NEW_SPECIFICATION_REQUIRED),
            gate=gate,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.utcoffset() is None:
            raise ValueError("requirements gate clock must be timezone-aware")

        return timestamp


__all__ = [
    "CurrentRequirementsSpecificationRepository",
    "LocalRequirementsGateService",
    "RequirementsGateDecisionResult",
    "RequirementsGateDecisionStatus",
    "RequirementsGateSubmissionResult",
    "RequirementsGateSubmissionStatus",
    "RequirementsGateUnitOfWork",
    "RequirementsGateUnitOfWorkFactory",
    "RequirementsReadinessResult",
    "RequirementsWorkflowReadiness",
    "requirements_artifact_reference",
    "requirements_gate_is_currently_approved",
    "requirements_readiness",
]
