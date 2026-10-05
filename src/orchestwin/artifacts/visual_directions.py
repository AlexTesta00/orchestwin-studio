from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID

from orchestwin.artifacts.visual_catalog import (
    BackgroundTreatment,
    BorderWeight,
    CornerStyle,
    Density,
    Elevation,
    Emphasis,
    HeaderStyle,
    HeadingCase,
    HeadingWeight,
    SurfaceTone,
    TypeScale,
)
from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
)

VISUAL_DIRECTIONS_VERSION: Final = 1
DIRECTION_AXES: Final = ("layout", "shape", "type", "colour", "density")
MIN_DIRECTION_DISTANCE: Final = 4
DIRECTION_CANDIDATES: Final = 5
MAX_DIRECTION_NAME_LENGTH: Final = 60
MAX_DIRECTION_CONCEPT_LENGTH: Final = 400
MIN_DIRECTION_RULES: Final = 3
MAX_DIRECTION_RULES: Final = 5
MAX_DIRECTION_RULE_LENGTH: Final = 240
_MAX_TYPICALITY: Final = 100
_MIN_CANDIDATES: Final = 2
_MAX_CANDIDATES: Final = 20
_TEXT_COLOUR_TOKEN: Final = "--vl-color-text"
_TEXT_COLOUR: Final = f"var({_TEXT_COLOUR_TOKEN})"
_SNAPSHOT_KEYS: Final = (
    "name",
    "concept",
    "rules",
    "axes",
    "typicality",
    "candidates",
    "vocabulary_version",
)


class DirectionLayout(StrEnum):
    PANELS = "PANELS"
    BANDS = "BANDS"
    EDITORIAL = "EDITORIAL"
    STAGE = "STAGE"
    WORKBENCH = "WORKBENCH"
    MOSAIC = "MOSAIC"


class DirectionShape(StrEnum):
    ROUNDED_OUTLINE = "ROUNDED_OUTLINE"
    SQUARE_RULES = "SQUARE_RULES"
    HEAVY_FRAME = "HEAVY_FRAME"
    SOFT_FILL = "SOFT_FILL"
    PILL = "PILL"


class DirectionType(StrEnum):
    EVEN = "EVEN"
    DISPLAY = "DISPLAY"
    CAPS_LABELS = "CAPS_LABELS"
    READING = "READING"


class DirectionColour(StrEnum):
    ACCENT_ONLY = "ACCENT_ONLY"
    FIELDS = "FIELDS"
    INK = "INK"
    TINTED = "TINTED"


class DirectionDensity(StrEnum):
    COMPACT = "COMPACT"
    COMFORTABLE = "COMFORTABLE"
    SPACIOUS = "SPACIOUS"


DIRECTION_AXIS_VALUES: Final = MappingProxyType(
    {
        "layout": DirectionLayout,
        "shape": DirectionShape,
        "type": DirectionType,
        "colour": DirectionColour,
        "density": DirectionDensity,
    }
)


def _frozen(table: Mapping[Any, Any]) -> MappingProxyType[Any, Any]:
    return MappingProxyType(
        {
            key: _frozen(value) if isinstance(value, Mapping) else value
            for key, value in table.items()
        }
    )


AXIS_DEFINITIONS: Final[Mapping[str, Mapping[StrEnum, str]]] = _frozen(
    {
        "layout": {
            DirectionLayout.PANELS: (
                "a header bar, a title row and the content grouped in bordered panels arranged "
                "in a grid"
            ),
            DirectionLayout.BANDS: (
                "a stack of full-width horizontal bands, each with its own background and "
                "one purpose, without cards"
            ),
            DirectionLayout.EDITORIAL: (
                "a printed page: a masthead, one wide column and one narrow side column, groups "
                "separated by rules and white space, without cards"
            ),
            DirectionLayout.STAGE: (
                "one centred column with a single task or object at a time, large and calm, "
                "everything else small around it"
            ),
            DirectionLayout.WORKBENCH: (
                "a tool surface that uses the whole width: a slim toolbar, dense rows or tables "
                "from edge to edge, filters or details in a side column"
            ),
            DirectionLayout.MOSAIC: (
                "a grid of tiles of clearly different sizes, where the size of a tile "
                "says how much it matters"
            ),
        },
        "shape": {
            DirectionShape.ROUNDED_OUTLINE: (
                "rounded corners and thin outlines around panels and controls"
            ),
            DirectionShape.SQUARE_RULES: (
                "square corners, with thin rules above or below the groups instead of boxes "
                "around them"
            ),
            DirectionShape.HEAVY_FRAME: (
                "thick frames in the text colour and hard offset shadows without blur"
            ),
            DirectionShape.SOFT_FILL: (
                "filled surfaces without borders, told apart by their tone and by space"
            ),
            DirectionShape.PILL: (
                "pill-shaped controls, very large radii and surfaces that float on a soft shadow"
            ),
        },
        "type": {
            DirectionType.EVEN: (
                "a restrained scale: titles a little larger than the text, hierarchy from weight"
            ),
            DirectionType.DISPLAY: (
                "a very large and heavy title on every screen, four times the text size, "
                "with everything else small"
            ),
            DirectionType.CAPS_LABELS: (
                "small upper-case labels with wide tracking above their values, "
                "numbers in a monospace face aligned in columns"
            ),
            DirectionType.READING: (
                "a larger text size, a generous line height and a narrow measure, as in a book"
            ),
        },
        "colour": {
            DirectionColour.ACCENT_ONLY: (
                "neutral surfaces, with the primary colour only on the main action "
                "and on the current state"
            ),
            DirectionColour.FIELDS: (
                "large flat fields of the primary colour: whole bands, tiles or headers "
                "are filled with it"
            ),
            DirectionColour.INK: (
                "almost monochrome: text colour on the background, with the primary colour "
                "only as a small mark"
            ),
            DirectionColour.TINTED: (
                "tinted surfaces everywhere: groups sit on soft tints of the primary colour, "
                "with few borders"
            ),
        },
        "density": {
            DirectionDensity.COMPACT: "tight spacing and small controls, many rows visible at once",
            DirectionDensity.COMFORTABLE: "balanced spacing and controls of a standard height",
            DirectionDensity.SPACIOUS: "generous spacing, large controls, few things on a screen",
        },
    }
)

AXIS_BINDINGS: Final[Mapping[str, Mapping[StrEnum, Mapping[str, tuple[StrEnum, ...]]]]] = _frozen(
    {
        "layout": {
            DirectionLayout.PANELS: {"header": (HeaderStyle.COMPACT_BAR, HeaderStyle.MINIMAL)},
            DirectionLayout.BANDS: {"header": (HeaderStyle.HERO_BAND,)},
            DirectionLayout.EDITORIAL: {
                "header": (HeaderStyle.MINIMAL, HeaderStyle.CENTERED_TITLE)
            },
            DirectionLayout.STAGE: {"header": (HeaderStyle.CENTERED_TITLE, HeaderStyle.MINIMAL)},
            DirectionLayout.WORKBENCH: {"header": (HeaderStyle.COMPACT_BAR,)},
            DirectionLayout.MOSAIC: {"header": (HeaderStyle.MINIMAL, HeaderStyle.COMPACT_BAR)},
        },
        "shape": {
            DirectionShape.ROUNDED_OUTLINE: {
                "corners": (CornerStyle.SOFT, CornerStyle.ROUND),
                "borders": (BorderWeight.HAIRLINE,),
                "elevation": (Elevation.FLAT, Elevation.SUBTLE),
            },
            DirectionShape.SQUARE_RULES: {
                "corners": (CornerStyle.SHARP,),
                "borders": (BorderWeight.HAIRLINE,),
                "elevation": (Elevation.FLAT,),
            },
            DirectionShape.HEAVY_FRAME: {
                "corners": (CornerStyle.SHARP, CornerStyle.SOFT),
                "borders": (BorderWeight.BOLD,),
                "elevation": (Elevation.FLAT,),
            },
            DirectionShape.SOFT_FILL: {
                "corners": (CornerStyle.SOFT, CornerStyle.ROUND),
                "borders": (BorderWeight.NONE, BorderWeight.HAIRLINE),
                "elevation": (Elevation.FLAT,),
            },
            DirectionShape.PILL: {
                "corners": (CornerStyle.PILL,),
                "borders": (BorderWeight.NONE, BorderWeight.HAIRLINE),
                "elevation": (Elevation.SUBTLE, Elevation.RAISED),
            },
        },
        "type": {
            DirectionType.EVEN: {
                "type_scale": (TypeScale.COMPACT, TypeScale.REGULAR),
                "heading_weight": (HeadingWeight.REGULAR, HeadingWeight.SEMIBOLD),
            },
            DirectionType.DISPLAY: {
                "type_scale": (TypeScale.DISPLAY,),
                "heading_weight": (HeadingWeight.SEMIBOLD, HeadingWeight.BLACK),
                "heading_case": (HeadingCase.SENTENCE, HeadingCase.UPPERCASE),
            },
            DirectionType.CAPS_LABELS: {
                "type_scale": (TypeScale.COMPACT, TypeScale.REGULAR),
                "heading_case": (HeadingCase.UPPERCASE, HeadingCase.SMALL_CAPS),
            },
            DirectionType.READING: {
                "type_scale": (TypeScale.REGULAR, TypeScale.DISPLAY),
                "heading_case": (HeadingCase.SENTENCE,),
                "heading_weight": (HeadingWeight.REGULAR, HeadingWeight.SEMIBOLD),
            },
        },
        "colour": {
            DirectionColour.ACCENT_ONLY: {
                "emphasis": (Emphasis.RESTRAINED, Emphasis.BALANCED),
                "background": (BackgroundTreatment.PLAIN, BackgroundTreatment.GRADIENT),
            },
            DirectionColour.FIELDS: {
                "emphasis": (Emphasis.BOLD,),
                "background": (BackgroundTreatment.PLAIN,),
            },
            DirectionColour.INK: {
                "emphasis": (Emphasis.RESTRAINED,),
                "background": (BackgroundTreatment.PLAIN,),
            },
            DirectionColour.TINTED: {
                "emphasis": (Emphasis.BALANCED, Emphasis.BOLD),
                "background": (BackgroundTreatment.TINTED, BackgroundTreatment.GRADIENT),
                "surface_tone": (SurfaceTone.TINTED, SurfaceTone.WARM, SurfaceTone.COOL),
            },
        },
        "density": {
            DirectionDensity.COMPACT: {"density": (Density.COMPACT,)},
            DirectionDensity.COMFORTABLE: {"density": (Density.COMFORTABLE,)},
            DirectionDensity.SPACIOUS: {"density": (Density.SPACIOUS,)},
        },
    }
)

_AXIS_TOKENS: Final[Mapping[str, Mapping[StrEnum, Mapping[str, str]]]] = _frozen(
    {
        "layout": {
            DirectionLayout.PANELS: {"--vl-content-width": "1200px"},
            DirectionLayout.BANDS: {"--vl-content-width": "1120px"},
            DirectionLayout.EDITORIAL: {"--vl-content-width": "1080px"},
            DirectionLayout.STAGE: {"--vl-content-width": "640px"},
            DirectionLayout.WORKBENCH: {"--vl-content-width": "1600px"},
            DirectionLayout.MOSAIC: {"--vl-content-width": "1280px"},
        },
        "shape": {
            DirectionShape.ROUNDED_OUTLINE: {},
            DirectionShape.SQUARE_RULES: {
                "--vl-radius-control": "0px",
                "--vl-radius-panel": "0px",
                "--vl-border-width": "1px",
                "--vl-shadow": "none",
            },
            DirectionShape.HEAVY_FRAME: {
                "--vl-border-width": "3px",
                "--vl-shadow": f"6px 6px 0 {_TEXT_COLOUR}",
            },
            DirectionShape.SOFT_FILL: {"--vl-shadow": "none"},
            DirectionShape.PILL: {"--vl-radius-panel": "28px"},
        },
        "type": {
            DirectionType.EVEN: {"--vl-line-height-heading": "1.2"},
            DirectionType.DISPLAY: {
                "--vl-size-display": "72px",
                "--vl-size-display-narrow": "40px",
                "--vl-size-title": "22px",
                "--vl-line-height-heading": "1.02",
            },
            DirectionType.CAPS_LABELS: {
                "--vl-size-label": "12px",
                "--vl-label-tracking": "0.1em",
                "--vl-line-height-heading": "1.15",
            },
            DirectionType.READING: {
                "--vl-size-body": "18px",
                "--vl-line-height": "1.7",
                "--vl-measure": "66ch",
                "--vl-line-height-heading": "1.25",
            },
        },
        "colour": {
            DirectionColour.ACCENT_ONLY: {},
            DirectionColour.FIELDS: {},
            DirectionColour.INK: {},
            DirectionColour.TINTED: {},
        },
        "density": {
            DirectionDensity.COMPACT: {"--vl-section-gap": "24px"},
            DirectionDensity.COMFORTABLE: {"--vl-section-gap": "48px"},
            DirectionDensity.SPACIOUS: {"--vl-section-gap": "88px"},
        },
    }
)


def _axis_value(axis: str, value: object) -> StrEnum:
    expected = DIRECTION_AXIS_VALUES[axis]
    if isinstance(value, expected):
        return value
    if not isinstance(value, str) or value not in expected.__members__:
        raise ValueError(f"unknown visual direction value for {axis}: {value!r}")
    return expected(value)


@dataclass(frozen=True, slots=True)
class DirectionAxes:
    layout: DirectionLayout
    shape: DirectionShape
    type: DirectionType
    colour: DirectionColour
    density: DirectionDensity

    def __post_init__(self) -> None:
        for axis in DIRECTION_AXES:
            object.__setattr__(self, axis, _axis_value(axis, getattr(self, axis)))

    def to_snapshot(self) -> dict[str, str]:
        return {axis: getattr(self, axis).value for axis in DIRECTION_AXES}

    @classmethod
    def from_snapshot(cls, payload: Mapping[str, object]) -> DirectionAxes:
        if not isinstance(payload, Mapping) or set(payload) != set(DIRECTION_AXES):
            raise ValueError("visual direction axes require exactly " + ", ".join(DIRECTION_AXES))
        if not all(isinstance(payload[axis], str) for axis in DIRECTION_AXES):
            raise ValueError("visual direction axes must be strings")
        return cls(**{axis: payload[axis] for axis in DIRECTION_AXES})


HABITUAL_AXES: Final = DirectionAxes(
    layout=DirectionLayout.PANELS,
    shape=DirectionShape.ROUNDED_OUTLINE,
    type=DirectionType.EVEN,
    colour=DirectionColour.ACCENT_ONLY,
    density=DirectionDensity.COMFORTABLE,
)


def _require_normalized(value: object, *, label: str, maximum_length: int) -> None:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    if normalize_required_text(value, label=label, maximum_length=maximum_length) != value:
        raise ValueError(f"{label} must be normalized")


def _require_bounded(value: object, *, label: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ValueError(f"{label} must be an integer from {minimum} to {maximum}")


@dataclass(frozen=True, slots=True)
class VisualDirection:
    name: str
    concept: str
    rules: tuple[str, ...]
    axes: DirectionAxes
    typicality: int
    candidates: int
    vocabulary_version: int

    def __post_init__(self) -> None:
        _require_normalized(
            self.name, label="visual direction name", maximum_length=MAX_DIRECTION_NAME_LENGTH
        )
        _require_normalized(
            self.concept,
            label="visual direction concept",
            maximum_length=MAX_DIRECTION_CONCEPT_LENGTH,
        )
        if not isinstance(self.rules, tuple):
            raise ValueError("visual direction rules must be a tuple")
        if not MIN_DIRECTION_RULES <= len(self.rules) <= MAX_DIRECTION_RULES:
            raise ValueError(
                f"a visual direction needs {MIN_DIRECTION_RULES} to {MAX_DIRECTION_RULES} rules"
            )
        for rule in self.rules:
            _require_normalized(
                rule, label="visual direction rule", maximum_length=MAX_DIRECTION_RULE_LENGTH
            )
        if not isinstance(self.axes, DirectionAxes):
            raise ValueError("visual direction axes must be DirectionAxes")
        _require_bounded(
            self.typicality, label="visual direction typicality", minimum=0, maximum=_MAX_TYPICALITY
        )
        _require_bounded(
            self.candidates,
            label="visual direction candidates",
            minimum=_MIN_CANDIDATES,
            maximum=_MAX_CANDIDATES,
        )
        validate_positive_integer(
            self.vocabulary_version, label="visual directions vocabulary version"
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "concept": self.concept,
            "rules": list(self.rules),
            "axes": self.axes.to_snapshot(),
            "typicality": self.typicality,
            "candidates": self.candidates,
            "vocabulary_version": self.vocabulary_version,
        }

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def create_visual_direction(
    *,
    name: str,
    concept: str,
    rules: Iterable[str],
    axes: DirectionAxes,
    typicality: int,
    candidates: int,
) -> VisualDirection:
    if isinstance(rules, str):
        raise ValueError("visual direction rules must be a sequence of texts")
    return VisualDirection(
        name=normalize_required_text(
            name, label="visual direction name", maximum_length=MAX_DIRECTION_NAME_LENGTH
        ),
        concept=normalize_required_text(
            concept, label="visual direction concept", maximum_length=MAX_DIRECTION_CONCEPT_LENGTH
        ),
        rules=tuple(
            normalize_required_text(
                rule, label="visual direction rule", maximum_length=MAX_DIRECTION_RULE_LENGTH
            )
            for rule in rules
        ),
        axes=axes,
        typicality=typicality,
        candidates=candidates,
        vocabulary_version=VISUAL_DIRECTIONS_VERSION,
    )


def visual_direction_from_snapshot(payload: Mapping[str, object]) -> VisualDirection:
    if not isinstance(payload, Mapping):
        raise ValueError("visual direction snapshot must be a mapping")
    if set(payload) != set(_SNAPSHOT_KEYS):
        raise ValueError("visual direction snapshot requires exactly " + ", ".join(_SNAPSHOT_KEYS))
    rules = payload["rules"]
    if not isinstance(rules, list):
        raise ValueError("visual direction rules must be a list")
    direction = VisualDirection(
        name=payload["name"],
        concept=payload["concept"],
        rules=tuple(rules),
        axes=DirectionAxes.from_snapshot(payload["axes"]),
        typicality=payload["typicality"],
        candidates=payload["candidates"],
        vocabulary_version=payload["vocabulary_version"],
    )
    if direction.to_snapshot() != dict(payload):
        raise ValueError("visual direction snapshot is not canonical")
    return direction


def differing_axes(first: DirectionAxes, second: DirectionAxes) -> tuple[str, ...]:
    return tuple(axis for axis in DIRECTION_AXES if getattr(first, axis) != getattr(second, axis))


def direction_distance(first: DirectionAxes, second: DirectionAxes) -> int:
    return len(differing_axes(first, second))


def _eligible_pairs(
    directions: Sequence[VisualDirection],
) -> list[tuple[VisualDirection, VisualDirection]]:
    return [
        (first, second)
        for index, first in enumerate(directions)
        for second in directions[index + 1 :]
        if direction_distance(first.axes, second.axes) >= MIN_DIRECTION_DISTANCE
    ]


def _pair_key(
    pair: tuple[VisualDirection, VisualDirection], project_id: UUID
) -> tuple[int, int, str]:
    first, second = pair
    seed = (
        f"orchestwin-visual-directions-v{VISUAL_DIRECTIONS_VERSION}:"
        f"{project_id}:{first.name}:{second.name}"
    )
    return (
        -direction_distance(first.axes, second.axes),
        first.typicality + second.typicality,
        hashlib.sha256(seed.encode("utf-8")).hexdigest(),
    )


def select_directions(
    candidates: Sequence[VisualDirection],
    *,
    project_id: UUID,
    avoided: Iterable[DirectionAxes] = (),
) -> tuple[VisualDirection, VisualDirection]:
    directions = tuple(candidates)
    excluded = frozenset(avoided)
    usable = tuple(item for item in directions if item.axes not in excluded)
    pairs = _eligible_pairs(usable) or _eligible_pairs(directions)
    if not pairs:
        raise ValueError("the candidate directions are too close to each other")
    return min(pairs, key=lambda pair: _pair_key(pair, project_id))


def _bound_dimensions(direction: VisualDirection) -> dict[str, tuple[str, ...]]:
    return {
        dimension: tuple(item.value for item in values)
        for axis in DIRECTION_AXES
        for dimension, values in AXIS_BINDINGS[axis][getattr(direction.axes, axis)].items()
    }


def direction_exploration(
    base: Mapping[str, Mapping[str, Sequence[str]]],
    directions: Mapping[str, VisualDirection],
) -> dict[str, dict[str, tuple[str, ...]]]:
    exploration: dict[str, dict[str, tuple[str, ...]]] = {}
    for code, dimensions in base.items():
        explored = {name: tuple(values) for name, values in dimensions.items()}
        direction = directions.get(code)
        if direction is not None:
            explored.update(_bound_dimensions(direction))
        exploration[code] = explored
    return exploration


def direction_tokens(direction: VisualDirection, tokens: Mapping[str, str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for axis in DIRECTION_AXES:
        overrides.update(_AXIS_TOKENS[axis][getattr(direction.axes, axis)])
    if any(_TEXT_COLOUR in value for value in overrides.values()):
        text = tokens.get(_TEXT_COLOUR_TOKEN)
        if not isinstance(text, str):
            raise ValueError("the visual direction tokens need the text colour of the language")
        overrides = {name: value.replace(_TEXT_COLOUR, text) for name, value in overrides.items()}
    return overrides


def visual_directions_snapshot() -> dict[str, object]:
    return {
        "version": VISUAL_DIRECTIONS_VERSION,
        "axes": {
            axis: [item.value for item in values] for axis, values in DIRECTION_AXIS_VALUES.items()
        },
        "definitions": {
            axis: {value.value: text for value, text in texts.items()}
            for axis, texts in AXIS_DEFINITIONS.items()
        },
        "bindings": {
            axis: {
                value.value: {
                    dimension: [item.value for item in ids] for dimension, ids in bound.items()
                }
                for value, bound in values.items()
            }
            for axis, values in AXIS_BINDINGS.items()
        },
        "tokens": {
            axis: {value.value: dict(tokens) for value, tokens in values.items()}
            for axis, values in _AXIS_TOKENS.items()
        },
        "minimum_distance": MIN_DIRECTION_DISTANCE,
        "candidates": DIRECTION_CANDIDATES,
    }


VISUAL_DIRECTIONS_CONTENT_HASH: Final = snapshot_content_hash(visual_directions_snapshot())


__all__ = [
    "AXIS_BINDINGS",
    "AXIS_DEFINITIONS",
    "DIRECTION_AXES",
    "DIRECTION_AXIS_VALUES",
    "DIRECTION_CANDIDATES",
    "HABITUAL_AXES",
    "MAX_DIRECTION_CONCEPT_LENGTH",
    "MAX_DIRECTION_NAME_LENGTH",
    "MAX_DIRECTION_RULES",
    "MAX_DIRECTION_RULE_LENGTH",
    "MIN_DIRECTION_DISTANCE",
    "MIN_DIRECTION_RULES",
    "VISUAL_DIRECTIONS_CONTENT_HASH",
    "VISUAL_DIRECTIONS_VERSION",
    "DirectionAxes",
    "DirectionColour",
    "DirectionDensity",
    "DirectionLayout",
    "DirectionShape",
    "DirectionType",
    "VisualDirection",
    "create_visual_direction",
    "differing_axes",
    "direction_distance",
    "direction_exploration",
    "direction_tokens",
    "select_directions",
    "visual_direction_from_snapshot",
    "visual_directions_snapshot",
]
