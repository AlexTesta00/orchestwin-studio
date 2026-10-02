from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from orchestwin.projects.requirements_primitives import (
    RequirementSourceReference,
    canonical_json,
    canonical_requirement_sources,
    canonical_uuid_tuple,
    normalize_required_text,
    snapshot_content_hash,
    validate_display_code,
)


@dataclass(frozen=True, slots=True)
class UserNeed:
    id: UUID
    code: str
    title: str
    statement: str
    scenario_ids: tuple[UUID, ...]
    sources: tuple[RequirementSourceReference, ...]

    def __post_init__(self) -> None:
        validate_display_code(self.code, prefix="NED", label="user-need code")
        for value, label, maximum in (
            (self.title, "user-need title", 200),
            (self.statement, "user-need statement", 2000),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum) != value:
                raise ValueError(f"{label} must be normalized")
        if self.scenario_ids != canonical_uuid_tuple(
            self.scenario_ids, label="user-need scenario IDs", require_items=True
        ):
            raise ValueError("user-need scenario IDs must use canonical order")
        if self.sources != canonical_requirement_sources(self.sources, require_items=True):
            raise ValueError("user-need sources must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "code": self.code,
            "title": self.title,
            "statement": self.statement,
            "scenario_ids": [str(value) for value in self.scenario_ids],
            "sources": [source.to_snapshot() for source in self.sources],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def create_user_need(
    *,
    need_id: UUID,
    code: str,
    title: str,
    statement: str,
    scenario_ids: Iterable[UUID],
    sources: Iterable[RequirementSourceReference],
) -> UserNeed:
    return UserNeed(
        id=need_id,
        code=code,
        title=normalize_required_text(title, label="user-need title", maximum_length=200),
        statement=normalize_required_text(
            statement, label="user-need statement", maximum_length=2000
        ),
        scenario_ids=canonical_uuid_tuple(
            scenario_ids, label="user-need scenario IDs", require_items=True
        ),
        sources=canonical_requirement_sources(sources, require_items=True),
    )


__all__ = ["UserNeed", "create_user_need"]
