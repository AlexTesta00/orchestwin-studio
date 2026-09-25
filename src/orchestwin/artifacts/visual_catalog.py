from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from enum import StrEnum
from functools import cache
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.visual_color import contrast_ratio, hue_difference, oklch_to_hex
from orchestwin.projects.requirements_primitives import canonical_json

VISUAL_CATALOG_VERSION: Final = 1
DISTINCT_VISUAL_DIMENSIONS: Final = 3
HUE_FAMILY_SEPARATION_DEGREES: Final = 30.0
CHROMA_SCALE_SEPARATION: Final = 0.3
_SOLVE_STEPS: Final = 14
_SAFETY_STEPS: Final = 40
_SAFETY_STEP_SIZE: Final = 0.005
_WHITE: Final = "#ffffff"


class LayoutArchetype(StrEnum):
    GUIDED_STEPS = "GUIDED_STEPS"
    SINGLE_CARD = "SINGLE_CARD"
    LIST_DETAIL = "LIST_DETAIL"
    DASHBOARD = "DASHBOARD"
    SPLIT_SCREEN = "SPLIT_SCREEN"
    CONVERSATIONAL = "CONVERSATIONAL"
    TABLE_FIRST = "TABLE_FIRST"
    CARD_GALLERY = "CARD_GALLERY"
    FEED_TIMELINE = "FEED_TIMELINE"
    KANBAN_BOARD = "KANBAN_BOARD"
    SEARCH_FIRST = "SEARCH_FIRST"
    FOCUS_MODE = "FOCUS_MODE"


class HueFamily(StrEnum):
    CRIMSON = "CRIMSON"
    CORAL = "CORAL"
    TERRACOTTA = "TERRACOTTA"
    AMBER = "AMBER"
    OCHRE = "OCHRE"
    OLIVE = "OLIVE"
    FOREST = "FOREST"
    EMERALD = "EMERALD"
    TEAL = "TEAL"
    OCEAN = "OCEAN"
    COBALT = "COBALT"
    INDIGO = "INDIGO"
    VIOLET = "VIOLET"
    PLUM = "PLUM"
    MAGENTA = "MAGENTA"
    ROSE = "ROSE"
    SLATE = "SLATE"
    GRAPHITE = "GRAPHITE"
    SAND = "SAND"


class ColorScheme(StrEnum):
    MONOCHROME = "MONOCHROME"
    ANALOGOUS = "ANALOGOUS"
    COMPLEMENTARY = "COMPLEMENTARY"
    TRIADIC = "TRIADIC"
    SPLIT_COMPLEMENTARY = "SPLIT_COMPLEMENTARY"
    NEUTRAL_ACCENT = "NEUTRAL_ACCENT"


class ColorMode(StrEnum):
    LIGHT = "LIGHT"
    DARK = "DARK"
    HIGH_CONTRAST_LIGHT = "HIGH_CONTRAST_LIGHT"
    HIGH_CONTRAST_DARK = "HIGH_CONTRAST_DARK"


class Saturation(StrEnum):
    MUTED = "MUTED"
    BALANCED = "BALANCED"
    VIVID = "VIVID"


class SurfaceTone(StrEnum):
    NEUTRAL = "NEUTRAL"
    TINTED = "TINTED"
    WARM = "WARM"
    COOL = "COOL"


class FontFamily(StrEnum):
    HUMANIST_SANS = "HUMANIST_SANS"
    GEOMETRIC_SANS = "GEOMETRIC_SANS"
    GROTESQUE_SANS = "GROTESQUE_SANS"
    SOFT_SANS = "SOFT_SANS"
    NARROW_SANS = "NARROW_SANS"
    WIDE_SANS = "WIDE_SANS"
    SYSTEM_UI = "SYSTEM_UI"
    TRANSITIONAL_SERIF = "TRANSITIONAL_SERIF"
    OLD_STYLE_SERIF = "OLD_STYLE_SERIF"
    MODERN_SERIF = "MODERN_SERIF"
    SLAB_SERIF = "SLAB_SERIF"
    MONOSPACE = "MONOSPACE"
    DISPLAY_HEAVY = "DISPLAY_HEAVY"
    SCRIPT = "SCRIPT"


class TypeScale(StrEnum):
    COMPACT = "COMPACT"
    REGULAR = "REGULAR"
    DISPLAY = "DISPLAY"


class HeadingCase(StrEnum):
    SENTENCE = "SENTENCE"
    UPPERCASE = "UPPERCASE"
    SMALL_CAPS = "SMALL_CAPS"


class HeadingWeight(StrEnum):
    REGULAR = "REGULAR"
    SEMIBOLD = "SEMIBOLD"
    BLACK = "BLACK"


class CornerStyle(StrEnum):
    SHARP = "SHARP"
    SOFT = "SOFT"
    ROUND = "ROUND"
    PILL = "PILL"


class Density(StrEnum):
    COMPACT = "COMPACT"
    COMFORTABLE = "COMFORTABLE"
    SPACIOUS = "SPACIOUS"


class ButtonStyle(StrEnum):
    FILLED = "FILLED"
    OUTLINED = "OUTLINED"
    SOFT = "SOFT"
    GHOST = "GHOST"


class InputStyle(StrEnum):
    BOXED = "BOXED"
    UNDERLINED = "UNDERLINED"
    FILLED = "FILLED"


class Elevation(StrEnum):
    FLAT = "FLAT"
    SUBTLE = "SUBTLE"
    RAISED = "RAISED"


class BorderWeight(StrEnum):
    NONE = "NONE"
    HAIRLINE = "HAIRLINE"
    BOLD = "BOLD"


class NavigationPattern(StrEnum):
    NONE = "NONE"
    TOP_BAR = "TOP_BAR"
    SIDE_RAIL = "SIDE_RAIL"
    TABS = "TABS"


class HeaderStyle(StrEnum):
    MINIMAL = "MINIMAL"
    COMPACT_BAR = "COMPACT_BAR"
    HERO_BAND = "HERO_BAND"
    CENTERED_TITLE = "CENTERED_TITLE"


class BackgroundTreatment(StrEnum):
    PLAIN = "PLAIN"
    TINTED = "TINTED"
    GRADIENT = "GRADIENT"
    DOTS = "DOTS"
    GRID = "GRID"
    STRIPES = "STRIPES"


class Emphasis(StrEnum):
    RESTRAINED = "RESTRAINED"
    BALANCED = "BALANCED"
    BOLD = "BOLD"


class DesignTone(StrEnum):
    ESSENTIAL = "ESSENTIAL"
    WARM = "WARM"
    INSTITUTIONAL = "INSTITUTIONAL"
    PLAYFUL = "PLAYFUL"
    TECHNICAL = "TECHNICAL"
    EDITORIAL = "EDITORIAL"
    LUXURIOUS = "LUXURIOUS"
    ENERGETIC = "ENERGETIC"
    CALM = "CALM"
    RUSTIC = "RUSTIC"
    FUTURISTIC = "FUTURISTIC"
    CLINICAL = "CLINICAL"
    ARTISANAL = "ARTISANAL"
    CIVIC = "CIVIC"


@dataclass(frozen=True, slots=True)
class ArchetypeSpec:
    label: str
    description: str
    suited_for: str
    minimum_screens: int
    maximum_screens: int
    recipe: str
    navigation: tuple[NavigationPattern, ...]
    minimum_workflow_steps: int
    minimum_information_areas: int


@dataclass(frozen=True, slots=True)
class HueSpec:
    hue: float
    chroma_scale: float
    dark_on_primary: bool


@dataclass(frozen=True, slots=True)
class ModeSpec:
    dark: bool
    high_contrast: bool
    tint: float
    background: float
    surface: float
    surface_alt: float
    border: float
    text: float
    muted: float
    primary: float
    soft: float
    accent: float
    status: float
    text_threshold: float
    ui_threshold: float


@dataclass(frozen=True, slots=True)
class FontSpec:
    stack: str
    category: str
    body_safe: bool


ARCHETYPES: Final = MappingProxyType(
    {
        LayoutArchetype.GUIDED_STEPS: ArchetypeSpec(
            "Guided steps",
            "One step per screen with visible progress and a final confirmation",
            "sequential tasks with several inputs or decisions",
            3,
            4,
            "SCR-001 and SCR-002 are DEFAULT step screens, each with a HEADING naming the step, "
            "one to three labelled inputs and a BUTTON to the next screen; the last screen is "
            "SUCCESS with a summary CARD and a return LINK to SCR-001.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR),
            3,
            1,
        ),
        LayoutArchetype.SINGLE_CARD: ArchetypeSpec(
            "Single card",
            "One focused card holding the whole task and its result",
            "one short task with few inputs",
            2,
            3,
            "SCR-001 is DEFAULT with a HEADING, the task inputs and one primary BUTTON to "
            "SCR-002; SCR-002 is SUCCESS with a STATUS confirmation, an illustrative result "
            "and a return action to SCR-001.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR),
            1,
            1,
        ),
        LayoutArchetype.LIST_DETAIL: ArchetypeSpec(
            "List and detail",
            "A list of items beside the detail or the form of one item",
            "collections that are browsed, opened and edited",
            2,
            4,
            "SCR-001 is DEFAULT and lists the items as LIST elements, one item per element, "
            "with a BUTTON or LINK to the detail or insert screen; SCR-002 is DEFAULT and shows "
            "one item's fields or the insert form with a BUTTON to the final screen; the final "
            "screen is SUCCESS and returns to SCR-001.",
            (NavigationPattern.TOP_BAR, NavigationPattern.SIDE_RAIL, NavigationPattern.TABS),
            2,
            2,
        ),
        LayoutArchetype.DASHBOARD: ArchetypeSpec(
            "Dashboard",
            "An overview of status tiles and summaries with quick actions",
            "monitoring, totals and recurring checks",
            2,
            4,
            "SCR-001 is DEFAULT and opens with two to four STATUS or CARD tiles carrying example "
            "figures, a LIST of recent items and a primary BUTTON to the action screen; SCR-002 "
            "is DEFAULT with the action form; the final screen is SUCCESS with the updated tile "
            "and a return action.",
            (NavigationPattern.TOP_BAR, NavigationPattern.SIDE_RAIL, NavigationPattern.TABS),
            1,
            2,
        ),
        LayoutArchetype.SPLIT_SCREEN: ArchetypeSpec(
            "Split screen",
            "Inputs on one side and the live result on the other",
            "calculators, converters and configurators",
            2,
            3,
            "SCR-001 is DEFAULT with the inputs and a BUTTON followed by a CARD that shows an "
            "example result; SCR-002 is SUCCESS with the confirmed result as STATUS and a "
            "return action.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR),
            1,
            2,
        ),
        LayoutArchetype.CONVERSATIONAL: ArchetypeSpec(
            "Conversational",
            "A dialogue where every request and answer is a message",
            "assistants, guided intake and help desks",
            2,
            3,
            "SCR-001 is DEFAULT and shows two to four TEXT messages alternating the person and "
            "the system, then a TEXT_INPUT composer with a send BUTTON; SCR-002 is SUCCESS with "
            "the concluding message as STATUS and a LINK to start again.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR),
            2,
            1,
        ),
        LayoutArchetype.TABLE_FIRST: ArchetypeSpec(
            "Table first",
            "A data table with filters and row actions",
            "records, registers and inventories",
            2,
            4,
            "SCR-001 is DEFAULT and starts with a HEADING naming the register, three to six LIST "
            "elements each holding one row with its columns separated by ' · ', and a BUTTON to "
            "add a record; SCR-002 is DEFAULT with the record form; the final screen is SUCCESS.",
            (NavigationPattern.TOP_BAR, NavigationPattern.SIDE_RAIL, NavigationPattern.TABS),
            1,
            2,
        ),
        LayoutArchetype.CARD_GALLERY: ArchetypeSpec(
            "Card gallery",
            "A grid of cards, one per item, opening into a detail",
            "catalogues, media and products",
            2,
            4,
            "SCR-001 is DEFAULT with a HEADING and three to six CARD elements each describing "
            "one item, plus a LINK or BUTTON to the detail screen; SCR-002 is DEFAULT with the "
            "detail and an action BUTTON; the final screen is SUCCESS.",
            (NavigationPattern.TOP_BAR, NavigationPattern.SIDE_RAIL, NavigationPattern.TABS),
            1,
            2,
        ),
        LayoutArchetype.FEED_TIMELINE: ArchetypeSpec(
            "Feed and timeline",
            "A chronological stream of entries with a composer on top",
            "logs, journals, activity and notices",
            2,
            3,
            "SCR-001 is DEFAULT with a composer made of a TEXT_INPUT and a BUTTON followed by "
            "three to five CARD entries each starting with a time or date; SCR-002 is SUCCESS "
            "showing the new entry confirmed with a return action.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR, NavigationPattern.TABS),
            1,
            1,
        ),
        LayoutArchetype.KANBAN_BOARD: ArchetypeSpec(
            "Kanban board",
            "Columns of cards that move through stages",
            "tasks, requests and pipelines",
            2,
            3,
            "SCR-001 is DEFAULT with one HEADING per column, two or three columns, each followed "
            "by its CARD items, and a BUTTON to add an item; SCR-002 is DEFAULT with the add "
            "form; the final screen is SUCCESS.",
            (NavigationPattern.TOP_BAR, NavigationPattern.SIDE_RAIL),
            2,
            2,
        ),
        LayoutArchetype.SEARCH_FIRST: ArchetypeSpec(
            "Search first",
            "A prominent search box with the results underneath",
            "lookups, directories and finding one item quickly",
            2,
            3,
            "SCR-001 is DEFAULT and opens with a HEADING, a TEXT_INPUT query field, a search "
            "BUTTON and LIST suggestions; the following screen lists the results as CARD "
            "elements with a LINK back; the final screen is SUCCESS.",
            (NavigationPattern.NONE, NavigationPattern.TOP_BAR, NavigationPattern.TABS),
            1,
            1,
        ),
        LayoutArchetype.FOCUS_MODE: ArchetypeSpec(
            "Focus mode",
            "One question or action at a time on an uncluttered screen",
            "people under pressure, small screens and low familiarity with software",
            2,
            4,
            "SCR-001 and every following DEFAULT screen carry one HEADING, at most one input "
            "and one BUTTON; the final screen is SUCCESS with a single STATUS line and a "
            "return action.",
            (NavigationPattern.NONE,),
            2,
            1,
        ),
    }
)

HUES: Final = MappingProxyType(
    {
        HueFamily.CRIMSON: HueSpec(20, 1.0, False),
        HueFamily.CORAL: HueSpec(35, 1.0, False),
        HueFamily.TERRACOTTA: HueSpec(50, 0.9, False),
        HueFamily.AMBER: HueSpec(70, 1.0, True),
        HueFamily.OCHRE: HueSpec(90, 0.9, True),
        HueFamily.OLIVE: HueSpec(115, 0.7, True),
        HueFamily.FOREST: HueSpec(145, 0.8, False),
        HueFamily.EMERALD: HueSpec(160, 0.9, False),
        HueFamily.TEAL: HueSpec(185, 0.9, False),
        HueFamily.OCEAN: HueSpec(220, 1.0, False),
        HueFamily.COBALT: HueSpec(255, 1.0, False),
        HueFamily.INDIGO: HueSpec(275, 1.0, False),
        HueFamily.VIOLET: HueSpec(300, 1.0, False),
        HueFamily.PLUM: HueSpec(320, 0.9, False),
        HueFamily.MAGENTA: HueSpec(340, 1.0, False),
        HueFamily.ROSE: HueSpec(355, 0.9, False),
        HueFamily.SLATE: HueSpec(250, 0.35, False),
        HueFamily.GRAPHITE: HueSpec(60, 0.06, False),
        HueFamily.SAND: HueSpec(75, 0.35, True),
    }
)

MODES: Final = MappingProxyType(
    {
        ColorMode.LIGHT: ModeSpec(
            False,
            False,
            0.012,
            0.985,
            0.997,
            0.955,
            0.90,
            0.28,
            0.50,
            0.55,
            0.94,
            0.60,
            0.50,
            4.5,
            3.0,
        ),
        ColorMode.DARK: ModeSpec(
            True,
            False,
            0.02,
            0.21,
            0.26,
            0.31,
            0.40,
            0.95,
            0.76,
            0.74,
            0.34,
            0.78,
            0.76,
            4.5,
            3.0,
        ),
        ColorMode.HIGH_CONTRAST_LIGHT: ModeSpec(
            False,
            True,
            0.005,
            1.0,
            1.0,
            0.96,
            0.50,
            0.15,
            0.34,
            0.42,
            0.93,
            0.44,
            0.40,
            7.0,
            4.5,
        ),
        ColorMode.HIGH_CONTRAST_DARK: ModeSpec(
            True,
            True,
            0.012,
            0.08,
            0.14,
            0.20,
            0.62,
            0.99,
            0.86,
            0.84,
            0.28,
            0.86,
            0.85,
            7.0,
            4.5,
        ),
    }
)

SATURATION_CHROMA: Final = MappingProxyType(
    {Saturation.MUTED: 0.055, Saturation.BALANCED: 0.11, Saturation.VIVID: 0.19}
)

STATUS_CHROMA_SCALE: Final = MappingProxyType(
    {Saturation.MUTED: 0.6, Saturation.BALANCED: 1.0, Saturation.VIVID: 1.3}
)

SCHEME_ACCENT_OFFSET: Final = MappingProxyType(
    {
        ColorScheme.MONOCHROME: 0.0,
        ColorScheme.ANALOGOUS: 35.0,
        ColorScheme.COMPLEMENTARY: 180.0,
        ColorScheme.TRIADIC: 120.0,
        ColorScheme.SPLIT_COMPLEMENTARY: 150.0,
        ColorScheme.NEUTRAL_ACCENT: 0.0,
    }
)

SURFACE_HUES: Final = MappingProxyType({SurfaceTone.WARM: 75.0, SurfaceTone.COOL: 250.0})
SUCCESS_HUE: Final = 150.0
DANGER_HUE: Final = 28.0
STATUS_CHROMA: Final = 0.11

FONTS: Final = MappingProxyType(
    {
        FontFamily.HUMANIST_SANS: FontSpec(
            '"Segoe UI", "Helvetica Neue", "Noto Sans", Arial, sans-serif', "sans", True
        ),
        FontFamily.GEOMETRIC_SANS: FontSpec(
            '"Century Gothic", "Avenir Next", Avenir, "Trebuchet MS", "URW Gothic", sans-serif',
            "sans",
            True,
        ),
        FontFamily.GROTESQUE_SANS: FontSpec(
            'Arial, Helvetica, "Liberation Sans", "Nimbus Sans", sans-serif', "sans", True
        ),
        FontFamily.SOFT_SANS: FontSpec(
            'Candara, Optima, "Gill Sans", "Segoe UI", "Noto Sans", sans-serif', "sans", True
        ),
        FontFamily.NARROW_SANS: FontSpec(
            'Bahnschrift, "Arial Narrow", "Helvetica Neue Condensed", "Franklin Gothic Medium", '
            '"Roboto Condensed", sans-serif',
            "sans",
            True,
        ),
        FontFamily.WIDE_SANS: FontSpec(
            'Verdana, Tahoma, "DejaVu Sans", Geneva, sans-serif', "sans", True
        ),
        FontFamily.SYSTEM_UI: FontSpec(
            'system-ui, -apple-system, "Segoe UI Variable", "Segoe UI", Roboto, sans-serif',
            "sans",
            True,
        ),
        FontFamily.TRANSITIONAL_SERIF: FontSpec(
            'Georgia, "Times New Roman", Times, "Liberation Serif", serif', "serif", True
        ),
        FontFamily.OLD_STYLE_SERIF: FontSpec(
            'Garamond, "EB Garamond", "Palatino Linotype", Palatino, "Book Antiqua", '
            '"Hoefler Text", serif',
            "serif",
            True,
        ),
        FontFamily.MODERN_SERIF: FontSpec(
            'Didot, "Bodoni MT", "Bodoni 72", Constantia, Cambria, Georgia, serif',
            "serif",
            False,
        ),
        FontFamily.SLAB_SERIF: FontSpec(
            'Rockwell, "Rockwell Nova", "Roboto Slab", "Zilla Slab", "Sitka Heading", Cambria, '
            "serif",
            "serif",
            True,
        ),
        FontFamily.MONOSPACE: FontSpec(
            '"Cascadia Code", Consolas, "SF Mono", Menlo, "DejaVu Sans Mono", "Courier New", '
            "monospace",
            "mono",
            False,
        ),
        FontFamily.DISPLAY_HEAVY: FontSpec(
            '"Arial Black", "Franklin Gothic Heavy", Impact, "Helvetica Neue", sans-serif',
            "display",
            False,
        ),
        FontFamily.SCRIPT: FontSpec(
            '"Segoe Script", "Snell Roundhand", "Brush Script MT", "Apple Chancery", cursive',
            "script",
            False,
        ),
    }
)

SCRIPT_TONES: Final = frozenset(
    {
        DesignTone.PLAYFUL,
        DesignTone.ARTISANAL,
        DesignTone.LUXURIOUS,
        DesignTone.WARM,
        DesignTone.RUSTIC,
    }
)
DISPLAY_TONES: Final = frozenset(
    {
        DesignTone.ENERGETIC,
        DesignTone.PLAYFUL,
        DesignTone.FUTURISTIC,
        DesignTone.EDITORIAL,
        DesignTone.CIVIC,
    }
)
MONOSPACE_BODY_TONES: Final = frozenset(
    {DesignTone.TECHNICAL, DesignTone.FUTURISTIC, DesignTone.CLINICAL}
)
HIGH_CONTRAST_BUTTONS: Final = frozenset({ButtonStyle.FILLED, ButtonStyle.OUTLINED})

TYPE_SCALES: Final = MappingProxyType(
    {
        TypeScale.COMPACT: ("14px", "20px", "26px", "1.45"),
        TypeScale.REGULAR: ("16px", "24px", "32px", "1.55"),
        TypeScale.DISPLAY: ("17px", "30px", "44px", "1.6"),
    }
)
HEADING_CASES: Final = MappingProxyType(
    {
        HeadingCase.SENTENCE: ("none", "normal", "0"),
        HeadingCase.UPPERCASE: ("uppercase", "normal", "0.08em"),
        HeadingCase.SMALL_CAPS: ("none", "small-caps", "0.04em"),
    }
)
HEADING_WEIGHTS: Final = MappingProxyType(
    {HeadingWeight.REGULAR: "500", HeadingWeight.SEMIBOLD: "700", HeadingWeight.BLACK: "900"}
)
CORNERS: Final = MappingProxyType(
    {
        CornerStyle.SHARP: ("2px", "4px"),
        CornerStyle.SOFT: ("8px", "12px"),
        CornerStyle.ROUND: ("14px", "20px"),
        CornerStyle.PILL: ("999px", "24px"),
    }
)
DENSITIES: Final = MappingProxyType(
    {
        Density.COMPACT: ("6px", "10px", "36px"),
        Density.COMFORTABLE: ("10px", "16px", "44px"),
        Density.SPACIOUS: ("14px", "24px", "52px"),
    }
)
BORDER_WIDTHS: Final = MappingProxyType(
    {BorderWeight.NONE: "0px", BorderWeight.HAIRLINE: "1px", BorderWeight.BOLD: "2px"}
)
SHADOWS: Final = MappingProxyType(
    {
        Elevation.FLAT: ("none", "none"),
        Elevation.SUBTLE: ("0 1px 2px rgba(0, 0, 0, 0.06)", "0 1px 3px rgba(0, 0, 0, 0.5)"),
        Elevation.RAISED: ("0 12px 32px rgba(0, 0, 0, 0.14)", "0 12px 32px rgba(0, 0, 0, 0.6)"),
    }
)

PALETTE_ROLES: Final = (
    "background",
    "surface",
    "surface_alt",
    "border",
    "text",
    "text_muted",
    "primary",
    "on_primary",
    "primary_soft",
    "accent",
    "on_accent",
    "success",
    "success_soft",
    "danger",
    "danger_soft",
)


@dataclass(frozen=True, slots=True)
class VisualChoices:
    archetype: LayoutArchetype
    hue_family: HueFamily
    color_scheme: ColorScheme
    color_mode: ColorMode
    saturation: Saturation
    surface_tone: SurfaceTone
    heading_family: FontFamily
    body_family: FontFamily
    type_scale: TypeScale
    heading_case: HeadingCase
    heading_weight: HeadingWeight
    corners: CornerStyle
    density: Density
    buttons: ButtonStyle
    inputs: InputStyle
    elevation: Elevation
    borders: BorderWeight
    navigation: NavigationPattern
    header: HeaderStyle
    background: BackgroundTreatment
    emphasis: Emphasis
    tone: DesignTone

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            expected = VISUAL_DIMENSIONS[field.name]
            if not isinstance(value, expected):
                object.__setattr__(self, field.name, expected(value))
        validate_visual_choices(self)

    def to_snapshot(self) -> dict[str, str]:
        return {name: getattr(self, name).value for name in VISUAL_DIMENSION_NAMES}

    @classmethod
    def from_snapshot(cls, payload) -> VisualChoices:
        values = {}
        for name, expected in VISUAL_DIMENSIONS.items():
            if name not in payload:
                raise ValueError(f"visual choices require {name}")
            raw = payload[name]
            if not isinstance(raw, str) or raw not in expected.__members__:
                raise ValueError(f"unknown visual choice for {name}: {raw!r}")
            values[name] = expected(raw)
        unknown = set(payload) - set(values)
        if unknown:
            raise ValueError(f"unknown visual choice dimensions: {sorted(unknown)}")
        return cls(**values)


VISUAL_DIMENSIONS: Final = MappingProxyType(
    {
        "archetype": LayoutArchetype,
        "hue_family": HueFamily,
        "color_scheme": ColorScheme,
        "color_mode": ColorMode,
        "saturation": Saturation,
        "surface_tone": SurfaceTone,
        "heading_family": FontFamily,
        "body_family": FontFamily,
        "type_scale": TypeScale,
        "heading_case": HeadingCase,
        "heading_weight": HeadingWeight,
        "corners": CornerStyle,
        "density": Density,
        "buttons": ButtonStyle,
        "inputs": InputStyle,
        "elevation": Elevation,
        "borders": BorderWeight,
        "navigation": NavigationPattern,
        "header": HeaderStyle,
        "background": BackgroundTreatment,
        "emphasis": Emphasis,
        "tone": DesignTone,
    }
)
VISUAL_DIMENSION_NAMES: Final = tuple(VISUAL_DIMENSIONS)


def validate_visual_choices(choices: VisualChoices) -> None:
    archetype = ARCHETYPES[choices.archetype]
    mode = MODES[choices.color_mode]
    if choices.navigation not in archetype.navigation:
        raise ValueError(
            f"navigation {choices.navigation.value} is not available for {choices.archetype.value}"
        )
    body = FONTS[choices.body_family]
    if not body.body_safe and not (
        choices.body_family is FontFamily.MONOSPACE and choices.tone in MONOSPACE_BODY_TONES
    ):
        raise ValueError(f"{choices.body_family.value} is not readable as a body family")
    if choices.heading_family is FontFamily.SCRIPT:
        if choices.tone not in SCRIPT_TONES:
            raise ValueError("script headings require a playful, artisanal or warm tone")
        if choices.heading_case is not HeadingCase.SENTENCE:
            raise ValueError("script headings keep sentence case")
    if choices.heading_family is FontFamily.DISPLAY_HEAVY and choices.tone not in DISPLAY_TONES:
        raise ValueError("heavy display headings require an energetic, playful or civic tone")
    if mode.high_contrast:
        if choices.buttons not in HIGH_CONTRAST_BUTTONS:
            raise ValueError("high contrast modes require filled or outlined buttons")
        if choices.borders is BorderWeight.NONE:
            raise ValueError("high contrast modes require visible borders")
        if FontFamily.SCRIPT in (choices.heading_family, choices.body_family):
            raise ValueError("high contrast modes exclude script typefaces")


def visual_differences(first: VisualChoices, second: VisualChoices) -> tuple[str, ...]:
    return tuple(
        name for name in VISUAL_DIMENSION_NAMES if getattr(first, name) is not getattr(second, name)
    )


def hue_families_are_distinct(first: HueFamily, second: HueFamily) -> bool:
    if first is second:
        return False
    first_spec, second_spec = HUES[first], HUES[second]
    return (
        hue_difference(first_spec.hue, second_spec.hue) >= HUE_FAMILY_SEPARATION_DEGREES
        or abs(first_spec.chroma_scale - second_spec.chroma_scale) >= CHROMA_SCALE_SEPARATION
    )


def require_distinct_visual_choices(choices: Sequence[VisualChoices]) -> None:
    for index, first in enumerate(choices):
        for second in choices[index + 1 :]:
            if first.archetype is second.archetype:
                raise ValueError("design alternatives must use different layout archetypes")
            if not hue_families_are_distinct(first.hue_family, second.hue_family):
                raise ValueError("design alternatives must use clearly different hue families")
            further = [
                name
                for name in visual_differences(first, second)
                if name not in ("archetype", "hue_family")
            ]
            if len(further) < DISTINCT_VISUAL_DIMENSIONS:
                raise ValueError(
                    "design alternatives must differ in at least "
                    f"{DISTINCT_VISUAL_DIMENSIONS} further visual dimensions"
                )


def _satisfies(colour: str, references: Iterable[tuple[str, float]]) -> bool:
    return all(contrast_ratio(colour, other) >= threshold for other, threshold in references)


def _solve(
    start: float,
    chroma: float,
    hue: float,
    references: tuple[tuple[str, float], ...],
    darker: bool,
) -> str:
    if _satisfies(oklch_to_hex(start, chroma, hue), references):
        return oklch_to_hex(start, chroma, hue)
    extreme = 0.0 if darker else 1.0
    if not _satisfies(oklch_to_hex(extreme, chroma, hue), references):
        return oklch_to_hex(extreme, chroma, hue)
    low, high = (extreme, start) if darker else (start, extreme)
    for _ in range(_SOLVE_STEPS):
        middle = (low + high) / 2
        if _satisfies(oklch_to_hex(middle, chroma, hue), references):
            if darker:
                low = middle
            else:
                high = middle
        elif darker:
            high = middle
        else:
            low = middle
    level = low if darker else high
    for _ in range(_SAFETY_STEPS):
        if _satisfies(oklch_to_hex(level, chroma, hue), references):
            break
        level += -_SAFETY_STEP_SIZE if darker else _SAFETY_STEP_SIZE
    return oklch_to_hex(level, chroma, hue)


def _surface_hue(hue_family: HueFamily, surface_tone: SurfaceTone) -> float:
    if surface_tone in SURFACE_HUES:
        return SURFACE_HUES[surface_tone]
    return HUES[hue_family].hue


@cache
def resolve_palette(
    hue_family: HueFamily,
    color_scheme: ColorScheme,
    color_mode: ColorMode,
    saturation: Saturation,
    surface_tone: SurfaceTone,
) -> dict[str, str]:
    hue_spec = HUES[hue_family]
    mode = MODES[color_mode]
    hue = hue_spec.hue
    primary_chroma = SATURATION_CHROMA[saturation] * hue_spec.chroma_scale
    surface_hue = _surface_hue(hue_family, surface_tone)
    surface_chroma = 0.0 if surface_tone is SurfaceTone.NEUTRAL else mode.tint
    text_chroma = 0.0 if surface_tone is SurfaceTone.NEUTRAL else mode.tint * 1.5
    text_threshold = mode.text_threshold
    ui_threshold = mode.ui_threshold
    background = oklch_to_hex(mode.background, surface_chroma, surface_hue)
    surface = oklch_to_hex(mode.surface, surface_chroma * 0.5, surface_hue)
    surface_alt = oklch_to_hex(mode.surface_alt, surface_chroma, surface_hue)
    surfaces = (
        (background, text_threshold),
        (surface, text_threshold),
        (surface_alt, text_threshold),
    )
    text = _solve(mode.text, text_chroma, surface_hue, surfaces, not mode.dark)
    text_muted = _solve(mode.muted, text_chroma, surface_hue, surfaces, not mode.dark)
    border = oklch_to_hex(mode.border, surface_chroma, surface_hue)
    if mode.high_contrast:
        border = _solve(
            mode.border, surface_chroma, surface_hue, ((background, ui_threshold),), not mode.dark
        )
    primary, on_primary = _solve_emphasis(
        hue, primary_chroma, mode, background, hue_spec.dark_on_primary, mode.primary
    )
    primary_soft = _solve(
        mode.soft,
        min(primary_chroma, 0.05),
        hue,
        ((text, text_threshold),),
        mode.dark,
    )
    accent_hue = (hue + SCHEME_ACCENT_OFFSET[color_scheme]) % 360
    accent_chroma = 0.012 if color_scheme is ColorScheme.NEUTRAL_ACCENT else primary_chroma * 0.9
    accent, on_accent = _solve_emphasis(
        accent_hue, accent_chroma, mode, background, False, mode.accent
    )
    status_chroma = STATUS_CHROMA * STATUS_CHROMA_SCALE[saturation]
    status_references = ((background, text_threshold), (surface, text_threshold))
    success = _solve(mode.status, status_chroma, SUCCESS_HUE, status_references, not mode.dark)
    danger = _solve(mode.status, status_chroma, DANGER_HUE, status_references, not mode.dark)
    success_soft = _solve(mode.soft, 0.05, SUCCESS_HUE, ((success, text_threshold),), mode.dark)
    danger_soft = _solve(mode.soft, 0.05, DANGER_HUE, ((danger, text_threshold),), mode.dark)
    return {
        "background": background,
        "surface": surface,
        "surface_alt": surface_alt,
        "border": border,
        "text": text,
        "text_muted": text_muted,
        "primary": primary,
        "on_primary": on_primary,
        "primary_soft": primary_soft,
        "accent": accent,
        "on_accent": on_accent,
        "success": success,
        "success_soft": success_soft,
        "danger": danger,
        "danger_soft": danger_soft,
    }


def _solve_emphasis(
    hue: float,
    chroma: float,
    mode: ModeSpec,
    background: str,
    dark_on_emphasis: bool,
    start: float,
) -> tuple[str, str]:
    if mode.dark:
        ink = oklch_to_hex(0.16, min(chroma, 0.03), hue)
        colour = _solve(
            start,
            chroma,
            hue,
            ((ink, mode.text_threshold), (background, mode.ui_threshold)),
            False,
        )
        return colour, ink
    if dark_on_emphasis and not mode.high_contrast:
        ink = oklch_to_hex(0.13, min(chroma, 0.02), hue)
        colour = _solve(0.72, chroma, hue, ((background, mode.ui_threshold),), True)
        if contrast_ratio(ink, colour) >= mode.text_threshold:
            return colour, ink
    colour = _solve(
        start,
        chroma,
        hue,
        ((_WHITE, mode.text_threshold), (background, mode.ui_threshold)),
        True,
    )
    return colour, _WHITE


def resolve_typography(choices: VisualChoices) -> dict[str, str]:
    return {
        "heading_stack": FONTS[choices.heading_family].stack,
        "body_stack": FONTS[choices.body_family].stack,
    }


def resolve_visual_tokens(choices: VisualChoices) -> dict[str, str]:
    palette = resolve_palette(
        choices.hue_family,
        choices.color_scheme,
        choices.color_mode,
        choices.saturation,
        choices.surface_tone,
    )
    typography = resolve_typography(choices)
    body_size, title_size, display_size, line_height = TYPE_SCALES[choices.type_scale]
    transform, variant, tracking = HEADING_CASES[choices.heading_case]
    control_radius, panel_radius = CORNERS[choices.corners]
    space, gap, control_height = DENSITIES[choices.density]
    light_shadow, dark_shadow = SHADOWS[choices.elevation]
    tokens = {f"--vl-color-{role.replace('_', '-')}": palette[role] for role in PALETTE_ROLES}
    tokens.update(
        {
            "--vl-font-heading": typography["heading_stack"],
            "--vl-font-body": typography["body_stack"],
            "--vl-heading-weight": HEADING_WEIGHTS[choices.heading_weight],
            "--vl-heading-transform": transform,
            "--vl-heading-variant": variant,
            "--vl-heading-tracking": tracking,
            "--vl-size-body": body_size,
            "--vl-size-title": title_size,
            "--vl-size-display": display_size,
            "--vl-line-height": line_height,
            "--vl-space": space,
            "--vl-gap": gap,
            "--vl-control-height": control_height,
            "--vl-radius-control": control_radius,
            "--vl-radius-panel": panel_radius,
            "--vl-border-width": BORDER_WIDTHS[choices.borders],
            "--vl-shadow": dark_shadow if MODES[choices.color_mode].dark else light_shadow,
        }
    )
    return tokens


def _fit_clause(spec: ArchetypeSpec) -> str:
    clause = ""
    if spec.minimum_workflow_steps > 1:
        clause += f", a workflow of at least {spec.minimum_workflow_steps} steps"
    if spec.minimum_information_areas > 1:
        clause += f", at least {spec.minimum_information_areas} information areas"
    return clause


def visual_catalog_summary() -> str:
    lines = [
        f"Visual catalog version {VISUAL_CATALOG_VERSION}. Every alternative sets one value per "
        "dimension; every id below is exact.",
        "archetype (layout; the mockup follows its recipe): "
        + "; ".join(
            f"{key.value} = {spec.label}, for {spec.suited_for}, navigation "
            + "/".join(item.value for item in spec.navigation)
            + _fit_clause(spec)
            for key, spec in ARCHETYPES.items()
        )
        + ".",
        "Colour: hue_family, color_scheme, color_mode, saturation and surface_tone are resolved "
        "into a verified palette; DARK and HIGH_CONTRAST modes are real options, not defaults. "
        "Typography: heading_family and body_family, with type_scale, heading_case and "
        "heading_weight, from "
        + ", ".join(f"{key.value} ({spec.category})" for key, spec in FONTS.items())
        + ". Body families must be readable: never SCRIPT, DISPLAY_HEAVY or MODERN_SERIF; "
        "MONOSPACE bodies only with TECHNICAL, FUTURISTIC or CLINICAL tones. SCRIPT headings "
        "only with PLAYFUL, ARTISANAL, LUXURIOUS, WARM or RUSTIC tones and SENTENCE case; "
        "DISPLAY_HEAVY headings only with ENERGETIC, PLAYFUL, FUTURISTIC, EDITORIAL or CIVIC "
        "tones. Shape and structure: corners, density, buttons, inputs, elevation, borders, "
        "header, background, emphasis and tone follow the schema enums; navigation must be one "
        "listed for the chosen archetype. "
        "HIGH_CONTRAST modes require FILLED or OUTLINED buttons, visible borders and no SCRIPT. "
        "Alternatives must use different archetypes, different hue families and differ in at "
        f"least {DISTINCT_VISUAL_DIMENSIONS} further dimensions; hue families closer than "
        f"{HUE_FAMILY_SEPARATION_DEGREES:.0f} degrees count as the same family unless one of "
        "them is SLATE, GRAPHITE or SAND.",
    ]
    return " ".join(" ".join(line.split()) for line in lines)


def visual_catalog_snapshot() -> dict[str, object]:
    return {
        "version": VISUAL_CATALOG_VERSION,
        "dimensions": {
            name: [item.value for item in enum] for name, enum in VISUAL_DIMENSIONS.items()
        },
        "archetypes": {
            key.value: {
                "label": spec.label,
                "description": spec.description,
                "suited_for": spec.suited_for,
                "minimum_screens": spec.minimum_screens,
                "maximum_screens": spec.maximum_screens,
                "recipe": spec.recipe,
                "navigation": [item.value for item in spec.navigation],
                "minimum_workflow_steps": spec.minimum_workflow_steps,
                "minimum_information_areas": spec.minimum_information_areas,
            }
            for key, spec in ARCHETYPES.items()
        },
        "hues": {
            key.value: {
                "hue": spec.hue,
                "chroma_scale": spec.chroma_scale,
                "dark_on_primary": spec.dark_on_primary,
            }
            for key, spec in HUES.items()
        },
        "modes": {
            key.value: {field.name: getattr(spec, field.name) for field in fields(spec)}
            for key, spec in MODES.items()
        },
        "saturation_chroma": {key.value: value for key, value in SATURATION_CHROMA.items()},
        "scheme_accent_offset": {key.value: value for key, value in SCHEME_ACCENT_OFFSET.items()},
        "fonts": {
            key.value: {
                "stack": spec.stack,
                "category": spec.category,
                "body_safe": spec.body_safe,
            }
            for key, spec in FONTS.items()
        },
        "type_scales": {key.value: list(value) for key, value in TYPE_SCALES.items()},
        "corners": {key.value: list(value) for key, value in CORNERS.items()},
        "densities": {key.value: list(value) for key, value in DENSITIES.items()},
        "palette_roles": list(PALETTE_ROLES),
    }


def visual_catalog_content_hash() -> str:
    return hashlib.sha256(canonical_json(visual_catalog_snapshot()).encode("utf-8")).hexdigest()


VISUAL_CATALOG_CONTENT_HASH: Final = visual_catalog_content_hash()


__all__ = [
    "ARCHETYPES",
    "CHROMA_SCALE_SEPARATION",
    "DISTINCT_VISUAL_DIMENSIONS",
    "FONTS",
    "HUES",
    "HUE_FAMILY_SEPARATION_DEGREES",
    "MODES",
    "PALETTE_ROLES",
    "VISUAL_CATALOG_CONTENT_HASH",
    "VISUAL_CATALOG_VERSION",
    "VISUAL_DIMENSIONS",
    "VISUAL_DIMENSION_NAMES",
    "ArchetypeSpec",
    "BackgroundTreatment",
    "BorderWeight",
    "ButtonStyle",
    "ColorMode",
    "ColorScheme",
    "CornerStyle",
    "Density",
    "DesignTone",
    "Elevation",
    "Emphasis",
    "FontFamily",
    "FontSpec",
    "HeaderStyle",
    "HeadingCase",
    "HeadingWeight",
    "HueFamily",
    "HueSpec",
    "InputStyle",
    "LayoutArchetype",
    "ModeSpec",
    "NavigationPattern",
    "Saturation",
    "SurfaceTone",
    "TypeScale",
    "VisualChoices",
    "hue_families_are_distinct",
    "require_distinct_visual_choices",
    "resolve_palette",
    "resolve_typography",
    "resolve_visual_tokens",
    "validate_visual_choices",
    "visual_catalog_content_hash",
    "visual_catalog_snapshot",
    "visual_catalog_summary",
    "visual_differences",
]
