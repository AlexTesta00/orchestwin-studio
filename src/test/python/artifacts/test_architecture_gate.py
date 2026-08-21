"""Tests for Gate 6 Architecture Package approval behavior."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.artifacts.architecture_gate import (
    ArchitectureGateDecisionStatus,
    ArchitectureGateSubmissionStatus,
    ArchitectureWorkflowReadiness,
    LocalArchitectureGateService,
    architecture_artifact_reference,
)
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEvent,
    HumanGateIssueCode,
    HumanGateStatus,
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

from .architecture_fixtures import (
    ARCHITECTURE_CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    architecture_version,
)

VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000801")
STARTED_AT = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)


def version_one() -> ArchitecturePackageVersion:
    """Create one current Architecture Package for Gate 6."""
    return replace(
        architecture_version(),
        created_at=ARCHITECTURE_CREATED_AT,
    )


def version_two() -> ArchitecturePackageVersion:
    """Create a newer immutable Architecture Package for stale-gate tests."""
    first = version_one()
    package = replace(
        first.package,
        open_questions=(
            *first.package.open_questions,
            "Should the execution profile remain unresolved?",
        ),
    )

    return ArchitecturePackageVersion(
        id=VERSION_TWO_ID,
        project_id=PROJECT_ID,
        version_number=2,
        based_on_version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=ARCHITECTURE_CREATED_AT + timedelta(minutes=10),
    )


class InMemoryPackages:
    """Return one configurable owner-scoped current Architecture Package."""

    def __init__(self, current: ArchitecturePackageVersion | None) -> None:
        self.current = current

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return None

        return self.current


class InMemoryGates:
    """Persist Gate 6 state and append-only events in memory."""

    def __init__(self) -> None:
        self.latest: HumanGate | None = None
        self.events: list[HumanGateEvent] = []

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        self.latest = gate
        self.events.append(event)
        return gate

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        if (
            project_id != PROJECT_ID
            or owner_user_id != OWNER_ID
            or gate_type is not HumanGateType.ARCHITECTURE
        ):
            return None

        return self.latest

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        if self.latest != previous_gate:
            raise AssertionError("in-memory Gate 6 state changed")

        self.latest = updated_gate
        self.events.append(event)
        return updated_gate

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return ()

        return tuple(event for event in self.events if event.gate_id == gate_id)


class InMemoryGateUnitOfWork:
    """Expose shared package and gate repositories."""

    def __init__(self, packages: InMemoryPackages, gates: InMemoryGates) -> None:
        self.packages = packages
        self.gates = gates

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class InMemoryGateUowFactory:
    """Create Gate 6 units over shared in-memory state."""

    def __init__(self, packages: InMemoryPackages, gates: InMemoryGates) -> None:
        self.packages = packages
        self.gates = gates

    def __call__(self, *, owner_user_id: UUID) -> InMemoryGateUnitOfWork:
        assert owner_user_id == OWNER_ID
        return InMemoryGateUnitOfWork(self.packages, self.gates)


class MutableClock:
    """Provide deterministic monotonic Gate 6 timestamps."""

    def __init__(self) -> None:
        self.current = STARTED_AT + timedelta(minutes=20)

    def __call__(self) -> datetime:
        return self.current

    def advance(self) -> None:
        self.current += timedelta(minutes=1)


class SequentialIds:
    """Provide deterministic unique gate and event IDs."""

    def __init__(self, start: int) -> None:
        self.value = start

    def __call__(self) -> UUID:
        result = UUID(int=self.value)
        self.value += 1
        return result


def service_fixture(current: ArchitecturePackageVersion | None):
    """Create one deterministic Gate 6 service fixture."""
    packages = InMemoryPackages(current)
    gates = InMemoryGates()
    clock = MutableClock()
    service = LocalArchitectureGateService(
        unit_of_work_factory=InMemoryGateUowFactory(packages, gates),
        clock=clock,
        gate_id_factory=SequentialIds(800),
        event_id_factory=SequentialIds(900),
    )

    return service, packages, gates, clock


def run(coroutine):
    """Run one async Gate 6 use case synchronously."""
    return asyncio.run(coroutine)


def test_gate_six_approves_the_exact_architecture_package() -> None:
    """Move from submission to implementation readiness for one exact version."""
    service, _packages, gates, clock = service_fixture(version_one())

    submitted = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert submitted.status is ArchitectureGateSubmissionStatus.SUBMITTED
    assert submitted.gate is not None
    assert submitted.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert submitted.gate.gate_type is HumanGateType.ARCHITECTURE
    assert submitted.gate.artifact == architecture_artifact_reference(version_one())

    clock.advance()
    approved = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.APPROVE,
        )
    )
    readiness = run(
        service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert approved.status is ArchitectureGateDecisionStatus.APPLIED
    assert approved.gate is not None
    assert approved.gate.status is HumanGateStatus.APPROVED
    assert readiness.status is ArchitectureWorkflowReadiness.READY_FOR_IMPLEMENTATION
    assert len(gates.events) == 2


def test_gate_six_request_revision_reaches_human_pause_at_limit() -> None:
    """Prevent an unbounded architecture-planning revision loop."""
    service, _packages, gates, clock = service_fixture(version_one())
    exact_draft = create_human_gate(
        gate_id=UUID(int=1001),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.ARCHITECTURE,
        artifact=architecture_artifact_reference(version_one()),
        iteration=3,
        max_iterations=3,
        created_at=clock.current,
    )
    pending = transition_human_gate(
        exact_draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=clock.current,
        event_id=UUID(int=1002),
    )
    assert pending.event is not None
    gates.latest = pending.gate
    gates.events.append(pending.event)
    clock.advance()

    result = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.REQUEST_REVISION,
            reason="Revise the component boundaries and test strategy before approval.",
        )
    )

    assert result.status is ArchitectureGateDecisionStatus.APPLIED
    assert result.gate is not None
    assert result.gate.status is HumanGateStatus.PAUSED_NEEDS_HUMAN


def test_newer_architecture_package_invalidates_an_approved_gate() -> None:
    """Do not carry Gate 6 approval from version one to version two."""
    service, packages, gates, clock = service_fixture(version_one())
    run(service.submit(project_id=PROJECT_ID, owner_user_id=OWNER_ID))
    clock.advance()
    run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.APPROVE,
        )
    )

    packages.current = version_two()
    clock.advance()
    readiness = run(
        service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    stale = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.APPROVE,
        )
    )

    assert readiness.status is ArchitectureWorkflowReadiness.ARCHITECTURE_APPROVAL_REQUIRED
    assert stale.status is ArchitectureGateDecisionStatus.ARTIFACT_STALE
    assert stale.gate is not None
    assert stale.gate.status is HumanGateStatus.STALE
    assert gates.latest == stale.gate


def test_gate_six_reject_requires_an_owner_reason() -> None:
    """Preserve the generic human-gate reason policy at Gate 6."""
    service, _packages, _gates, clock = service_fixture(version_one())
    run(service.submit(project_id=PROJECT_ID, owner_user_id=OWNER_ID))
    clock.advance()

    result = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.REJECT,
        )
    )

    assert result.status is ArchitectureGateDecisionStatus.REJECTED
    assert result.issue is HumanGateIssueCode.REASON_REQUIRED


def test_gate_six_reports_missing_package_without_creating_state() -> None:
    """Return a typed blocker when no Architecture Package exists."""
    service, _packages, gates, _clock = service_fixture(None)

    result = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is ArchitectureGateSubmissionStatus.PACKAGE_NOT_FOUND
    assert gates.latest is None
    assert gates.events == []
