"""Tests for the versioned fixed agent catalog."""

import json
from types import MappingProxyType

import pytest

from orchestwin.agents.catalog import (
    AGENT_CATALOG,
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    ALWAYS_PRESENT_AGENT_IDS,
    SELECTABLE_SPECIALIST_AGENT_IDS,
    AgentCapability,
    AgentCatalogKind,
    AgentIdentifier,
    AgentSelectionPolicy,
    agent_catalog_canonical_json,
    agent_catalog_content_hash,
    agent_catalog_snapshot,
    all_agent_catalog_entries,
    catalog_entries_for_mode,
    catalog_entry,
)
from orchestwin.projects.domain import ProjectMode


def test_catalog_contains_every_declared_agent_once() -> None:
    """Keep the enum, mapping, and declaration order aligned."""
    entries = all_agent_catalog_entries()

    assert tuple(entry.agent_id for entry in entries) == tuple(AgentIdentifier)
    assert len(entries) == 17
    assert len({entry.agent_id for entry in entries}) == len(entries)
    assert isinstance(AGENT_CATALOG, MappingProxyType)


def test_always_present_platform_components_match_contract() -> None:
    """Expose the six components required in every project team."""
    assert ALWAYS_PRESENT_AGENT_IDS == (
        AgentIdentifier.WORKFLOW_ORCHESTRATOR,
        AgentIdentifier.INTAKE_CLARIFICATION_AGENT,
        AgentIdentifier.TEAM_SELECTOR,
        AgentIdentifier.HUMAN_GATE_CONTROLLER,
        AgentIdentifier.ARTIFACT_MANAGER,
        AgentIdentifier.SANDBOX_CONTROLLER,
    )

    for agent_id in ALWAYS_PRESENT_AGENT_IDS:
        entry = catalog_entry(agent_id)

        assert entry.kind is AgentCatalogKind.PLATFORM_COMPONENT
        assert entry.selection_policy is AgentSelectionPolicy.ALWAYS_PRESENT
        assert entry.is_always_present is True


def test_selectable_specialists_match_contract() -> None:
    """Expose only the eleven owner-selectable specialist roles."""
    assert SELECTABLE_SPECIALIST_AGENT_IDS == (
        AgentIdentifier.REQUIREMENTS_ANALYST,
        AgentIdentifier.UX_RESEARCHER_USER_MODELER,
        AgentIdentifier.UX_UI_DESIGNER,
        AgentIdentifier.SOFTWARE_ARCHITECT,
        AgentIdentifier.FRONTEND_ENGINEER,
        AgentIdentifier.BACKEND_ENGINEER,
        AgentIdentifier.MOBILE_ENGINEER,
        AgentIdentifier.QA_TEST_ENGINEER,
        AgentIdentifier.SECURITY_REVIEWER,
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
        AgentIdentifier.INTEGRATION_ENGINEER,
    )

    for agent_id in SELECTABLE_SPECIALIST_AGENT_IDS:
        entry = catalog_entry(agent_id)

        assert entry.kind is AgentCatalogKind.SPECIALIST
        assert entry.selection_policy is AgentSelectionPolicy.OWNER_SELECTABLE
        assert entry.is_always_present is False


@pytest.mark.parametrize(
    "mode",
    tuple(ProjectMode),
)
def test_initial_catalog_supports_both_project_modes(mode: ProjectMode) -> None:
    """Keep role availability independent from greenfield or brownfield mode."""
    compatible = catalog_entries_for_mode(mode)

    assert compatible == all_agent_catalog_entries()
    assert all(entry.supported_project_modes == frozenset(ProjectMode) for entry in compatible)


def test_every_entry_uses_current_version_and_localization_keys() -> None:
    """Keep the fixed catalog versioned and frontend-localizable."""
    for entry in all_agent_catalog_entries():
        key_prefix = f"agentCatalog.roles.{entry.agent_id.value.casefold()}"

        assert entry.catalog_version == AGENT_CATALOG_VERSION
        assert entry.name_key == f"{key_prefix}.name"
        assert entry.description_key == f"{key_prefix}.description"
        assert entry.capabilities
        assert len(set(entry.capabilities)) == len(entry.capabilities)


def test_catalog_exposes_role_specific_capabilities() -> None:
    """Preserve meaningful typed capabilities for selection rules."""
    orchestrator = catalog_entry(AgentIdentifier.WORKFLOW_ORCHESTRATOR)
    user_modeler = catalog_entry(AgentIdentifier.UX_RESEARCHER_USER_MODELER)
    qa_engineer = catalog_entry(AgentIdentifier.QA_TEST_ENGINEER)

    assert orchestrator.capabilities == (
        AgentCapability.WORKFLOW_ORCHESTRATION,
        AgentCapability.GOVERNED_ROUTING,
    )
    assert user_modeler.capabilities == (
        AgentCapability.USER_RESEARCH,
        AgentCapability.USER_MODELING,
    )
    assert qa_engineer.capabilities == (
        AgentCapability.QUALITY_ASSURANCE,
        AgentCapability.TEST_ENGINEERING,
    )


def test_catalog_snapshot_and_hash_are_deterministic() -> None:
    """Create a stable fingerprint for future team-proposal snapshots."""
    first_snapshot = agent_catalog_snapshot()
    second_snapshot = agent_catalog_snapshot()
    canonical_json = agent_catalog_canonical_json()

    assert first_snapshot == second_snapshot
    assert json.loads(canonical_json) == first_snapshot

    assert agent_catalog_content_hash() == AGENT_CATALOG_CONTENT_HASH
    assert len(AGENT_CATALOG_CONTENT_HASH) == 64
    assert all(character in "0123456789abcdef" for character in AGENT_CATALOG_CONTENT_HASH)

    assert first_snapshot["catalog_version"] == AGENT_CATALOG_VERSION
    assert len(first_snapshot["agents"]) == 17
