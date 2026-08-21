"""Tests for governed Design Package generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.models.design import (
    DesignAgentTeamInput,
    DesignProposalIssueCode,
    DesignProposalProviderKind,
    DesignProposalRequest,
    DesignProposalResult,
    DesignProposalStatus,
    DesignRequirementsInput,
    DesignUserModelingInput,
    DesignUserTwinInput,
)
from orchestwin.models.fake_design import FakeDeterministicDesignAdapter
from orchestwin.projects.design_application import (
    DesignGenerationIssueCode,
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
    HumanGateStatus,
    HumanGateType,
)

from .design_fixtures import OWNER_ID, PROJECT_ID, requirements_version

DESIGN_VERSION_ID = UUID("00000000-0000-4000-8000-000000000091")
GATE_ID = UUID("00000000-0000-4000-8000-000000000092")
CREATED_AT = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


def current_requirements_version() -> RequirementsSpecificationVersion:
    """Align the shared Requirements fixture with the active fixed catalog."""
    base = requirements_version()
    specification = replace(
        base.specification,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
    )

    return replace(
        base,
        specification=specification,
        content_hash=specification.content_hash,
    )


def grounded_observation() -> ProfileObservation:
    """Create one concrete, owner-provided User Twin observation."""
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


def governed_context(
    *,
    approved: bool = True,
) -> GovernedDesignContext:
    """Create one exact Gate-4-approved design context."""
    requirements = current_requirements_version()
    specification = requirements.specification
    twin = specification.user_twin_references[0]
    requirements_input = DesignRequirementsInput(version=requirements)
    team = DesignAgentTeamInput(
        reference=VersionedArtifactReference(
            kind=ArtifactKind.AGENT_TEAM,
            artifact_id=specification.agent_team_reference.artifact_id,
            version_number=specification.agent_team_reference.version_number,
            content_hash=specification.agent_team_reference.content_hash,
        ),
        selected_agent_ids=(
            AgentIdentifier.WORKFLOW_ORCHESTRATOR,
            AgentIdentifier.UX_UI_DESIGNER,
            AgentIdentifier.QA_TEST_ENGINEER,
        ),
    )
    user_modeling = DesignUserModelingInput(
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
    )
    artifact = GateArtifactReference(
        project_id=PROJECT_ID,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact_id=requirements.id,
        version=requirements.version_number,
        content_hash=requirements.content_hash,
    )
    gate = HumanGate(
        id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.REQUIREMENTS,
        artifact=artifact,
        iteration=1,
        max_iterations=3,
        status=(HumanGateStatus.APPROVED if approved else HumanGateStatus.PENDING_APPROVAL),
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        event_sequence=1,
    )

    return GovernedDesignContext(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=requirements_input,
        team=team,
        user_modeling=user_modeling,
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        requirements_gate=gate,
    )


class StaticGovernance:
    """Return a configured context for every owner-scoped load."""

    def __init__(self, context: GovernedDesignContext | None) -> None:
        self.context = context
        self.calls = 0

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedDesignContext | None:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        self.calls += 1
        return self.context


class SequencedGovernance:
    """Return a different context after a provider call."""

    def __init__(self, contexts: tuple[GovernedDesignContext | None, ...]) -> None:
        self._contexts = contexts
        self.calls = 0

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedDesignContext | None:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        index = min(self.calls, len(self._contexts) - 1)
        self.calls += 1
        return self._contexts[index]


class CountingProposalPort:
    """Delegate to the deterministic adapter while exposing call count."""

    def __init__(self) -> None:
        self.calls = 0
        self.delegate = FakeDeterministicDesignAdapter()

    async def propose(self, request: DesignProposalRequest) -> DesignProposalResult:
        self.calls += 1
        return await self.delegate.propose(request)


class StaticProposalPort:
    """Return one configured provider result."""

    def __init__(self, result: DesignProposalResult) -> None:
        self.result = result
        self.calls = 0

    async def propose(self, request: DesignProposalRequest) -> DesignProposalResult:
        del request
        self.calls += 1
        return self.result


class InMemoryPackageRepository:
    """Minimal repository fake with configurable append behavior."""

    def __init__(
        self,
        *,
        current: DesignPackageVersion | None = None,
        append_status: DesignVersionAppendStatus = DesignVersionAppendStatus.APPENDED,
    ) -> None:
        self.current_version = current
        self.append_status = append_status
        self.appended: list[DesignPackageVersion] = []

    async def current(self, *, project_id: UUID) -> DesignPackageVersion | None:
        assert project_id == PROJECT_ID
        return self.current_version

    async def append(self, version: DesignPackageVersion) -> DesignVersionAppendStatus:
        self.appended.append(version)
        if self.append_status is DesignVersionAppendStatus.APPENDED:
            self.current_version = version
        return self.append_status


@dataclass
class InMemoryUnitOfWork:
    """Transactional fake used by the application service."""

    packages: InMemoryPackageRepository
    commits: int = 0
    rollbacks: int = 0

    async def __aenter__(self) -> InMemoryUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class UnitOfWorkFactory:
    """Expose one shared in-memory repository through short-lived units."""

    def __init__(self, repository: InMemoryPackageRepository) -> None:
        self.repository = repository
        self.units: list[InMemoryUnitOfWork] = []

    def __call__(self, *, owner_user_id: UUID) -> InMemoryUnitOfWork:
        assert owner_user_id == OWNER_ID
        unit = InMemoryUnitOfWork(packages=self.repository)
        self.units.append(unit)
        return unit


def run(service: LocalDesignGenerationService):
    """Execute one generation request synchronously for concise tests."""
    return asyncio.run(
        service.generate(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
        )
    )


def service(
    *,
    governance,
    proposals,
    repository: InMemoryPackageRepository | None = None,
) -> tuple[LocalDesignGenerationService, UnitOfWorkFactory]:
    """Create a deterministic application service and its inspectable UoW factory."""
    resolved_repository = repository if repository is not None else InMemoryPackageRepository()
    factory = UnitOfWorkFactory(resolved_repository)
    application = LocalDesignGenerationService(
        governance=governance,
        proposals=proposals,
        uow_factory=factory,
        uuid_factory=lambda: DESIGN_VERSION_ID,
        clock=lambda: CREATED_AT,
    )
    return application, factory


def generated_version() -> DesignPackageVersion:
    """Create an existing Design Package version through the real service path."""
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=CountingProposalPort(),
    )
    result = run(application)
    assert result.version is not None
    return result.version


def test_generation_creates_one_unselected_immutable_design_version() -> None:
    """Persist deterministic design output only after exact Requirements approval."""
    governance = StaticGovernance(governed_context())
    proposals = CountingProposalPort()
    repository = InMemoryPackageRepository()
    application, factory = service(
        governance=governance,
        proposals=proposals,
        repository=repository,
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.CREATED
    assert result.issue is None
    assert result.version is not None
    assert result.version.id == DESIGN_VERSION_ID
    assert result.version.version_number == 1
    assert result.version.based_on_version_number is None
    assert result.version.created_by_user_id == OWNER_ID
    assert result.version.created_at == CREATED_AT
    assert result.version.package.owner_selected_alternative_id is None
    assert result.version.package.prototype is None
    assert not result.version.package.ready_for_gate
    assert repository.appended == [result.version]
    assert proposals.calls == 1
    assert governance.calls == 2
    assert sum(unit.commits for unit in factory.units) == 1


def test_generation_rejects_missing_or_unapproved_requirements() -> None:
    """Keep design generation behind exact Gate 4 approval."""
    for context, expected_issue in (
        (None, DesignGenerationIssueCode.PROJECT_NOT_FOUND),
        (
            governed_context(approved=False),
            DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED,
        ),
        (
            replace(governed_context(), requirements_gate=None),
            DesignGenerationIssueCode.REQUIREMENTS_APPROVAL_REQUIRED,
        ),
    ):
        proposals = CountingProposalPort()
        application, factory = service(
            governance=StaticGovernance(context),
            proposals=proposals,
        )

        result = run(application)

        assert result.status is DesignGenerationStatus.REJECTED
        assert result.issue is expected_issue
        assert result.version is None
        assert proposals.calls == 0
        assert not factory.units


def test_generation_rejects_when_a_design_package_already_exists() -> None:
    """Prevent a second initial proposal from replacing versioned owner state."""
    existing = generated_version()
    proposals = CountingProposalPort()
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=proposals,
        repository=InMemoryPackageRepository(current=existing),
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.REJECTED
    assert result.issue is DesignGenerationIssueCode.DESIGN_PACKAGE_ALREADY_EXISTS
    assert proposals.calls == 0


def test_generation_preserves_typed_provider_rejections() -> None:
    """Map expected provider refusal without raising hidden exceptions."""
    proposals = StaticProposalPort(
        DesignProposalResult(
            status=DesignProposalStatus.REJECTED,
            provider_kind=DesignProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id="fake-design-test",
            provider_version=1,
            issue=DesignProposalIssueCode.GROUNDED_INPUT_REQUIRED,
        )
    )
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.REJECTED
    assert result.issue is DesignGenerationIssueCode.PROPOSAL_REJECTED
    assert result.proposal_issue is DesignProposalIssueCode.GROUNDED_INPUT_REQUIRED


def test_generation_rejects_provider_selection_before_owner_review() -> None:
    """Do not let a provider silently make the Gate 5 owner selection."""
    context = governed_context()
    proposal = asyncio.run(FakeDeterministicDesignAdapter().propose(context.to_proposal_request()))
    assert proposal.package is not None
    selected_package = replace(
        proposal.package,
        owner_selected_alternative_id=proposal.package.alternatives[0].id,
    )
    proposals = StaticProposalPort(
        replace(
            proposal,
            package=selected_package,
        )
    )
    application, _ = service(
        governance=StaticGovernance(context),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.REJECTED
    assert result.issue is DesignGenerationIssueCode.INVALID_PROPOSAL


def test_generation_rejects_context_changes_after_provider_execution() -> None:
    """Discard stale output when Gate 4 ceases to approve the exact input tuple."""
    approved = governed_context()
    changed = replace(approved, requirements_gate=None)
    proposals = CountingProposalPort()
    application, factory = service(
        governance=SequencedGovernance((approved, changed)),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.REJECTED
    assert result.issue is DesignGenerationIssueCode.CONTEXT_CHANGED
    assert proposals.calls == 1
    assert len(factory.units) == 1
    assert not factory.repository.appended


def test_generation_reports_append_conflicts_without_committing() -> None:
    """Keep persistence conflicts typed and leave the transaction uncommitted."""
    repository = InMemoryPackageRepository(
        append_status=DesignVersionAppendStatus.VERSION_CONFLICT,
    )
    application, factory = service(
        governance=StaticGovernance(governed_context()),
        proposals=CountingProposalPort(),
        repository=repository,
    )

    result = run(application)

    assert result.status is DesignGenerationStatus.REJECTED
    assert result.issue is DesignGenerationIssueCode.PERSISTENCE_REJECTED
    assert result.persistence_status is DesignVersionAppendStatus.VERSION_CONFLICT
    assert repository.appended
    assert sum(unit.commits for unit in factory.units) == 0
