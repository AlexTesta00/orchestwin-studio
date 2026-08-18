"""Immutable versioned requirements specifications."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from orchestwin.projects.requirements import (
    Requirement,
    UserStory,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextKind,
    RequirementsContextReference,
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_quality import (
    AcceptanceCriterion,
    DefinitionOfDoneItem,
    ProjectRisk,
    UsageScenario,
)

REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION: Final = 1
MIN_REQUIREMENTS_USER_TWINS: Final = 1
MAX_REQUIREMENTS_USER_TWINS: Final = 4


class _ArtifactWithIdentity(Protocol):
    """Structural identity shared by specification artifacts."""

    id: UUID
    code: str


def _canonical_artifacts[Artifact: _ArtifactWithIdentity](
    values: Iterable[Artifact],
    *,
    label: str,
    require_items: bool,
) -> tuple[Artifact, ...]:
    """Return artifacts with unique identity/code in stable code order."""
    artifacts = tuple(values)

    if require_items and not artifacts:
        raise ValueError(f"{label} must not be empty")

    ids = tuple(artifact.id for artifact in artifacts)
    codes = tuple(artifact.code for artifact in artifacts)

    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} identities must be unique")

    if len(codes) != len(set(codes)):
        raise ValueError(f"{label} codes must be unique")

    return tuple(
        sorted(
            artifacts,
            key=lambda artifact: artifact.code,
        )
    )


def _ids(
    values: Sequence[_ArtifactWithIdentity],
) -> frozenset[UUID]:
    """Return the immutable identity set of typed artifacts."""
    return frozenset(value.id for value in values)


def _require_subset(
    references: Iterable[UUID],
    available: frozenset[UUID],
    *,
    label: str,
) -> None:
    """Reject references that do not resolve inside a specification."""
    missing = frozenset(references) - available

    if missing:
        raise ValueError(f"{label} contain unknown references")


@dataclass(frozen=True, slots=True)
class RequirementsSpecification:
    """Complete requirements baseline for one governed project context."""

    project_id: UUID
    project_brief_reference: RequirementsContextReference
    agent_team_reference: RequirementsContextReference
    user_modeling_reference: RequirementsContextReference
    catalog_version: int
    catalog_content_hash: str
    user_twin_references: tuple[
        UserTwinVersionReference,
        ...,
    ]
    requirements: tuple[Requirement, ...]
    user_stories: tuple[UserStory, ...]
    acceptance_criteria: tuple[
        AcceptanceCriterion,
        ...,
    ]
    scenarios: tuple[UsageScenario, ...]
    risks: tuple[ProjectRisk, ...]
    definition_of_done: tuple[
        DefinitionOfDoneItem,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect exact context, canonical order, and references."""
        expected_context_kinds = (
            (
                self.project_brief_reference,
                RequirementsContextKind.PROJECT_BRIEF,
                "Project Brief",
            ),
            (
                self.agent_team_reference,
                RequirementsContextKind.AGENT_TEAM,
                "Agent Team",
            ),
            (
                self.user_modeling_reference,
                RequirementsContextKind.USER_MODELING,
                "User Modeling",
            ),
        )

        for (
            reference,
            expected_kind,
            label,
        ) in expected_context_kinds:
            if reference.kind is not expected_kind:
                raise ValueError(f"requirements {label} reference uses the wrong context kind")

        validate_positive_integer(
            self.catalog_version,
            label="requirements catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="requirements catalog content hash",
        )

        if self.user_twin_references != canonical_user_twin_references(
            self.user_twin_references,
            require_items=True,
        ):
            raise ValueError("requirements User Twin references must use canonical order")

        twin_count = len(self.user_twin_references)

        if not (MIN_REQUIREMENTS_USER_TWINS <= twin_count <= MAX_REQUIREMENTS_USER_TWINS):
            raise ValueError(
                "a requirements specification requires between one and four User Twins"
            )

        collection_rules = (
            (
                self.requirements,
                "requirements",
                True,
            ),
            (
                self.user_stories,
                "user stories",
                True,
            ),
            (
                self.acceptance_criteria,
                "acceptance criteria",
                True,
            ),
            (
                self.scenarios,
                "scenarios",
                True,
            ),
            (
                self.risks,
                "risks",
                False,
            ),
            (
                self.definition_of_done,
                "Definition of Done items",
                True,
            ),
        )

        for (
            values,
            label,
            require_items,
        ) in collection_rules:
            if values != _canonical_artifacts(
                values,
                label=label,
                require_items=require_items,
            ):
                raise ValueError(f"{label} must use canonical code order")

        requirement_ids = _ids(self.requirements)
        user_story_ids = _ids(self.user_stories)
        criterion_ids = _ids(self.acceptance_criteria)
        twin_references = frozenset(self.user_twin_references)

        for requirement in self.requirements:
            unknown_twins = frozenset(requirement.user_twin_references) - twin_references

            if unknown_twins:
                raise ValueError(
                    "requirements contain User Twin references outside the specification"
                )

        for story in self.user_stories:
            if story.user_twin_reference not in twin_references:
                raise ValueError("user stories must reference a User Twin in the specification")

            _require_subset(
                story.requirement_ids,
                requirement_ids,
                label="user-story requirement IDs",
            )

        for criterion in self.acceptance_criteria:
            _require_subset(
                criterion.requirement_ids,
                requirement_ids,
                label=("acceptance-criterion requirement IDs"),
            )
            _require_subset(
                criterion.user_story_ids,
                user_story_ids,
                label=("acceptance-criterion user-story IDs"),
            )

        for scenario in self.scenarios:
            if scenario.actor not in twin_references:
                raise ValueError("scenarios must reference a User Twin in the specification")

            _require_subset(
                scenario.requirement_ids,
                requirement_ids,
                label="scenario requirement IDs",
            )
            _require_subset(
                scenario.acceptance_criterion_ids,
                criterion_ids,
                label=("scenario acceptance-criterion IDs"),
            )

        for risk in self.risks:
            _require_subset(
                risk.requirement_ids,
                requirement_ids,
                label="risk requirement IDs",
            )

        for item in self.definition_of_done:
            _require_subset(
                item.requirement_ids,
                requirement_ids,
                label=("Definition of Done requirement IDs"),
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic complete requirements snapshot."""
        return {
            "schema_version": (REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION),
            "project_id": str(self.project_id),
            "context": {
                "project_brief": (self.project_brief_reference.to_snapshot()),
                "agent_team": (self.agent_team_reference.to_snapshot()),
                "user_modeling": (self.user_modeling_reference.to_snapshot()),
                "catalog": {
                    "version": self.catalog_version,
                    "content_hash": (self.catalog_content_hash),
                },
            },
            "user_twin_references": [
                reference.to_snapshot() for reference in self.user_twin_references
            ],
            "requirements": [value.to_snapshot() for value in self.requirements],
            "user_stories": [value.to_snapshot() for value in self.user_stories],
            "acceptance_criteria": [value.to_snapshot() for value in self.acceptance_criteria],
            "scenarios": [value.to_snapshot() for value in self.scenarios],
            "risks": [value.to_snapshot() for value in self.risks],
            "definition_of_done": [value.to_snapshot() for value in self.definition_of_done],
        }

    def canonical_json(self) -> str:
        """Serialize this complete specification deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of the complete specification."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class RequirementsSpecificationVersion:
    """One immutable version of a project requirements specification."""

    id: UUID
    project_id: UUID
    version_number: int
    specification: RequirementsSpecification
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect project scope, content hash, timestamp, and lineage."""
        validate_positive_integer(
            self.version_number,
            label=("requirements specification version number"),
        )

        if self.specification.project_id != self.project_id:
            raise ValueError("requirements specification version must belong to its project")

        if self.created_at.utcoffset() is None:
            raise ValueError("requirements specification timestamp must be timezone-aware")

        validate_sha256(
            self.content_hash,
            label=("requirements specification content hash"),
        )

        if self.content_hash != self.specification.content_hash:
            raise ValueError("requirements specification hash must match its content")

        expected_base = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base:
            raise ValueError(
                "requirements specification lineage "
                "must reference the immediately preceding version"
            )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic specification-version snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": (self.based_on_version_number),
            "content_hash": self.content_hash,
            "specification": (self.specification.to_snapshot()),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }


def create_requirements_specification(
    *,
    project_id: UUID,
    project_brief_reference: RequirementsContextReference,
    agent_team_reference: RequirementsContextReference,
    user_modeling_reference: RequirementsContextReference,
    catalog_version: int,
    catalog_content_hash: str,
    user_twin_references: Iterable[UserTwinVersionReference],
    requirements: Iterable[Requirement],
    user_stories: Iterable[UserStory],
    acceptance_criteria: Iterable[AcceptanceCriterion],
    scenarios: Iterable[UsageScenario],
    risks: Iterable[ProjectRisk],
    definition_of_done: Iterable[DefinitionOfDoneItem],
) -> RequirementsSpecification:
    """Create a complete specification in deterministic artifact order."""
    return RequirementsSpecification(
        project_id=project_id,
        project_brief_reference=project_brief_reference,
        agent_team_reference=agent_team_reference,
        user_modeling_reference=user_modeling_reference,
        catalog_version=catalog_version,
        catalog_content_hash=catalog_content_hash,
        user_twin_references=(
            canonical_user_twin_references(
                user_twin_references,
                require_items=True,
            )
        ),
        requirements=_canonical_artifacts(
            requirements,
            label="requirements",
            require_items=True,
        ),
        user_stories=_canonical_artifacts(
            user_stories,
            label="user stories",
            require_items=True,
        ),
        acceptance_criteria=_canonical_artifacts(
            acceptance_criteria,
            label="acceptance criteria",
            require_items=True,
        ),
        scenarios=_canonical_artifacts(
            scenarios,
            label="scenarios",
            require_items=True,
        ),
        risks=_canonical_artifacts(
            risks,
            label="risks",
            require_items=False,
        ),
        definition_of_done=_canonical_artifacts(
            definition_of_done,
            label="Definition of Done items",
            require_items=True,
        ),
    )


__all__ = [
    "MAX_REQUIREMENTS_USER_TWINS",
    "MIN_REQUIREMENTS_USER_TWINS",
    "REQUIREMENTS_SPECIFICATION_SCHEMA_VERSION",
    "RequirementsSpecification",
    "RequirementsSpecificationVersion",
    "create_requirements_specification",
]
