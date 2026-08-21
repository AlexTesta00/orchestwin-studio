"""Tests for deterministic governed architecture proposals."""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.models import fake_architecture
from orchestwin.models.architecture import (
    ArchitectureAgentTeamInput,
    ArchitectureDesignInput,
    ArchitectureProposalIssueCode,
    ArchitectureProposalProviderKind,
    ArchitectureProposalRequest,
    ArchitectureProposalStatus,
    ArchitectureRequirementsInput,
)
from orchestwin.models.fake_architecture import (
    FAKE_ARCHITECTURE_PROVIDER_ID,
    FAKE_ARCHITECTURE_PROVIDER_VERSION,
    FakeDeterministicArchitectureAdapter,
)
from orchestwin.projects.domain import ProjectMode

_FIXTURE_PACKAGE_NAME = "fake_architecture_test_artifacts"
_FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "artifacts"


def load_design_fixtures() -> ModuleType:
    """Load shared Design fixtures with their package-relative imports intact."""
    package_spec = importlib.util.spec_from_file_location(
        _FIXTURE_PACKAGE_NAME,
        _FIXTURE_DIRECTORY / "__init__.py",
        submodule_search_locations=[str(_FIXTURE_DIRECTORY)],
    )

    if package_spec is None or package_spec.loader is None:
        raise AssertionError("could not load the Design fixture package")

    package = importlib.util.module_from_spec(package_spec)
    sys.modules[_FIXTURE_PACKAGE_NAME] = package
    package_spec.loader.exec_module(package)

    return importlib.import_module(f"{_FIXTURE_PACKAGE_NAME}.design_fixtures")


DESIGN_FIXTURES = load_design_fixtures()


def proposal_request(
    *,
    selected_agent_ids: tuple[AgentIdentifier, ...] | None = None,
    selected: bool = True,
) -> ArchitectureProposalRequest:
    """Create one complete governed architecture request."""
    design_package = DESIGN_FIXTURES.design_package(
        selected=selected,
        include_prototype=selected,
    )
    design_version = DESIGN_FIXTURES.design_version(package=design_package)

    return ArchitectureProposalRequest(
        project_id=DESIGN_FIXTURES.PROJECT_ID,
        project_mode=ProjectMode.GREENFIELD_GENERATION,
        requirements=ArchitectureRequirementsInput(version=DESIGN_FIXTURES.requirements_version()),
        design=ArchitectureDesignInput(version=design_version),
        team=ArchitectureAgentTeamInput(
            reference=design_package.grounding.agent_team_reference,
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


def propose(request: ArchitectureProposalRequest):
    """Run the fake adapter synchronously for concise unit tests."""
    return asyncio.run(FakeDeterministicArchitectureAdapter().propose(request))


def test_fake_architecture_proposal_is_reproducible_and_identified() -> None:
    """Return identical provider output for identical governed input."""
    request = proposal_request()

    first = propose(request)
    second = propose(request)

    assert first.status is ArchitectureProposalStatus.PROPOSED
    assert first.provider_kind is ArchitectureProposalProviderKind.FAKE_DETERMINISTIC
    assert first.provider_id == FAKE_ARCHITECTURE_PROVIDER_ID
    assert first.provider_version == FAKE_ARCHITECTURE_PROVIDER_VERSION
    assert first == second
    assert first.content_hash == second.content_hash
    assert first.package is not None


def test_fake_architecture_preserves_exact_design_grounding() -> None:
    """Keep architecture planning scoped to the approved selected Design Package."""
    request = proposal_request()
    result = propose(request)

    assert result.package is not None

    grounding = result.package.grounding
    design = request.design.version

    assert grounding.design_package_reference == request.design.reference
    assert grounding.requirements_reference == request.requirements.reference
    assert grounding.agent_team_reference == request.team.reference
    assert grounding.owner_selected_alternative_id == design.package.owner_selected_alternative_id
    assert grounding.prototype_id == design.package.prototype.id
    assert result.package.architecture.selected_design_alternative_id == (
        design.package.owner_selected_alternative_id
    )
    assert result.package.architecture.prototype_id == design.package.prototype.id


def test_fake_architecture_covers_every_requirement_criterion_and_component() -> None:
    """Produce an internally complete architecture and test plan."""
    request = proposal_request()
    result = propose(request)

    assert result.package is not None

    package = result.package
    specification = request.requirements.version.specification
    requirement_ids = {requirement.id for requirement in specification.requirements}
    criterion_ids = {criterion.id for criterion in specification.acceptance_criteria}
    component_ids = {component.id for component in package.architecture.components}
    planned_requirements = {
        requirement_id
        for test_case in package.test_plan.test_cases
        for requirement_id in test_case.requirement_ids
    }
    planned_criteria = {
        criterion_id
        for test_case in package.test_plan.test_cases
        for criterion_id in test_case.acceptance_criterion_ids
    }

    assert set(package.architecture.requirement_ids) == requirement_ids
    assert set(package.architecture.acceptance_criterion_ids) == criterion_ids
    assert set(package.test_plan.architecture_component_ids) == component_ids
    assert planned_requirements == requirement_ids
    assert planned_criteria == criterion_ids
    assert all(
        set(test_case.architecture_component_ids) == component_ids
        for test_case in package.test_plan.test_cases
    )
    assert package.test_plan.quality_gates[0].minimum_pass_rate == 100
    assert package.test_plan.quality_gates[0].blocking


def test_fake_architecture_keeps_execution_capability_explicitly_unresolved() -> None:
    """Avoid claiming a validated stack before capability negotiation."""
    result = propose(proposal_request())

    assert result.package is not None

    package = result.package
    combined_assumptions = (
        package.architecture.assumptions + package.test_plan.assumptions + package.open_questions
    )

    assert any("execution profile" in value.casefold() for value in combined_assumptions)
    assert package.architecture.data_entities == ()
    assert package.architecture.api_operations == ()


def test_fake_architecture_requires_the_software_architect() -> None:
    """Reject an approved team that cannot own architecture planning."""
    result = propose(
        proposal_request(
            selected_agent_ids=(
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.QA_TEST_ENGINEER,
            )
        )
    )

    assert result.status is ArchitectureProposalStatus.REJECTED
    assert result.issue is ArchitectureProposalIssueCode.SOFTWARE_ARCHITECT_REQUIRED
    assert result.package is None


def test_fake_architecture_requires_the_qa_test_engineer() -> None:
    """Reject an approved team that cannot own the test plan."""
    result = propose(
        proposal_request(
            selected_agent_ids=(
                AgentIdentifier.WORKFLOW_ORCHESTRATOR,
                AgentIdentifier.SOFTWARE_ARCHITECT,
            )
        )
    )

    assert result.status is ArchitectureProposalStatus.REJECTED
    assert result.issue is ArchitectureProposalIssueCode.QA_TEST_ENGINEER_REQUIRED
    assert result.package is None


def test_fake_architecture_requires_owner_design_selection() -> None:
    """Do not plan architecture before the owner-selected prototype exists."""
    result = propose(proposal_request(selected=False))

    assert result.status is ArchitectureProposalStatus.REJECTED
    assert result.issue is ArchitectureProposalIssueCode.DESIGN_SELECTION_REQUIRED
    assert result.package is None


def test_fake_architecture_rejects_insufficient_grounding(monkeypatch) -> None:
    """Keep weakly grounded inputs inside the typed provider boundary."""
    monkeypatch.setattr(fake_architecture, "_has_grounded_input", lambda request: False)

    result = propose(proposal_request())

    assert result.status is ArchitectureProposalStatus.REJECTED
    assert result.issue is ArchitectureProposalIssueCode.GROUNDED_INPUT_REQUIRED
    assert result.package is None


def test_fake_architecture_maps_invalid_domain_output_to_typed_issue(
    monkeypatch,
) -> None:
    """Map deterministic domain-construction failures to one stable issue."""

    def invalid_package(request: ArchitectureProposalRequest):
        del request
        raise ValueError("invalid deterministic package")

    monkeypatch.setattr(fake_architecture, "_build_package", invalid_package)

    result = propose(proposal_request())

    assert result.status is ArchitectureProposalStatus.REJECTED
    assert result.issue is ArchitectureProposalIssueCode.INVALID_PROVIDER_OUTPUT
    assert result.package is None


def test_fake_architecture_output_changes_with_exact_request_content() -> None:
    """Derive stable but different identities when approved context changes."""
    request = proposal_request()
    changed_design = replace(
        request.design.version,
        id=UUID(int=request.design.version.id.int + 100),
    )
    changed_request = replace(
        request,
        design=ArchitectureDesignInput(version=changed_design),
    )

    first = propose(request)
    second = propose(changed_request)

    assert first.package is not None
    assert second.package is not None
    assert first.package.architecture.id != second.package.architecture.id
