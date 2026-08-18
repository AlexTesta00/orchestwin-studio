"""Typed traceability and coverage for requirements specifications."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)


class TraceabilityNodeKind(StrEnum):
    """Kinds of nodes in the requirements traceability graph."""

    USER_TWIN = "USER_TWIN"
    USER_STORY = "USER_STORY"
    REQUIREMENT = "REQUIREMENT"
    ACCEPTANCE_CRITERION = "ACCEPTANCE_CRITERION"
    SCENARIO = "SCENARIO"
    RISK = "RISK"
    DEFINITION_OF_DONE = "DEFINITION_OF_DONE"


class TraceabilityLinkKind(StrEnum):
    """Semantic relationships between requirements artifacts."""

    ACTS_AS = "ACTS_AS"
    MOTIVATES = "MOTIVATES"
    VERIFIED_BY = "VERIFIED_BY"
    EXERCISES = "EXERCISES"
    AFFECTS = "AFFECTS"
    GOVERNS = "GOVERNS"


@dataclass(
    frozen=True,
    slots=True,
    order=True,
)
class TraceabilityNodeReference:
    """Stable reference to one traceability node."""

    kind: TraceabilityNodeKind
    artifact_id: UUID

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic traceability-reference snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_id": str(self.artifact_id),
        }


@dataclass(frozen=True, slots=True)
class TraceabilityNode:
    """One queryable artifact represented in the graph."""

    reference: TraceabilityNodeReference
    display_code: str

    def __post_init__(self) -> None:
        """Protect human-readable node metadata."""
        if not self.display_code or self.display_code != self.display_code.strip():
            raise ValueError("traceability display code must be normalized")

    @property
    def sort_key(
        self,
    ) -> tuple[str, str, str]:
        """Return deterministic node ordering metadata."""
        return (
            self.reference.kind.value,
            self.display_code,
            self.reference.artifact_id.hex,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic traceability-node snapshot."""
        return {
            "reference": self.reference.to_snapshot(),
            "display_code": self.display_code,
        }


@dataclass(frozen=True, slots=True)
class TraceabilityLink:
    """One typed relationship between requirements artifacts."""

    kind: TraceabilityLinkKind
    source: TraceabilityNodeReference
    target: TraceabilityNodeReference

    @property
    def sort_key(
        self,
    ) -> tuple[str, str, str, str, str]:
        """Return deterministic link ordering metadata."""
        return (
            self.kind.value,
            self.source.kind.value,
            self.source.artifact_id.hex,
            self.target.kind.value,
            self.target.artifact_id.hex,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic traceability-link snapshot."""
        return {
            "kind": self.kind.value,
            "source": self.source.to_snapshot(),
            "target": self.target.to_snapshot(),
        }


_ALLOWED_LINK_SHAPES: Final = frozenset(
    {
        (
            TraceabilityLinkKind.ACTS_AS,
            TraceabilityNodeKind.USER_TWIN,
            TraceabilityNodeKind.USER_STORY,
        ),
        (
            TraceabilityLinkKind.MOTIVATES,
            TraceabilityNodeKind.USER_STORY,
            TraceabilityNodeKind.REQUIREMENT,
        ),
        (
            TraceabilityLinkKind.VERIFIED_BY,
            TraceabilityNodeKind.REQUIREMENT,
            TraceabilityNodeKind.ACCEPTANCE_CRITERION,
        ),
        (
            TraceabilityLinkKind.VERIFIED_BY,
            TraceabilityNodeKind.USER_STORY,
            TraceabilityNodeKind.ACCEPTANCE_CRITERION,
        ),
        (
            TraceabilityLinkKind.EXERCISES,
            TraceabilityNodeKind.SCENARIO,
            TraceabilityNodeKind.REQUIREMENT,
        ),
        (
            TraceabilityLinkKind.EXERCISES,
            TraceabilityNodeKind.SCENARIO,
            TraceabilityNodeKind.ACCEPTANCE_CRITERION,
        ),
        (
            TraceabilityLinkKind.AFFECTS,
            TraceabilityNodeKind.RISK,
            TraceabilityNodeKind.REQUIREMENT,
        ),
        (
            TraceabilityLinkKind.GOVERNS,
            TraceabilityNodeKind.DEFINITION_OF_DONE,
            TraceabilityNodeKind.REQUIREMENT,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class RequirementsTraceability:
    """Deterministic graph for one specification version."""

    project_id: UUID
    specification_version_id: UUID
    specification_version_number: int
    specification_content_hash: str
    nodes: tuple[TraceabilityNode, ...]
    links: tuple[TraceabilityLink, ...]

    def __post_init__(self) -> None:
        """Protect graph identity, order, and link integrity."""
        validate_positive_integer(
            self.specification_version_number,
            label=("traceability specification version number"),
        )
        validate_sha256(
            self.specification_content_hash,
            label=("traceability specification content hash"),
        )

        if not self.nodes:
            raise ValueError("requirements traceability requires nodes")

        references = tuple(node.reference for node in self.nodes)

        if len(references) != len(set(references)):
            raise ValueError("traceability node references must be unique")

        display_codes = tuple(node.display_code for node in self.nodes)

        if len(display_codes) != len(set(display_codes)):
            raise ValueError("traceability display codes must be unique")

        expected_nodes = tuple(
            sorted(
                self.nodes,
                key=lambda node: node.sort_key,
            )
        )

        if self.nodes != expected_nodes:
            raise ValueError("traceability nodes must use canonical order")

        if len(self.links) != len(set(self.links)):
            raise ValueError("traceability links must be unique")

        expected_links = tuple(
            sorted(
                self.links,
                key=lambda link: link.sort_key,
            )
        )

        if self.links != expected_links:
            raise ValueError("traceability links must use canonical order")

        reference_set = frozenset(references)

        for link in self.links:
            if link.source not in reference_set or link.target not in reference_set:
                raise ValueError("traceability links must reference graph nodes")

            shape = (
                link.kind,
                link.source.kind,
                link.target.kind,
            )

            if shape not in _ALLOWED_LINK_SHAPES:
                raise ValueError("traceability link kind is incompatible with its nodes")

    def outgoing(
        self,
        reference: TraceabilityNodeReference,
    ) -> tuple[TraceabilityLink, ...]:
        """Return outgoing links in canonical order."""
        return tuple(link for link in self.links if link.source == reference)

    def incoming(
        self,
        reference: TraceabilityNodeReference,
    ) -> tuple[TraceabilityLink, ...]:
        """Return incoming links in canonical order."""
        return tuple(link for link in self.links if link.target == reference)

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic traceability graph snapshot."""
        return {
            "project_id": str(self.project_id),
            "specification_version_id": str(self.specification_version_id),
            "specification_version_number": (self.specification_version_number),
            "specification_content_hash": (self.specification_content_hash),
            "nodes": [node.to_snapshot() for node in self.nodes],
            "links": [link.to_snapshot() for link in self.links],
        }

    def canonical_json(self) -> str:
        """Serialize this traceability graph deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this traceability graph."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class RequirementsCoverageSummary:
    """Report uncovered requirements relationships."""

    project_id: UUID
    specification_version_id: UUID
    requirement_count: int
    user_story_count: int
    acceptance_criterion_count: int
    requirement_ids_without_user_stories: tuple[
        UUID,
        ...,
    ]
    requirement_ids_without_acceptance_criteria: tuple[
        UUID,
        ...,
    ]
    user_story_ids_without_acceptance_criteria: tuple[
        UUID,
        ...,
    ]
    acceptance_criterion_ids_without_scenarios: tuple[
        UUID,
        ...,
    ]

    @property
    def has_full_acceptance_coverage(self) -> bool:
        """Return whether requirements and stories have criteria."""
        return (
            not self.requirement_ids_without_acceptance_criteria
            and not self.user_story_ids_without_acceptance_criteria
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic coverage-summary snapshot."""
        return {
            "project_id": str(self.project_id),
            "specification_version_id": str(self.specification_version_id),
            "counts": {
                "requirements": self.requirement_count,
                "user_stories": self.user_story_count,
                "acceptance_criteria": (self.acceptance_criterion_count),
            },
            "requirement_ids_without_user_stories": [
                str(value) for value in self.requirement_ids_without_user_stories
            ],
            "requirement_ids_without_acceptance_criteria": [
                str(value) for value in self.requirement_ids_without_acceptance_criteria
            ],
            "user_story_ids_without_acceptance_criteria": [
                str(value) for value in self.user_story_ids_without_acceptance_criteria
            ],
            "acceptance_criterion_ids_without_scenarios": [
                str(value) for value in self.acceptance_criterion_ids_without_scenarios
            ],
            "has_full_acceptance_coverage": (self.has_full_acceptance_coverage),
        }


def _reference(
    kind: TraceabilityNodeKind,
    artifact_id: UUID,
) -> TraceabilityNodeReference:
    """Create one concise traceability node reference."""
    return TraceabilityNodeReference(
        kind=kind,
        artifact_id=artifact_id,
    )


def _twin_display_code(
    twin_id: UUID,
) -> str:
    """Return a stable readable User Twin traceability code."""
    return f"UT-{twin_id.hex.upper()}"


def build_requirements_traceability(
    version: RequirementsSpecificationVersion,
) -> RequirementsTraceability:
    """Build the typed graph for one specification version."""
    specification = version.specification
    nodes: list[TraceabilityNode] = []
    links: list[TraceabilityLink] = []

    for twin in specification.user_twin_references:
        nodes.append(
            TraceabilityNode(
                reference=_reference(
                    TraceabilityNodeKind.USER_TWIN,
                    twin.twin_id,
                ),
                display_code=_twin_display_code(twin.twin_id),
            )
        )

    for story in specification.user_stories:
        story_reference = _reference(
            TraceabilityNodeKind.USER_STORY,
            story.id,
        )
        nodes.append(
            TraceabilityNode(
                reference=story_reference,
                display_code=story.code,
            )
        )
        links.append(
            TraceabilityLink(
                kind=TraceabilityLinkKind.ACTS_AS,
                source=_reference(
                    TraceabilityNodeKind.USER_TWIN,
                    story.user_twin_reference.twin_id,
                ),
                target=story_reference,
            )
        )

        for requirement_id in story.requirement_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.MOTIVATES,
                    source=story_reference,
                    target=_reference(
                        TraceabilityNodeKind.REQUIREMENT,
                        requirement_id,
                    ),
                )
            )

    for requirement in specification.requirements:
        nodes.append(
            TraceabilityNode(
                reference=_reference(
                    TraceabilityNodeKind.REQUIREMENT,
                    requirement.id,
                ),
                display_code=requirement.code,
            )
        )

    for criterion in specification.acceptance_criteria:
        criterion_reference = _reference(
            TraceabilityNodeKind.ACCEPTANCE_CRITERION,
            criterion.id,
        )
        nodes.append(
            TraceabilityNode(
                reference=criterion_reference,
                display_code=criterion.code,
            )
        )

        for requirement_id in criterion.requirement_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.VERIFIED_BY,
                    source=_reference(
                        TraceabilityNodeKind.REQUIREMENT,
                        requirement_id,
                    ),
                    target=criterion_reference,
                )
            )

        for story_id in criterion.user_story_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.VERIFIED_BY,
                    source=_reference(
                        TraceabilityNodeKind.USER_STORY,
                        story_id,
                    ),
                    target=criterion_reference,
                )
            )

    for scenario in specification.scenarios:
        scenario_reference = _reference(
            TraceabilityNodeKind.SCENARIO,
            scenario.id,
        )
        nodes.append(
            TraceabilityNode(
                reference=scenario_reference,
                display_code=scenario.code,
            )
        )

        for requirement_id in scenario.requirement_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.EXERCISES,
                    source=scenario_reference,
                    target=_reference(
                        TraceabilityNodeKind.REQUIREMENT,
                        requirement_id,
                    ),
                )
            )

        for criterion_id in scenario.acceptance_criterion_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.EXERCISES,
                    source=scenario_reference,
                    target=_reference(
                        TraceabilityNodeKind.ACCEPTANCE_CRITERION,
                        criterion_id,
                    ),
                )
            )

    for risk in specification.risks:
        risk_reference = _reference(
            TraceabilityNodeKind.RISK,
            risk.id,
        )
        nodes.append(
            TraceabilityNode(
                reference=risk_reference,
                display_code=risk.code,
            )
        )

        for requirement_id in risk.requirement_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.AFFECTS,
                    source=risk_reference,
                    target=_reference(
                        TraceabilityNodeKind.REQUIREMENT,
                        requirement_id,
                    ),
                )
            )

    for item in specification.definition_of_done:
        item_reference = _reference(
            TraceabilityNodeKind.DEFINITION_OF_DONE,
            item.id,
        )
        nodes.append(
            TraceabilityNode(
                reference=item_reference,
                display_code=item.code,
            )
        )

        for requirement_id in item.requirement_ids:
            links.append(
                TraceabilityLink(
                    kind=TraceabilityLinkKind.GOVERNS,
                    source=item_reference,
                    target=_reference(
                        TraceabilityNodeKind.REQUIREMENT,
                        requirement_id,
                    ),
                )
            )

    return RequirementsTraceability(
        project_id=version.project_id,
        specification_version_id=version.id,
        specification_version_number=(version.version_number),
        specification_content_hash=version.content_hash,
        nodes=tuple(
            sorted(
                nodes,
                key=lambda node: node.sort_key,
            )
        ),
        links=tuple(
            sorted(
                links,
                key=lambda link: link.sort_key,
            )
        ),
    )


def summarize_requirements_coverage(
    version: RequirementsSpecificationVersion,
) -> RequirementsCoverageSummary:
    """Report uncovered relationships without inventing links."""
    specification: RequirementsSpecification = version.specification

    story_requirement_ids = frozenset(
        requirement_id
        for story in specification.user_stories
        for requirement_id in story.requirement_ids
    )
    criterion_requirement_ids = frozenset(
        requirement_id
        for criterion in specification.acceptance_criteria
        for requirement_id in criterion.requirement_ids
    )
    criterion_story_ids = frozenset(
        story_id
        for criterion in specification.acceptance_criteria
        for story_id in criterion.user_story_ids
    )
    scenario_criterion_ids = frozenset(
        criterion_id
        for scenario in specification.scenarios
        for criterion_id in scenario.acceptance_criterion_ids
    )

    return RequirementsCoverageSummary(
        project_id=version.project_id,
        specification_version_id=version.id,
        requirement_count=len(specification.requirements),
        user_story_count=len(specification.user_stories),
        acceptance_criterion_count=len(specification.acceptance_criteria),
        requirement_ids_without_user_stories=tuple(
            requirement.id
            for requirement in specification.requirements
            if requirement.id not in story_requirement_ids
        ),
        requirement_ids_without_acceptance_criteria=tuple(
            requirement.id
            for requirement in specification.requirements
            if requirement.id not in criterion_requirement_ids
        ),
        user_story_ids_without_acceptance_criteria=tuple(
            story.id for story in specification.user_stories if story.id not in criterion_story_ids
        ),
        acceptance_criterion_ids_without_scenarios=tuple(
            criterion.id
            for criterion in specification.acceptance_criteria
            if criterion.id not in scenario_criterion_ids
        ),
    )


__all__ = [
    "RequirementsCoverageSummary",
    "RequirementsTraceability",
    "TraceabilityLink",
    "TraceabilityLinkKind",
    "TraceabilityNode",
    "TraceabilityNodeKind",
    "TraceabilityNodeReference",
    "build_requirements_traceability",
    "summarize_requirements_coverage",
]
