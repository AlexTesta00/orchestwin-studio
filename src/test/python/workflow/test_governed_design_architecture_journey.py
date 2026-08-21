"""Sprint 06 acceptance test for the governed Design and Architecture journey."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, TracebackType
from typing import Protocol
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.artifacts.architecture_gate import (
    ArchitectureGateDecisionStatus,
    ArchitectureGateSubmissionStatus,
    ArchitectureWorkflowReadiness,
    LocalArchitectureGateService,
)
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureDiffPersistenceStatus,
    ArchitectureRevisionStatus,
    LocalArchitectureRevisionService,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitecturePackageDiff,
    ArchitecturePackageDiffStatus,
    ArchitectureRevisionDecision,
)
from orchestwin.artifacts.design import DesignCritiqueKind
from orchestwin.artifacts.design_gate import (
    DesignGateDecisionStatus,
    DesignGateSubmissionStatus,
    DesignWorkflowReadiness,
    LocalDesignGateService,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    DesignRevisionStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignPackageDiffStatus,
    DesignRevisionDecision,
)
from orchestwin.artifacts.prototypes import (
    PrototypeElementKind,
    PrototypeScreenState,
    PrototypeViewport,
    create_declarative_prototype,
    create_prototype_element,
    create_prototype_screen,
    create_prototype_transition,
)
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.artifacts.traceability import (
    ArtifactGraphLinkKind,
    ArtifactGraphNodeKind,
    build_cross_stage_artifact_graph,
)
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureRequirementsInput,
)
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignRequirementsInput,
    DesignUserModelingInput,
    DesignUserTwinInput,
)
from orchestwin.models.fake_architecture import FakeDeterministicArchitectureAdapter
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter
from orchestwin.projects.architecture_application import (
    ArchitectureGenerationStatus,
    ArchitectureVersionAppendStatus,
    GovernedArchitectureContext,
    LocalArchitectureGenerationService,
)
from orchestwin.projects.design_application import (
    DesignGenerationStatus,
    DesignVersionAppendStatus,
    GovernedDesignContext,
    LocalDesignGenerationService,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import UserTwinVersionReference
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
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

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"
FIXTURE_PACKAGE_NAME = "governed_design_architecture_fixtures"

DESIGN_VERSION_ONE_ID = UUID("00000000-0000-4000-8000-000000002001")
DESIGN_DIFF_ID = UUID("00000000-0000-4000-8000-000000002002")
DESIGN_VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000002003")
DESIGN_GATE_ID = UUID("00000000-0000-4000-8000-000000002004")
DESIGN_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000002005")
DESIGN_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000002006")
PROTOTYPE_ID = UUID("00000000-0000-4000-8000-000000002010")
PROTOTYPE_ENTRY_SCREEN_ID = UUID("00000000-0000-4000-8000-000000002011")
PROTOTYPE_RESULT_SCREEN_ID = UUID("00000000-0000-4000-8000-000000002012")
PROTOTYPE_INPUT_ID = UUID("00000000-0000-4000-8000-000000002013")
PROTOTYPE_BUTTON_ID = UUID("00000000-0000-4000-8000-000000002014")
PROTOTYPE_STATUS_ID = UUID("00000000-0000-4000-8000-000000002015")
PROTOTYPE_TRANSITION_ID = UUID("00000000-0000-4000-8000-000000002016")

ARCHITECTURE_VERSION_ONE_ID = UUID("00000000-0000-4000-8000-000000002101")
ARCHITECTURE_DIFF_ONE_ID = UUID("00000000-0000-4000-8000-000000002102")
ARCHITECTURE_VERSION_TWO_ID = UUID("00000000-0000-4000-8000-000000002103")
ARCHITECTURE_DIFF_TWO_ID = UUID("00000000-0000-4000-8000-000000002104")
ARCHITECTURE_VERSION_THREE_ID = UUID("00000000-0000-4000-8000-000000002105")
ARCHITECTURE_GATE_ONE_ID = UUID("00000000-0000-4000-8000-000000002106")
ARCHITECTURE_GATE_TWO_ID = UUID("00000000-0000-4000-8000-000000002107")
ARCHITECTURE_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000002108")
ARCHITECTURE_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000002109")
ARCHITECTURE_STALE_EVENT_ID = UUID("00000000-0000-4000-8000-000000002110")
ARCHITECTURE_RESUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000002111")

REQUIREMENTS_GATE_ID = UUID("00000000-0000-4000-8000-000000002201")
REQUIREMENTS_SUBMIT_EVENT_ID = UUID("00000000-0000-4000-8000-000000002202")
REQUIREMENTS_APPROVE_EVENT_ID = UUID("00000000-0000-4000-8000-000000002203")
BASE_TIME = datetime(2026, 8, 21, 17, 0, tzinfo=UTC)


def load_design_fixtures() -> ModuleType:
    """Load the test-only Requirements fixture without importing tests in production."""
    package = ModuleType(FIXTURE_PACKAGE_NAME)
    package.__path__ = [str(FIXTURE_DIRECTORY)]
    sys.modules[FIXTURE_PACKAGE_NAME] = package

    module_name = f"{FIXTURE_PACKAGE_NAME}.design_fixtures"
    spec = importlib.util.spec_from_file_location(
        module_name,
        FIXTURE_DIRECTORY / "design_fixtures.py",
    )

    if spec is None or spec.loader is None:
        raise AssertionError("could not load Design journey fixtures")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


FIXTURES = load_design_fixtures()
PROJECT_ID: UUID = FIXTURES.PROJECT_ID
OWNER_ID: UUID = FIXTURES.OWNER_ID


class PackageVersion(Protocol):
    """Shared immutable identity used by the in-memory stage repositories."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    content_hash: str
    created_by_user_id: UUID


class ReviewableDiff(Protocol):
    """Shared diff state used by the in-memory revision repositories."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    base_version_id: UUID
    status: object
    created_at: datetime


class InMemoryPackageRepository[VersionT: PackageVersion, StatusT]:
    """Append-only owner-scoped package repository for one workflow stage."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        appended: StatusT,
        project_not_found: StatusT,
        version_conflict: StatusT,
        content_conflict: StatusT,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._appended = appended
        self._project_not_found = project_not_found
        self._version_conflict = version_conflict
        self._content_conflict = content_conflict
        self.versions: list[VersionT] = []

    async def current(self, *, project_id: UUID) -> VersionT | None:
        """Return the latest package version for one project."""
        candidates = [version for version in self.versions if version.project_id == project_id]
        return candidates[-1] if candidates else None

    async def append(self, version: VersionT) -> StatusT:
        """Append only a linear, content-distinct owner-scoped version."""
        if version.created_by_user_id != self._owner_user_id:
            return self._project_not_found

        current = await self.current(project_id=version.project_id)

        if current is None:
            if version.version_number != 1 or version.based_on_version_number is not None:
                return self._version_conflict
        elif (
            version.version_number != current.version_number + 1
            or version.based_on_version_number != current.version_number
        ):
            return self._version_conflict
        elif version.content_hash == current.content_hash:
            return self._content_conflict

        self.versions.append(version)
        return self._appended

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> VersionT | None:
        """Return the current package only for its owner."""
        if owner_user_id != self._owner_user_id:
            return None

        return await self.current(project_id=project_id)


class InMemoryDiffRepository[DiffT: ReviewableDiff, StatusT]:
    """Owner-scoped reviewable diff repository shared by both stages."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        proposed_status: object,
        created: StatusT,
        updated: StatusT,
        conflict: StatusT,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._proposed_status = proposed_status
        self._created = created
        self._updated = updated
        self._conflict = conflict
        self.diffs: dict[UUID, DiffT] = {}

    async def create(self, diff: DiffT) -> StatusT:
        """Persist one owner-scoped proposed diff."""
        if diff.owner_user_id != self._owner_user_id or diff.id in self.diffs:
            return self._conflict

        self.diffs[diff.id] = diff
        return self._created

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> DiffT | None:
        """Return one project-scoped diff."""
        diff = self.diffs.get(diff_id)
        return diff if diff is not None and diff.project_id == project_id else None

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> DiffT | None:
        """Return the pending diff for one exact base version."""
        return next(
            (
                diff
                for diff in self.diffs.values()
                if diff.project_id == project_id
                and diff.base_version_id == base_version_id
                and diff.status == self._proposed_status
            ),
            None,
        )

    async def history(self, *, project_id: UUID) -> tuple[DiffT, ...]:
        """Return project diffs in deterministic creation order."""
        return tuple(
            sorted(
                (diff for diff in self.diffs.values() if diff.project_id == project_id),
                key=lambda diff: (diff.created_at, diff.id.hex),
            )
        )

    async def save_decision(self, diff: DiffT) -> StatusT:
        """Replace only an existing proposed diff with its owner decision."""
        current = self.diffs.get(diff.id)

        if current is None or current.status != self._proposed_status:
            return self._conflict

        self.diffs[diff.id] = diff
        return self._updated


class InMemoryCommandUnitOfWork:
    """No-op transaction boundary over shared in-memory repositories."""

    def __init__(self, packages, diffs) -> None:
        self.packages = packages
        self.diffs = diffs

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


class InMemoryCommandUnitOfWorkFactory:
    """Create command Units of Work over shared owner-scoped repositories."""

    def __init__(self, *, owner_user_id: UUID, packages, diffs) -> None:
        self._owner_user_id = owner_user_id
        self._packages = packages
        self._diffs = diffs

    def __call__(self, *, owner_user_id: UUID) -> InMemoryCommandUnitOfWork:
        assert owner_user_id == self._owner_user_id
        return InMemoryCommandUnitOfWork(self._packages, self._diffs)


@dataclass(slots=True)
class InMemoryGateState:
    """Shared gate and event state across Design and Architecture services."""

    gates: list[HumanGate]
    events: list[HumanGateEvent]


class InMemoryGateRepository:
    """Persist exact gate transitions and append-only events."""

    def __init__(self, state: InMemoryGateState) -> None:
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
        return (
            None
            if not candidates
            else max(candidates, key=lambda gate: (gate.iteration, gate.created_at, gate.id.hex))
        )

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
            if current.id != previous_gate.id:
                continue

            if current != previous_gate:
                raise RuntimeError("gate changed concurrently in the Sprint 06 journey")

            self._state.gates[index] = updated_gate
            self._state.events.append(event)
            return updated_gate

        raise RuntimeError("gate is missing from the Sprint 06 journey")

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[HumanGateEvent, ...]:
        owned_gate_ids = {
            gate.id
            for gate in self._state.gates
            if gate.project_id == project_id and gate.owner_user_id == owner_user_id
        }

        if gate_id not in owned_gate_ids:
            return ()

        return tuple(
            sorted(
                (event for event in self._state.events if event.gate_id == gate_id),
                key=lambda event: event.sequence_number,
            )
        )


class InMemoryGateUnitOfWork:
    """Gate transaction boundary over current packages and shared gate state."""

    def __init__(self, packages, gates: InMemoryGateRepository) -> None:
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


class InMemoryGateUnitOfWorkFactory:
    """Create owner-scoped Gate Units of Work."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        packages,
        gates: InMemoryGateRepository,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._packages = packages
        self._gates = gates

    def __call__(self, *, owner_user_id: UUID) -> InMemoryGateUnitOfWork:
        assert owner_user_id == self._owner_user_id
        return InMemoryGateUnitOfWork(self._packages, self._gates)


class StaticDesignGovernance:
    """Expose one exact approved Requirements context."""

    def __init__(self, context: GovernedDesignContext) -> None:
        self._context = context

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedDesignContext | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None

        return self._context


class StaticArchitectureGovernance:
    """Expose one exact approved Design context."""

    def __init__(self, context: GovernedArchitectureContext) -> None:
        self._context = context

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedArchitectureContext | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None

        return self._context


def iterator_factory(values):
    """Return one deterministic zero-argument value factory."""
    iterator = iter(values)

    def next_value():
        return next(iterator)

    return next_value


def requirements_version() -> RequirementsSpecificationVersion:
    """Return the complete immutable Requirements baseline for this journey."""
    return FIXTURES.requirements_version()


def selected_agent_ids() -> tuple[AgentIdentifier, ...]:
    """Return the required Design and Architecture specialists in catalog order."""
    selected = {
        AgentIdentifier.WORKFLOW_ORCHESTRATOR,
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.SOFTWARE_ARCHITECT,
        AgentIdentifier.QA_TEST_ENGINEER,
    }
    return tuple(
        entry.agent_id for entry in all_agent_catalog_entries() if entry.agent_id in selected
    )


def grounded_observation() -> ProfileObservation:
    """Create one concrete owner-provided User Twin observation."""
    return ProfileObservation(
        observation_key="user_twin.goals",
        value=ObservationValue.from_items(("Create reservations accurately",)),
        epistemic_status=EpistemicStatus.USER_PROVIDED,
        confidence=ConfidenceScore(1.0),
        provenance=ObservationProvenance.from_references(
            (
                EvidenceReference(
                    source_kind=EvidenceSourceKind.PROJECT_BRIEF,
                    source_id="brief-version",
                    source_version=1,
                    content_hash="b" * 64,
                    locator="target_users[0]",
                ),
            )
        ),
        human_validation=HumanValidationRequirement.NOT_REQUIRED,
    )


def approved_requirements_gate(
    requirements: RequirementsSpecificationVersion,
) -> HumanGate:
    """Create an exact Gate 4 approval through real state transitions."""
    draft = create_human_gate(
        gate_id=REQUIREMENTS_GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=HumanGateType.REQUIREMENTS,
            artifact_id=requirements.id,
            version=requirements.version_number,
            content_hash=requirements.content_hash,
        ),
        created_at=BASE_TIME,
    )
    submitted = transition_human_gate(
        draft,
        action=HumanGateAction.SUBMIT,
        actor_user_id=OWNER_ID,
        occurred_at=BASE_TIME + timedelta(minutes=1),
        event_id=REQUIREMENTS_SUBMIT_EVENT_ID,
    )
    assert submitted.status is HumanGateTransitionStatus.APPLIED

    approved = transition_human_gate(
        submitted.gate,
        action=HumanGateAction.APPROVE,
        actor_user_id=OWNER_ID,
        occurred_at=BASE_TIME + timedelta(minutes=2),
        event_id=REQUIREMENTS_APPROVE_EVENT_ID,
    )
    assert approved.status is HumanGateTransitionStatus.APPLIED
    return approved.gate


def design_context(
    requirements: RequirementsSpecificationVersion,
) -> GovernedDesignContext:
    """Create the exact approved context consumed by Design generation."""
    specification = requirements.specification
    twin = specification.user_twin_references[0]

    return GovernedDesignContext(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=DesignRequirementsInput(version=requirements),
        team=DesignAgentTeamInput(
            reference=VersionedArtifactReference(
                kind=ArtifactKind.AGENT_TEAM,
                artifact_id=specification.agent_team_reference.artifact_id,
                version_number=specification.agent_team_reference.version_number,
                content_hash=specification.agent_team_reference.content_hash,
            ),
            selected_agent_ids=selected_agent_ids(),
        ),
        user_modeling=DesignUserModelingInput(
            reference=VersionedArtifactReference(
                kind=ArtifactKind.USER_MODELING,
                artifact_id=specification.user_modeling_reference.artifact_id,
                version_number=specification.user_modeling_reference.version_number,
                content_hash=specification.user_modeling_reference.content_hash,
            ),
            user_twins=(
                DesignUserTwinInput(
                    reference=UserTwinVersionReference(
                        twin_id=twin.twin_id,
                        version_number=twin.version_number,
                        content_hash=twin.content_hash,
                        name=twin.name,
                    ),
                    observations=(grounded_observation(),),
                ),
            ),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        requirements_gate=approved_requirements_gate(requirements),
    )


def owner_prototype(version: DesignPackageVersion):
    """Create a trusted declarative prototype for the first proposed alternative."""
    alternative = version.package.alternatives[0]
    requirement_id = version.package.grounding.requirement_ids[0]
    user_story_id = version.package.grounding.user_story_ids[0]
    criterion_id = version.package.grounding.acceptance_criterion_ids[0]
    input_element = create_prototype_element(
        element_id=PROTOTYPE_INPUT_ID,
        code="ELM-001",
        kind=PrototypeElementKind.TEXT_INPUT,
        content="Reservation details",
        accessible_name="Reservation details",
        requirement_ids=(requirement_id,),
        user_story_ids=(user_story_id,),
        field_name="reservation_details",
        required=True,
    )
    submit_button = create_prototype_element(
        element_id=PROTOTYPE_BUTTON_ID,
        code="ELM-002",
        kind=PrototypeElementKind.BUTTON,
        content="Save reservation",
        accessible_name="Save reservation",
        acceptance_criterion_ids=(criterion_id,),
    )
    result_status = create_prototype_element(
        element_id=PROTOTYPE_STATUS_ID,
        code="ELM-003",
        kind=PrototypeElementKind.STATUS,
        content="Reservation saved",
        acceptance_criterion_ids=(criterion_id,),
    )
    entry_screen = create_prototype_screen(
        screen_id=PROTOTYPE_ENTRY_SCREEN_ID,
        code="SCR-001",
        title="Create reservation",
        state=PrototypeScreenState.DEFAULT,
        elements=(input_element, submit_button),
        requirement_ids=(requirement_id,),
        user_story_ids=(user_story_id,),
    )
    result_screen = create_prototype_screen(
        screen_id=PROTOTYPE_RESULT_SCREEN_ID,
        code="SCR-002",
        title="Reservation result",
        state=PrototypeScreenState.SUCCESS,
        elements=(result_status,),
        acceptance_criterion_ids=(criterion_id,),
    )
    transition = create_prototype_transition(
        transition_id=PROTOTYPE_TRANSITION_ID,
        code="TRN-001",
        source_screen_id=entry_screen.id,
        trigger_element_id=submit_button.id,
        target_screen_id=result_screen.id,
        outcome="The reservation result becomes visible.",
    )

    return create_declarative_prototype(
        prototype_id=PROTOTYPE_ID,
        code="PRT-001",
        title="Owner-selected reservation prototype",
        design_alternative_id=alternative.id,
        entry_screen_id=entry_screen.id,
        screens=(entry_screen, result_screen),
        transitions=(transition,),
        supported_viewports=(PrototypeViewport.MOBILE, PrototypeViewport.DESKTOP),
    )


def architecture_context(
    *,
    requirements: RequirementsSpecificationVersion,
    design: DesignPackageVersion,
    design_gate: HumanGate,
) -> GovernedArchitectureContext:
    """Create the exact Gate-5-approved context consumed by Architecture generation."""
    grounding = design.package.grounding

    return GovernedArchitectureContext(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=ArchitectureRequirementsInput(version=requirements),
        design=ArchitectureDesignInput(version=design),
        team=ArchitectureAgentTeamInput(
            reference=grounding.agent_team_reference,
            selected_agent_ids=selected_agent_ids(),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        design_gate=design_gate,
    )


async def run_governed_design_architecture_journey() -> None:
    """Run deterministic Design, Gate 5, Architecture, Gate 6, and staleness."""
    requirements = requirements_version()
    gate_state = InMemoryGateState(gates=[], events=[])
    gates = InMemoryGateRepository(gate_state)

    design_packages = InMemoryPackageRepository[
        DesignPackageVersion,
        DesignVersionAppendStatus,
    ](
        owner_user_id=OWNER_ID,
        appended=DesignVersionAppendStatus.APPENDED,
        project_not_found=DesignVersionAppendStatus.PROJECT_NOT_FOUND,
        version_conflict=DesignVersionAppendStatus.VERSION_CONFLICT,
        content_conflict=DesignVersionAppendStatus.CONTENT_CONFLICT,
    )
    design_diffs = InMemoryDiffRepository[
        DesignPackageDiff,
        DesignDiffPersistenceStatus,
    ](
        owner_user_id=OWNER_ID,
        proposed_status=DesignPackageDiffStatus.PROPOSED,
        created=DesignDiffPersistenceStatus.CREATED,
        updated=DesignDiffPersistenceStatus.UPDATED,
        conflict=DesignDiffPersistenceStatus.CONFLICT,
    )
    design_uow_factory = InMemoryCommandUnitOfWorkFactory(
        owner_user_id=OWNER_ID,
        packages=design_packages,
        diffs=design_diffs,
    )
    design_generation = LocalDesignGenerationService(
        governance=StaticDesignGovernance(design_context(requirements)),
        proposals=FakeDeterministicDesignAdapter(),
        uow_factory=design_uow_factory,
        uuid_factory=lambda: DESIGN_VERSION_ONE_ID,
        clock=lambda: BASE_TIME + timedelta(minutes=3),
    )

    generated_design = await design_generation.generate(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
    )

    assert generated_design.status is DesignGenerationStatus.CREATED
    assert generated_design.version is not None
    design_v1 = generated_design.version
    assert design_v1.id == DESIGN_VERSION_ONE_ID
    assert design_v1.version_number == 1
    assert design_v1.package.owner_selected_alternative_id is None
    assert design_v1.package.prototype is None
    assert not design_v1.package.ready_for_gate
    assert len(design_v1.package.alternatives) == 3
    assert all(
        critique.kind is DesignCritiqueKind.SYNTHETIC_USER_TWIN
        and critique.epistemic_status is EpistemicStatus.MODEL_INFERRED
        and critique.human_validation is HumanValidationRequirement.REQUIRED
        and critique.requires_human_validation
        for critique in design_v1.package.critiques
    )

    prototype = owner_prototype(design_v1)
    selected_alternative = design_v1.package.alternatives[0]
    design_revisions = LocalDesignRevisionService(
        uow_factory=design_uow_factory,
        uuid_factory=iterator_factory((DESIGN_DIFF_ID, DESIGN_VERSION_TWO_ID)),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=4),
                BASE_TIME + timedelta(minutes=5),
            )
        ),
    )
    design_proposal = await design_revisions.propose_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        proposed_package=replace(
            design_v1.package,
            owner_selected_alternative_id=selected_alternative.id,
            prototype=prototype,
        ),
    )
    design_decision = await design_revisions.decide_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        diff_id=DESIGN_DIFF_ID,
        decision=DesignRevisionDecision.APPROVE,
    )

    assert design_proposal.status is DesignRevisionStatus.CREATED
    assert design_decision.status is DesignRevisionStatus.APPLIED
    assert design_decision.version is not None
    design_v2 = design_decision.version
    assert design_v2.id == DESIGN_VERSION_TWO_ID
    assert design_v2.version_number == 2
    assert design_v2.package.owner_selected_alternative_id == selected_alternative.id
    assert design_v2.package.prototype == prototype
    assert design_v2.package.ready_for_gate

    design_gate_service = LocalDesignGateService(
        unit_of_work_factory=InMemoryGateUnitOfWorkFactory(
            owner_user_id=OWNER_ID,
            packages=design_packages,
            gates=gates,
        ),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=6),
                BASE_TIME + timedelta(minutes=7),
            )
        ),
        gate_id_factory=lambda: DESIGN_GATE_ID,
        event_id_factory=iterator_factory((DESIGN_SUBMIT_EVENT_ID, DESIGN_APPROVE_EVENT_ID)),
    )
    design_submission = await design_gate_service.submit(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    design_approval = await design_gate_service.decide(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        action=HumanGateAction.APPROVE,
    )
    design_readiness = await design_gate_service.readiness(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert design_submission.status is DesignGateSubmissionStatus.SUBMITTED
    assert design_approval.status is DesignGateDecisionStatus.APPLIED
    assert design_approval.gate is not None
    assert design_approval.gate.status is HumanGateStatus.APPROVED
    assert design_approval.gate.artifact.artifact_id == design_v2.id
    assert design_approval.gate.artifact.content_hash == design_v2.content_hash
    assert design_readiness.status is DesignWorkflowReadiness.READY_FOR_ARCHITECTURE_PLANNING

    architecture_packages = InMemoryPackageRepository[
        ArchitecturePackageVersion,
        ArchitectureVersionAppendStatus,
    ](
        owner_user_id=OWNER_ID,
        appended=ArchitectureVersionAppendStatus.APPENDED,
        project_not_found=ArchitectureVersionAppendStatus.PROJECT_NOT_FOUND,
        version_conflict=ArchitectureVersionAppendStatus.VERSION_CONFLICT,
        content_conflict=ArchitectureVersionAppendStatus.CONTENT_CONFLICT,
    )
    architecture_diffs = InMemoryDiffRepository[
        ArchitecturePackageDiff,
        ArchitectureDiffPersistenceStatus,
    ](
        owner_user_id=OWNER_ID,
        proposed_status=ArchitecturePackageDiffStatus.PROPOSED,
        created=ArchitectureDiffPersistenceStatus.CREATED,
        updated=ArchitectureDiffPersistenceStatus.UPDATED,
        conflict=ArchitectureDiffPersistenceStatus.CONFLICT,
    )
    architecture_uow_factory = InMemoryCommandUnitOfWorkFactory(
        owner_user_id=OWNER_ID,
        packages=architecture_packages,
        diffs=architecture_diffs,
    )
    architecture_generation = LocalArchitectureGenerationService(
        governance=StaticArchitectureGovernance(
            architecture_context(
                requirements=requirements,
                design=design_v2,
                design_gate=design_approval.gate,
            )
        ),
        proposals=FakeDeterministicArchitectureAdapter(),
        uow_factory=architecture_uow_factory,
        uuid_factory=lambda: ARCHITECTURE_VERSION_ONE_ID,
        clock=lambda: BASE_TIME + timedelta(minutes=8),
    )

    generated_architecture = await architecture_generation.generate(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
    )

    assert generated_architecture.status is ArchitectureGenerationStatus.CREATED
    assert generated_architecture.version is not None
    architecture_v1 = generated_architecture.version
    assert architecture_v1.id == ARCHITECTURE_VERSION_ONE_ID
    assert architecture_v1.version_number == 1
    assert architecture_v1.package.grounding.design_package_reference.artifact_id == design_v2.id
    assert architecture_v1.package.grounding.design_package_reference.content_hash == (
        design_v2.content_hash
    )
    assert architecture_v1.package.architecture.requirement_ids == (
        design_v2.package.grounding.requirement_ids
    )
    assert architecture_v1.package.test_plan.requirement_ids == (
        design_v2.package.grounding.requirement_ids
    )

    architecture_revisions = LocalArchitectureRevisionService(
        uow_factory=architecture_uow_factory,
        uuid_factory=iterator_factory(
            (
                ARCHITECTURE_DIFF_ONE_ID,
                ARCHITECTURE_VERSION_TWO_ID,
                ARCHITECTURE_DIFF_TWO_ID,
                ARCHITECTURE_VERSION_THREE_ID,
            )
        ),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=9),
                BASE_TIME + timedelta(minutes=10),
                BASE_TIME + timedelta(minutes=13),
                BASE_TIME + timedelta(minutes=14),
            )
        ),
    )
    architecture_proposal_v2 = await architecture_revisions.propose_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        proposed_package=replace(
            architecture_v1.package,
            open_questions=(
                *architecture_v1.package.open_questions,
                "Which execution profile should verify the approved test plan?",
            ),
        ),
    )
    architecture_decision_v2 = await architecture_revisions.decide_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        diff_id=ARCHITECTURE_DIFF_ONE_ID,
        decision=ArchitectureRevisionDecision.APPROVE,
    )

    assert architecture_proposal_v2.status is ArchitectureRevisionStatus.CREATED
    assert architecture_decision_v2.status is ArchitectureRevisionStatus.APPLIED
    assert architecture_decision_v2.version is not None
    architecture_v2 = architecture_decision_v2.version
    assert architecture_v2.id == ARCHITECTURE_VERSION_TWO_ID
    assert architecture_v2.version_number == 2

    architecture_gate_service = LocalArchitectureGateService(
        unit_of_work_factory=InMemoryGateUnitOfWorkFactory(
            owner_user_id=OWNER_ID,
            packages=architecture_packages,
            gates=gates,
        ),
        clock=iterator_factory(
            (
                BASE_TIME + timedelta(minutes=11),
                BASE_TIME + timedelta(minutes=12),
                BASE_TIME + timedelta(minutes=15),
            )
        ),
        gate_id_factory=iterator_factory((ARCHITECTURE_GATE_ONE_ID, ARCHITECTURE_GATE_TWO_ID)),
        event_id_factory=iterator_factory(
            (
                ARCHITECTURE_SUBMIT_EVENT_ID,
                ARCHITECTURE_APPROVE_EVENT_ID,
                ARCHITECTURE_STALE_EVENT_ID,
                ARCHITECTURE_RESUBMIT_EVENT_ID,
            )
        ),
    )
    architecture_submission = await architecture_gate_service.submit(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    architecture_approval = await architecture_gate_service.decide(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        action=HumanGateAction.APPROVE,
    )
    ready_for_implementation = await architecture_gate_service.readiness(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert architecture_submission.status is ArchitectureGateSubmissionStatus.SUBMITTED
    assert architecture_approval.status is ArchitectureGateDecisionStatus.APPLIED
    assert architecture_approval.gate is not None
    assert architecture_approval.gate.status is HumanGateStatus.APPROVED
    assert architecture_approval.gate.artifact.artifact_id == architecture_v2.id
    assert ready_for_implementation.status is ArchitectureWorkflowReadiness.READY_FOR_IMPLEMENTATION

    architecture_proposal_v3 = await architecture_revisions.propose_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        proposed_package=replace(
            architecture_v2.package,
            open_questions=(
                *architecture_v2.package.open_questions,
                "Which environment will provide reproducible implementation evidence?",
            ),
        ),
    )
    architecture_decision_v3 = await architecture_revisions.decide_revision(
        owner_user_id=OWNER_ID,
        project_id=PROJECT_ID,
        diff_id=ARCHITECTURE_DIFF_TWO_ID,
        decision=ArchitectureRevisionDecision.APPROVE,
    )

    assert architecture_proposal_v3.status is ArchitectureRevisionStatus.CREATED
    assert architecture_decision_v3.status is ArchitectureRevisionStatus.APPLIED
    assert architecture_decision_v3.version is not None
    architecture_v3 = architecture_decision_v3.version
    assert architecture_v3.id == ARCHITECTURE_VERSION_THREE_ID
    assert architecture_v3.version_number == 3

    stale_readiness = await architecture_gate_service.readiness(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )
    resubmitted_architecture = await architecture_gate_service.submit(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
    )

    assert stale_readiness.status is ArchitectureWorkflowReadiness.ARCHITECTURE_APPROVAL_REQUIRED
    assert stale_readiness.gate is not None
    assert stale_readiness.gate.artifact.artifact_id == architecture_v2.id
    assert resubmitted_architecture.status is ArchitectureGateSubmissionStatus.SUBMITTED
    assert resubmitted_architecture.gate is not None
    assert resubmitted_architecture.gate.iteration == 2
    assert resubmitted_architecture.gate.artifact.artifact_id == architecture_v3.id
    assert resubmitted_architecture.gate.status is HumanGateStatus.PENDING_APPROVAL
    assert len(resubmitted_architecture.events) == 2

    previous_architecture_gate = next(
        gate for gate in gate_state.gates if gate.id == ARCHITECTURE_GATE_ONE_ID
    )
    assert previous_architecture_gate.status is HumanGateStatus.STALE

    graph = build_cross_stage_artifact_graph(
        requirements,
        design_v2,
        architecture_v3,
    )
    repeated_graph = build_cross_stage_artifact_graph(
        requirements,
        design_v2,
        architecture_v3,
    )

    assert graph == repeated_graph
    assert graph.content_hash == repeated_graph.content_hash
    assert graph.nodes
    assert graph.links
    assert {
        ArtifactGraphNodeKind.REQUIREMENTS_SPECIFICATION,
        ArtifactGraphNodeKind.DESIGN_PACKAGE,
        ArtifactGraphNodeKind.DECLARATIVE_PROTOTYPE,
        ArtifactGraphNodeKind.ARCHITECTURE_PACKAGE,
        ArtifactGraphNodeKind.SOFTWARE_ARCHITECTURE,
        ArtifactGraphNodeKind.TEST_PLAN,
        ArtifactGraphNodeKind.TEST_CASE,
    }.issubset({node.reference.kind for node in graph.nodes})
    assert {
        ArtifactGraphLinkKind.GROUNDED_IN,
        ArtifactGraphLinkKind.REALIZES,
        ArtifactGraphLinkKind.TESTS,
        ArtifactGraphLinkKind.VERIFIED_BY,
    }.issubset({link.kind for link in graph.links})

    assert tuple(version.version_number for version in design_packages.versions) == (1, 2)
    assert tuple(version.version_number for version in architecture_packages.versions) == (
        1,
        2,
        3,
    )
    assert all(
        diff.status is DesignPackageDiffStatus.APPROVED for diff in design_diffs.diffs.values()
    )
    assert all(
        diff.status is ArchitecturePackageDiffStatus.APPROVED
        for diff in architecture_diffs.diffs.values()
    )


def test_governed_design_architecture_journey_reaches_gate_six_and_detects_staleness() -> None:
    """Verify the complete Sprint 06 owner-governed acceptance journey."""
    asyncio.run(run_governed_design_architecture_journey())
