"""Versioned fixed agent catalog for OrchesTwin Studio."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from orchestwin.projects.domain import ProjectMode

AGENT_CATALOG_VERSION: Final = 1


class AgentIdentifier(StrEnum):
    """Stable identifiers for every agent available in the fixed catalog."""

    WORKFLOW_ORCHESTRATOR = "WORKFLOW_ORCHESTRATOR"
    INTAKE_CLARIFICATION_AGENT = "INTAKE_CLARIFICATION_AGENT"
    TEAM_SELECTOR = "TEAM_SELECTOR"
    HUMAN_GATE_CONTROLLER = "HUMAN_GATE_CONTROLLER"
    ARTIFACT_MANAGER = "ARTIFACT_MANAGER"
    SANDBOX_CONTROLLER = "SANDBOX_CONTROLLER"

    REQUIREMENTS_ANALYST = "REQUIREMENTS_ANALYST"
    UX_RESEARCHER_USER_MODELER = "UX_RESEARCHER_USER_MODELER"
    UX_UI_DESIGNER = "UX_UI_DESIGNER"
    SOFTWARE_ARCHITECT = "SOFTWARE_ARCHITECT"
    FRONTEND_ENGINEER = "FRONTEND_ENGINEER"
    BACKEND_ENGINEER = "BACKEND_ENGINEER"
    MOBILE_ENGINEER = "MOBILE_ENGINEER"
    QA_TEST_ENGINEER = "QA_TEST_ENGINEER"
    SECURITY_REVIEWER = "SECURITY_REVIEWER"
    ACCESSIBILITY_REVIEWER = "ACCESSIBILITY_REVIEWER"
    INTEGRATION_ENGINEER = "INTEGRATION_ENGINEER"


class AgentCatalogKind(StrEnum):
    """Top-level groups exposed by the catalog."""

    PLATFORM_COMPONENT = "PLATFORM_COMPONENT"
    SPECIALIST = "SPECIALIST"


class AgentSelectionPolicy(StrEnum):
    """How a catalog entry participates in a project team."""

    ALWAYS_PRESENT = "ALWAYS_PRESENT"
    OWNER_SELECTABLE = "OWNER_SELECTABLE"


class AgentCapability(StrEnum):
    """Stable capability labels attached to catalog entries."""

    WORKFLOW_ORCHESTRATION = "WORKFLOW_ORCHESTRATION"
    GOVERNED_ROUTING = "GOVERNED_ROUTING"
    PROJECT_INTAKE = "PROJECT_INTAKE"
    BRIEF_CLARIFICATION = "BRIEF_CLARIFICATION"
    TEAM_SELECTION = "TEAM_SELECTION"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    ARTIFACT_MANAGEMENT = "ARTIFACT_MANAGEMENT"
    PROVENANCE_MANAGEMENT = "PROVENANCE_MANAGEMENT"
    SANDBOX_CONTROL = "SANDBOX_CONTROL"

    REQUIREMENTS_ANALYSIS = "REQUIREMENTS_ANALYSIS"
    ACCEPTANCE_CRITERIA = "ACCEPTANCE_CRITERIA"
    USER_RESEARCH = "USER_RESEARCH"
    USER_MODELING = "USER_MODELING"
    UX_DESIGN = "UX_DESIGN"
    UI_DESIGN = "UI_DESIGN"
    SOFTWARE_ARCHITECTURE = "SOFTWARE_ARCHITECTURE"
    FRONTEND_ENGINEERING = "FRONTEND_ENGINEERING"
    BACKEND_ENGINEERING = "BACKEND_ENGINEERING"
    MOBILE_ENGINEERING = "MOBILE_ENGINEERING"
    QUALITY_ASSURANCE = "QUALITY_ASSURANCE"
    TEST_ENGINEERING = "TEST_ENGINEERING"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    ACCESSIBILITY_REVIEW = "ACCESSIBILITY_REVIEW"
    SYSTEM_INTEGRATION = "SYSTEM_INTEGRATION"


@dataclass(frozen=True, slots=True)
class AgentCatalogEntry:
    """One immutable role definition in a versioned catalog."""

    agent_id: AgentIdentifier
    catalog_version: int
    kind: AgentCatalogKind
    selection_policy: AgentSelectionPolicy
    capabilities: tuple[AgentCapability, ...]
    supported_project_modes: frozenset[ProjectMode]
    name_key: str
    description_key: str

    def __post_init__(self) -> None:
        """Protect catalog identity, localization, and selection invariants."""
        if self.catalog_version < 1:
            raise ValueError("agent catalog version must be positive")

        if not self.capabilities:
            raise ValueError("agent catalog entry must expose capabilities")

        if len(self.capabilities) != len(set(self.capabilities)):
            raise ValueError("agent catalog entry capabilities must be unique")

        if not self.supported_project_modes:
            raise ValueError("agent catalog entry must support at least one project mode")

        localization_prefix = f"agentCatalog.roles.{self.agent_id.value.casefold()}"

        if self.name_key != f"{localization_prefix}.name":
            raise ValueError("agent catalog name key does not match its identifier")

        if self.description_key != f"{localization_prefix}.description":
            raise ValueError("agent catalog description key does not match its identifier")

        is_platform_component = (
            self.kind is AgentCatalogKind.PLATFORM_COMPONENT
            and self.selection_policy is AgentSelectionPolicy.ALWAYS_PRESENT
        )
        is_selectable_specialist = (
            self.kind is AgentCatalogKind.SPECIALIST
            and self.selection_policy is AgentSelectionPolicy.OWNER_SELECTABLE
        )

        if not (is_platform_component or is_selectable_specialist):
            raise ValueError("agent catalog kind and selection policy are inconsistent")

    @property
    def is_always_present(self) -> bool:
        """Return whether every project team must include this role."""
        return self.selection_policy is AgentSelectionPolicy.ALWAYS_PRESENT


type AgentDefinition = tuple[
    AgentIdentifier,
    tuple[AgentCapability, ...],
]


_PLATFORM_COMPONENT_DEFINITIONS: Final[tuple[AgentDefinition, ...]] = (
    (
        AgentIdentifier.WORKFLOW_ORCHESTRATOR,
        (
            AgentCapability.WORKFLOW_ORCHESTRATION,
            AgentCapability.GOVERNED_ROUTING,
        ),
    ),
    (
        AgentIdentifier.INTAKE_CLARIFICATION_AGENT,
        (
            AgentCapability.PROJECT_INTAKE,
            AgentCapability.BRIEF_CLARIFICATION,
        ),
    ),
    (
        AgentIdentifier.TEAM_SELECTOR,
        (AgentCapability.TEAM_SELECTION,),
    ),
    (
        AgentIdentifier.HUMAN_GATE_CONTROLLER,
        (AgentCapability.HUMAN_APPROVAL,),
    ),
    (
        AgentIdentifier.ARTIFACT_MANAGER,
        (
            AgentCapability.ARTIFACT_MANAGEMENT,
            AgentCapability.PROVENANCE_MANAGEMENT,
        ),
    ),
    (
        AgentIdentifier.SANDBOX_CONTROLLER,
        (AgentCapability.SANDBOX_CONTROL,),
    ),
)


_SPECIALIST_DEFINITIONS: Final[tuple[AgentDefinition, ...]] = (
    (
        AgentIdentifier.REQUIREMENTS_ANALYST,
        (
            AgentCapability.REQUIREMENTS_ANALYSIS,
            AgentCapability.ACCEPTANCE_CRITERIA,
        ),
    ),
    (
        AgentIdentifier.UX_RESEARCHER_USER_MODELER,
        (
            AgentCapability.USER_RESEARCH,
            AgentCapability.USER_MODELING,
        ),
    ),
    (
        AgentIdentifier.UX_UI_DESIGNER,
        (
            AgentCapability.UX_DESIGN,
            AgentCapability.UI_DESIGN,
        ),
    ),
    (
        AgentIdentifier.SOFTWARE_ARCHITECT,
        (AgentCapability.SOFTWARE_ARCHITECTURE,),
    ),
    (
        AgentIdentifier.FRONTEND_ENGINEER,
        (AgentCapability.FRONTEND_ENGINEERING,),
    ),
    (
        AgentIdentifier.BACKEND_ENGINEER,
        (AgentCapability.BACKEND_ENGINEERING,),
    ),
    (
        AgentIdentifier.MOBILE_ENGINEER,
        (AgentCapability.MOBILE_ENGINEERING,),
    ),
    (
        AgentIdentifier.QA_TEST_ENGINEER,
        (
            AgentCapability.QUALITY_ASSURANCE,
            AgentCapability.TEST_ENGINEERING,
        ),
    ),
    (
        AgentIdentifier.SECURITY_REVIEWER,
        (AgentCapability.SECURITY_REVIEW,),
    ),
    (
        AgentIdentifier.ACCESSIBILITY_REVIEWER,
        (AgentCapability.ACCESSIBILITY_REVIEW,),
    ),
    (
        AgentIdentifier.INTEGRATION_ENGINEER,
        (AgentCapability.SYSTEM_INTEGRATION,),
    ),
)


_ALL_PROJECT_MODES: Final[frozenset[ProjectMode]] = frozenset(ProjectMode)


def _catalog_entry(
    definition: AgentDefinition,
    *,
    kind: AgentCatalogKind,
    selection_policy: AgentSelectionPolicy,
) -> AgentCatalogEntry:
    """Build one entry using the current fixed-catalog contract."""
    agent_id, capabilities = definition
    localization_prefix = f"agentCatalog.roles.{agent_id.value.casefold()}"

    return AgentCatalogEntry(
        agent_id=agent_id,
        catalog_version=AGENT_CATALOG_VERSION,
        kind=kind,
        selection_policy=selection_policy,
        capabilities=capabilities,
        supported_project_modes=_ALL_PROJECT_MODES,
        name_key=f"{localization_prefix}.name",
        description_key=f"{localization_prefix}.description",
    )


AGENT_CATALOG: Final[Mapping[AgentIdentifier, AgentCatalogEntry]] = MappingProxyType(
    {
        **{
            definition[0]: _catalog_entry(
                definition,
                kind=AgentCatalogKind.PLATFORM_COMPONENT,
                selection_policy=AgentSelectionPolicy.ALWAYS_PRESENT,
            )
            for definition in _PLATFORM_COMPONENT_DEFINITIONS
        },
        **{
            definition[0]: _catalog_entry(
                definition,
                kind=AgentCatalogKind.SPECIALIST,
                selection_policy=AgentSelectionPolicy.OWNER_SELECTABLE,
            )
            for definition in _SPECIALIST_DEFINITIONS
        },
    }
)


ALWAYS_PRESENT_AGENT_IDS: Final[tuple[AgentIdentifier, ...]] = tuple(
    agent_id for agent_id, _ in _PLATFORM_COMPONENT_DEFINITIONS
)


SELECTABLE_SPECIALIST_AGENT_IDS: Final[tuple[AgentIdentifier, ...]] = tuple(
    agent_id for agent_id, _ in _SPECIALIST_DEFINITIONS
)


def catalog_entry(agent_id: AgentIdentifier) -> AgentCatalogEntry:
    """Return one immutable catalog entry by stable identifier."""
    return AGENT_CATALOG[agent_id]


def all_agent_catalog_entries() -> tuple[AgentCatalogEntry, ...]:
    """Return the complete fixed catalog in stable declaration order."""
    return tuple(AGENT_CATALOG.values())


def catalog_entries_for_mode(mode: ProjectMode) -> tuple[AgentCatalogEntry, ...]:
    """Return entries compatible with one project mode."""
    return tuple(entry for entry in AGENT_CATALOG.values() if mode in entry.supported_project_modes)


def agent_catalog_snapshot() -> dict[str, object]:
    """Return a deterministic JSON-serializable catalog snapshot."""
    agents = [
        {
            "agent_id": entry.agent_id.value,
            "kind": entry.kind.value,
            "selection_policy": entry.selection_policy.value,
            "capabilities": [capability.value for capability in entry.capabilities],
            "supported_project_modes": sorted(mode.value for mode in entry.supported_project_modes),
            "name_key": entry.name_key,
            "description_key": entry.description_key,
        }
        for entry in AGENT_CATALOG.values()
    ]

    return {
        "catalog_version": AGENT_CATALOG_VERSION,
        "agents": agents,
    }


def agent_catalog_canonical_json() -> str:
    """Serialize the fixed catalog with deterministic ordering."""
    return json.dumps(
        agent_catalog_snapshot(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def agent_catalog_content_hash() -> str:
    """Return the SHA-256 fingerprint of the complete catalog."""
    return hashlib.sha256(agent_catalog_canonical_json().encode("utf-8")).hexdigest()


AGENT_CATALOG_CONTENT_HASH: Final = agent_catalog_content_hash()
