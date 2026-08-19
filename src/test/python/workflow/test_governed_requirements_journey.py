"""Sprint 05 acceptance test for the governed Requirements journey."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.models.fake_requirements import FakeDeterministicRequirementsAdapter
from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
    RequirementsUserTwinInput,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_application import (
    GovernedRequirementsContext,
    LocalRequirementsGenerationService,
    RequirementsGenerationStatus,
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_gate import (
    LocalRequirementsGateService,
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionStatus,
    RequirementsWorkflowReadiness,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_revision_application import (
    LocalRequirementsRevisionService,
    RequirementsDiffPersistenceStatus,
    RequirementsRevisionDecision,
    RequirementsRevisionStatus,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffStatus,
    RequirementsSpecificationDiff,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.projects.requirements_traceability import (
    build_requirements_traceability,
    summarize_requirements_coverage,
)
from orchestwin.twins.epistemics import (
    ConfidenceScore,
    EpistemicStatus,
    EvidenceReference,
    EvidenceSourceKind,
    HumanValidationRequirement,
    ObservationProvenance,
    ObservationValue,
    ProfileObservation,
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
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000020")

SPECIFICATION_V1_ID = UUID("00000000-0000-4000-8000-000000000101")
DIFF_V1_ID = UUID("00000000-0000-4000-8000-000000000102")
SPECIFICATION_V2_ID = UUID("00000000-0000-4000-8000-000000000103")
DIFF_V2_ID = UUID("00000000-0000-4000-8000-000000000104")
SPECIFICATION_V3_ID = UUID("00000000-0000-4000-8000-000000000105")

GATE_V2_ID = UUID("00000000-0000-4000-8000-000000000201")
GATE_V3_ID = UUID("00000000-0000-4000-8000-000000000202")
GATE_V2_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000211")
GATE_V2_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000212")
GATE_V2_STALE_EVENT_ID = UUID("00000000-0000-4000-8000-000000000213")
GATE_V3_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000000214")

BASE_TIME = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


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
    """Create the exact User Twin used by the requirements provider."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name="Hotel Receptionist Twin",
    )


def goal_observation() -> ProfileObservation:
    """Create one user-provided User Twin goal with inspectable evidence."""
    return ProfileObservation(
        observation_key="user_twin.goals",
        value=ObservationValue.from_items(("Reduce booking errors",)),
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(1.0),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.PROJECT_BRIEF,
                    source_id="brief-version",
                    source_version=1,
                    content_hash="b" * 64,
                    locator="goals[0]",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )


def approved_context_gate(
    *,
    gate_id: UUID,
    gate_type: HumanGateType,
    reference: RequirementsContextReference,
    ordinal: int,
) -> HumanGate:
    """Create an approved human gate for one exact upstream artifact."""
    draft = create_human_gate(
        gate_id=gate_id,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=gate_type,
            artifact_id=reference.artifact_id,
            version=reference.version_number,
            content_hash=reference.content_hash,
        ),
        created_at=BASE_TIME + timedelta(minutes=ordinal),
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=BASE_TIME + timedelta(minutes=ordinal + 1),
        event_id=UUID(int=1000 + ordinal),
    )
    assert submitted.status is HumanGateTransitionStatus.APPLIED

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=BASE_TIME + timedelta(minutes=ordinal + 2),
        event_id=UUID(int=2000 + ordinal),
    )
    assert approved.status is HumanGateTransitionStatus.APPLIED

    return approved.gate


def governed_context() -> GovernedRequirementsContext:
    """Create exact Brief, Team, and User Modeling inputs approved by Gates one,two,three."""
    brief_reference = context_reference(RequirementsContextKind.PROJECT_BRIEF, 11)
    team_reference = context_reference(RequirementsContextKind.AGENT_TEAM, 12)
    modeling_reference = context_reference(RequirementsContextKind.USER_MODELING, 13)
    selected = {
        AgentIdentifier.WORKFLOW_ORCHESTRATOR,
        AgentIdentifier.REQUIREMENTS_ANALYST,
        AgentIdentifier.QA_TEST_ENGINEER,
    }

    brief = RequirementsBriefInput(
        reference=brief_reference,
        name="Hotel Operations",
        problem="Reservation updates are error-prone.",
        goals=("Reduce booking errors",),
        target_users=("Hotel receptionists",),
        technical_constraints=("Use PostgreSQL",),
        functional_requirements=(
            "Create and update reservations",
            "Search room availability",
        ),
        non_functional_requirements=("Reservation searches respond promptly",),
        risks=("Concurrent updates may create conflicts",),
        definition_of_done=("All automated tests pass",),
    )
    team = RequirementsTeamInput(
        reference=team_reference,
        selected_agent_ids=tuple(
            entry.agent_id for entry in all_agent_catalog_entries() if entry.agent_id in selected
        ),
    )
    user_modeling = RequirementsUserModelingInput(
        reference=modeling_reference,
        user_twins=(
            RequirementsUserTwinInput(
                reference=twin_reference(),
                observations=(goal_observation(),),
            ),
        ),
    )

    return GovernedRequirementsContext(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        brief=brief,
        team=team,
        user_modeling=user_modeling,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        brief_gate=approved_context_gate(
            gate_id=UUID(int=301),
            gate_type=HumanGateType.PROJECT_BRIEF,
            reference=brief_reference,
            ordinal=1,
        ),
        team_gate=approved_context_gate(
            gate_id=UUID(int=302),
            gate_type=HumanGateType.AGENT_TEAM,
            reference=team_reference,
            ordinal=4,
        ),
        user_modeling_gate=approved_context_gate(
            gate_id=UUID(int=303),
            gate_type=HumanGateType.USER_MODELING,
            reference=modeling_reference,
            ordinal=7,
        ),
    )


@dataclass(slots=True)
class InMemoryRequirementsState:
    """Shared mutable state for the acceptance-test persistence adapters."""

    versions: list[RequirementsSpecificationVersion]
    diffs: dict[UUID, RequirementsSpecificationDiff]
    gates: list[HumanGate]
    events: list[HumanGateEvent]


class InMemoryGovernance:
    """Expose one stable governed context."""

    def __init__(self, context: GovernedRequirementsContext) -> None:
        self._context = context

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedRequirementsContext | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None

        return self._context


class InMemorySpecificationRepository:
    """Append-only specification repository used by all journey services."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self._state = state

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        versions = [value for value in self._state.versions if value.project_id == project_id]
        return versions[-1] if versions else None

    async def append(
        self,
        version: RequirementsSpecificationVersion,
    ) -> RequirementsVersionAppendStatus:
        current = await self.current(project_id=version.project_id)

        if current is None:
            if version.version_number != 1:
                return RequirementsVersionAppendStatus.VERSION_CONFLICT
        elif (
            version.version_number != current.version_number + 1
            or version.based_on_version_number != current.version_number
        ):
            return RequirementsVersionAppendStatus.VERSION_CONFLICT
        elif version.content_hash == current.content_hash:
            return RequirementsVersionAppendStatus.CONTENT_CONFLICT

        self._state.versions.append(version)
        return RequirementsVersionAppendStatus.APPENDED

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        if owner_user_id != OWNER_ID:
            return None

        return await self.current(project_id=project_id)


class InMemoryDiffRepository:
    """Reviewable requirements-diff repository."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self._state = state

    async def create(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        if diff.id in self._state.diffs:
            return RequirementsDiffPersistenceStatus.CONFLICT

        self._state.diffs[diff.id] = diff
        return RequirementsDiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        diff = self._state.diffs.get(diff_id)
        return diff if diff is not None and diff.project_id == project_id else None

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        return next(
            (
                diff
                for diff in self._state.diffs.values()
                if diff.project_id == project_id
                and diff.base_version_id == base_version_id
                and diff.status is RequirementsDiffStatus.PROPOSED
            ),
            None,
        )

    async def save_decision(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        current = self._state.diffs.get(diff.id)

        if current is None or current.status is not RequirementsDiffStatus.PROPOSED:
            return RequirementsDiffPersistenceStatus.CONFLICT

        self._state.diffs[diff.id] = diff
        return RequirementsDiffPersistenceStatus.UPDATED


class InMemoryRequirementsUnitOfWork:
    """No-op transaction boundary over shared in-memory state."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self.specifications = InMemorySpecificationRepository(state)
        self.diffs = InMemoryDiffRepository(state)

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class InMemoryRequirementsUnitOfWorkFactory:
    """Create command Units of Work over shared in-memory state."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self._state = state

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> InMemoryRequirementsUnitOfWork:
        assert owner_user_id == OWNER_ID
        return InMemoryRequirementsUnitOfWork(self._state)


class InMemoryGateRepository:
    """Persist Gate 4 state transitions and append-only events."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self._state = state

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: HumanGateType,
    ) -> HumanGate | None:
        candidates = [
            gate
            for gate in self._state.gates
            if gate.project_id == project_id
            and gate.owner_user_id == owner_user_id
            and gate.gate_type is gate_type
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda gate: (gate.iteration, gate.created_at, gate.id.hex))

    async def add_with_event(
        self,
        *,
        gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        self._state.gates.append(gate)
        self._state.events.append(event)
        return gate

    async def save_transition(
        self,
        *,
        previous_gate: HumanGate,
        updated_gate: HumanGate,
        event: HumanGateEvent,
    ) -> HumanGate:
        for index, current in enumerate(self._state.gates):
            if current.id == previous_gate.id:
                if current != previous_gate:
                    raise RuntimeError("Gate 4 changed concurrently in the acceptance fixture")

                self._state.gates[index] = updated_gate
                self._state.events.append(event)
                return updated_gate

        raise RuntimeError("Gate 4 is missing from the acceptance fixture")

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        gate_ids = {
            gate.id
            for gate in self._state.gates
            if gate.project_id == project_id and gate.owner_user_id == owner_user_id
        }

        if gate_id not in gate_ids:
            return ()

        return tuple(
            sorted(
                (event for event in self._state.events if event.gate_id == gate_id),
                key=lambda event: event.sequence_number,
            )
        )


class InMemoryGateUnitOfWork:
    """Gate transaction boundary over shared in-memory state."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self.specifications = InMemorySpecificationRepository(state)
        self.gates = InMemoryGateRepository(state)

    async def __aenter__(self):
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback


class InMemoryGateUnitOfWorkFactory:
    """Create Gate 4 Units of Work over shared state."""

    def __init__(self, state: InMemoryRequirementsState) -> None:
        self._state = state

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> InMemoryGateUnitOfWork:
        assert owner_user_id == OWNER_ID
        return InMemoryGateUnitOfWork(self._state)


def iterator_factory(values):
    """Return one deterministic zero-argument factory."""
    iterator = iter(values)

    def next_value():
        return next(iterator)

    return next_value


def revised_specification(
    version: RequirementsSpecificationVersion,
    statement: str,
):
    """Return a complete replacement preserving stable artifact identity."""
    requirement = replace(
        version.specification.requirements[0],
        statement=statement,
    )

    return replace(
        version.specification,
        requirements=(requirement, *version.specification.requirements[1:]),
    )


async def run_governed_requirements_journey() -> None:
    """Run generation, owner revision, Gate 4 approval, and staleness."""
    state = InMemoryRequirementsState(
        versions=[],
        diffs={},
        gates=[],
        events=[],
    )
    command_uow_factory = InMemoryRequirementsUnitOfWorkFactory(state)
    generation = LocalRequirementsGenerationService(
        governance=InMemoryGovernance(governed_context()),
        proposals=FakeDeterministicRequirementsAdapter(),
        uow_factory=command_uow_factory,
        uuid_factory=lambda: SPECIFICATION_V1_ID,
        clock=lambda: BASE_TIME + timedelta(minutes=20),
    )

    generated = await generation.generate(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
    )

    assert generated.status is RequirementsGenerationStatus.CREATED
    assert generated.version is not None
    assert generated.version.id == SPECIFICATION_V1_ID
    assert generated.version.version_number == 1

    revisions = LocalRequirementsRevisionService(
        uow_factory=command_uow_factory,
        uuid_factory=iterator_factory(
            (DIFF_V1_ID, SPECIFICATION_V2_ID, DIFF_V2_ID, SPECIFICATION_V3_ID)
        ),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=21),
                BASE_TIME + timedelta(minutes=22),
                BASE_TIME + timedelta(minutes=31),
                BASE_TIME + timedelta(minutes=32),
            )
        ),
    )
    proposed_v2 = await revisions.propose_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        proposed_specification=revised_specification(
            generated.version,
            ("Create and update reservations while preventing overlapping room allocations."),
        ),
    )

    assert proposed_v2.status is RequirementsRevisionStatus.CREATED
    assert proposed_v2.diff is not None
    assert proposed_v2.diff.status is RequirementsDiffStatus.PROPOSED

    approved_v2 = await revisions.decide_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        diff_id=DIFF_V1_ID,
        decision=RequirementsRevisionDecision.APPROVE,
    )

    assert approved_v2.status is RequirementsRevisionStatus.APPLIED
    assert approved_v2.version is not None
    assert approved_v2.version.id == SPECIFICATION_V2_ID
    assert approved_v2.version.version_number == 2
    assert approved_v2.version.based_on_version_number == 1
    assert generated.version.specification.requirements[0].statement != (
        approved_v2.version.specification.requirements[0].statement
    )

    gate_service = LocalRequirementsGateService(
        unit_of_work_factory=InMemoryGateUnitOfWorkFactory(state),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=23),
                BASE_TIME + timedelta(minutes=24),
                BASE_TIME + timedelta(minutes=33),
            )
        ),
        gate_id_factory=iterator_factory((GATE_V2_ID, GATE_V3_ID)),
        event_id_factory=iterator_factory(
            (
                GATE_V2_SUBMIT_EVENT_ID,
                GATE_V2_APPROVE_EVENT_ID,
                GATE_V2_STALE_EVENT_ID,
                GATE_V3_SUBMIT_EVENT_ID,
            )
        ),
    )

    submitted_v2 = await gate_service.submit(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    approved_gate_v2 = await gate_service.decide(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        action=HumanGateAction.APPROVE,
    )
    ready_v2 = await gate_service.readiness(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert submitted_v2.status is RequirementsGateSubmissionStatus.SUBMITTED
    assert submitted_v2.gate is not None
    assert submitted_v2.gate.artifact.artifact_id == SPECIFICATION_V2_ID
    assert approved_gate_v2.status is RequirementsGateDecisionStatus.APPLIED
    assert approved_gate_v2.gate is not None
    assert approved_gate_v2.gate.status is HumanGateStatus.APPROVED
    assert ready_v2.status is RequirementsWorkflowReadiness.READY_FOR_DESIGN_EXPLORATION

    proposed_v3 = await revisions.propose_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        proposed_specification=revised_specification(
            approved_v2.version,
            (
                "Create, update, and cancel reservations while preventing "
                "overlapping room allocations."
            ),
        ),
    )
    approved_v3 = await revisions.decide_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        diff_id=DIFF_V2_ID,
        decision=RequirementsRevisionDecision.APPROVE,
    )

    assert proposed_v3.status is RequirementsRevisionStatus.CREATED
    assert approved_v3.status is RequirementsRevisionStatus.APPLIED
    assert approved_v3.version is not None
    assert approved_v3.version.id == SPECIFICATION_V3_ID
    assert approved_v3.version.version_number == 3

    stale_readiness = await gate_service.readiness(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert stale_readiness.status is RequirementsWorkflowReadiness.REQUIREMENTS_APPROVAL_REQUIRED
    assert stale_readiness.gate is not None
    assert stale_readiness.gate.artifact.artifact_id == SPECIFICATION_V2_ID

    submitted_v3 = await gate_service.submit(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert submitted_v3.status is RequirementsGateSubmissionStatus.SUBMITTED
    assert submitted_v3.gate is not None
    assert submitted_v3.gate.iteration == 2
    assert submitted_v3.gate.artifact.artifact_id == SPECIFICATION_V3_ID
    assert submitted_v3.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert len(submitted_v3.events) == 2

    previous_gate = next(gate for gate in state.gates if gate.id == GATE_V2_ID)
    assert previous_gate.status is HumanGateStatus.STALE

    assert tuple(version.version_number for version in state.versions) == (1, 2, 3)
    assert all(diff.status is RequirementsDiffStatus.APPROVED for diff in state.diffs.values())

    traceability = build_requirements_traceability(approved_v3.version)
    coverage = summarize_requirements_coverage(approved_v3.version)

    assert traceability.links
    assert coverage.has_full_acceptance_coverage is True


def test_governed_requirements_journey_reaches_design_readiness_and_detects_staleness() -> None:
    """Verify the complete Sprint 05 owner-governed acceptance journey."""
    asyncio.run(run_governed_requirements_journey())
