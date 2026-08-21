"""Immutable versioned packages for governed design exploration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

from orchestwin.artifacts.design import (
    DesignAlternative,
    SyntheticDesignCritique,
)
from orchestwin.artifacts.prototypes import DeclarativePrototype
from orchestwin.artifacts.references import (
    ArtifactKind,
    VersionedArtifactReference,
    require_artifact_kind,
)
from orchestwin.projects.requirements_primitives import (
    RequirementsContextReference,
    UserTwinVersionReference,
    canonical_json,
    canonical_user_twin_references,
    canonical_uuid_tuple,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecificationVersion,
)

DESIGN_PACKAGE_SCHEMA_VERSION: Final = 1
MIN_DESIGN_ALTERNATIVES: Final = 2
MAX_DESIGN_ALTERNATIVES: Final = 4
_MAX_CONCERN_TEXT_LENGTH: Final = 4000
_MAX_OPEN_QUESTION_LENGTH: Final = 2000


class _ArtifactWithIdentity(Protocol):
    """Identity and display code shared by package collections."""

    id: UUID
    code: str


@dataclass(frozen=True, slots=True)
class DesignGrounding:
    """Exact approved context and identity index used by design artifacts."""

    requirements_reference: VersionedArtifactReference
    agent_team_reference: VersionedArtifactReference
    user_modeling_reference: VersionedArtifactReference
    catalog_version: int
    catalog_content_hash: str
    requirement_ids: tuple[UUID, ...]
    user_story_ids: tuple[UUID, ...]
    acceptance_criterion_ids: tuple[UUID, ...]
    user_twin_references: tuple[UserTwinVersionReference, ...]

    def __post_init__(self) -> None:
        """Protect exact context kinds, catalog metadata, and identity indexes."""
        for reference, expected, label in (
            (
                self.requirements_reference,
                ArtifactKind.REQUIREMENTS_SPECIFICATION,
                "design Requirements reference",
            ),
            (
                self.agent_team_reference,
                ArtifactKind.AGENT_TEAM,
                "design Agent Team reference",
            ),
            (
                self.user_modeling_reference,
                ArtifactKind.USER_MODELING,
                "design User Modeling reference",
            ),
        ):
            require_artifact_kind(reference, expected=expected, label=label)

        validate_positive_integer(
            self.catalog_version,
            label="design grounding catalog version",
        )
        validate_sha256(
            self.catalog_content_hash,
            label="design grounding catalog content hash",
        )

        for values, label in (
            (self.requirement_ids, "design grounding requirement IDs"),
            (self.user_story_ids, "design grounding user-story IDs"),
            (
                self.acceptance_criterion_ids,
                "design grounding acceptance-criterion IDs",
            ),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=True,
            ):
                raise ValueError(f"{label} must use canonical order")

        if self.user_twin_references != canonical_user_twin_references(
            self.user_twin_references,
            require_items=True,
        ):
            raise ValueError("design grounding User Twin references must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic design-grounding snapshot."""
        return {
            "requirements_reference": self.requirements_reference.to_snapshot(),
            "agent_team_reference": self.agent_team_reference.to_snapshot(),
            "user_modeling_reference": self.user_modeling_reference.to_snapshot(),
            "catalog": {
                "version": self.catalog_version,
                "content_hash": self.catalog_content_hash,
            },
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "user_story_ids": [str(value) for value in self.user_story_ids],
            "acceptance_criterion_ids": [str(value) for value in self.acceptance_criterion_ids],
            "user_twin_references": [
                reference.to_snapshot() for reference in self.user_twin_references
            ],
        }


@dataclass(frozen=True, slots=True)
class DesignConcern:
    """One reviewable concern attached to requirements and alternatives."""

    id: UUID
    code: str
    summary: str
    mitigation: str
    requirement_ids: tuple[UUID, ...]
    design_alternative_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect normalized concern content and stable traceability."""
        validate_display_code(
            self.code,
            prefix="DRK",
            label="design concern code",
        )

        for value, label in (
            (self.summary, "design concern summary"),
            (self.mitigation, "design concern mitigation"),
        ):
            if (
                normalize_required_text(
                    value,
                    label=label,
                    maximum_length=_MAX_CONCERN_TEXT_LENGTH,
                )
                != value
            ):
                raise ValueError(f"{label} must be normalized")

        for values, label in (
            (self.requirement_ids, "design concern requirement IDs"),
            (self.design_alternative_ids, "design concern alternative IDs"),
        ):
            if values != canonical_uuid_tuple(
                values,
                label=label,
                require_items=True,
            ):
                raise ValueError(f"{label} must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic concern snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "summary": self.summary,
            "mitigation": self.mitigation,
            "requirement_ids": [str(value) for value in self.requirement_ids],
            "design_alternative_ids": [str(value) for value in self.design_alternative_ids],
        }


@dataclass(frozen=True, slots=True)
class DesignExplorationPackage:
    """Complete design exploration state for one governed Requirements baseline."""

    project_id: UUID
    grounding: DesignGrounding
    alternatives: tuple[DesignAlternative, ...]
    critiques: tuple[SyntheticDesignCritique, ...]
    recommended_alternative_id: UUID | None
    owner_selected_alternative_id: UUID | None
    prototype: DeclarativePrototype | None
    concerns: tuple[DesignConcern, ...] = ()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Protect diversity, critique coverage, and internal traceability."""
        if self.alternatives != _canonical_artifacts(
            self.alternatives,
            label="design alternatives",
            require_items=True,
        ):
            raise ValueError("design alternatives must use canonical code order")

        alternative_count = len(self.alternatives)

        if not MIN_DESIGN_ALTERNATIVES <= alternative_count <= MAX_DESIGN_ALTERNATIVES:
            raise ValueError("a design package requires between two and four alternatives")

        approaches = tuple(alternative.approach for alternative in self.alternatives)

        if len(approaches) != len(set(approaches)):
            raise ValueError("design alternatives must use distinct approaches")

        if self.critiques != _canonical_artifacts(
            self.critiques,
            label="design critiques",
            require_items=True,
        ):
            raise ValueError("design critiques must use canonical code order")

        if self.concerns != _canonical_artifacts(
            self.concerns,
            label="design concerns",
            require_items=False,
        ):
            raise ValueError("design concerns must use canonical code order")

        if self.open_questions != normalize_text_items(
            self.open_questions,
            label="design package open questions",
            maximum_item_length=_MAX_OPEN_QUESTION_LENGTH,
            require_items=False,
        ):
            raise ValueError("design package open questions must be normalized")

        requirement_ids = frozenset(self.grounding.requirement_ids)
        user_story_ids = frozenset(self.grounding.user_story_ids)
        criterion_ids = frozenset(self.grounding.acceptance_criterion_ids)
        twin_references = frozenset(self.grounding.user_twin_references)
        alternative_ids = frozenset(alternative.id for alternative in self.alternatives)

        for alternative in self.alternatives:
            _require_subset(
                alternative.requirement_ids,
                requirement_ids,
                label="design alternative requirement IDs",
            )
            _require_subset(
                alternative.user_story_ids,
                user_story_ids,
                label="design alternative user-story IDs",
            )
            _require_subset(
                alternative.acceptance_criterion_ids,
                criterion_ids,
                label="design alternative acceptance-criterion IDs",
            )

            if not frozenset(alternative.user_twin_references).issubset(twin_references):
                raise ValueError(
                    "design alternatives contain User Twin references outside the package"
                )

        critique_pairs: set[tuple[UUID, UserTwinVersionReference]] = set()

        for critique in self.critiques:
            if critique.design_alternative_id not in alternative_ids:
                raise ValueError("design critiques reference unknown alternatives")

            if critique.user_twin_reference not in twin_references:
                raise ValueError("design critiques reference User Twins outside the package")

            pair = (critique.design_alternative_id, critique.user_twin_reference)

            if pair in critique_pairs:
                raise ValueError("design critique alternative/User Twin pairs must be unique")

            critique_pairs.add(pair)

        expected_pairs = {
            (alternative_id, twin_reference)
            for alternative_id in alternative_ids
            for twin_reference in twin_references
        }

        if critique_pairs != expected_pairs:
            raise ValueError("design critiques must cover every alternative/User Twin pair")

        for value, label in (
            (self.recommended_alternative_id, "recommended design alternative"),
            (self.owner_selected_alternative_id, "owner-selected design alternative"),
        ):
            if value is not None and value not in alternative_ids:
                raise ValueError(f"{label} must reference an alternative in the package")

        if self.prototype is not None:
            if self.owner_selected_alternative_id is None:
                raise ValueError("a design prototype requires an owner-selected alternative")

            if self.prototype.design_alternative_id != self.owner_selected_alternative_id:
                raise ValueError("design prototype must represent the owner-selected alternative")

            _validate_prototype_scope(
                self.prototype,
                requirement_ids=requirement_ids,
                user_story_ids=user_story_ids,
                criterion_ids=criterion_ids,
            )

        for concern in self.concerns:
            _require_subset(
                concern.requirement_ids,
                requirement_ids,
                label="design concern requirement IDs",
            )
            _require_subset(
                concern.design_alternative_ids,
                alternative_ids,
                label="design concern alternative IDs",
            )

    @property
    def ready_for_gate(self) -> bool:
        """Return whether owner selection and prototype make Gate 5 possible."""
        return self.owner_selected_alternative_id is not None and self.prototype is not None

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic complete Design Package snapshot."""
        return {
            "schema_version": DESIGN_PACKAGE_SCHEMA_VERSION,
            "project_id": str(self.project_id),
            "grounding": self.grounding.to_snapshot(),
            "alternatives": [alternative.to_snapshot() for alternative in self.alternatives],
            "critiques": [critique.to_snapshot() for critique in self.critiques],
            "recommended_alternative_id": (
                None
                if self.recommended_alternative_id is None
                else str(self.recommended_alternative_id)
            ),
            "owner_selected_alternative_id": (
                None
                if self.owner_selected_alternative_id is None
                else str(self.owner_selected_alternative_id)
            ),
            "prototype": None if self.prototype is None else self.prototype.to_snapshot(),
            "concerns": [concern.to_snapshot() for concern in self.concerns],
            "open_questions": list(self.open_questions),
        }

    def canonical_json(self) -> str:
        """Serialize this Design Package deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this Design Package."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class DesignPackageVersion:
    """One immutable version of a project Design Package."""

    id: UUID
    project_id: UUID
    version_number: int
    package: DesignExplorationPackage
    content_hash: str
    created_by_user_id: UUID
    created_at: datetime
    based_on_version_number: int | None = None

    def __post_init__(self) -> None:
        """Protect project scope, hash, timestamp, and linear lineage."""
        validate_positive_integer(
            self.version_number,
            label="Design Package version number",
        )

        if self.package.project_id != self.project_id:
            raise ValueError("Design Package version must belong to its project")

        if self.created_at.utcoffset() is None:
            raise ValueError("Design Package timestamp must be timezone-aware")

        validate_sha256(
            self.content_hash,
            label="Design Package content hash",
        )

        if self.content_hash != self.package.content_hash:
            raise ValueError("Design Package hash must match its content")

        expected_base = None if self.version_number == 1 else self.version_number - 1

        if self.based_on_version_number != expected_base:
            raise ValueError(
                "Design Package lineage must reference the immediately preceding version"
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


def create_design_grounding(
    version: RequirementsSpecificationVersion,
) -> DesignGrounding:
    """Create exact design grounding from an immutable Requirements version."""
    specification = version.specification

    return DesignGrounding(
        requirements_reference=VersionedArtifactReference(
            kind=ArtifactKind.REQUIREMENTS_SPECIFICATION,
            artifact_id=version.id,
            version_number=version.version_number,
            content_hash=version.content_hash,
        ),
        agent_team_reference=_context_reference(
            specification.agent_team_reference,
            kind=ArtifactKind.AGENT_TEAM,
        ),
        user_modeling_reference=_context_reference(
            specification.user_modeling_reference,
            kind=ArtifactKind.USER_MODELING,
        ),
        catalog_version=specification.catalog_version,
        catalog_content_hash=specification.catalog_content_hash,
        requirement_ids=canonical_uuid_tuple(
            (requirement.id for requirement in specification.requirements),
            label="design grounding requirement IDs",
            require_items=True,
        ),
        user_story_ids=canonical_uuid_tuple(
            (story.id for story in specification.user_stories),
            label="design grounding user-story IDs",
            require_items=True,
        ),
        acceptance_criterion_ids=canonical_uuid_tuple(
            (criterion.id for criterion in specification.acceptance_criteria),
            label="design grounding acceptance-criterion IDs",
            require_items=True,
        ),
        user_twin_references=canonical_user_twin_references(
            specification.user_twin_references,
            require_items=True,
        ),
    )


def create_design_concern(
    *,
    concern_id: UUID,
    code: str,
    summary: str,
    mitigation: str,
    requirement_ids: Iterable[UUID],
    design_alternative_ids: Iterable[UUID],
) -> DesignConcern:
    """Create one normalized and traceable design concern."""
    return DesignConcern(
        id=concern_id,
        code=code,
        summary=normalize_required_text(
            summary,
            label="design concern summary",
            maximum_length=_MAX_CONCERN_TEXT_LENGTH,
        ),
        mitigation=normalize_required_text(
            mitigation,
            label="design concern mitigation",
            maximum_length=_MAX_CONCERN_TEXT_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="design concern requirement IDs",
            require_items=True,
        ),
        design_alternative_ids=canonical_uuid_tuple(
            design_alternative_ids,
            label="design concern alternative IDs",
            require_items=True,
        ),
    )


def create_design_exploration_package(
    *,
    project_id: UUID,
    grounding: DesignGrounding,
    alternatives: Iterable[DesignAlternative],
    critiques: Iterable[SyntheticDesignCritique],
    recommended_alternative_id: UUID | None = None,
    owner_selected_alternative_id: UUID | None = None,
    prototype: DeclarativePrototype | None = None,
    concerns: Iterable[DesignConcern] = (),
    open_questions: Iterable[str] = (),
) -> DesignExplorationPackage:
    """Create a complete package in deterministic collection order."""
    return DesignExplorationPackage(
        project_id=project_id,
        grounding=grounding,
        alternatives=_canonical_artifacts(
            alternatives,
            label="design alternatives",
            require_items=True,
        ),
        critiques=_canonical_artifacts(
            critiques,
            label="design critiques",
            require_items=True,
        ),
        recommended_alternative_id=recommended_alternative_id,
        owner_selected_alternative_id=owner_selected_alternative_id,
        prototype=prototype,
        concerns=_canonical_artifacts(
            concerns,
            label="design concerns",
            require_items=False,
        ),
        open_questions=normalize_text_items(
            open_questions,
            label="design package open questions",
            maximum_item_length=_MAX_OPEN_QUESTION_LENGTH,
            require_items=False,
        ),
    )


def _context_reference(
    reference: RequirementsContextReference,
    *,
    kind: ArtifactKind,
) -> VersionedArtifactReference:
    """Translate an exact Requirements context reference without losing metadata."""
    return VersionedArtifactReference(
        kind=kind,
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
    )


def _canonical_artifacts[Artifact: _ArtifactWithIdentity](
    values: Iterable[Artifact],
    *,
    label: str,
    require_items: bool,
) -> tuple[Artifact, ...]:
    """Return identity-safe artifacts in stable code order."""
    artifacts = tuple(values)

    if require_items and not artifacts:
        raise ValueError(f"{label} must not be empty")

    ids = tuple(artifact.id for artifact in artifacts)
    codes = tuple(artifact.code for artifact in artifacts)

    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} identities must be unique")

    if len(codes) != len(set(codes)):
        raise ValueError(f"{label} codes must be unique")

    return tuple(sorted(artifacts, key=lambda artifact: artifact.code))


def _require_subset(
    references: Iterable[UUID],
    available: Iterable[UUID],
    *,
    label: str,
) -> None:
    """Reject references that do not resolve inside the Design Package."""
    if not frozenset(references).issubset(frozenset(available)):
        raise ValueError(f"{label} contain unknown references")


def _validate_prototype_scope(
    prototype: DeclarativePrototype,
    *,
    requirement_ids: frozenset[UUID],
    user_story_ids: frozenset[UUID],
    criterion_ids: frozenset[UUID],
) -> None:
    """Require prototype traceability to resolve in the Requirements scope."""
    for screen in prototype.screens:
        _require_subset(
            screen.requirement_ids,
            requirement_ids,
            label="prototype screen requirement IDs",
        )
        _require_subset(
            screen.user_story_ids,
            user_story_ids,
            label="prototype screen user-story IDs",
        )
        _require_subset(
            screen.acceptance_criterion_ids,
            criterion_ids,
            label="prototype screen acceptance-criterion IDs",
        )

        for element in screen.elements:
            _require_subset(
                element.requirement_ids,
                requirement_ids,
                label="prototype element requirement IDs",
            )
            _require_subset(
                element.user_story_ids,
                user_story_ids,
                label="prototype element user-story IDs",
            )
            _require_subset(
                element.acceptance_criterion_ids,
                criterion_ids,
                label="prototype element acceptance-criterion IDs",
            )


__all__ = [
    "DESIGN_PACKAGE_SCHEMA_VERSION",
    "MAX_DESIGN_ALTERNATIVES",
    "MIN_DESIGN_ALTERNATIVES",
    "DesignConcern",
    "DesignExplorationPackage",
    "DesignGrounding",
    "DesignPackageVersion",
    "create_design_concern",
    "create_design_exploration_package",
    "create_design_grounding",
]
