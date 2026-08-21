"""Immutable versioned packages for governed architecture and test planning."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from orchestwin.artifacts.architecture import SoftwareArchitecture
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.references import (
    ArtifactKind,
    VersionedArtifactReference,
    require_artifact_kind,
)
from orchestwin.artifacts.test_plans import TestPlan
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    canonical_uuid_tuple,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

ARCHITECTURE_PACKAGE_SCHEMA_VERSION: Final = 1
_MAX_OPEN_QUESTION_LENGTH: Final = 2000


@dataclass(frozen=True, slots=True)
class ArchitectureGrounding:
    """Exact approved design and inherited context used for architecture planning."""

    project_id: UUID
    design_package_reference: VersionedArtifactReference
    requirements_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    user_modeling_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str
    owner_selected_alternative_id: UUID
    prototype_id: UUID
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReference, ...]

    def __post_init__(self) -> None:
        """Protect exact artifact kinds, catalog metadata, and identity indexes."""
        for reference, expected, label in (
            (
                self.design_package_reference,
                ArtifactKind.DESIGN_PACKAGE,
                "architecture Design Package reference",
            ),
            (
                self.requirements_reference,
                ArtifactKind.REQUIREMENTS_SPECIFICATION,
                "architecture Requirements reference",
            ),
            (
                self.agent_team_reference,
                ArtifactKind.AGENT_TEAM,
                "architecture Agent Team reference",
            ),
            (
                self.user_modeling_reference,
                ArtifactKind.USER_MODELING,
                "architecture User Modeling reference",
            ),
        ):
            require_artifact_kind(reference, expected=expected, label=label)

        validate_positive_integer(
            self.catalog_version,
            label="architecture grounding catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="architecture grounding catalog content hash",
        )

        for values, label in (
            (self.requirement_ids, "architecture grounding requirement IDs"),
            (self.user_story_ids, "architecture grounding user-story IDs"),
            (
                self.acceptance_criterion_ids,
                "architecture grounding acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(values, label=label, require_items=True):
                raise ValueError(f"{label} must use canonical order")

        if self.user_twin_references != canonical_user_twin_references(
            self.user_twin_references,
            require_items=True,
        ):
            raise ValueError("architecture grounding User Twin references must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic architecture-grounding snapshot."""
        return {
            "project_id": str(self.project_id),
            "design_package_reference": self.design_package_reference.to_snapshot(),
            "requirements_reference": self.requirements_reference.to_snapshot(),
            "agent_team_reference": self.agent_team_reference.to_snapshot(),
            "user_modeling_reference": self.user_modeling_reference.to_snapshot(),
            "catalog": {
                "version": self.catalog_version,
                "content_hash": self.catalog_content_hash,
            },
            "owner_selected_alternative_id": str(self.owner_selected_alternative_id),
            "prototype_id": str(self.prototype_id),
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "user_twin_references": [
                reference.to_snapshot() for reference in self.user_twin_references
            ],
        }


@dataclass(frozen=True, slots=True)
class ArchitecturePlanningPackage:
    """Complete architecture and test-plan state for one selected design."""

    project_id: UUID
    grounding: ArchitectureGrounding
    architecture: SoftwareArchitecture
    test_plan: TestPlan
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect exact cross-stage grounding and internal package consistency."""
        if self.grounding.project_id != self.project_id:
            raise ValueError("Architecture Package grounding must belong to its project")

        if self.open_questions != normalize_text_items(
            self.open_questions,
            label="architecture package open questions",
            maximum_item_length=_MAX_OPEN_QUESTION_LENGTH,
            require_items=False,
        ):
            raise ValueError("architecture package open questions must be normalized")

        self._validate_architecture()
        self._validate_test_plan()

    def _validate_architecture(self) -> None:
        """Require the architecture to describe exactly the selected Design Package scope."""
        if (
            self.architecture.selected_design_alternative_id
            != self.grounding.owner_selected_alternative_id
        ):
            raise ValueError("architecture must reference the owner-selected design alternative")

        if self.architecture.prototype_id != self.grounding.prototype_id:
            raise ValueError("architecture must reference the selected declarative prototype")

        if self.architecture.requirement_ids != self.grounding.requirement_ids:
            raise ValueError("architecture must cover the exact grounded requirement set")

        if self.architecture.acceptance_criterion_ids != self.grounding.acceptance_criterion_ids:
            raise ValueError("architecture must cover the exact grounded acceptance-criterion set")

    def _validate_test_plan(self) -> None:
        """Require the test plan to verify exactly the architecture and selected design."""
        if self.test_plan.architecture_id != self.architecture.id:
            raise ValueError("test plan must reference the packaged architecture")

        if (
            self.test_plan.selected_design_alternative_id
            != self.grounding.owner_selected_alternative_id
        ):
            raise ValueError("test plan must reference the owner-selected design alternative")

        if self.test_plan.requirement_ids != self.grounding.requirement_ids:
            raise ValueError("test plan must cover the exact grounded requirement set")

        if self.test_plan.acceptance_criterion_ids != self.grounding.acceptance_criterion_ids:
            raise ValueError("test plan must cover the exact grounded acceptance-criterion set")

        expected_component_ids = canonical_uuid_tuple(
            (component.id for component in self.architecture.components),
            label="packaged architecture component IDs",
            require_items=True,
        )

        if self.test_plan.architecture_component_ids != expected_component_ids:
            raise ValueError("test plan must cover every packaged architecture component")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic complete Architecture Package snapshot."""
        return {
            "schema_version": ARCHITECTURE_PACKAGE_SCHEMA_VERSION,
            "project_id": str(self.project_id),
            "grounding": self.grounding.to_snapshot(),
            "architecture": self.architecture.to_snapshot(),
            "test_plan": self.test_plan.to_snapshot(),
            "open_questions": list(self.open_questions),
        }

    def canonical_json(self) -> str:
        """Serialize this Architecture Package deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this Architecture Package."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class ArchitecturePackageVersion:
    """One immutable version of a project Architecture Package."""

    id: UUID
    project_id: UUID
    version_number: int
    package: ArchitecturePlanningPackage
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect project scope, content hash, timestamp, and linear lineage."""
        validate_positive_integer(
            self.version_number,
            label="Architecture Package version number",
        )

        if self.package.project_id != self.project_id:
            raise ValueError("Architecture Package version must belong to its project")

        if self.created_at.utcoffset() is None:
            raise ValueError("Architecture Package timestamp must be timezone-aware")

        validate_sha256(
            self.content_hash,
            label="Architecture Package content hash",
        )

        if self.content_hash != self.package.content_hash:
            raise ValueError("Architecture Package hash must match its content")

        expected_base = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base:
            raise ValueError(
                "Architecture Package lineage must reference the immediately preceding version"
            )

    @property
    def reference(self) -> VersionedArtifactReference:
        """Return the exact version/hash tuple used by later governed stages."""
        return VersionedArtifactReference(
            kind=ArtifactKind.ARCHITECTURE_PACKAGE,
            artifact_id=self.id,
            version_number=self.version_number,
            content_hash=self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic package-version snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": self.based_on_version_number,
            "content_hash": self.content_hash,
            "package": self.package.to_snapshot(),
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }


def create_architecture_grounding(
    version: DesignPackageVersion,
) -> ArchitectureGrounding:
    """Create exact architecture grounding from an immutable selected Design Package."""
    package = version.package

    if not package.ready_for_gate:
        raise ValueError("architecture grounding requires an owner-selected design and prototype")

    selected_alternative_id = package.owner_selected_alternative_id
    prototype = package.prototype

    if selected_alternative_id is None or prototype is None:
        raise ValueError("architecture grounding requires an owner-selected design and prototype")

    design_grounding = package.grounding

    return ArchitectureGrounding(
        project_id=version.project_id,
        design_package_reference=VersionedArtifactReference(
            kind=ArtifactKind.DESIGN_PACKAGE,
            artifact_id=version.id,
            version_number=version.version_number,
            content_hash=version.content_hash,
        ),
        requirements_reference=design_grounding.requirements_reference,
        agent_team_reference=design_grounding.agent_team_reference,
        user_modeling_reference=design_grounding.user_modeling_reference,
        catalog_version=design_grounding.catalog_version,
        catalog_content_hash=design_grounding.catalog_content_hash,
        owner_selected_alternative_id=selected_alternative_id,
        prototype_id=prototype.id,
        requirement_ids=design_grounding.requirement_ids,
        user_story_ids=design_grounding.user_story_ids,
        acceptance_criterion_ids=design_grounding.acceptance_criterion_ids,
        user_twin_references=design_grounding.user_twin_references,
    )


def create_architecture_planning_package(
    *,
    project_id: UUID,
    grounding: ArchitectureGrounding,
    architecture: SoftwareArchitecture,
    test_plan: TestPlan,
    open_questions: Iterable[str] = (),
) -> ArchitecturePlanningPackage:
    """Create a complete Architecture Package from normalized stage artifacts."""
    return ArchitecturePlanningPackage(
        project_id=project_id,
        grounding=grounding,
        architecture=architecture,
        test_plan=test_plan,
        open_questions=normalize_text_items(
            open_questions,
            label="architecture package open questions",
            maximum_item_length=_MAX_OPEN_QUESTION_LENGTH,
            require_items=False,
        ),
    )


__all__ = [
    "ARCHITECTURE_PACKAGE_SCHEMA_VERSION",
    "ArchitectureGrounding",
    "ArchitecturePackageVersion",
    "ArchitecturePlanningPackage",
    "create_architecture_grounding",
    "create_architecture_planning_package",
]
