"""Provider-independent contracts for requirements proposals."""

from __future__ import annotations

from collections.abc import Iterable
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
from orchestwin.projects.briefs import BriefField
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
)
from orchestwin.twins.epistemics import (
    ProfileObservation,
)

REQUIREMENTS_PROPOSAL_SCHEMA_VERSION: Final = 1
MAX_REQUIREMENTS_PROVIDER_ID_LENGTH: Final = 128
MIN_REQUIREMENTS_PROPOSAL_TWINS: Final = 1
MAX_REQUIREMENTS_PROPOSAL_TWINS: Final = 4

_MAX_BRIEF_NAME_LENGTH: Final = 200
_MAX_BRIEF_TEXT_LENGTH: Final = 4000
_MAX_BRIEF_ITEM_LENGTH: Final = 2000

_AGENT_ORDER: Final = tuple(entry.agent_id for entry in all_agent_catalog_entries())


class RequirementsProposalProviderKind(StrEnum):
    """Stable categories of requirements proposal providers."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class RequirementsProposalStatus(StrEnum):
    """Stable outcome of a requirements proposal operation."""

    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"


class RequirementsProposalIssueCode(StrEnum):
    """Expected reasons a proposal cannot be produced."""

    REQUIREMENTS_ANALYST_REQUIRED = "REQUIREMENTS_ANALYST_REQUIRED"
    GROUNDED_INPUT_REQUIRED = "GROUNDED_INPUT_REQUIRED"
    INVALID_PROVIDER_OUTPUT = "INVALID_PROVIDER_OUTPUT"


def _agent_position(
    agent_id: AgentIdentifier,
) -> int:
    """Return one agent's stable fixed-catalog position."""
    return _AGENT_ORDER.index(agent_id)


def _canonical_agent_ids(
    values: Iterable[AgentIdentifier],
) -> tuple[AgentIdentifier, ...]:
    """Return duplicate-free agent IDs in fixed-catalog order."""
    agent_ids = tuple(values)

    if not agent_ids:
        raise ValueError("requirements team input must contain selected agents")

    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("requirements team agents must be unique")

    return tuple(
        sorted(
            agent_ids,
            key=_agent_position,
        )
    )


@dataclass(frozen=True, slots=True)
class RequirementsBriefInput:
    """Governed Project Brief content exposed to providers."""

    reference: RequirementsContextReference
    name: str
    description: str | None = None
    problem: str | None = None
    goals: tuple[str, ...] = ()
    target_users: tuple[str, ...] = ()
    domain: str | None = None
    technical_constraints: tuple[str, ...] = ()
    temporal_constraints: str | None = None
    budget: str | None = None
    functional_requirements: tuple[str, ...] = ()
    non_functional_requirements: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    stakeholders: tuple[str, ...] = ()
    available_artifacts: tuple[str, ...] = ()
    definition_of_done: tuple[str, ...] = ()
    unknown_fields: frozenset[BriefField] = frozenset()

    def __post_init__(self) -> None:
        """Protect exact context and normalized Brief content."""
        if self.reference.kind is not RequirementsContextKind.PROJECT_BRIEF:
            raise ValueError("requirements brief input requires a Project Brief reference")

        if (
            normalize_required_text(
                self.name,
                label="requirements brief name",
                maximum_length=_MAX_BRIEF_NAME_LENGTH,
            )
            != self.name
        ):
            raise ValueError("requirements brief name must be normalized")

        for value, label in (
            (
                self.description,
                "requirements brief description",
            ),
            (
                self.problem,
                "requirements brief problem",
            ),
            (
                self.domain,
                "requirements brief domain",
            ),
            (
                self.temporal_constraints,
                "requirements brief temporal constraints",
            ),
            (
                self.budget,
                "requirements brief budget",
            ),
        ):
            if (
                normalize_optional_text(
                    value,
                    label=label,
                    maximum_length=_MAX_BRIEF_TEXT_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")

        item_fields = (
            (
                self.goals,
                "requirements brief goals",
            ),
            (
                self.target_users,
                "requirements brief target users",
            ),
            (
                self.technical_constraints,
                "requirements brief technical constraints",
            ),
            (
                self.functional_requirements,
                "requirements brief functional requirements",
            ),
            (
                self.non_functional_requirements,
                "requirements brief non-functional requirements",
            ),
            (
                self.risks,
                "requirements brief risks",
            ),
            (
                self.stakeholders,
                "requirements brief stakeholders",
            ),
            (
                self.available_artifacts,
                "requirements brief available artifacts",
            ),
            (
                self.definition_of_done,
                "requirements brief Definition of Done",
            ),
        )

        for values, label in item_fields:
            if values != normalize_text_items(
                values,
                label=label,
                maximum_item_length=_MAX_BRIEF_ITEM_LENGTH,
                require_items=False,
            ):
                raise ValueError(f"{label} must be normalized and unique")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing Brief snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "name": self.name,
            "description": self.description,
            "problem": self.problem,
            "goals": list(self.goals),
            "target_users": list(self.target_users),
            "domain": self.domain,
            "technical_constraints": list(self.technical_constraints),
            "temporal_constraints": (self.temporal_constraints),
            "budget": self.budget,
            "functional_requirements": list(self.functional_requirements),
            "non_functional_requirements": list(self.non_functional_requirements),
            "risks": list(self.risks),
            "stakeholders": list(self.stakeholders),
            "available_artifacts": list(self.available_artifacts),
            "definition_of_done": list(self.definition_of_done),
            "unknown_fields": sorted(field.value for field in self.unknown_fields),
        }


@dataclass(frozen=True, slots=True)
class RequirementsTeamInput:
    """Exact approved Agent Team exposed to providers."""

    reference: RequirementsContextReference
    selected_agent_ids: tuple[AgentIdentifier, ...]

    def __post_init__(self) -> None:
        """Protect exact context and fixed-catalog ordering."""
        if self.reference.kind is not RequirementsContextKind.AGENT_TEAM:
            raise ValueError("requirements team input requires an Agent Team reference")

        if self.selected_agent_ids != _canonical_agent_ids(self.selected_agent_ids):
            raise ValueError("requirements team agents must use fixed-catalog order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-facing Team snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "selected_agent_ids": [agent_id.value for agent_id in self.selected_agent_ids],
        }


@dataclass(frozen=True, slots=True)
class RequirementsUserTwinInput:
    """One exact User Twin profile exposed to providers."""

    reference: UserTwinVersionReference
    observations: tuple[
        ProfileObservation,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect complete and deterministic observations."""
        if not self.observations:
            raise ValueError("requirements User Twin input requires observations")

        keys = tuple(observation.observation_key for observation in self.observations)

        if len(keys) != len(set(keys)):
            raise ValueError("requirements User Twin observations must be unique")

        if keys != tuple(sorted(keys)):
            raise ValueError("requirements User Twin observations must use canonical key order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a provider-facing User Twin snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "observations": [observation.to_snapshot() for observation in self.observations],
        }


@dataclass(frozen=True, slots=True)
class RequirementsUserModelingInput:
    """Exact approved User Modeling state exposed to providers."""

    reference: RequirementsContextReference
    user_twins: tuple[
        RequirementsUserTwinInput,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect context kind, cardinality, and twin order."""
        if self.reference.kind is not RequirementsContextKind.USER_MODELING:
            raise ValueError("requirements User Modeling input requires a User Modeling reference")

        twin_count = len(self.user_twins)

        if not (MIN_REQUIREMENTS_PROPOSAL_TWINS <= twin_count <= MAX_REQUIREMENTS_PROPOSAL_TWINS):
            raise ValueError(
                "requirements User Modeling input requires between one and four User Twins"
            )

        references = tuple(value.reference for value in self.user_twins)
        canonical_references = canonical_user_twin_references(
            references,
            require_items=True,
        )

        if references != canonical_references:
            raise ValueError("requirements User Modeling twins must use canonical reference order")

    @property
    def user_twin_references(
        self,
    ) -> tuple[UserTwinVersionReference, ...]:
        """Return exact User Twin references."""
        return tuple(value.reference for value in self.user_twins)

    def to_snapshot(self) -> dict[str, object]:
        """Return a provider-facing User Modeling snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "user_twins": [value.to_snapshot() for value in self.user_twins],
        }


@dataclass(frozen=True, slots=True)
class RequirementsProposalRequest:
    """Typed governed context supplied to a provider."""

    project_id: UUID
    project_mode: ProjectMode
    brief: RequirementsBriefInput
    team: RequirementsTeamInput
    user_modeling: RequirementsUserModelingInput
    catalog_version: int
    catalog_content_hash: str

    def __post_init__(self) -> None:
        """Protect current fixed-catalog metadata."""
        validate_positive_integer(
            self.catalog_version,
            label="requirements proposal catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label=("requirements proposal catalog content hash"),
        )

        if (
            self.catalog_version != AGENT_CATALOG_VERSION
            or self.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
        ):
            raise ValueError("requirements proposal request must use the current agent catalog")

    def to_snapshot(self) -> dict[str, object]:
        """Return the complete deterministic provider request."""
        return {
            "schema_version": (REQUIREMENTS_PROPOSAL_SCHEMA_VERSION),
            "project_id": str(self.project_id),
            "project_mode": self.project_mode.value,
            "catalog": {
                "version": self.catalog_version,
                "content_hash": (self.catalog_content_hash),
            },
            "brief": self.brief.to_snapshot(),
            "team": self.team.to_snapshot(),
            "user_modeling": (self.user_modeling.to_snapshot()),
        }

    def canonical_json(self) -> str:
        """Serialize this provider request deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the provider request."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class RequirementsProposalResult:
    """Typed result returned by requirements providers."""

    status: RequirementsProposalStatus
    provider_kind: RequirementsProposalProviderKind
    provider_id: str
    provider_version: int
    specification: RequirementsSpecification | None = None
    issue: RequirementsProposalIssueCode | None = None

    def __post_init__(self) -> None:
        """Protect provider metadata and result shapes."""
        normalized_provider_id = self.provider_id.strip()

        if not normalized_provider_id or normalized_provider_id != self.provider_id:
            raise ValueError("requirements provider ID must be normalized")

        if len(self.provider_id) > MAX_REQUIREMENTS_PROVIDER_ID_LENGTH:
            raise ValueError("requirements provider ID exceeds maximum length")

        validate_positive_integer(
            self.provider_version,
            label="requirements provider version",
        )

        proposed = self.status is RequirementsProposalStatus.PROPOSED

        if proposed:
            if self.specification is None or self.issue is not None:
                raise ValueError(
                    "a proposed requirements result requires a specification and no issue"
                )

            return

        if self.specification is not None or self.issue is None:
            raise ValueError(
                "a rejected requirements result requires one issue and no specification"
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic provider-result snapshot."""
        return {
            "schema_version": (REQUIREMENTS_PROPOSAL_SCHEMA_VERSION),
            "status": self.status.value,
            "provider": {
                "kind": self.provider_kind.value,
                "id": self.provider_id,
                "version": self.provider_version,
            },
            "specification": (
                None if self.specification is None else self.specification.to_snapshot()
            ),
            "issue": (None if self.issue is None else self.issue.value),
        }

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the provider response."""
        return snapshot_content_hash(self.to_snapshot())


@runtime_checkable
class RequirementsProposalPort(Protocol):
    """Provider-independent requirements proposal boundary."""

    async def propose(
        self,
        request: RequirementsProposalRequest,
    ) -> RequirementsProposalResult:
        """Produce a typed proposal or rejected result."""


__all__ = [
    "MAX_REQUIREMENTS_PROVIDER_ID_LENGTH",
    "REQUIREMENTS_PROPOSAL_SCHEMA_VERSION",
    "RequirementsBriefInput",
    "RequirementsProposalIssueCode",
    "RequirementsProposalPort",
    "RequirementsProposalProviderKind",
    "RequirementsProposalRequest",
    "RequirementsProposalResult",
    "RequirementsProposalStatus",
    "RequirementsTeamInput",
    "RequirementsUserModelingInput",
    "RequirementsUserTwinInput",
]
