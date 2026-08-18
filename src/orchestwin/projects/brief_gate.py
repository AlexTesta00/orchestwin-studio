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


Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


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
    if gate is None or version is None:
        return False

    return (
        gate.status is HumanGateStatus.APPROVED
        and gate.artifact == project_brief_artifact_reference(version)
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

            artifact = project_brief_artifact_reference(version)
            latest = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.PROJECT_BRIEF),
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
                    return ProjectBriefGateSubmissionResult(
                        status=(ProjectBriefGateSubmissionStatus.GATE_BLOCKED),
                        gate=latest,
                    )

                if latest.status is not HumanGateStatus.STALE:
                    stale_result = mark_human_gate_stale(
                        latest,
                        current_artifact=(artifact),
                        occurred_at=timestamp,
                        event_id=(self._event_id_factory()),
                    )

                    if stale_result.status is HumanGateTransitionStatus.REJECTED:
                        return ProjectBriefGateSubmissionResult(
                            status=(ProjectBriefGateSubmissionStatus.TRANSITION_REJECTED),
                            gate=latest,
                            issue=(stale_result.issue),
                        )

                    if (
                        stale_result.status is HumanGateTransitionStatus.APPLIED
                        and stale_result.event is not None
                    ):
                        await unit.gates.save_transition(
                            previous_gate=latest,
                            updated_gate=(stale_result.gate),
                            event=(stale_result.event),
                        )
                        stale_events.append(stale_result.event)
                        latest = stale_result.gate

                next_iteration = latest.iteration + 1
                max_iterations = latest.max_iterations

                if next_iteration > max_iterations:
                    return ProjectBriefGateSubmissionResult(
                        status=(ProjectBriefGateSubmissionStatus.ITERATION_LIMIT_REACHED),
                        gate=latest,
                        events=tuple(stale_events),
                    )
            else:
                next_iteration = 1
                max_iterations = DEFAULT_GATE_ITERATION_LIMIT

            draft = create_human_gate(
                gate_id=(self._gate_id_factory()),
                project_id=project_id,
                owner_user_id=owner_user_id,
                gate_type=(HumanGateType.PROJECT_BRIEF),
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
                event_id=(self._event_id_factory()),
            )

            if submitted.status is not HumanGateTransitionStatus.APPLIED or submitted.event is None:
                return ProjectBriefGateSubmissionResult(
                    status=(ProjectBriefGateSubmissionStatus.TRANSITION_REJECTED),
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

            return ProjectBriefGateSubmissionResult(
                status=(ProjectBriefGateSubmissionStatus.SUBMITTED),
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

            gate = await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.PROJECT_BRIEF),
            )

            if gate is None:
                return ProjectBriefGateDecisionResult(
                    status=(ProjectBriefGateDecisionStatus.GATE_NOT_FOUND)
                )

            if action is HumanGateAction.SUBMIT:
                return ProjectBriefGateDecisionResult(
                    status=(ProjectBriefGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=(HumanGateIssueCode.INVALID_TRANSITION),
                )

            current_artifact = project_brief_artifact_reference(version)

            if gate.artifact != current_artifact:
                stale_result = mark_human_gate_stale(
                    gate,
                    current_artifact=(current_artifact),
                    occurred_at=timestamp,
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

                    return ProjectBriefGateDecisionResult(
                        status=(ProjectBriefGateDecisionStatus.ARTIFACT_STALE),
                        gate=(stale_result.gate),
                        event=(stale_result.event),
                    )

                if stale_result.status is HumanGateTransitionStatus.NO_CHANGE:
                    return ProjectBriefGateDecisionResult(
                        status=(ProjectBriefGateDecisionStatus.ARTIFACT_STALE),
                        gate=gate,
                    )

                return ProjectBriefGateDecisionResult(
                    status=(ProjectBriefGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=stale_result.issue,
                )

            transition = transition_human_gate(
                gate,
                action=action,
                actor_user_id=owner_user_id,
                occurred_at=timestamp,
                reason=reason,
                event_id=(self._event_id_factory()),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return ProjectBriefGateDecisionResult(
                    status=(ProjectBriefGateDecisionStatus.REJECTED),
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=(transition.gate),
                event=transition.event,
            )

            return ProjectBriefGateDecisionResult(
                status=(ProjectBriefGateDecisionStatus.APPLIED),
                gate=persisted,
                event=transition.event,
            )

    async def current_gate(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> HumanGate | None:
        """Return the latest owner-scoped Project Brief gate."""
        async with self._unit_of_work_factory() as unit:
            return await unit.gates.get_latest_owned_for_update(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_type=(HumanGateType.PROJECT_BRIEF),
            )

    async def gate_events(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return the append-only Gate 1 event history."""
        async with self._unit_of_work_factory() as unit:
            return await unit.gates.list_events_owned(
                project_id=project_id,
                owner_user_id=(owner_user_id),
                gate_id=gate_id,
            )

    async def _submit_existing(
        self,
        *,
        unit: ProjectBriefGateUnitOfWork,
        gate: HumanGate,
        owner_user_id: UUID,
        occurred_at: datetime,
    ) -> ProjectBriefGateSubmissionResult:
        """Submit a draft or report the current artifact state."""
        if gate.status is HumanGateStatus.PENDING_APPROVAL:
            return ProjectBriefGateSubmissionResult(
                status=(ProjectBriefGateSubmissionStatus.ALREADY_PENDING),
                gate=gate,
            )

        if gate.status is HumanGateStatus.APPROVED:
            return ProjectBriefGateSubmissionResult(
                status=(ProjectBriefGateSubmissionStatus.ALREADY_APPROVED),
                gate=gate,
            )

        if gate.status is HumanGateStatus.DRAFT:
            transition = transition_human_gate(
                gate,
                action=HumanGateAction.SUBMIT,
                actor_user_id=owner_user_id,
                occurred_at=occurred_at,
                event_id=(self._event_id_factory()),
            )

            if (
                transition.status is not HumanGateTransitionStatus.APPLIED
                or transition.event is None
            ):
                return ProjectBriefGateSubmissionResult(
                    status=(ProjectBriefGateSubmissionStatus.TRANSITION_REJECTED),
                    gate=gate,
                    issue=transition.issue,
                )

            persisted = await unit.gates.save_transition(
                previous_gate=gate,
                updated_gate=(transition.gate),
                event=transition.event,
            )

            return ProjectBriefGateSubmissionResult(
                status=(ProjectBriefGateSubmissionStatus.SUBMITTED),
                gate=persisted,
                events=(transition.event,),
            )

        if gate.status in {
            HumanGateStatus.PAUSED,
            HumanGateStatus.CANCELLED,
            HumanGateStatus.PAUSED_NEEDS_HUMAN,
        }:
            return ProjectBriefGateSubmissionResult(
                status=(ProjectBriefGateSubmissionStatus.GATE_BLOCKED),
                gate=gate,
            )

        return ProjectBriefGateSubmissionResult(
            status=(ProjectBriefGateSubmissionStatus.NEW_BRIEF_REQUIRED),
            gate=gate,
        )

    def _current_time(self) -> datetime:
        """Return and validate the injected application clock."""
        timestamp = self._clock()

        if timestamp.tzinfo is None:
            raise ValueError("Project Brief gate clock must be timezone-aware")

        return timestamp
