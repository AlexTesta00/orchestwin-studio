from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    RequirementSourceReference,
    canonical_json,
    canonical_requirement_sources,
    canonical_uuid_tuple,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_display_code,
)


@dataclass(frozen=True, slots=True)
class JourneyPhase:
    title: str
    action: str
    need_ids: tuple[UUID, ...]
    touchpoint: str | None = None
    criticalities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, label, maximum in (
            (self.title, "journey phase title", 200),
            (self.action, "journey phase action", 2000),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum) != value:
                raise ValueError(f"{label} must be normalized")
        if (
            normalize_optional_text(
                self.touchpoint, label="journey phase touchpoint", maximum_length=2000
            )
            != self.touchpoint
        ):
            raise ValueError("journey phase touchpoint must be normalized")
        if self.criticalities != normalize_text_items(
            self.criticalities,
            label="journey phase criticalities",
            maximum_item_length=2000,
            require_items=False,
        ):
            raise ValueError("journey phase criticalities must be normalized")
        if self.need_ids != canonical_uuid_tuple(
            self.need_ids, label="journey phase need IDs", require_items=True
        ):
            raise ValueError("journey phase need IDs must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "title": self.title,
            "action": self.action,
            "touchpoint": self.touchpoint,
            "criticalities": list(self.criticalities),
            "need_ids": [str(value) for value in self.need_ids],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class UserJourney:
    id: UUID
    code: str
    title: str
    scenario_id: UUID
    phases: tuple[JourneyPhase, ...]
    sources: tuple[RequirementSourceReference, ...]

    def __post_init__(self) -> None:
        validate_display_code(self.code, prefix="JRN", label="user-journey code")
        if (
            normalize_required_text(self.title, label="user-journey title", maximum_length=200)
            != self.title
        ):
            raise ValueError("user-journey title must be normalized")
        if not isinstance(self.phases, tuple) or not 1 <= len(self.phases) <= 32:
            raise ValueError("a user journey requires between 1 and 32 ordered phases")
        if not all(isinstance(phase, JourneyPhase) for phase in self.phases):
            raise ValueError("user-journey phases must be JourneyPhase values")
        if self.sources != canonical_requirement_sources(self.sources, require_items=True):
            raise ValueError("user-journey sources must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "scenario_id": str(self.scenario_id),
            "phases": [phase.to_snapshot() for phase in self.phases],
            "sources": [source.to_snapshot() for source in self.sources],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def create_journey_phase(
    *,
    title: str,
    action: str,
    need_ids: Iterable[UUID],
    touchpoint: str | None = None,
    criticalities: Iterable[str] = (),
) -> JourneyPhase:
    return JourneyPhase(
        title=normalize_required_text(title, label="journey phase title", maximum_length=200),
        action=normalize_required_text(action, label="journey phase action", maximum_length=2000),
        need_ids=canonical_uuid_tuple(need_ids, label="journey phase need IDs", require_items=True),
        touchpoint=normalize_optional_text(
            touchpoint, label="journey phase touchpoint", maximum_length=2000
        ),
        criticalities=normalize_text_items(
            criticalities,
            label="journey phase criticalities",
            maximum_item_length=2000,
            require_items=False,
        ),
    )


def create_user_journey(
    *,
    journey_id: UUID,
    code: str,
    title: str,
    scenario_id: UUID,
    phases: Iterable[JourneyPhase],
    sources: Iterable[RequirementSourceReference],
) -> UserJourney:
    return UserJourney(
        id=journey_id,
        code=code,
        title=normalize_required_text(title, label="user-journey title", maximum_length=200),
        scenario_id=scenario_id,
        phases=tuple(phases),
        sources=canonical_requirement_sources(sources, require_items=True),
    )


__all__ = ["JourneyPhase", "UserJourney", "create_journey_phase", "create_user_journey"]
