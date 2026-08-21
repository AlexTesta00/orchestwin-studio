"""Provider-independent contracts for governed architecture proposals."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.artifacts.architecture_packages import ArchitecturePlanningPackage
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import (
    ArtifactKind,
    VersionedArtifactReference,
    require_artifact_kind,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    RequirementsContextReference,
    canonical_json,
    canonical_uuid_tuple,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion

ARCHITECTURE_PROPOSAL_SCHEMA_VERSION: Final = 1
MAX_ARCHITECTURE_PROVIDER_ID_LENGTH: Final = 128

_AGENT_ORDER: Final = tuple(entry.agent_id for entry in all_agent_catalog_entries())


class ArchitectureProposalProviderKind(StrEnum):
    """Stable categories of architecture proposal providers."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class ArchitectureProposalStatus(StrEnum):
    """Stable outcome of an architecture proposal operation."""

    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"


class ArchitectureProposalIssueCode(StrEnum):
    """Expected reasons a provider cannot produce an Architecture Package."""

    SOFTWARE_ARCHITECT_REQUIRED = "SOFTWARE_ARCHITECT_REQUIRED"
    QA_TEST_ENGINEER_REQUIRED = "QA_TEST_ENGINEER_REQUIRED"
    DESIGN_SELECTION_REQUIRED = "DESIGN_SELECTION_REQUIRED"
    GROUNDED_INPUT_REQUIRED = "GROUNDED_INPUT_REQUIRED"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"


@dataclass(frozen=True, slots=True)
class ArchitectureRequirementsInput:
    """Exact approved Requirements baseline exposed to an architecture provider."""

    version: RequirementsSpecificationVersion

    @property
    def reference(self) -> VersionedArtifactReference:
        """Return the exact Requirements version reference."""
        return VersionedArtifactReference(
            kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
            artifact_id=self.version.id,
            version_number=self.version.version_number,
            content_hash=self.version.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete provider-facing Requirements snapshot."""
        return self.version.to_snapshot()


@dataclass(frozen=True, slots=True)
class ArchitectureDesignInput:
    """Exact immutable Design Package exposed to an architecture provider."""

    version: DesignPackageVersion

    @property
    def reference(self) -> VersionedArtifactReference:
        """Return the exact Design Package version reference."""
        return VersionedArtifactReference(
            kind=ArtifactKind.DESIGN_PACKAGE,
            artifact_id=self.version.id,
            version_number=self.version.version_number,
            content_hash=self.version.content_hash,
        )

    @property
    def ready_for_architecture(self) -> bool:
        """Return whether an owner selection and prototype are available."""
        return self.version.package.ready_for_gate

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete provider-facing Design Package snapshot."""
        return self.version.to_snapshot()


@dataclass(frozen=True, slots=True)
class ArchitectureAgentTeamInput:
    """Exact approved Agent Team exposed to an architecture provider."""

    reference: VersionedArtifactReference
    selected_agent_ids: tuple[AgentIdentifier, ...]

    def __post_init__(self) -> None:
        """Protect exact Team identity and fixed-catalog order."""
        require_artifact_kind(
            self.reference,
            expected=ArtifactKind.AGENT_TEAM,
            label="architecture Agent Team input",
        )

        expected = _canonical_agent_ids(self.selected_agent_ids)

        if self.selected_agent_ids != expected:
            raise ValueError("architecture Agent Team agents must use fixed-catalog order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing Team snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "selected_agent_ids": [agent_id.value for agent_id in self.selected_agent_ids],
        }


@dataclass(frozen=True, slots=True)
class ArchitectureProposalRequest:
    """Typed governed context supplied to an architecture provider."""

    project_id: UUID
    project_mode: ProjectMode
    requirements: ArchitectureRequirementsInput
    design: ArchitectureDesignInput
    team: ArchitectureAgentTeamInput
    catalog_version: int
    catalog_content_hash: str

    def __post_init__(self) -> None:
        """Protect project scope, exact stage links, and catalog metadata."""
        validate_positive_integer(
            self.catalog_version,
            label="architecture proposal catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="architecture proposal catalog content hash",
        )

        if (
            self.catalog_version != AGENT_CATALOG_VERSION
            or self.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
        ):
            raise ValueError("architecture proposal request must use the current agent catalog")

        requirements_version = self.requirements.version
        design_version = self.design.version
        specification = requirements_version.specification
        grounding = design_version.package.grounding

        if requirements_version.project_id != self.project_id:
            raise ValueError("architecture proposal Requirements must belong to its project")

        if design_version.project_id != self.project_id:
            raise ValueError("architecture proposal Design Package must belong to its project")

        if self.requirements.reference != grounding.requirements_reference:
            raise ValueError(
                "architecture proposal Requirements must match the Design Package grounding"
            )

        if self.team.reference != grounding.agent_team_reference:
            raise ValueError("architecture proposal team must match the Design Package grounding")

        if not _matches_context_reference(
            grounding.agent_team_reference,
            specification.agent_team_reference,
        ):
            raise ValueError(
                "architecture proposal Design Package team must match the Requirements context"
            )

        if not _matches_context_reference(
            grounding.user_modeling_reference,
            specification.user_modeling_reference,
        ):
            raise ValueError(
                "architecture proposal Design Package User Modeling must match Requirements"
            )

        if (
            grounding.catalog_version != self.catalog_version
            or grounding.catalog_content_hash != self.catalog_content_hash
            or specification.catalog_version != self.catalog_version
            or specification.catalog_content_hash != self.catalog_content_hash
        ):
            raise ValueError(
                "architecture proposal catalog metadata must match Requirements and Design"
            )

        expected_requirement_ids = canonical_uuid_tuple(
            (requirement.id for requirement in specification.requirements),
            label="architecture proposal requirement IDs",
            require_items=True,
        )
        expected_story_ids = canonical_uuid_tuple(
            (story.id for story in specification.user_stories),
            label="architecture proposal user-story IDs",
            require_items=True,
        )
        expected_criterion_ids = canonical_uuid_tuple(
            (criterion.id for criterion in specification.acceptance_criteria),
            label="architecture proposal acceptance-criterion IDs",
            require_items=True,
        )

        if grounding.requirement_ids != expected_requirement_ids:
            raise ValueError(
                "architecture proposal Design Package requirements must match Requirements"
            )

        if grounding.user_story_ids != expected_story_ids:
            raise ValueError("architecture proposal Design Package stories must match Requirements")

        if grounding.acceptance_criterion_ids != expected_criterion_ids:
            raise ValueError(
                "architecture proposal Design Package criteria must match Requirements"
            )

        if grounding.user_twin_references != specification.user_twin_references:
            raise ValueError(
                "architecture proposal Design Package User Twins must match Requirements"
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete deterministic provider request."""
        return {
            "schema_version": ARCHITECTURE_PROPOSAL_SCHEMA_VERSION,
            "project_id": str(self.project_id),
            "project_mode": self.project_mode.value,
            "catalog": {
                "version": self.catalog_version,
                "content_hash": self.catalog_content_hash,
            },
            "requirements": self.requirements.to_snapshot(),
            "design": self.design.to_snapshot(),
            "team": self.team.to_snapshot(),
        }

    def canonical_json(self) -> str:
        """Serialize this provider request deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the provider request."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class ArchitectureProposalResult:
    """Typed result returned by an architecture provider."""

    status: ArchitectureProposalStatus
    provider_kind: ArchitectureProposalProviderKind
    provider_id: str
    provider_version: int
    package: ArchitecturePlanningPackage | None = None
    issue: ArchitectureProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect provider metadata and success/rejection shapes."""
        normalized_provider_id = self.provider_id.strip()

        if not normalized_provider_id or normalized_provider_id != self.provider_id:
            raise ValueError("architecture provider ID must be normalized")

        if len(self.provider_id) > MAX_ARCHITECTURE_PROVIDER_ID_LENGTH:
            raise ValueError("architecture provider ID exceeds maximum length")

        validate_positive_integer(
            self.provider_version,
            label="architecture provider version",
        )

        if self.status is ArchitectureProposalStatus.PROPOSED:
            if self.package is None or self.issue is not None:
                raise ValueError("a proposed architecture result requires a package and no issue")
            return

        if self.package is not None or self.issue is None:
            raise ValueError("a rejected architecture result requires one issue and no package")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-result snapshot."""
        return {
            "schema_version": ARCHITECTURE_PROPOSAL_SCHEMA_VERSION,
            "status": self.status.value,
            "provider": {
                "kind": self.provider_kind.value,
                "id": self.provider_id,
                "version": self.provider_version,
            },
            "package": None if self.package is None else self.package.to_snapshot(),
            "issue": None if self.issue is None else self.issue.value,
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the provider response."""
        return snapshot_content_hash(self.to_snapshot())


@runtime_checkable
class ArchitectureProposalPort(Protocol):
    """Provider-independent architecture proposal boundary."""

    async def propose(
        self,
        request: ArchitectureProposalRequest,
    ) -> ArchitectureProposalResult:
        """Produce a typed Architecture Package proposal or rejection."""


def _matches_context_reference(
    reference: VersionedArtifactReference,
    expected: RequirementsContextReference,
) -> bool:
    """Compare exact identity metadata across stage-specific reference types."""
    return (
        reference.artifact_id == expected.artifact_id
        and reference.version_number == expected.version_number
        and reference.content_hash == expected.content_hash
    )


def _agent_position(agent_id: AgentIdentifier) -> int:
    """Return one agent's stable fixed-catalog position."""
    return _AGENT_ORDER.index(agent_id)


def _canonical_agent_ids(
    values: tuple[AgentIdentifier, ...],
) -> tuple[AgentIdentifier, ...]:
    """Return duplicate-free agents in fixed-catalog order."""
    if not values:
        raise ValueError("architecture Agent Team input must contain selected agents")

    if len(values) != len(set(values)):
        raise ValueError("architecture Agent Team agents must be unique")

    return tuple(sorted(values, key=_agent_position))


__all__ = [
    "ARCHITECTURE_PROPOSAL_SCHEMA_VERSION",
    "MAX_ARCHITECTURE_PROVIDER_ID_LENGTH",
    "ArchitectureAgentTeamInput",
    "ArchitectureDesignInput",
    "ArchitectureProposalIssueCode",
    "ArchitectureProposalPort",
    "ArchitectureProposalProviderKind",
    "ArchitectureProposalRequest",
    "ArchitectureProposalResult",
    "ArchitectureProposalStatus",
    "ArchitectureRequirementsInput",
]
