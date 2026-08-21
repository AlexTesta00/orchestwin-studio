"""Tests for governed Architecture Package generation."""

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
from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureProposalIssueCode,
    ArchitectureProposalProviderKind,
    ArchitectureProposalRequest,
    ArchitectureProposalResult,
    ArchitectureProposalStatus,
    ArchitectureRequirementsInput,
)
from orchestwin.models.fake_architecture import FakeDeterministicArchitectureAdapter
from orchestwin.projects.architecture_application import (
    ArchitectureGenerationIssueCode,
    ArchitectureGenerationStatus,
    ArchitectureVersionAppendStatus,
    GovernedArchitectureContext,
    LocalArchitectureGenerationService,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.gates import (
    GateArtifactReference,
    HumanGate,
    HumanGateStatus,
    HumanGateType,
)

from .design_fixtures import OWNER_ID, PROJECT_ID, design_version, requirements_version

ARCHITECTURE_VERSION_ID = UUID("00000000-0000-4000-8000-000000000801")
GATE_ID = UUID("00000000-0000-4000-8000-000000000802")
CREATED_AT = datetime(2026, 8, 21, 13, 0, tzinfo=UTC)


def governed_context(
    *,
    approved: bool = True,
) -> GovernedArchitectureContext:
    """Create one exact Gate-5-approved architecture context."""
    requirements = requirements_version()
    design = design_version()
    grounding = design.package.grounding
    gate = HumanGate(
        id=GATE_ID,
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        gate_type=HumanGateType.DESIGN,
        artifact=GateArtifactReference(
            project_id=PROJECT_ID,
            gate_type=HumanGateType.DESIGN,
            artifact_id=design.id,
            version=design.version_number,
            content_hash=design.content_hash,
        ),
        iteration=1,
        max_iterations=3,
        status=(HumanGateStatus.APPROVED if approved else HumanGateStatus.PENDING_APPROVAL),
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        event_sequence=1,
    )

    return GovernedArchitectureContext(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=ArchitectureRequirementsInput(version=requirements),
        design=ArchitectureDesignInput(version=design),
        team=ArchitectureAgentTeamInput(
            reference=grounding.agent_team_reference,
            selected_agent_ids=(
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.SOFTWARE_ARCHITECT,
                AgentIdentifier.QA_TEST_ENGINEER,
            ),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
        design_gate=gate,
    )


class StaticGovernance:
    """Return a configured context for every owner-scoped load."""

    def __init__(self, context: GovernedArchitectureContext | None) -> None:
        self.context = context
        self.calls = 0

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedArchitectureContext | None:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        self.calls += 1
        return self.context


class SequencedGovernance:
    """Return a different context after a provider call."""

    def __init__(
        self,
        contexts: tuple[GovernedArchitectureContext | None, ...],
    ) -> None:
        self._contexts = contexts
        self.calls = 0

    async def load_current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> GovernedArchitectureContext | None:
        assert owner_user_id == OWNER_ID
        assert project_id == PROJECT_ID
        index = min(self.calls, len(self._contexts) - 1)
        self.calls += 1
        return self._contexts[index]


class CountingProposalPort:
    """Delegate to the deterministic adapter while exposing call count."""

    def __init__(self) -> None:
        self.calls = 0
        self.delegate = FakeDeterministicArchitectureAdapter()

    async def propose(
        self,
        request: ArchitectureProposalRequest,
    ) -> ArchitectureProposalResult:
        self.calls += 1
        return await self.delegate.propose(request)


class StaticProposalPort:
    """Return one configured provider result."""

    def __init__(self, result: ArchitectureProposalResult) -> None:
        self.result = result
        self.calls = 0

    async def propose(
        self,
        request: ArchitectureProposalRequest,
    ) -> ArchitectureProposalResult:
        del request
        self.calls += 1
        return self.result


class InMemoryPackageRepository:
    """Minimal repository fake with configurable append behavior."""

    def __init__(
        self,
        *,
        current: ArchitecturePackageVersion | None = None,
        append_status: ArchitectureVersionAppendStatus = (ArchitectureVersionAppendStatus.APPENDED),
    ) -> None:
        self.current_version = current
        self.append_status = append_status
        self.appended: list[ArchitecturePackageVersion] = []

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        assert project_id == PROJECT_ID
        return self.current_version

    async def append(
        self,
        version: ArchitecturePackageVersion,
    ) -> ArchitectureVersionAppendStatus:
        self.appended.append(version)
        if self.append_status is ArchitectureVersionAppendStatus.APPENDED:
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
    """Expose one repository through short-lived units."""

    def __init__(self, repository: InMemoryPackageRepository) -> None:
        self.repository = repository
        self.units: list[InMemoryUnitOfWork] = []

    def __call__(self, *, owner_user_id: UUID) -> InMemoryUnitOfWork:
        assert owner_user_id == OWNER_ID
        unit = InMemoryUnitOfWork(packages=self.repository)
        self.units.append(unit)
        return unit


def run(service: LocalArchitectureGenerationService):
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
) -> tuple[LocalArchitectureGenerationService, UnitOfWorkFactory]:
    """Create a deterministic service and inspectable UoW factory."""
    resolved_repository = repository if repository is not None else InMemoryPackageRepository()
    factory = UnitOfWorkFactory(resolved_repository)
    application = LocalArchitectureGenerationService(
        governance=governance,
        proposals=proposals,
        uow_factory=factory,
        uuid_factory=lambda: ARCHITECTURE_VERSION_ID,
        clock=lambda: CREATED_AT,
    )
    return application, factory


def generated_version() -> ArchitecturePackageVersion:
    """Create an existing Architecture Package through the real service path."""
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=CountingProposalPort(),
    )
    result = run(application)
    assert result.version is not None
    return result.version


def test_generation_creates_one_grounded_immutable_architecture_version() -> None:
    """Persist deterministic output only after exact Design approval."""
    governance = StaticGovernance(governed_context())
    proposals = CountingProposalPort()
    repository = InMemoryPackageRepository()
    application, factory = service(
        governance=governance,
        proposals=proposals,
        repository=repository,
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.CREATED
    assert result.issue is None
    assert result.version is not None
    assert result.version.id == ARCHITECTURE_VERSION_ID
    assert result.version.version_number == 1
    assert result.version.based_on_version_number is None
    assert result.version.created_by_user_id == OWNER_ID
    assert result.version.created_at == CREATED_AT
    assert (
        result.version.package.grounding.design_package_reference
        == governed_context().design.reference
    )
    assert repository.appended == [result.version]
    assert proposals.calls == 1
    assert governance.calls == 2
    assert sum(unit.commits for unit in factory.units) == 1


def test_generation_rejects_missing_or_unapproved_design() -> None:
    """Keep architecture planning behind exact Gate 5 approval."""
    for context, expected_issue in (
        (None, ArchitectureGenerationIssueCode.PROJECT_NOT_FOUND),
        (
            governed_context(approved=False),
            ArchitectureGenerationIssueCode.DESIGN_APPROVAL_REQUIRED,
        ),
        (
            replace(governed_context(), design_gate=None),
            ArchitectureGenerationIssueCode.DESIGN_APPROVAL_REQUIRED,
        ),
    ):
        proposals = CountingProposalPort()
        application, factory = service(
            governance=StaticGovernance(context),
            proposals=proposals,
        )

        result = run(application)

        assert result.status is ArchitectureGenerationStatus.REJECTED
        assert result.issue is expected_issue
        assert result.version is None
        assert proposals.calls == 0
        assert not factory.units


def test_generation_rejects_when_an_architecture_package_already_exists() -> None:
    """Prevent a second initial proposal from replacing versioned owner state."""
    existing = generated_version()
    proposals = CountingProposalPort()
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=proposals,
        repository=InMemoryPackageRepository(current=existing),
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.REJECTED
    assert result.issue is ArchitectureGenerationIssueCode.ARCHITECTURE_PACKAGE_ALREADY_EXISTS
    assert proposals.calls == 0


def test_generation_preserves_typed_provider_rejections() -> None:
    """Map expected provider refusal without raising hidden exceptions."""
    proposals = StaticProposalPort(
        ArchitectureProposalResult(
            status=ArchitectureProposalStatus.REJECTED,
            provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id="fake-architecture-test",
            provider_version=1,
            issue=ArchitectureProposalIssueCode.GROUNDED_INPUT_REQUIRED,
        )
    )
    application, _ = service(
        governance=StaticGovernance(governed_context()),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.REJECTED
    assert result.issue is ArchitectureGenerationIssueCode.PROPOSAL_REJECTED
    assert result.proposal_issue is ArchitectureProposalIssueCode.GROUNDED_INPUT_REQUIRED


def test_generation_rejects_a_provider_package_with_changed_grounding() -> None:
    """Do not persist output grounded in a different Design Package."""
    context = governed_context()
    proposal = asyncio.run(
        FakeDeterministicArchitectureAdapter().propose(context.to_proposal_request())
    )
    assert proposal.package is not None
    changed_grounding = replace(
        proposal.package.grounding,
        design_package_reference=replace(
            proposal.package.grounding.design_package_reference,
            content_hash="f" * 64,
        ),
    )
    changed_package = replace(proposal.package, grounding=changed_grounding)
    proposals = StaticProposalPort(replace(proposal, package=changed_package))
    application, _ = service(
        governance=StaticGovernance(context),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.REJECTED
    assert result.issue is ArchitectureGenerationIssueCode.INVALID_PROPOSAL


def test_generation_rejects_context_changes_after_provider_execution() -> None:
    """Discard stale output when Gate 5 ceases to approve the exact input tuple."""
    approved = governed_context()
    changed = replace(approved, design_gate=None)
    proposals = CountingProposalPort()
    application, factory = service(
        governance=SequencedGovernance((approved, changed)),
        proposals=proposals,
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.REJECTED
    assert result.issue is ArchitectureGenerationIssueCode.CONTEXT_CHANGED
    assert proposals.calls == 1
    assert len(factory.units) == 1
    assert not factory.repository.appended


def test_generation_reports_append_conflicts_without_committing() -> None:
    """Keep persistence conflicts typed and leave the transaction uncommitted."""
    repository = InMemoryPackageRepository(
        append_status=ArchitectureVersionAppendStatus.VERSION_CONFLICT,
    )
    application, factory = service(
        governance=StaticGovernance(governed_context()),
        proposals=CountingProposalPort(),
        repository=repository,
    )

    result = run(application)

    assert result.status is ArchitectureGenerationStatus.REJECTED
    assert result.issue is ArchitectureGenerationIssueCode.PERSISTENCE_REJECTED
    assert result.persistence_status is ArchitectureVersionAppendStatus.VERSION_CONFLICT
    assert repository.appended
    assert sum(unit.commits for unit in factory.units) == 0
