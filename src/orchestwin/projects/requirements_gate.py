from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
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
    return gate_is_currently_approved(gate, version, requirements_artifact_reference)


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


_OUTCOMES = GateOutcomes(
    submission=RequirementsGateSubmissionResult,
    submission_status=RequirementsGateSubmissionStatus,
    new_artifact_required=RequirementsGateSubmissionStatus.NEW_SPECIFICATION_REQUIRED,
    decision=RequirementsGateDecisionResult,
    decision_status=RequirementsGateDecisionStatus,
)


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

            return await submit_artifact(
                unit.gates,
                requirements_artifact_reference(version),
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

            return await decide_current(
                unit.gates,
                requirements_artifact_reference(version),
                project_id=project_id,
                owner_user_id=owner_user_id,
                action=action,
                reason=reason,
                occurred_at=timestamp,
                event_id_factory=self._event_id_factory,
                outcomes=_OUTCOMES,
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
        return await latest_gate(
            self._unit_of_work_factory(owner_user_id=owner_user_id),
            HumanGateType.REQUIREMENTS,
            project_id=project_id,
            owner_user_id=owner_user_id,
        )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only owner-scoped Gate 4 history."""
        return await gate_history(
            self._unit_of_work_factory(owner_user_id=owner_user_id),
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_id=gate_id,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        return current_time(
            self._clock, "requirements gate clock must be timezone-aware", by_offset=True
        )


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
