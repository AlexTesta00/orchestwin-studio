"""Provider-independent contracts for governed design proposals."""

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
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
)
from orchestwin.artifacts.references import (
    ArtifactKind,
    VersionedArtifactReference,
    require_artifact_kind,
)
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    RequirementsContextReference,
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
)
from orchestwin.twins.epistemics import ProfileObservation

DESIGN_PROPOSAL_SCHEMA_VERSION: Final = 1
MAX_DESIGN_PROVIDER_ID_LENGTH: Final = 128
MIN_DESIGN_PROPOSAL_TWINS: Final = 1
MAX_DESIGN_PROPOSAL_TWINS: Final = 4

_AGENT_ORDER: Final = tuple(entry.agent_id for entry in all_agent_catalog_entries())


class DesignProposalProviderKind(StrEnum):
    """Stable categories of design proposal providers."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class DesignProposalStatus(StrEnum):
    """Stable outcome of a design proposal operation."""

    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"


class DesignProposalIssueCode(StrEnum):
    """Expected reasons a provider cannot produce a Design Package."""

    UX_DESIGNER_REQUIRED = "UX_DESIGNER_REQUIRED"
    GROUNDED_INPUT_REQUIRED = "GROUNDED_INPUT_REQUIRED"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"


@dataclass(frozen=True, slots=True)
class DesignRequirementsInput:
    """Exact approved Requirements baseline exposed to a design provider."""

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
class DesignAgentTeamInput:
    """Exact approved Agent Team exposed to a design provider."""

    reference: VersionedArtifactReference
    selected_agent_ids: tuple[AgentIdentifier, ...]

    def __post_init__(self) -> None:
        """Protect exact Team identity and fixed-catalog order."""
        require_artifact_kind(
            self.reference,
            expected=ArtifactKind.AGENT_TEAM,
            label="design Agent Team input",
        )

        expected = _canonical_agent_ids(self.selected_agent_ids)

        if self.selected_agent_ids != expected:
            raise ValueError("design Agent Team agents must use fixed-catalog order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing Team snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "selected_agent_ids": [agent_id.value for agent_id in self.selected_agent_ids],
        }


@dataclass(frozen=True, slots=True)
class DesignUserTwinInput:
    """One exact User Twin profile exposed to a design provider."""

    reference: UserTwinVersionReference
    observations: tuple[ProfileObservation, ...]

    def __post_init__(self) -> None:
        """Protect complete and deterministic User Twin observations."""
        if not self.observations:
            raise ValueError("design User Twin input requires observations")

        keys = tuple(observation.observation_key for observation in self.observations)

        if len(keys) != len(set(keys)):
            raise ValueError("design User Twin observations must be unique")

        if keys != tuple(sorted(keys)):
            raise ValueError("design User Twin observations must use canonical key order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing User Twin snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "observations": [observation.to_snapshot() for observation in self.observations],
        }


@dataclass(frozen=True, slots=True)
class DesignUserModelingInput:
    """Exact approved User Modeling state exposed to a design provider."""

    reference: VersionedArtifactReference
    user_twins: tuple[DesignUserTwinInput, ...]

    def __post_init__(self) -> None:
        """Protect context kind, cardinality, and User Twin order."""
        require_artifact_kind(
            self.reference,
            expected=ArtifactKind.USER_MODELING,
            label="design User Modeling input",
        )

        twin_count = len(self.user_twins)

        if not MIN_DESIGN_PROPOSAL_TWINS <= twin_count <= MAX_DESIGN_PROPOSAL_TWINS:
            raise ValueError("design input requires between one and four User Twins")

        references = tuple(user_twin.reference for user_twin in self.user_twins)
        expected = canonical_user_twin_references(
            references,
            require_items=True,
        )

        if references != expected:
            raise ValueError("design User Modeling twins must use canonical reference order")

    @property
    def user_twin_references(self) -> tuple[UserTwinVersionReference, ...]:
        """Return exact User Twin references in provider order."""
        return tuple(user_twin.reference for user_twin in self.user_twins)

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing User Modeling snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "user_twins": [user_twin.to_snapshot() for user_twin in self.user_twins],
        }


@dataclass(frozen=True, slots=True)
class DesignProposalRequest:
    """Typed governed context supplied to a design provider."""

    project_id: UUID
    project_mode: ProjectMode
    requirements: DesignRequirementsInput
    team: DesignAgentTeamInput
    user_modeling: DesignUserModelingInput
    catalog_version: int
    catalog_content_hash: str

    def __post_init__(self) -> None:
        """Protect project scope, catalog metadata, and exact User Twin context."""
        validate_positive_integer(
            self.catalog_version,
            label="design proposal catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="design proposal catalog content hash",
        )

        if (
            self.catalog_version != AGENT_CATALOG_VERSION
            or self.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
        ):
            raise ValueError("design proposal request must use the current agent catalog")

        requirements_version = self.requirements.version
        specification = requirements_version.specification

        if requirements_version.project_id != self.project_id:
            raise ValueError("design proposal Requirements must belong to its project")

        if not _matches_context_reference(
            self.team.reference,
            specification.agent_team_reference,
        ):
            raise ValueError("design proposal team must match the Requirements context")

        if not _matches_context_reference(
            self.user_modeling.reference,
            specification.user_modeling_reference,
        ):
            raise ValueError("design proposal User Modeling must match the Requirements context")

        if (
            specification.catalog_version != self.catalog_version
            or specification.catalog_content_hash != self.catalog_content_hash
        ):
            raise ValueError(
                "design proposal catalog metadata must match the Requirements specification"
            )

        if self.user_modeling.user_twin_references != specification.user_twin_references:
            raise ValueError("design proposal User Twins must match the Requirements specification")

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete deterministic provider request."""
        return {
            "schema_version": DESIGN_PROPOSAL_SCHEMA_VERSION,
            "project_id": str(self.project_id),
            "project_mode": self.project_mode.value,
            "catalog": {
                "version": self.catalog_version,
                "content_hash": self.catalog_content_hash,
            },
            "requirements": self.requirements.to_snapshot(),
            "team": self.team.to_snapshot(),
            "user_modeling": self.user_modeling.to_snapshot(),
        }

    def canonical_json(self) -> str:
        """Serialize this provider request deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the provider request."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class DesignProposalResult:
    """Typed result returned by a design provider."""

    status: DesignProposalStatus
    provider_kind: DesignProposalProviderKind
    provider_id: str
    provider_version: int
    package: DesignExplorationPackage | None = None
    issue: DesignProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect provider metadata and success/rejection shapes."""
        normalized_provider_id = self.provider_id.strip()

        if not normalized_provider_id or normalized_provider_id != self.provider_id:
            raise ValueError("design provider ID must be normalized")

        if len(self.provider_id) > MAX_DESIGN_PROVIDER_ID_LENGTH:
            raise ValueError("design provider ID exceeds maximum length")

        validate_positive_integer(
            self.provider_version,
            label="design provider version",
        )

        if self.status is DesignProposalStatus.PROPOSED:
            if self.package is None or self.issue is not None:
                raise ValueError("a proposed design result requires a package and no issue")
            return

        if self.package is not None or self.issue is None:
            raise ValueError("a rejected design result requires one issue and no package")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-result snapshot."""
        return {
            "schema_version": DESIGN_PROPOSAL_SCHEMA_VERSION,
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
class DesignProposalPort(Protocol):
    """Provider-independent design proposal boundary."""

    async def propose(
        self,
        request: DesignProposalRequest,
    ) -> DesignProposalResult:
        """Produce a typed Design Package proposal or rejection."""


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
        raise ValueError("design Agent Team input must contain selected agents")

    if len(values) != len(set(values)):
        raise ValueError("design Agent Team agents must be unique")

    return tuple(sorted(values, key=_agent_position))


__all__ = [
    "DESIGN_PROPOSAL_SCHEMA_VERSION",
    "MAX_DESIGN_PROVIDER_ID_LENGTH",
    "DesignAgentTeamInput",
    "DesignProposalIssueCode",
    "DesignProposalPort",
    "DesignProposalProviderKind",
    "DesignProposalRequest",
    "DesignProposalResult",
    "DesignProposalStatus",
    "DesignRequirementsInput",
    "DesignUserModelingInput",
    "DesignUserTwinInput",
]
