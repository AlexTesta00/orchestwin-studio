from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from orchestwin.artifacts.visual_catalog import (
    PALETTE_ROLES,
    VISUAL_CATALOG_CONTENT_HASH,
    VISUAL_CATALOG_VERSION,
    VisualChoices,
    resolve_palette,
    resolve_visual_tokens,
)
from orchestwin.artifacts.visual_color import is_hex_colour
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_json,
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

MAX_PRODUCT_NAME_LENGTH: Final = 80
MAX_VISUAL_RATIONALE_LENGTH: Final = 2000
MAX_TWIN_FIT_LENGTH: Final = 1000
_TOKEN_PREFIX: Final = "--vl-"


@dataclass(frozen=True, slots=True)
class TwinFit:
    twin_id: UUID
    name: str
    statement: str

    def __post_init__(self) -> None:
        for value, label in ((self.name, "twin fit name"), (self.statement, "twin fit statement")):
            if (
                normalize_required_text(value, label=label, maximum_length=MAX_TWIN_FIT_LENGTH)
                != value
            ):
                raise ValueError(f"{label} must be normalized")

    def to_snapshot(self) -> dict[str, str]:
        return {"twin_id": str(self.twin_id), "name": self.name, "statement": self.statement}


@dataclass(frozen=True, slots=True)
class VisualLanguage:
    choices: VisualChoices
    product_name: str
    rationale: str
    palette: tuple[tuple[str, str], ...]
    tokens: tuple[tuple[str, str], ...]
    catalog_version: int
    catalog_content_hash: str
    twin_fit: tuple[TwinFit, ...] = ()

    def __post_init__(self) -> None:
        validate_positive_integer(self.catalog_version, label="visual catalog version")
        identifiers = [item.twin_id for item in self.twin_fit]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("visual twin fit must name every twin at most once")
        validate_sha256(self.catalog_content_hash, label="visual catalog content hash")
        for value, label, maximum_length in (
            (self.product_name, "visual product name", MAX_PRODUCT_NAME_LENGTH),
            (self.rationale, "visual rationale", MAX_VISUAL_RATIONALE_LENGTH),
        ):
            if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
                raise ValueError(f"{label} must be normalized")
        roles = dict(self.palette)
        if len(roles) != len(self.palette) or set(roles) != set(PALETTE_ROLES):
            raise ValueError("visual palette must define every role exactly once")
        if not all(is_hex_colour(value) for value in roles.values()):
            raise ValueError("visual palette colours must be lowercase hex values")
        names = dict(self.tokens)
        if len(names) != len(self.tokens):
            raise ValueError("visual tokens must be unique")
        if not names or not all(
            isinstance(name, str)
            and name.startswith(_TOKEN_PREFIX)
            and isinstance(value, str)
            and value.strip() == value
            and value
            for name, value in names.items()
        ):
            raise ValueError("visual tokens must be named CSS custom properties")
        object.__setattr__(self, "palette", tuple((role, roles[role]) for role in PALETTE_ROLES))
        object.__setattr__(self, "tokens", tuple(sorted(names.items())))

    @property
    def palette_roles(self) -> dict[str, str]:
        return dict(self.palette)

    @property
    def token_values(self) -> dict[str, str]:
        return dict(self.tokens)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "catalog_version": self.catalog_version,
            "catalog_content_hash": self.catalog_content_hash,
            "choices": self.choices.to_snapshot(),
            "product_name": self.product_name,
            "rationale": self.rationale,
            "palette": dict(self.palette),
            "tokens": dict(self.tokens),
            "twin_fit": [item.to_snapshot() for item in self.twin_fit],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def create_twin_fit(*, reference: UserTwinVersionReference, statement: str) -> TwinFit:
    return TwinFit(
        twin_id=reference.twin_id,
        name=reference.name,
        statement=normalize_required_text(
            statement, label="twin fit statement", maximum_length=MAX_TWIN_FIT_LENGTH
        ),
    )


def create_visual_language(
    *,
    choices: VisualChoices,
    product_name: str,
    rationale: str,
    twin_fit: tuple[TwinFit, ...] = (),
) -> VisualLanguage:
    palette = resolve_palette(
        choices.hue_family,
        choices.color_scheme,
        choices.color_mode,
        choices.saturation,
        choices.surface_tone,
    )
    return VisualLanguage(
        choices=choices,
        product_name=normalize_required_text(
            product_name,
            label="visual product name",
            maximum_length=MAX_PRODUCT_NAME_LENGTH,
        ),
        rationale=normalize_required_text(
            rationale,
            label="visual rationale",
            maximum_length=MAX_VISUAL_RATIONALE_LENGTH,
        ),
        palette=tuple(palette.items()),
        tokens=tuple(resolve_visual_tokens(choices).items()),
        catalog_version=VISUAL_CATALOG_VERSION,
        catalog_content_hash=VISUAL_CATALOG_CONTENT_HASH,
        twin_fit=tuple(twin_fit),
    )


def _string_mapping(value: object, *, label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    items = []
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise ValueError(f"{label} must map strings to strings")
        items.append((key, item))
    return tuple(items)


def _twin_fit(value: object) -> tuple[TwinFit, ...]:
    if not isinstance(value, list):
        raise ValueError("visual twin fit must be a list")
    items = []
    for entry in value:
        if not isinstance(entry, Mapping) or set(entry) != {"twin_id", "name", "statement"}:
            raise ValueError("visual twin fit entries need twin_id, name and statement")
        if not all(isinstance(entry[key], str) for key in ("twin_id", "name", "statement")):
            raise ValueError("visual twin fit entries must be strings")
        try:
            twin_id = UUID(str(entry["twin_id"]))
        except ValueError as error:
            raise ValueError("visual twin fit twin_id must be a UUID") from error
        items.append(
            TwinFit(twin_id=twin_id, name=str(entry["name"]), statement=str(entry["statement"]))
        )
    return tuple(items)


def visual_language_from_snapshot(payload: Mapping[str, object]) -> VisualLanguage:
    if not isinstance(payload, Mapping):
        raise ValueError("visual language snapshot must be a mapping")
    for key in (
        "catalog_version",
        "catalog_content_hash",
        "choices",
        "product_name",
        "rationale",
        "palette",
        "tokens",
        "twin_fit",
    ):
        if key not in payload:
            raise ValueError(f"visual language snapshot requires {key}")
    choices = payload["choices"]
    if not isinstance(choices, Mapping):
        raise ValueError("visual language choices must be a mapping")
    catalog_version = payload["catalog_version"]
    if type(catalog_version) is not int:
        raise ValueError("visual catalog version must be an integer")
    for key in ("catalog_content_hash", "product_name", "rationale"):
        if not isinstance(payload[key], str):
            raise ValueError(f"visual language {key} must be a string")
    language = VisualLanguage(
        choices=VisualChoices.from_snapshot(choices),
        product_name=str(payload["product_name"]),
        rationale=str(payload["rationale"]),
        palette=_string_mapping(payload["palette"], label="visual palette"),
        tokens=_string_mapping(payload["tokens"], label="visual tokens"),
        catalog_version=catalog_version,
        catalog_content_hash=str(payload["catalog_content_hash"]),
        twin_fit=_twin_fit(payload["twin_fit"]),
    )
    if language.to_snapshot() != dict(payload):
        raise ValueError("visual language snapshot is not canonical")
    return language


__all__ = [
    "MAX_PRODUCT_NAME_LENGTH",
    "MAX_TWIN_FIT_LENGTH",
    "MAX_VISUAL_RATIONALE_LENGTH",
    "TwinFit",
    "VisualLanguage",
    "create_twin_fit",
    "create_visual_language",
    "visual_language_from_snapshot",
]
