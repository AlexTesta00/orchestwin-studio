from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.projects.requirements import (
    RequirementKind,
    RequirementPriority,
    create_requirement,
    create_user_story,
)
from orchestwin.projects.requirements_gate import (
    LocalRequirementsGateService,
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionStatus,
    RequirementsWorkflowReadiness,
    requirements_artifact_reference,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    RequirementSourceKind,
    RequirementSourceReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_quality import (
    DefinitionOfDoneApplicability,
    VerificationMethod,
    create_acceptance_criterion,
    create_definition_of_done_item,
    create_usage_scenario,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
    create_requirements_specification,
)
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

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
VERSION_ONE_ID = UUID("00000000-0000-4000-8000-000000000003")
VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000000004")
REQUIREMENT_ID = UUID("00000000-0000-4000-8000-000000000010")
STORY_ID = UUID("00000000-0000-4000-8000-000000000020")
CRITERION_ID = UUID("00000000-0000-4000-8000-000000000030")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000000040")
DOD_ID = UUID("00000000-0000-4000-8000-000000000050")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000060")
STARTED_AT = datetime(2026, 8, 18, 11, 0, tzinfo=UTC)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed context reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:x}" * 64,
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def version_one() -> RequirementsSpecificationVersion:
    """Create the initial complete requirements specification version."""
    source = RequirementSourceReference(
        kind=RequirementSourceKind.PROJECT_BRIEF,
        source_id="brief-version",
        source_version=1,
        content_hash="b" * 64,
        locator="functional_requirements[0]",
    )
    requirement = create_requirement(
        requirement_id=REQUIREMENT_ID,
        code="REQ-001",
        title="Create reservations",
        statement="The system must create reservations.",
        kind=RequirementKind.FUNCTIONAL,
        priority=RequirementPriority.MUST,
        sources=(source,),
        user_twin_references=(twin_reference(),),
    )
    story = create_user_story(
        story_id=STORY_ID,
        code="USR-001",
        user_twin_reference=twin_reference(),
        goal="create a reservation",
        benefit="serve a guest accurately",
        requirement_ids=(REQUIREMENT_ID,),
    )
    criterion = create_acceptance_criterion(
        criterion_id=CRITERION_ID,
        code="AC-001",
        statement="A reservation receives a unique identifier.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        requirement_ids=(REQUIREMENT_ID,),
        user_story_ids=(STORY_ID,),
    )
    scenario = create_usage_scenario(
        scenario_id=SCENARIO_ID,
        code="SCN-001",
        title="Create a reservation",
        actor=twin_reference(),
        preconditions=(),
        trigger="A guest requests a room.",
        steps=("Save the reservation.",),
        expected_outcome="The reservation can be retrieved.",
        requirement_ids=(REQUIREMENT_ID,),
        acceptance_criterion_ids=(CRITERION_ID,),
    )
    done = create_definition_of_done_item(
        item_id=DOD_ID,
        code="DOD-001",
        statement="All automated acceptance tests pass.",
        verification_method=VerificationMethod.AUTOMATED_TEST,
        applicability=DefinitionOfDoneApplicability.REQUIRED,
        requirement_ids=(REQUIREMENT_ID,),
    )
    specification = create_requirements_specification(
        project_id=PROJECT_ID,
        project_brief_reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        agent_team_reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        user_modeling_reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        catalog_version=1,
        catalog_content_hash="c" * 64,
        user_twin_references=(twin_reference(),),
        requirements=(requirement,),
        user_stories=(story,),
        acceptance_criteria=(criterion,),
        scenarios=(scenario,),
        risks=(),
        definition_of_done=(done,),
    )

    return RequirementsSpecificationVersion(
        id=VERSION_ONE_ID,
        project_id=PROJECT_ID,
        version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=STARTED_AT,
    )


def version_two() -> RequirementsSpecificationVersion:
    """Create a newer immutable specification for stale-gate tests."""
    first = version_one()
    requirement = replace(
        first.specification.requirements[0],
        statement="The system must create and update reservations.",
    )
    specification = replace(
        first.specification,
        requirements=(requirement,),
    )

    return RequirementsSpecificationVersion(
        id=VERSION_TWO_ID,
        project_id=PROJECT_ID,
        version_number=2,
        based_on_version_number=1,
        specification=specification,
        content_hash=specification.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=STARTED_AT + timedelta(minutes=10),
    )


class InMemorySpecifications:
    """Return one configurable owner-scoped current specification."""

    def __init__(
        self,
        current: RequirementsSpecificationVersion | None,
    ) -> None:
        self.current = current

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        if project_id != PROJECT_ID or owner_user_id != OWNER_ID:
            return None

        return self.current


class InMemoryGates:
    """Persist Gate 4 state and append-only events in memory."""

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
            or gate_type is not HumanGateType.REQUIREMENTS
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
            raise AssertionError("in-memory Gate 4 state changed")

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
    """Expose shared specification and gate repositories."""

    def __init__(
        self,
        specifications: InMemorySpecifications,
        gates: InMemoryGates,
    ) -> None:
        self.specifications = specifications
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
    """Create Gate 4 units over shared in-memory state."""

    def __init__(
        self,
        specifications: InMemorySpecifications,
        gates: InMemoryGates,
    ) -> None:
        self.specifications = specifications
        self.gates = gates

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> InMemoryGateUnitOfWork:
        assert owner_user_id == OWNER_ID
        return InMemoryGateUnitOfWork(
            self.specifications,
            self.gates,
        )


class MutableClock:
    """Provide deterministic monotonic Gate 4 timestamps."""

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


def service_fixture(
    current: RequirementsSpecificationVersion | None,
) -> tuple[
    LocalRequirementsGateService,
    InMemorySpecifications,
    InMemoryGates,
    MutableClock,
]:
    """Create one deterministic Gate 4 service fixture."""
    specifications = InMemorySpecifications(current)
    gates = InMemoryGates()
    clock = MutableClock()
    service = LocalRequirementsGateService(
        unit_of_work_factory=InMemoryGateUowFactory(
            specifications,
            gates,
        ),
        clock=clock,
        gate_id_factory=SequentialIds(100),
        event_id_factory=SequentialIds(200),
    )

    return service, specifications, gates, clock


def run(coroutine):
    """Run one async Gate 4 use case synchronously."""
    return asyncio.run(coroutine)


def test_gate_four_approves_the_exact_current_specification() -> None:
    """Move from submission to design readiness for one exact version."""
    service, _specifications, gates, clock = service_fixture(version_one())

    submitted = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert submitted.status is RequirementsGateSubmissionStatus.SUBMITTED
    assert submitted.gate is not None
    assert submitted.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert submitted.gate.artifact.artifact_id == VERSION_ONE_ID
    assert submitted.gate.artifact.version == 1
    assert submitted.gate.artifact.content_hash == version_one().content_hash

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

    assert approved.status is RequirementsGateDecisionStatus.APPLIED
    assert approved.gate is not None
    assert approved.gate.status is HumanGateStatus.APPROVED
    assert readiness.status is (RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION)
    assert len(gates.events) == 2


def test_gate_four_request_revision_reaches_human_pause_at_limit() -> None:
    """Prevent an unbounded requirements revision loop."""
    service, _specifications, gates, clock = service_fixture(version_one())
    exact_draft = create_human_gate(
        gate_id=UUID(int=301),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact=requirements_artifact_reference(version_one()),
        iteration=3,
        max_iterations=3,
        created_at=clock.current,
    )
    pending = transition_human_gate(
        exact_draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=clock.current,
        event_id=UUID(int=302),
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
            reason="Clarify the concurrency acceptance criterion.",
        )
    )

    assert result.status is RequirementsGateDecisionStatus.APPLIED
    assert result.gate is not None
    assert result.gate.status is HumanGateStatus.PAUSED_NEEDS_HUMAN


def test_newer_specification_invalidates_an_approved_gate() -> None:
    """Do not carry Gate 4 approval from version one to version two."""
    service, specifications, gates, clock = service_fixture(version_one())
    run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    clock.advance()
    run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.APPROVE,
        )
    )

    specifications.current = version_two()
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

    assert readiness.status is (RequirementsWorkflowReadiness.REQUIREMENTS_APPROVAL_REQUIRED)
    assert stale.status is RequirementsGateDecisionStatus.ARTIFACT_STALE
    assert stale.gate is not None
    assert stale.gate.status is HumanGateStatus.STALE
    assert gates.latest == stale.gate


def test_gate_four_reject_requires_an_owner_reason() -> None:
    """Preserve the generic human-gate reason policy at Gate 4."""
    service, _specifications, _gates, clock = service_fixture(version_one())
    run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )
    clock.advance()

    result = run(
        service.decide(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            action=HumanGateAction.REJECT,
        )
    )

    assert result.status is RequirementsGateDecisionStatus.REJECTED
    assert result.issue is HumanGateIssueCode.REASON_REQUIRED


def test_gate_four_reports_missing_specification_without_creating_state() -> None:
    """Return a typed blocker when no requirements baseline exists."""
    service, _specifications, gates, _clock = service_fixture(None)

    result = run(
        service.submit(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert result.status is (RequirementsGateSubmissionStatus.SPECIFICATION_NOT_FOUND)
    assert gates.latest is None
    assert gates.events == []
