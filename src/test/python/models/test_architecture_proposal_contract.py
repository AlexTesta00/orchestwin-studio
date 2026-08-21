"""Tests for provider-independent architecture proposal contracts."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import ArtifactKind, VersionedArtifactReference
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureProposalIssueCode,
    ArchitectureProposalPort,
    ArchitectureProposalProviderKind,
    ArchitectureProposalRequest,
    ArchitectureProposalResult,
    ArchitectureProposalStatus,
    ArchitectureRequirementsInput,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion

_FIXTURE_PACKAGE_NAME = "architecture_proposal_test_artifacts"
_FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"
FOREIGN_PROJECT_ID = UUID("00000000-0000-4000-8000-000000000999")


def load_architecture_fixtures() -> tuple[ModuleType, ModuleType]:
    """Load shared artifact fixtures as a private package for relative imports."""
    package_spec = importlib.util.spec_from_file_location(
        _FIXTURE_PACKAGE_NAME,
        _FIXTURE_DIRECTORY / "__init__.py",
        submodule_search_locations=[str(_FIXTURE_DIRECTORY)],
    )

    if package_spec is None or package_spec.loader is None:
        raise AssertionError("could not load the architecture fixture package")

    package = importlib.util.module_from_spec(package_spec)
    sys.modules[_FIXTURE_PACKAGE_NAME] = package
    package_spec.loader.exec_module(package)

    design_module = importlib.import_module(f"{_FIXTURE_PACKAGE_NAME}.design_fixtures")
    architecture_module = importlib.import_module(f"{_FIXTURE_PACKAGE_NAME}.architecture_fixtures")

    return design_module, architecture_module


DESIGN_FIXTURES, ARCHITECTURE_FIXTURES = load_architecture_fixtures()
PROJECT_ID: UUID = DESIGN_FIXTURES.PROJECT_ID


def stage_reference(
    kind: ArtifactKind,
    ordinal: int,
) -> VersionedArtifactReference:
    """Create one exact post-Requirements artifact reference."""
    return VersionedArtifactReference(
        kind=kind,
        artifact_id=UUID(int=ordinal),
        version_number=1,
        content_hash=f"{ordinal:064x}",
    )


def proposal_request(
    *,
    selected_agent_ids: tuple[AgentIdentifier, ...] | None = None,
    requirements: RequirementsSpecificationVersion | None = None,
    design: DesignPackageVersion | None = None,
) -> ArchitectureProposalRequest:
    """Create one complete governed architecture request."""
    requirements_input = (
        requirements if requirements is not None else DESIGN_FIXTURES.requirements_version()
    )
    design_input = design if design is not None else DESIGN_FIXTURES.design_version()
    grounding = design_input.package.grounding

    return ArchitectureProposalRequest(
        project_id=PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=ArchitectureRequirementsInput(version=requirements_input),
        design=ArchitectureDesignInput(version=design_input),
        team=ArchitectureAgentTeamInput(
            reference=grounding.agent_team_reference,
            selected_agent_ids=(
                selected_agent_ids
                if selected_agent_ids is not None
                else (
                    AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                    AgentIdentifier.SOFTWARE_ARCHITECT,
                    AgentIdentifier.QA_TEST_ENGINEER,
                )
            ),
        ),
        catalog_version=AGENT_CATALOG_VERSION,
        catalog_content_hash=AGENT_CATALOG_CONTENT_HASH,
    )


def test_request_preserves_exact_requirements_design_and_team_context() -> None:
    """Expose every approved stage input through one deterministic contract."""
    request = proposal_request()
    snapshot = request.to_snapshot()

    assert (
        request.requirements.reference
        == request.design.version.package.grounding.requirements_reference
    )
    assert request.team.reference == request.design.version.package.grounding.agent_team_reference
    assert request.design.ready_for_architecture
    assert snapshot["requirements"]["id"] == str(request.requirements.version.id)
    assert snapshot["design"]["id"] == str(request.design.version.id)
    assert snapshot["team"]["reference"]["kind"] == "AGENT_TEAM"
    assert len(request.content_hash) == 64


def test_team_input_requires_unique_fixed_catalog_order() -> None:
    """Keep the architecture provider aligned with the approved fixed catalog."""
    with pytest.raises(ValueError, match="must be unique"):
        ArchitectureAgentTeamInput(
            reference=stage_reference(ArtifactKind.AGENT_TEAM, 14),
            selected_agent_ids=(
                AgentIdentifier.SOFTWARE_ARCHITECT,
                AgentIdentifier.SOFTWARE_ARCHITECT,
            ),
        )

    with pytest.raises(ValueError, match="fixed-catalog order"):
        ArchitectureAgentTeamInput(
            reference=stage_reference(ArtifactKind.AGENT_TEAM, 14),
            selected_agent_ids=(
                AgentIdentifier.QA_TEST_ENGINEER,
                AgentIdentifier.SOFTWARE_ARCHITECT,
            ),
        )


def test_request_rejects_a_design_package_from_another_project() -> None:
    """Prevent architecture planning across project boundaries."""
    request = proposal_request()
    foreign_package = replace(
        request.design.version.package,
        project_id=FOREIGN_PROJECT_ID,
    )
    foreign_design = replace(
        request.design.version,
        project_id=FOREIGN_PROJECT_ID,
        package=foreign_package,
        content_hash=foreign_package.content_hash,
    )

    with pytest.raises(ValueError, match="Design Package must belong to its project"):
        replace(
            request,
            design=ArchitectureDesignInput(version=foreign_design),
        )


def test_request_requires_the_design_grounded_requirements_version() -> None:
    """Reject a Design Package grounded in a different Requirements artifact."""
    request = proposal_request()
    grounding = replace(
        request.design.version.package.grounding,
        requirements_reference=stage_reference(
            ArtifactKind.REQUIREMENTS_SPECIFICATION,
            99,
        ),
    )
    package = replace(request.design.version.package, grounding=grounding)
    design = replace(
        request.design.version,
        package=package,
        content_hash=package.content_hash,
    )

    with pytest.raises(ValueError, match="Requirements must match the Design Package"):
        replace(
            request,
            design=ArchitectureDesignInput(version=design),
        )


def test_request_requires_the_exact_design_grounded_team() -> None:
    """Reject a provider Team reference different from the selected Design context."""
    request = proposal_request()
    team = replace(
        request.team,
        reference=stage_reference(ArtifactKind.AGENT_TEAM, 99),
    )

    with pytest.raises(ValueError, match="team must match the Design Package"):
        replace(request, team=team)


def test_request_requires_design_context_to_match_requirements_context() -> None:
    """Protect exact Team and User Modeling lineage across governed stages."""
    request = proposal_request()
    foreign_team_reference = stage_reference(ArtifactKind.AGENT_TEAM, 99)
    grounding = replace(
        request.design.version.package.grounding,
        agent_team_reference=foreign_team_reference,
    )
    package = replace(request.design.version.package, grounding=grounding)
    design = replace(
        request.design.version,
        package=package,
        content_hash=package.content_hash,
    )
    team = replace(request.team, reference=foreign_team_reference)

    with pytest.raises(ValueError, match="team must match the Requirements context"):
        replace(
            request,
            design=ArchitectureDesignInput(version=design),
            team=team,
        )


def test_request_rejects_noncurrent_catalog_metadata() -> None:
    """Keep architecture proposals reproducible against the current catalog."""
    request = proposal_request()

    with pytest.raises(ValueError, match="current agent catalog"):
        replace(request, catalog_content_hash="0" * 64)


def test_request_leaves_provider_preconditions_as_typed_outcomes() -> None:
    """Allow the provider to reject missing roles or design selection explicitly."""
    missing_specialists = proposal_request(
        selected_agent_ids=(AgentIdentifier.WORKFLOW_ORCHESTRATOR,),
    )
    unselected_package = DESIGN_FIXTURES.design_package(
        selected=False,
        include_prototype=False,
    )
    unselected_design = DESIGN_FIXTURES.design_version(package=unselected_package)
    unselected_request = proposal_request(design=unselected_design)

    assert missing_specialists.team.selected_agent_ids == (AgentIdentifier.WORKFLOW_ORCHESTRATOR,)
    assert not unselected_request.design.ready_for_architecture


def test_result_enforces_proposed_and_rejected_shapes() -> None:
    """Keep expected provider failures typed rather than exceptional."""
    proposed = ArchitectureProposalResult(
        status=ArchitectureProposalStatus.PROPOSED,
        provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-architecture",
        provider_version=1,
        package=ARCHITECTURE_FIXTURES.architecture_package(),
    )
    rejected = ArchitectureProposalResult(
        status=ArchitectureProposalStatus.REJECTED,
        provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-architecture",
        provider_version=1,
        issue=ArchitectureProposalIssueCode.SOFTWARE_ARCHITECT_REQUIRED,
    )

    assert proposed.package is not None
    assert proposed.issue is None
    assert rejected.package is None
    assert rejected.issue is ArchitectureProposalIssueCode.SOFTWARE_ARCHITECT_REQUIRED
    assert len(proposed.content_hash) == 64

    with pytest.raises(ValueError, match="requires a package"):
        ArchitectureProposalResult(
            status=ArchitectureProposalStatus.PROPOSED,
            provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id="fake-architecture",
            provider_version=1,
        )

    with pytest.raises(ValueError, match="requires one issue"):
        ArchitectureProposalResult(
            status=ArchitectureProposalStatus.REJECTED,
            provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
            provider_id="fake-architecture",
            provider_version=1,
            package=ARCHITECTURE_FIXTURES.architecture_package(),
        )


def test_result_requires_normalized_bounded_provider_metadata() -> None:
    """Keep provider identities stable and safe for persistence and reporting."""
    with pytest.raises(ValueError, match="must be normalized"):
        ArchitectureProposalResult(
            status=ArchitectureProposalStatus.REJECTED,
            provider_kind=ArchitectureProposalProviderKind.MODEL_ADAPTER,
            provider_id=" model-adapter",
            provider_version=1,
            issue=ArchitectureProposalIssueCode.GROUNDED_INPUT_REQUIRED,
        )

    with pytest.raises(ValueError, match="exceeds maximum length"):
        ArchitectureProposalResult(
            status=ArchitectureProposalStatus.REJECTED,
            provider_kind=ArchitectureProposalProviderKind.MODEL_ADAPTER,
            provider_id="x" * 129,
            provider_version=1,
            issue=ArchitectureProposalIssueCode.INVALID_PROVIDER_OUTPUT,
        )


def test_architecture_proposal_port_is_runtime_checkable() -> None:
    """Allow composition roots to validate the provider boundary."""

    class FakePort:
        async def propose(
            self,
            request: ArchitectureProposalRequest,
        ) -> ArchitectureProposalResult:
            del request

            return ArchitectureProposalResult(
                status=ArchitectureProposalStatus.REJECTED,
                provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
                provider_id="fake-architecture",
                provider_version=1,
                issue=ArchitectureProposalIssueCode.DESIGN_SELECTION_REQUIRED,
            )

    assert isinstance(FakePort(), ArchitectureProposalPort)


def test_identical_requests_and_results_are_reproducibly_hashed() -> None:
    """Keep architecture provider input and output content-addressable."""
    first_request = proposal_request()
    second_request = proposal_request()
    first_result = ArchitectureProposalResult(
        status=ArchitectureProposalStatus.PROPOSED,
        provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-architecture",
        provider_version=1,
        package=ARCHITECTURE_FIXTURES.architecture_package(),
    )
    second_result = ArchitectureProposalResult(
        status=ArchitectureProposalStatus.PROPOSED,
        provider_kind=ArchitectureProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="fake-architecture",
        provider_version=1,
        package=ARCHITECTURE_FIXTURES.architecture_package(),
    )

    assert first_request.to_snapshot() == second_request.to_snapshot()
    assert first_request.content_hash == second_request.content_hash
    assert first_result.to_snapshot() == second_result.to_snapshot()
    assert first_result.content_hash == second_result.content_hash
