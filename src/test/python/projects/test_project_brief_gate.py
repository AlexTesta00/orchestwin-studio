"""Tests for Project Brief approval-gate application services."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from orchestwin.projects.brief_gate import (
    LocalProjectBriefGateService,
    ProjectBriefGateDecisionStatus,
    ProjectBriefGateSubmissionStatus,
    project_brief_gate_is_currently_approved,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateStatus,
    HumanGateTransitionStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
OTHER_OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


class IncrementingUuidFactory:
    """Return deterministic UUID values."""

    def __init__(
        self,
        *,
        start: int,
    ) -> None:
        self._next_value = start

    def __call__(self) -> UUID:
        value = UUID(int=self._next_value)
        self._next_value += 1
        return value


class InMemoryCurrentBriefRepository:
    """Owner-scoped current-brief repository double."""

    def __init__(self) -> None:
        self._versions: dict[
            tuple[UUID, UUID],
            ProjectBriefVersion,
        ] = {}

    def set_current(
        self,
        *,
        owner_user_id: UUID,
        version: ProjectBriefVersion,
    ) -> None:
        """Set the current brief for one owner and project."""
        self._versions[
            (
                version.project_id,
                owner_user_id,
            )
        ] = version

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current owner-scoped brief."""
        return self._versions.get(
            (
                project_id,
                owner_user_id,
            )
        )


class InMemoryHumanGateRepository:
    """In-memory human-gate repository with audit events."""

    def __init__(self) -> None:
        self.gates: list[HumanGate] = []
        self.events: list[HumanGateEvent] = []

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Persist a new gate and its first event."""
        self.gates.append(gate)
        self.events.append(event)
        return gate

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        """Return the highest gate iteration for the owner."""
        matching = [
            gate
            for gate in self.gates
            if (
                gate.project_id == project_id
                and gate.owner_user_id == owner_user_id
                and gate.gate_type is gate_type
            )
        ]

        if not matching:
            return None

        return max(
            matching,
            key=lambda gate: (
                gate.iteration,
                gate.created_at,
                gate.id,
            ),
        )

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        """Replace exactly one existing gate and append its event."""
        index = self.gates.index(previous_gate)
        self.gates[index] = updated_gate
        self.events.append(event)
        return updated_gate

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        """Return ordered events for an owner-scoped gate."""
        gate = next(
            (
                candidate
                for candidate in self.gates
                if (
                    candidate.id == gate_id
                    and candidate.project_id == project_id
                    and candidate.owner_user_id == owner_user_id
                )
            ),
            None,
        )

        if gate is None:
            return ()

        return tuple(
            sorted(
                (event for event in self.events if event.gate_id == gate_id),
                key=lambda event: event.sequence_number,
            )
        )


class InMemoryProjectBriefGateUnitOfWork:
    """Reusable in-memory Gate 1 transaction boundary."""

    def __init__(
        self,
        current_briefs: (InMemoryCurrentBriefRepository),
        gates: (InMemoryHumanGateRepository),
    ) -> None:
        self.current_briefs = current_briefs
        self.gates = gates

    async def __aenter__(
        self,
    ) -> InMemoryProjectBriefGateUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def complete_brief_version(
    *,
    version_number: int = 1,
    description: str | None = None,
) -> ProjectBriefVersion:
    """Create a brief with no missing fields."""
    provided_fields = {
        BriefField.NAME,
    }

    if description is not None:
        provided_fields.add(BriefField.DESCRIPTION)

    brief = create_project_brief(
        name="Project",
        description=description,
        unknown_fields=[field for field in BriefField if field not in provided_fields],
    )

    return ProjectBriefVersion(
        id=UUID(int=100 + version_number),
        project_id=PROJECT_ID,
        version_number=version_number,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def incomplete_brief_version() -> ProjectBriefVersion:
    """Create a brief containing missing fields."""
    brief = create_project_brief(name="Project")

    return ProjectBriefVersion(
        id=UUID(int=101),
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def build_service(
    current_briefs: (InMemoryCurrentBriefRepository),
    gates: (InMemoryHumanGateRepository),
) -> LocalProjectBriefGateService:
    """Create a deterministic Gate 1 application service."""
    return LocalProjectBriefGateService(
        unit_of_work_factory=lambda: InMemoryProjectBriefGateUnitOfWork(
            current_briefs,
            gates,
        ),
        clock=lambda: NOW,
        gate_id_factory=(IncrementingUuidFactory(start=1000)),
        event_id_factory=(IncrementingUuidFactory(start=2000)),
    )


def test_incomplete_brief_cannot_be_submitted() -> None:
    """Expose missing fields without creating a gate."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=(incomplete_brief_version()),
    )
    service = build_service(
        current_briefs,
        gates,
    )

    result = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (ProjectBriefGateSubmissionStatus.BRIEF_INCOMPLETE)
    assert BriefField.PROBLEM in (result.missing_fields)
    assert gates.gates == []
    assert gates.events == []


def test_complete_brief_is_submitted_once() -> None:
    """Create one pending Gate 1 for the exact current brief."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    version = complete_brief_version()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=version,
    )
    service = build_service(
        current_briefs,
        gates,
    )

    first = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    repeated = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert first.status is (ProjectBriefGateSubmissionStatus.SUBMITTED)
    assert first.gate is not None
    assert first.gate.status is (HumanGateStatus.PENDING_APPROVAL)
    assert first.gate.artifact.version == version.version_number
    assert first.gate.artifact.content_hash == version.content_hash
    assert len(first.events) == 1

    assert repeated.status is (ProjectBriefGateSubmissionStatus.ALREADY_PENDING)
    assert len(gates.gates) == 1
    assert len(gates.events) == 1


def test_owner_can_approve_the_current_brief() -> None:
    """Approve Gate 1 and expose current approval readiness."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    version = complete_brief_version()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=version,
    )
    service = build_service(
        current_briefs,
        gates,
    )

    asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    decision = asyncio.run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )
    )

    assert decision.status is (ProjectBriefGateDecisionStatus.APPLIED)
    assert decision.gate is not None
    assert decision.gate.status is (HumanGateStatus.APPROVED)
    assert (
        project_brief_gate_is_currently_approved(
            decision.gate,
            version,
        )
        is True
    )


def test_new_brief_stales_approval_and_creates_next_iteration() -> None:
    """Bind the next gate iteration to the new immutable brief."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    first_version = complete_brief_version()
    second_version = complete_brief_version(
        version_number=2,
        description=("Updated Project Brief."),
    )
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=first_version,
    )
    service = build_service(
        current_briefs,
        gates,
    )

    asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    asyncio.run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )
    )

    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=second_version,
    )

    result = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (ProjectBriefGateSubmissionStatus.SUBMITTED)
    assert result.gate is not None
    assert result.gate.iteration == 2
    assert result.gate.status is (HumanGateStatus.PENDING_APPROVAL)
    assert result.gate.artifact.version == 2
    assert len(result.events) == 2

    first_gate = next(gate for gate in gates.gates if gate.iteration == 1)

    assert first_gate.status is (HumanGateStatus.STALE)
    assert (
        project_brief_gate_is_currently_approved(
            first_gate,
            second_version,
        )
        is False
    )


def test_decision_detects_a_superseded_brief() -> None:
    """Refuse approval if a newer brief became current."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    first_version = complete_brief_version()
    second_version = complete_brief_version(
        version_number=2,
        description=("New current version."),
    )
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=first_version,
    )
    service = build_service(
        current_briefs,
        gates,
    )

    asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=second_version,
    )

    decision = asyncio.run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.APPROVE),
        )
    )

    assert decision.status is (ProjectBriefGateDecisionStatus.ARTIFACT_STALE)
    assert decision.gate is not None
    assert decision.gate.status is (HumanGateStatus.STALE)


def test_final_revision_request_pauses_gate_for_human() -> None:
    """Apply the iteration-limit state through the application service."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    version = complete_brief_version()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=version,
    )

    draft = create_human_gate(
        gate_id=UUID(int=3000),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=(HumanGateType.PROJECT_BRIEF),
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=(HumanGateType.PROJECT_BRIEF),
            artifact_id=version.id,
            version=(version.version_number),
            content_hash=(version.content_hash),
        ),
        iteration=3,
        max_iterations=3,
        created_at=NOW,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=NOW,
        event_id=UUID(int=3001),
    )

    assert submitted.status is (HumanGateTransitionStatus.APPLIED)
    assert submitted.event is not None

    asyncio.run(
        gates.add_with_event(
            gate=submitted.gate,
            event=submitted.event,
        )
    )

    service = build_service(
        current_briefs,
        gates,
    )
    decision = asyncio.run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=(HumanGateAction.REQUEST_REVISION),
            reason=("The brief requires another revision."),
        )
    )

    assert decision.status is (ProjectBriefGateDecisionStatus.APPLIED)
    assert decision.gate is not None
    assert decision.gate.status is (HumanGateStatus.PAUSED_NEEDS_HUMAN)


def test_other_owner_cannot_find_the_current_brief() -> None:
    """Avoid exposing another owner's Project Brief gate."""
    current_briefs = InMemoryCurrentBriefRepository()
    gates = InMemoryHumanGateRepository()
    current_briefs.set_current(
        owner_user_id=OWNER_ID,
        version=(complete_brief_version()),
    )
    service = build_service(
        current_briefs,
        gates,
    )

    result = asyncio.run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=(OTHER_OWNER_ID),
        )
    )

    assert result.status is (ProjectBriefGateSubmissionStatus.BRIEF_NOT_FOUND)
    assert gates.gates == []
