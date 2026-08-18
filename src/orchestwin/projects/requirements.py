"""Immutable requirement and user-story primitives."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    RequirementSourceReference,
    UserTwinVersionReference,
    canonical_json,
    canonical_requirement_sources,
    canonical_user_twin_references,
    canonical_uuid_tuple,
    normalize_required_text,
    snapshot_content_hash,
    validate_display_code,
)

_MAX_REQUIREMENT_TITLE_LENGTH: Final = 200
_MAX_REQUIREMENT_STATEMENT_LENGTH: Final = 4000
_MAX_USER_STORY_GOAL_LENGTH: Final = 2000
_MAX_USER_STORY_BENEFIT_LENGTH: Final = 2000


class RequirementKind(StrEnum):
    """Supported classifications of project requirements."""

    FUNCTIONAL = "FUNCTIONAL"
    NON_FUNCTIONAL = "NON_FUNCTIONAL"
    CONSTRAINT = "CONSTRAINT"


class RequirementPriority(StrEnum):
    """Owner-reviewable MoSCoW-style requirement priority."""

    MUST = "MUST"
    SHOULD = "SHOULD"
    COULD = "COULD"
    WONT_FOR_NOW = "WONT_FOR_NOW"


@dataclass(frozen=True, slots=True)
class Requirement:
    """One stable and inspectably grounded project requirement."""

    id: UUID
    code: str
    title: str
    statement: str
    kind: RequirementKind
    priority: RequirementPriority
    sources: tuple[RequirementSourceReference, ...]
    user_twin_references: tuple[
        UserTwinVersionReference,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect identity, normalized text, and canonical grounding."""
        validate_display_code(
            self.code,
            prefix="REQ",
            label="requirement code",
        )

        if (
            normalize_required_text(
                self.title,
                label="requirement title",
                maximum_length=_MAX_REQUIREMENT_TITLE_LENGTH,
            )
            != self.title
        ):
            raise ValueError("requirement title must be normalized")

        if (
            normalize_required_text(
                self.statement,
                label="requirement statement",
                maximum_length=_MAX_REQUIREMENT_STATEMENT_LENGTH,
            )
            != self.statement
        ):
            raise ValueError("requirement statement must be normalized")

        if self.sources != canonical_requirement_sources(
            self.sources,
            require_items=True,
        ):
            raise ValueError("requirement sources must use canonical order")

        if self.user_twin_references != canonical_user_twin_references(
            self.user_twin_references,
            require_items=False,
        ):
            raise ValueError("requirement User Twin references must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic requirement snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "statement": self.statement,
            "kind": self.kind.value,
            "priority": self.priority.value,
            "sources": [source.to_snapshot() for source in self.sources],
            "user_twin_references": [
                reference.to_snapshot() for reference in self.user_twin_references
            ],
        }

    def canonical_json(self) -> str:
        """Serialize this requirement deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this requirement."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class UserStory:
    """One structured user story grounded in an exact User Twin."""

    id: UUID
    code: str
    user_twin_reference: UserTwinVersionReference
    goal: str
    benefit: str
    requirement_ids: tuple[UUID, ...]

    def __post_init__(self) -> None:
        """Protect identity, normalized intent, and requirement links."""
        validate_display_code(
            self.code,
            prefix="USR",
            label="user-story code",
        )

        if (
            normalize_required_text(
                self.goal,
                label="user-story goal",
                maximum_length=_MAX_USER_STORY_GOAL_LENGTH,
            )
            != self.goal
        ):
            raise ValueError("user-story goal must be normalized")

        if (
            normalize_required_text(
                self.benefit,
                label="user-story benefit",
                maximum_length=_MAX_USER_STORY_BENEFIT_LENGTH,
            )
            != self.benefit
        ):
            raise ValueError("user-story benefit must be normalized")

        if self.requirement_ids != canonical_uuid_tuple(
            self.requirement_ids,
            label="user-story requirement IDs",
            require_items=True,
        ):
            raise ValueError("user-story requirement IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic user-story snapshot."""
        return {
            "id": str(self.id),
            "code": self.code,
            "user_twin_reference": (self.user_twin_reference.to_snapshot()),
            "goal": self.goal,
            "benefit": self.benefit,
            "requirement_ids": [str(value) for value in self.requirement_ids],
        }

    def canonical_json(self) -> str:
        """Serialize this user story deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this user story."""
        return snapshot_content_hash(self.to_snapshot())


def create_requirement(
    *,
    requirement_id: UUID,
    code: str,
    title: str,
    statement: str,
    kind: RequirementKind,
    priority: RequirementPriority,
    sources: Iterable[RequirementSourceReference],
    user_twin_references: Iterable[UserTwinVersionReference] = (),
) -> Requirement:
    """Create a normalized requirement with canonical references."""
    return Requirement(
        id=requirement_id,
        code=code,
        title=normalize_required_text(
            title,
            label="requirement title",
            maximum_length=_MAX_REQUIREMENT_TITLE_LENGTH,
        ),
        statement=normalize_required_text(
            statement,
            label="requirement statement",
            maximum_length=_MAX_REQUIREMENT_STATEMENT_LENGTH,
        ),
        kind=kind,
        priority=priority,
        sources=canonical_requirement_sources(
            sources,
            require_items=True,
        ),
        user_twin_references=(
            canonical_user_twin_references(
                user_twin_references,
                require_items=False,
            )
        ),
    )


def create_user_story(
    *,
    story_id: UUID,
    code: str,
    user_twin_reference: UserTwinVersionReference,
    goal: str,
    benefit: str,
    requirement_ids: Iterable[UUID],
) -> UserStory:
    """Create a normalized user story with canonical requirement links."""
    return UserStory(
        id=story_id,
        code=code,
        user_twin_reference=user_twin_reference,
        goal=normalize_required_text(
            goal,
            label="user-story goal",
            maximum_length=_MAX_USER_STORY_GOAL_LENGTH,
        ),
        benefit=normalize_required_text(
            benefit,
            label="user-story benefit",
            maximum_length=_MAX_USER_STORY_BENEFIT_LENGTH,
        ),
        requirement_ids=canonical_uuid_tuple(
            requirement_ids,
            label="user-story requirement IDs",
            require_items=True,
        ),
    )


__all__ = [
    "Requirement",
    "RequirementKind",
    "RequirementPriority",
    "UserStory",
    "create_requirement",
    "create_user_story",
]
