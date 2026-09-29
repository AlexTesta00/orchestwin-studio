from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.artifacts.generated_mockup_structure import derive_prototype, walk_elements
from orchestwin.artifacts.generated_mockup_styles import detail_name
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    GeneratedMockupError,
    generated_mockup_from_snapshot,
    screen_trees,
)
from orchestwin.artifacts.prototypes import DeclarativePrototype
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

_SNAPSHOT_KEYS: Final = frozenset({"mockup", "requirement_ids_by_code"})
_LISTED_CODES: Final = 5


def markup_requirement_codes(mockup: GeneratedMockup) -> tuple[str, ...]:
    codes: set[str] = set()
    for nodes in screen_trees(mockup).values():
        for node, _path, _ancestors in walk_elements(nodes):
            value = node.attribute("data-req")
            if value:
                codes.update(value.split(" "))
    return tuple(sorted(codes))


def _listed(codes: Iterable[str]) -> str:
    return ", ".join(detail_name(code) for code in sorted(codes)[:_LISTED_CODES])


def _valid_entry(entry: object) -> bool:
    return (
        isinstance(entry, tuple)
        and len(entry) == 2
        and isinstance(entry[0], str)
        and isinstance(entry[1], UUID)
    )


@dataclass(frozen=True, slots=True)
class BoundGeneratedMockup:
    mockup: GeneratedMockup
    requirement_ids_by_code: tuple[tuple[str, UUID], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mockup, GeneratedMockup):
            raise GeneratedMockupError("MOCKUP_INVALID", "the mockup must be a generated mockup")
        entries = self.requirement_ids_by_code
        if not isinstance(entries, tuple) or not all(_valid_entry(entry) for entry in entries):
            raise GeneratedMockupError(
                "REQUIREMENT_MAPPING", "requirement identifiers must pair codes with UUIDs"
            )
        codes = [code for code, _identifier in entries]
        if codes != sorted(set(codes)):
            raise GeneratedMockupError(
                "REQUIREMENT_MAPPING", "requirement codes must be unique and sorted"
            )
        identifiers = [identifier for _code, identifier in entries]
        if len(set(identifiers)) != len(identifiers):
            raise GeneratedMockupError(
                "REQUIREMENT_ID_DUPLICATED", "two requirement codes share one identifier"
            )
        named = set(markup_requirement_codes(self.mockup))
        unmapped = named - set(codes)
        if unmapped:
            raise GeneratedMockupError(
                "REQUIREMENT_CODE_UNMAPPED", f"no identifier for {_listed(unmapped)}"
            )
        unused = set(codes) - named
        if unused:
            raise GeneratedMockupError(
                "REQUIREMENT_CODE_UNUSED", f"{_listed(unused)} not named by the markup"
            )

    @property
    def design_alternative_id(self) -> UUID:
        return self.mockup.design_alternative_id

    @property
    def requirement_codes(self) -> tuple[str, ...]:
        return tuple(code for code, _identifier in self.requirement_ids_by_code)

    @property
    def requirement_ids(self) -> tuple[UUID, ...]:
        return tuple(identifier for _code, identifier in self.requirement_ids_by_code)

    def prototype(self) -> DeclarativePrototype:
        return derive_prototype(
            self.mockup,
            requirement_ids_by_code=dict(self.requirement_ids_by_code),
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "mockup": self.mockup.to_snapshot(),
            "requirement_ids_by_code": {
                code: str(identifier) for code, identifier in self.requirement_ids_by_code
            },
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def _entries(value: object) -> list[tuple[str, UUID]]:
    if isinstance(value, Mapping):
        items: Iterable[object] = value.items()
    elif isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise GeneratedMockupError(
            "REQUIREMENT_MAPPING", "requirement identifiers must map codes to UUIDs"
        )
    else:
        items = value
    entries: list[tuple[str, UUID]] = []
    for item in items:
        entry = tuple(item) if isinstance(item, tuple | list) else item
        if not _valid_entry(entry):
            raise GeneratedMockupError(
                "REQUIREMENT_MAPPING", "requirement identifiers must map codes to UUIDs"
            )
        entries.append(entry)
    return entries


def create_bound_mockup(
    *,
    mockup: GeneratedMockup,
    requirement_ids_by_code: Mapping[str, UUID] | Iterable[tuple[str, UUID]],
) -> BoundGeneratedMockup:
    entries = _entries(requirement_ids_by_code)
    return BoundGeneratedMockup(
        mockup=mockup,
        requirement_ids_by_code=tuple(sorted(entries, key=lambda entry: entry[0])),
    )


def bound_mockup_from_snapshot(
    payload: Mapping[str, object],
    *,
    token_names: Iterable[str],
) -> BoundGeneratedMockup:
    if not isinstance(payload, Mapping) or set(payload) != _SNAPSHOT_KEYS:
        raise GeneratedMockupError("SNAPSHOT_INVALID", "bound mockup snapshot keys")
    mockup_payload = payload["mockup"]
    mapping = payload["requirement_ids_by_code"]
    if not isinstance(mockup_payload, Mapping):
        raise GeneratedMockupError("SNAPSHOT_INVALID", "the mockup must be an object")
    if not isinstance(mapping, Mapping) or not all(
        isinstance(code, str) and isinstance(identifier, str)
        for code, identifier in mapping.items()
    ):
        raise GeneratedMockupError(
            "SNAPSHOT_INVALID", "requirement identifiers must map codes to text"
        )
    entries: list[tuple[str, UUID]] = []
    for code, identifier in mapping.items():
        try:
            entries.append((code, UUID(identifier)))
        except ValueError as error:
            raise GeneratedMockupError(
                "REQUIREMENT_MAPPING", f"identifier of {detail_name(code)}"
            ) from error
    bound = create_bound_mockup(
        mockup=generated_mockup_from_snapshot(mockup_payload, token_names=token_names),
        requirement_ids_by_code=entries,
    )
    if bound.to_snapshot()["requirement_ids_by_code"] != dict(mapping):
        raise GeneratedMockupError(
            "SNAPSHOT_NOT_CANONICAL", "requirement identifiers are not in their stored form"
        )
    return bound


__all__ = [
    "BoundGeneratedMockup",
    "bound_mockup_from_snapshot",
    "create_bound_mockup",
    "markup_requirement_codes",
]
