"""Application services for Project Brief human approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
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


class CurrentProjectBriefRepository(Protocol):
    """Repository port for locking the current owned brief."""

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Lock the project and return its current brief version."""


class ProjectBriefGateUnitOfWork(Protocol):
    """Transactional boundary for Project Brief gate use cases."""

    @property
    def current_briefs(
        self,
    ) -> CurrentProjectBriefRepository:
        """Return the current-brief repository."""

    @property
    def gates(
        self,
    ) -> HumanGateRepository:
        """Return the human-gate repository."""

    async def __aenter__(
        self,
    ) -> Self:
        """Open the transaction."""

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Commit or roll back the transaction."""


ProjectBriefGateUnitOfWorkFactory = Callable[
    [],
    ProjectBriefGateUnitOfWork,
]


class ProjectBriefGateSubmissionStatus(StrEnum):
    """Stable outcomes of submitting Gate 1."""

    SUBMITTED = "SUBMITTED"
    ALREADY_PENDING = "ALREADY_PENDING"
    ALREADY_APPROVED = "ALREADY_APPROVED"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    BRIEF_INCOMPLETE = "BRIEF_INCOMPLETE"
    NEW_BRIEF_REQUIRED = "NEW_BRIEF_REQUIRED"
    GATE_BLOCKED = "GATE_BLOCKED"
    ITERATION_LIMIT_REACHED = "ITERATION_LIMIT_REACHED"
    TRANSITION_REJECTED = "TRANSITION_REJECTED"


class ProjectBriefGateDecisionStatus(StrEnum):
    """Stable outcomes of a Gate 1 owner decision."""

    APPLIED = "APPLIED"
    GATE_NOT_FOUND = "GATE_NOT_FOUND"
    BRIEF_NOT_FOUND = "BRIEF_NOT_FOUND"
    ARTIFACT_STALE = "ARTIFACT_STALE"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ProjectBriefGateSubmissionResult:
    """Typed result of submitting the current Project Brief."""

    status: ProjectBriefGateSubmissionStatus
    gate: HumanGate | None = None
    events: tuple[HumanGateEvent, ...] = ()
    missing_fields: tuple[BriefField, ...] = ()
    issue: HumanGateIssueCode | None = None


@dataclass(frozen=True, slots=True)
class ProjectBriefGateDecisionResult:
    """Typed result of applying an owner decision to Gate 1."""

    status: ProjectBriefGateDecisionStatus
    gate: HumanGate | None = None
    event: HumanGateEvent | None = None
    issue: HumanGateIssueCode | None = None


class ProjectBriefGateService(Protocol):
    """Use cases exposed to the future Gate 1 API adapter."""

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefGateSubmissionResult:
        """Submit the current Project Brief for owner approval."""

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> ProjectBriefGateDecisionResult:
        """Apply an owner decision to the current Gate 1."""

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest Project Brief gate."""

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the owner-scoped Gate 1 event history."""


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def project_brief_artifact_reference(
    version: ProjectBriefVersion,
) -> GateArtifactReference:
    """Create the exact Gate 1 reference for one brief version."""
    return GateArtifactReference(
        project_id=version.project_id,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact_id=version.id,
        version=version.version_number,
        content_hash=version.content_hash,
    )


def project_brief_gate_is_currently_approved(
    gate: HumanGate | None,
    version: ProjectBriefVersion | None,
) -> bool:
    """Return whether Gate 1 approves the exact current brief."""
    return gate_is_currently_approved(gate, version, project_brief_artifact_reference)


_OUTCOMES = GateOutcomes(
    submission=ProjectBriefGateSubmissionResult,
    submission_status=ProjectBriefGateSubmissionStatus,
    new_artifact_required=ProjectBriefGateSubmissionStatus.NEW_BRIEF_REQUIRED,
    decision=ProjectBriefGateDecisionResult,
    decision_status=ProjectBriefGateDecisionStatus,
)


class LocalProjectBriefGateService:
    """Project Brief approval use cases composed from explicit ports."""

    def __init__(
        self,
        *,
        unit_of_work_factory: (ProjectBriefGateUnitOfWorkFactory),
        clock: Clock = utc_now,
        gate_id_factory: UuidFactory = uuid4,
        event_id_factory: UuidFactory = uuid4,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._gate_id_factory = gate_id_factory
        self._event_id_factory = event_id_factory

    async def submit(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefGateSubmissionResult:
        """Submit the current complete brief as Gate 1."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            version = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )

            if version is None:
                return ProjectBriefGateSubmissionResult(
                    status=(ProjectBriefGateSubmissionStatus.BRIEF_NOT_FOUND)
                )

            missing_fields = tuple(
                sorted(
                    version.brief.missing_fields,
                    key=lambda field: field.value,
                )
            )

            if missing_fields:
                return ProjectBriefGateSubmissionResult(
                    status=(ProjectBriefGateSubmissionStatus.BRIEF_INCOMPLETE),
                    missing_fields=missing_fields,
                )

            return await submit_artifact(
                unit.gates,
                project_brief_artifact_reference(version),
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
    ) -> ProjectBriefGateDecisionResult:
        """Apply one owner decision to the current Gate 1."""
        timestamp = self._current_time()

        async with self._unit_of_work_factory() as unit:
            version = await unit.current_briefs.get_current_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
            )

            if version is None:
                return ProjectBriefGateDecisionResult(
                    status=(ProjectBriefGateDecisionStatus.BRIEF_NOT_FOUND)
                )

            return await decide_current(
                unit.gates,
                project_brief_artifact_reference(version),
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
        """Return the latest owner-scoped Project Brief gate."""
        return await latest_gate(
            self._unit_of_work_factory(),
            HumanGateType.PROJECT_BRIEF,
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
        """Return the append-only Gate 1 event history."""
        return await gate_history(
            self._unit_of_work_factory(),
            project_id=project_id,
            owner_user_id=owner_user_id,
            gate_id=gate_id,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        return current_time(self._clock, "Project Brief gate clock must be timezone-aware")
