"""Tests for governed requirements specification generation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.models.fake_requirements import (
    FakeDeterministicRequirementsAdapter,
)
from orchestwin.models.requirements import (
    RequirementsBriefInput,
    RequirementsProposalRequest,
    RequirementsProposalResult,
    RequirementsTeamInput,
    RequirementsUserModelingInput,
    RequirementsUserTwinInput,
)
from orchestwin.projects.domain import (
    ProjectMode,
)
from orchestwin.projects.requirements_application import (
    GovernedRequirementsContext,
    LocalRequirementsGenerationService,
    RequirementsGenerationIssueCode,
    RequirementsGenerationStatus,
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
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
    HumanGateType,
    create_human_gate,
    transition_human_gate,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
TWIN_ID = UUID("00000000-0000-4000-8000-000000000010")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")

CREATED_AT = datetime(
    2026,
    8,
    18,
    10,
    0,
    tzinfo=UTC,
)


def context_reference(
    kind: RequirementsContextKind,
    ordinal: int,
) -> RequirementsContextReference:
    """Create one exact governed artifact reference."""
    return RequirementsContextReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=(f"{ordinal:x}" * 64),
    )


def twin_reference() -> UserTwinVersionReference:
    """Create one exact User Twin reference."""
    return UserTwinVersionReference(
        twin_id=TWIN_ID,
        version_number=1,
        content_hash="a" * 64,
        name=("Hotel Receptionist Twin"),
    )


def observation() -> ProfileObservation:
    """Create one grounded User Twin goal observation."""
    return ProfileObservation(
        observation_key=("user_twin.goals"),
        value=(ObservationValue.from_items(("Reduce booking errors",))),
        epistemic_status=(EpistemicStatus.USER_PROVIDED),
        confidence=(ConfidenceScore(1.0)),
        provenance=(
            ObservationProvenance.from_references(
                (
                    EvidenceReference(
                        source_kind=(EvidenceSourceKind.PROJECT_BRIEF),
                        source_id=("brief-version"),
                        source_version=1,
                        content_hash=("b" * 64),
                        locator=("goals[0]"),
                    ),
                )
            )
        ),
        human_validation=(HumanValidationRequirement.NOT_REQUIRED),
    )


def approved_gate(
    gate_type: HumanGateType,
    reference: (RequirementsContextReference),
) -> HumanGate:
    """Create one gate approving the exact supplied artifact."""
    draft = create_human_gate(
        gate_id=UUID(int=(100 + reference.version_number + len(reference.content_hash))),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=gate_type,
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=gate_type,
            artifact_id=(reference.artifact_id),
            version=(reference.version_number),
            content_hash=(reference.content_hash),
        ),
        created_at=CREATED_AT,
    )

    submitted = transition_human_gate(
        draft,
        action=(HumanGateAction.SUBMIT),
        actor_user_id=(OWNER_ID),
        occurred_at=(CREATED_AT + timedelta(minutes=1)),
        event_id=UUID(int=(200 + len(gate_type.value))),
    )

    approved = transition_human_gate(
        submitted.gate,
        action=(HumanGateAction.APPROVE),
        actor_user_id=(OWNER_ID),
        occurred_at=(CREATED_AT + timedelta(minutes=2)),
        event_id=UUID(int=(300 + len(gate_type.value))),
    )

    return approved.gate


def governed_context() -> GovernedRequirementsContext:
    """Create one fully approved requirements context."""
    brief = RequirementsBriefInput(
        reference=context_reference(
            RequirementsContextKind.PROJECT_BRIEF,
            11,
        ),
        name="Hotel Operations",
        problem=("Reservation updates are error-prone."),
        goals=("Reduce booking errors",),
        functional_requirements=("Create reservations",),
        definition_of_done=("All automated tests pass",),
    )

    team = RequirementsTeamInput(
        reference=context_reference(
            RequirementsContextKind.AGENT_TEAM,
            12,
        ),
        selected_agent_ids=(
            AgentIdentifier.WORKFLOW_ORCHESTRATOR,
            AgentIdentifier.REQUIREMENTS_ANALYST,
        ),
    )

    user_modeling = RequirementsUserModelingInput(
        reference=context_reference(
            RequirementsContextKind.USER_MODELING,
            13,
        ),
        user_twins=(
            RequirementsUserTwinInput(
                reference=(twin_reference()),
                observations=(observation(),),
            ),
        ),
    )

    return GovernedRequirementsContext(
        project_id=PROJECT_ID,
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
        team=team,
        user_modeling=user_modeling,
        catalog_version=(AGENT_CATALOG_VERSION),
        catalog_content_hash=(AGENT_CATALOG_CONTENT_HASH),
        brief_gate=approved_gate(
            HumanGateType.PROJECT_BRIEF,
            brief.reference,
        ),
        team_gate=approved_gate(
            HumanGateType.AGENT_TEAM,
            team.reference,
        ),
        user_modeling_gate=(
            approved_gate(
                HumanGateType.USER_MODELING,
                user_modeling.reference,
            )
        ),
    )


class FakeGovernance:
    """Return configured contexts in sequence."""

    def __init__(
        self,
        *contexts: (GovernedRequirementsContext | None),
    ) -> None:
        self._contexts = list(contexts)
        self.calls = 0

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedRequirementsContext | None:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID

        self.calls += 1

        if len(self._contexts) > 1:
            return self._contexts.pop(0)

        return self._contexts[0]


class InMemorySpecifications:
    """Minimal append-only repository fixture."""

    def __init__(
        self,
    ) -> None:
        self.versions: list[RequirementsSpecificationVersion] = []

        self.append_status = RequirementsVersionAppendStatus.APPENDED

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> RequirementsSpecificationVersion | None:
        values = [value for value in self.versions if value.project_id == project_id]

        return values[-1] if values else None

    async def append(
        self,
        version: (RequirementsSpecificationVersion),
    ) -> RequirementsVersionAppendStatus:
        if self.append_status is RequirementsVersionAppendStatus.APPENDED:
            self.versions.append(version)

        return self.append_status


class InMemoryUnitOfWork:
    """Share one in-memory repository across service transactions."""

    def __init__(
        self,
        specifications: (InMemorySpecifications),
    ) -> None:
        self.specifications = specifications
        self.committed = False

    async def __aenter__(
        self,
    ):
        return self

    async def __aexit__(
        self,
        exc_type: (type[BaseException] | None),
        exc_value: (BaseException | None),
        traceback: (TracebackType | None),
    ) -> None:
        del exc_type
        del exc_value
        del traceback

    async def commit(
        self,
    ) -> None:
        self.committed = True

    async def rollback(
        self,
    ) -> None:
        self.committed = False


class InMemoryUowFactory:
    """Create transactions over one shared repository."""

    def __init__(
        self,
        specifications: (InMemorySpecifications),
    ) -> None:
        self.specifications = specifications
        self.units: list[InMemoryUnitOfWork] = []

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> InMemoryUnitOfWork:
        assert owner_user_id == OWNER_ID

        unit = InMemoryUnitOfWork(self.specifications)

        self.units.append(unit)

        return unit


class InvalidProposalPort:
    """Return a structurally valid specification grounded in another Brief."""

    async def propose(
        self,
        request: (RequirementsProposalRequest),
    ) -> RequirementsProposalResult:
        result = await FakeDeterministicRequirementsAdapter().propose(request)

        assert result.specification is not None

        specification = replace(
            result.specification,
            project_brief_reference=(
                context_reference(
                    RequirementsContextKind.PROJECT_BRIEF,
                    14,
                )
            ),
        )

        return replace(
            result,
            specification=specification,
        )


def run_generation(
    service: (LocalRequirementsGenerationService),
):
    """Run one generation command synchronously."""
    return asyncio.run(
        service.generate(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )


def service(
    governance: FakeGovernance,
    repository: (InMemorySpecifications),
    *,
    proposals=None,
) -> LocalRequirementsGenerationService:
    """Create the application service with deterministic dependencies."""
    return LocalRequirementsGenerationService(
        governance=governance,
        proposals=(proposals or FakeDeterministicRequirementsAdapter()),
        uow_factory=(InMemoryUowFactory(repository)),
        uuid_factory=(lambda: VERSION_ID),
        clock=(lambda: CREATED_AT + timedelta(minutes=5)),
    )


def test_generation_persists_one_immutable_initial_version() -> None:
    """Create version one only after all three governed gates approve."""
    context = governed_context()
    governance = FakeGovernance(context)
    repository = InMemorySpecifications()

    result = run_generation(
        service(
            governance,
            repository,
        )
    )

    assert result.status is (RequirementsGenerationStatus.CREATED)
    assert result.issue is None
    assert result.version is not None
    assert result.version.id == VERSION_ID
    assert result.version.version_number == 1
    assert result.version.based_on_version_number is None
    assert repository.versions == [
        result.version,
    ]
    assert governance.calls == 2


def test_generation_rejects_when_gate_three_is_not_approved() -> None:
    """Prevent requirements generation before exact User Modeling approval."""
    context = governed_context()

    unapproved = replace(
        context,
        user_modeling_gate=(
            create_human_gate(
                project_id=(PROJECT_ID),
                owner_user_id=(OWNER_ID),
                gate_type=(HumanGateType.USER_MODELING),
                artifact=(context.user_modeling_gate.artifact),
                created_at=(CREATED_AT),
            )
        ),
    )

    result = run_generation(
        service(
            FakeGovernance(unapproved),
            InMemorySpecifications(),
        )
    )

    assert result.status is (RequirementsGenerationStatus.REJECTED)
    assert result.issue is (RequirementsGenerationIssueCode.USER_MODELING_APPROVAL_REQUIRED)


def test_generation_rejects_provider_output_after_context_changes() -> None:
    """Discard results produced from a context superseded in flight."""
    initial = governed_context()

    changed = replace(
        initial,
        brief=replace(
            initial.brief,
            name=("Changed Hotel Operations"),
        ),
    )

    result = run_generation(
        service(
            FakeGovernance(
                initial,
                changed,
            ),
            InMemorySpecifications(),
        )
    )

    assert result.status is (RequirementsGenerationStatus.REJECTED)
    assert result.issue is (RequirementsGenerationIssueCode.CONTEXT_CHANGED)


def test_generation_rejects_mismatched_provider_grounding() -> None:
    """Do not trust a provider that changes exact governed references."""
    result = run_generation(
        service(
            FakeGovernance(governed_context()),
            InMemorySpecifications(),
            proposals=(InvalidProposalPort()),
        )
    )

    assert result.status is (RequirementsGenerationStatus.REJECTED)
    assert result.issue is (RequirementsGenerationIssueCode.INVALID_PROPOSAL)


def test_generation_does_not_replace_an_existing_specification() -> None:
    """Keep initial generation distinct from later owner revisions."""
    context = governed_context()
    repository = InMemorySpecifications()

    first = run_generation(
        service(
            FakeGovernance(context),
            repository,
        )
    )

    assert first.version is not None

    second = run_generation(
        service(
            FakeGovernance(context),
            repository,
        )
    )

    assert second.status is (RequirementsGenerationStatus.REJECTED)
    assert second.issue is (RequirementsGenerationIssueCode.SPECIFICATION_ALREADY_EXISTS)
    assert repository.versions == [
        first.version,
    ]
