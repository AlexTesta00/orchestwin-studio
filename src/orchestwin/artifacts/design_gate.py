"""Gate 5 approval for exact immutable Design Package versions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design_packages import (
    DesignPackageVersion,
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
    return gate_is_currently_approved(gate, version, design_artifact_reference)


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


_OUTCOMES = GateOutcomes(
    submission=DesignGateSubmissionResult,
    submission_status=DesignGateSubmissionStatus,
    new_artifact_required=DesignGateSubmissionStatus.NEW_PACKAGE_REQUIRED,
    decision=DesignGateDecisionResult,
    decision_status=DesignGateDecisionStatus,
)


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

            return await submit_artifact(
                unit.gates,
                design_artifact_reference(version),
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

            return await decide_current(
                unit.gates,
                design_artifact_reference(version),
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
        return await latest_gate(
            self._unit_of_work_factory(owner_user_id=owner_user_id),
            HumanGateType.DESIGN,
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
        """Return the append-only owner-scoped Gate 5 history."""
        return await gate_history(
            self._unit_of_work_factory(owner_user_id=owner_user_id),
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_id=gate_id,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        return current_time(self._clock, "design gate clock must be timezone-aware", by_offset=True)


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
