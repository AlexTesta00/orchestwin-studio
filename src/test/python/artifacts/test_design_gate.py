"""Tests for Gate 5 Design Package approval behavior."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

import pytest

from orchestwin.artifacts.design_gate import (
    DesignGateDecisionStatus,
    DesignGateSubmissionStatus,
    DesignWorkflowReadiness,
    LocalDesignGateService,
    design_artifact_reference,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
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

from .design_fixtures import (
    CREATED_AT,
    OWNER_ID,
    PROJECT_ID,
    design_package,
    design_version,
)

VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000801")
STARTED_AT = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)


def version_one(*, ready: bool = True) -> DesignPackageVersion:
    """Create one current Design Package with configurable Gate 5 readiness."""
    package = design_package() if ready else design_package(selected=False, include_prototype=False)
    return replace(
        design_version(package=package),
        created_at=CREATED_AT,
    )


def version_two() -> DesignPackageVersion:
    """Create a newer immutable Design Package for stale-gate tests."""
    first = version_one()
    package = replace(
        first.package,
        open_questions=(
            *first.package.open_questions,
            "Should expert shortcuts remain visible?",
        ),
    )

    return DesignPackageVersion(
        id=VERSION_TWO_ID,
        project_id=PROJECT_ID,
        version_number=2,
        based_on_version_number=1,
        package=package,
        content_hash=package.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT + timedelta(minutes=10),
    )


class InMemoryPackages:
    """Return one configurable owner-scoped current Design Package."""

    def __init__(self, current: DesignPackageVersion | None) -> None:
        self.current = current

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignPackageVersion | None:
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return None

        return self.current


class InMemoryGates:
    """Persist Gate 5 state and append-only events in memory."""

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
            or gate_type is not HumanGateType.DESIGN
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
            raise AssertionError("in-memory Gate 5 state changed")

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
    """Create Gate 5 units over shared in-memory state."""

    def __init__(self, packages: InMemoryPackages, gates: InMemoryGates) -> None:
        self.packages = packages
        self.gates = gates

    def __call__(self, *, owner_user_id: UUID) -> InMemoryGateUnitOfWork:
        assert owner_user_id == OWNER_ID
        return InMemoryGateUnitOfWork(self.packages, self.gates)


class MutableClock:
    """Provide deterministic monotonic Gate 5 timestamps."""

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


def service_fixture(current: DesignPackageVersion | None):
    """Create one deterministic Gate 5 service fixture."""
    packages = InMemoryPackages(current)
    gates = InMemoryGates()
    clock = MutableClock()
    service = LocalDesignGateService(
        unit_of_work_factory=InMemoryGateUowFactory(packages, gates),
        clock=clock,
        gate_id_factory=SequentialIds(800),
        event_id_factory=SequentialIds(900),
    )

    return service, packages, gates, clock


def run(coroutine):
    """Run one async Gate 5 use case synchronously."""
    return asyncio.run(coroutine)


def test_gate_five_approves_the_exact_ready_design_package() -> None:
    """Move from submission to architecture readiness for one exact version."""
    service, _packages, gates, clock = service_fixture(version_one())

    submitted = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert submitted.status is DesignGateSubmissionStatus.SUBMITTED
    assert submitted.gate is not None
    assert submitted.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert submitted.gate.gate_type is HumanGateType.DESIGN
    assert submitted.gate.artifact == design_artifact_reference(version_one())

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

    assert approved.status is DesignGateDecisionStatus.APPLIED
    assert approved.gate is not None
    assert approved.gate.status is HumanGateStatus.APPROVED
    assert readiness.status is DesignWorkflowReadiness.READY_FOR_ARCHITECTURE_PLANNING
    assert len(gates.events) == 2


def test_gate_five_requires_owner_selection_and_a_declarative_prototype() -> None:
    """Do not submit alternatives alone before owner convergence."""
    service, _packages, gates, _clock = service_fixture(version_one(ready=False))

    submission = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    readiness = run(
        service.readiness(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert submission.status is DesignGateSubmissionStatus.PACKAGE_NOT_READY
    assert readiness.status is DesignWorkflowReadiness.DESIGN_REVIEW_REQUIRED
    assert gates.latest is None
    assert gates.events == []


def test_gate_five_request_revision_reaches_human_pause_at_limit() -> None:
    """Prevent an unbounded design revision loop."""
    service, _packages, gates, clock = service_fixture(version_one())
    exact_draft = create_human_gate(
        gate_id=UUID(int=1001),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.DESIGN,
        artifact=design_artifact_reference(version_one()),
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
            reason="Compare the focused workflow against the dashboard direction.",
        )
    )

    assert result.status is DesignGateDecisionStatus.APPLIED
    assert result.gate is not None
    assert result.gate.status is HumanGateStatus.PAUSED_NEEDS_HUMAN


def test_newer_design_package_invalidates_an_approved_gate() -> None:
    """Do not carry Gate 5 approval from version one to version two."""
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

    assert readiness.status is DesignWorkflowReadiness.DESIGN_APPROVAL_REQUIRED
    assert stale.status is DesignGateDecisionStatus.ARTIFACT_STALE
    assert stale.gate is not None
    assert stale.gate.status is HumanGateStatus.STALE
    assert gates.latest == stale.gate


def test_gate_five_reject_requires_an_owner_reason() -> None:
    """Preserve the generic human-gate reason policy at Gate 5."""
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

    assert result.status is DesignGateDecisionStatus.REJECTED
    assert result.issue is HumanGateIssueCode.REASON_REQUIRED


def test_gate_five_reports_missing_package_without_creating_state() -> None:
    """Return a typed blocker when no Design Package exists."""
    service, _packages, gates, _clock = service_fixture(None)

    result = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is DesignGateSubmissionStatus.PACKAGE_NOT_FOUND
    assert gates.latest is None
    assert gates.events == []


def numbered_version(number: int) -> DesignPackageVersion:
    first = design_package()

    return design_version(
        version_number=number,
        package=replace(
            first,
            open_questions=(
                *first.open_questions,
                f"Does version {number} keep the guided path?",
            ),
        ),
    )


def design_attempt(
    service: LocalDesignGateService,
    packages: InMemoryPackages,
    clock: MutableClock,
    number: int,
    action: HumanGateAction,
):
    packages.current = numbered_version(number)
    clock.advance()
    submitted = run(service.submit(project_id=PROJECT_ID, owner_user_id=OWNER_ID))

    if submitted.status is not DesignGateSubmissionStatus.SUBMITTED:
        return submitted, None

    clock.advance()
    decided = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=action,
            reason=(None if action is HumanGateAction.APPROVE else "Not this design."),
        )
    )

    assert decided.status is DesignGateDecisionStatus.APPLIED
    assert decided.gate is not None
    assert 1 <= decided.gate.iteration <= decided.gate.max_iterations

    return submitted, decided.gate


def test_every_approved_design_package_renews_the_budget_of_attempts() -> None:
    service, packages, gates, clock = service_fixture(None)

    approved = [
        design_attempt(
            service,
            packages,
            clock,
            number,
            HumanGateAction.APPROVE,
        )[1]
        for number in range(1, 6)
    ]

    assert [(gate.iteration, gate.max_iterations) for gate in approved if gate is not None] == [
        (1, 3),
        (2, 4),
        (3, 5),
        (4, 6),
        (5, 7),
    ]
    assert gates.latest == approved[-1]


@pytest.mark.parametrize("approvals", [0, 1, 4])
def test_three_rejected_design_packages_in_a_row_still_reach_the_limit(
    approvals: int,
) -> None:
    service, packages, _gates, clock = service_fixture(None)

    for number in range(1, approvals + 1):
        design_attempt(service, packages, clock, number, HumanGateAction.APPROVE)

    rejected = [
        design_attempt(service, packages, clock, number, HumanGateAction.REJECT)[1]
        for number in range(approvals + 1, approvals + 4)
    ]
    refused, _ = design_attempt(
        service,
        packages,
        clock,
        approvals + 4,
        HumanGateAction.APPROVE,
    )

    assert [gate.status for gate in rejected if gate is not None] == [HumanGateStatus.REJECTED] * 3
    assert refused.status is DesignGateSubmissionStatus.ITERATION_LIMIT_REACHED
    assert refused.gate is not None
    assert (refused.gate.iteration, refused.gate.max_iterations) == (
        approvals + 3,
        approvals + 3,
    )


@pytest.mark.parametrize("approvals", [0, 1, 4])
def test_three_design_packages_sent_back_in_a_row_still_pause_for_a_person(
    approvals: int,
) -> None:
    service, packages, _gates, clock = service_fixture(None)

    for number in range(1, approvals + 1):
        design_attempt(service, packages, clock, number, HumanGateAction.APPROVE)

    sent_back = [
        design_attempt(service, packages, clock, number, HumanGateAction.REQUEST_REVISION)[1]
        for number in range(approvals + 1, approvals + 4)
    ]
    blocked, _ = design_attempt(
        service,
        packages,
        clock,
        approvals + 4,
        HumanGateAction.APPROVE,
    )
    paused = sent_back[-1]

    assert [gate.status for gate in sent_back if gate is not None] == [
        HumanGateStatus.REVISION_REQUESTED,
        HumanGateStatus.REVISION_REQUESTED,
        HumanGateStatus.PAUSED_NEEDS_HUMAN,
    ]
    assert paused is not None
    assert (paused.iteration, paused.max_iterations) == (
        approvals + 3,
        approvals + 3,
    )
    assert blocked.status is DesignGateSubmissionStatus.GATE_BLOCKED


def test_an_approval_found_stale_before_the_next_design_package_still_renews_the_budget() -> None:
    service, packages, _gates, clock = service_fixture(None)

    for number in range(1, 4):
        design_attempt(service, packages, clock, number, HumanGateAction.APPROVE)

    packages.current = numbered_version(4)
    clock.advance()
    stale = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.APPROVE,
        )
    )
    submitted = run(service.submit(project_id=PROJECT_ID, owner_user_id=OWNER_ID))

    assert stale.status is DesignGateDecisionStatus.ARTIFACT_STALE
    assert submitted.status is DesignGateSubmissionStatus.SUBMITTED
    assert submitted.gate is not None
    assert (submitted.gate.iteration, submitted.gate.max_iterations) == (4, 6)
