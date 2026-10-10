from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.visual_color import colour_distance
from orchestwin.artifacts.visual_directions import (
    DirectionAxes,
    DirectionColour,
    DirectionDensity,
    DirectionLayout,
    DirectionShape,
    DirectionType,
    VisualDirection,
    create_visual_direction,
)

DESIGN_SYSTEM_ENV: Final = "ORCHESTWIN_DESIGN_SYSTEM"
MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH: Final = 2800
SYSTEM_COLOUR_TOLERANCE: Final = 0.02
SYSTEM_ALTERNATIVE_CODE: Final = "DES-003"
SYSTEM_DIRECTION_CANDIDATES: Final = 2
NEUTRAL_ROLES: Final = ("background", "surface", "surface_alt", "border", "text", "text_muted")


@dataclass(frozen=True, slots=True)
class SystemDirection:
    name: str
    concept: str
    rules: tuple[str, ...]
    axes: DirectionAxes
    typicality: int


@dataclass(frozen=True, slots=True)
class DesignSystem:
    identifier: str
    name: str
    instruction: str
    palette_text: str
    direction: SystemDirection
    tokens: Mapping[str, str] = field(hash=False)
    font_pair: tuple[str, str]
    system_colours: Mapping[str, str] = field(hash=False)
    neutral_light: Mapping[str, str] = field(hash=False)
    neutral_dark: Mapping[str, str] = field(hash=False)


def _listed(values: Iterable[str], conjunction: str) -> str:
    items = list(values)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" {conjunction} " + items[-1]


def _palette_text(
    light: Mapping[str, str],
    dark: Mapping[str, str],
    font_pair: tuple[str, str],
) -> str:
    heading, body = font_pair
    code = SYSTEM_ALTERNATIVE_CODE
    return (
        f"A design system is active, context.design_system names it, and {code} follows it in "
        f"its direction, its palette and its type pair; for {code} the system prevails over the "
        f"paragraph above. The primary and the accent of {code} are two different colours of "
        "context.design_system.colours, each written exactly as it is listed there, blue "
        f"included; its {_listed(NEUTRAL_ROLES, 'and')} are the neutral colours of the system, "
        f"{_listed((light[role] for role in NEUTRAL_ROLES), 'and')} in the light modes and "
        f"{_listed((dark[role] for role in NEUTRAL_ROLES), 'and')} in the dark modes; its "
        f"type_pair is {heading} for the heading and {body} for the body. The Studio refuses any "
        f"other primary, accent or type pair for {code}. The other two alternatives follow only "
        "their own directions and the paragraph above, never the colours or the type pair of the "
        "system, and the primaries of the three alternatives differ clearly from each other."
    )


_APPLE_INSTRUCTION: Final = (
    "This system prevails over the look described above wherever the two disagree, never over "
    "the technical contract. Content first, few familiar controls, hierarchy from type and "
    "space. Phone (390): a top bar (back chevron, up to two icon actions), a left-aligned large "
    "title, content, and a floating tab bar at the bottom with 3-5 filled icons over one-word "
    "labels. Desktop (1280): a top toolbar (title leading, actions and search trailing), "
    "optional sidebar instead of tabs, content at most var(--vl-content-width) wide. Bars are "
    "glass: color-mix(in srgb, var(--vl-color-surface) 72%, transparent) with backdrop-filter: "
    "saturate(180%) blur(20px); no glass inside content. Lists are grouped: rounded "
    "var(--vl-color-surface) sections (panel radius) on the var(--vl-color-background) grouped "
    "background, rows min 44px, 0.5px separators inset to the text, small muted section "
    "headers, trailing chevron for drill-down. One prominent action per view: a capsule filled "
    "with var(--vl-color-primary), its semibold label in var(--vl-color-on-primary) starting "
    "with a verb (Title Case only in English); other buttons are var(--vl-color-primary) text "
    "or var(--vl-color-surface-alt) capsules of the same height. Colour is sparse and "
    "meaningful: var(--vl-color-primary) only on interactive elements and selection, "
    "var(--vl-color-danger) only for destructive actions, var(--vl-color-text) text with "
    "var(--vl-color-text-muted) secondary lines, never colour alone. Line icons (filled only in "
    "the tab bar) as inline SVG, same weight as the adjacent text and centred on it; never copy "
    "Apple-licensed SF Symbols. Large images with rounded corners, never stretched. 8px grid, "
    "generous white space, aligned leading edges, page margins 16px at 390 and 32px at 1280. "
    "Large titles use var(--vl-size-display), var(--vl-size-display-narrow) below 720px; titles "
    "var(--vl-size-title) in semibold; labels var(--vl-size-label); capsules have a 999px "
    "radius and targets are at least 44x44px. Corners are generously rounded everywhere: cards, "
    "pictures, fields and sheets use the panel radius, buttons and chips are capsules. No "
    "gradients, textures or ornaments; one soft shadow, var(--vl-shadow), only on floating "
    "panels. Dark mode mirrors light, no shadows. Honour prefers-reduced-motion."
)
_APPLE_DIRECTION: Final = SystemDirection(
    name="Apple Human Interface Guidelines",
    concept=(
        "The interface of a native Apple app: content first, grouped lists on a quiet background, "
        "glass bars and one prominent capsule action on every view. It suits people who expect "
        "the calm and familiar behaviour of the apps on their own phone."
    ),
    rules=(
        "Every screen opens with a large title aligned to the leading edge, under a glass bar "
        "with a back chevron and at most two icon actions.",
        "Content sits in rounded grouped sections on the grouped background, with rows of at "
        "least 44 pixels and thin separators inset to the text.",
        "The one prominent action of a view is a filled capsule in the primary colour; colour "
        "appears only on interactive elements and on the current selection.",
    ),
    axes=DirectionAxes(
        layout=DirectionLayout.PANELS,
        shape=DirectionShape.SOFT_FILL,
        type=DirectionType.EVEN,
        colour=DirectionColour.ACCENT_ONLY,
        density=DirectionDensity.COMFORTABLE,
    ),
    typicality=50,
)
_APPLE_TOKENS: Final = MappingProxyType(
    {
        "--vl-size-display": "40px",
        "--vl-size-display-narrow": "34px",
        "--vl-size-title": "28px",
        "--vl-size-body": "17px",
        "--vl-size-label": "13px",
        "--vl-line-height": "1.47",
        "--vl-line-height-heading": "1.2",
        "--vl-space": "8px",
        "--vl-radius-control": "12px",
        "--vl-radius-panel": "20px",
        "--vl-shadow": "0 1px 2px rgba(0,0,0,.08), 0 8px 24px rgba(0,0,0,.08)",
        "--vl-section-gap": "24px",
        "--vl-heading-weight": "700",
        "--vl-heading-transform": "none",
        "--vl-heading-variant": "normal",
        "--vl-heading-tracking": "-0.01em",
        "--vl-content-width": "1100px",
    }
)
_APPLE_FONTS: Final = ("Geist", "Geist")
_APPLE_COLOURS: Final = MappingProxyType(
    {
        "blue": "#0088ff",
        "green": "#34c759",
        "indigo": "#6155f5",
        "orange": "#ff8d28",
        "pink": "#ff2d55",
        "purple": "#cb30e0",
        "red": "#ff383c",
        "teal": "#00c3d0",
        "yellow": "#ffcc00",
    }
)
_APPLE_LIGHT: Final = MappingProxyType(
    {
        "background": "#f2f2f7",
        "surface": "#ffffff",
        "surface_alt": "#e5e5ea",
        "border": "#c6c6c8",
        "text": "#000000",
        "text_muted": "#636366",
    }
)
_APPLE_DARK: Final = MappingProxyType(
    {
        "background": "#000000",
        "surface": "#1c1c1e",
        "surface_alt": "#2c2c2e",
        "border": "#38383a",
        "text": "#ffffff",
        "text_muted": "#98989f",
    }
)

APPLE_HIG: Final = DesignSystem(
    identifier="apple-hig",
    name="Apple Human Interface Guidelines",
    instruction=_APPLE_INSTRUCTION,
    palette_text=_palette_text(_APPLE_LIGHT, _APPLE_DARK, _APPLE_FONTS),
    direction=_APPLE_DIRECTION,
    tokens=_APPLE_TOKENS,
    font_pair=_APPLE_FONTS,
    system_colours=_APPLE_COLOURS,
    neutral_light=_APPLE_LIGHT,
    neutral_dark=_APPLE_DARK,
)
DESIGN_SYSTEMS: Final = MappingProxyType({APPLE_HIG.identifier: APPLE_HIG})


def design_system(identifier: str | None) -> DesignSystem | None:
    if identifier is None:
        return None
    system = DESIGN_SYSTEMS.get(identifier)
    if system is None:
        raise ValueError("unknown design system, expected one of: " + ", ".join(DESIGN_SYSTEMS))
    return system


def design_system_view(system: DesignSystem) -> dict[str, object]:
    heading, body = system.font_pair
    return {
        "name": system.name,
        "alternative_code": SYSTEM_ALTERNATIVE_CODE,
        "colours": dict(system.system_colours),
        "font_pair": {"heading": heading, "body": body},
    }


def system_direction(system: DesignSystem) -> VisualDirection:
    direction = system.direction
    return create_visual_direction(
        name=direction.name,
        concept=direction.concept,
        rules=direction.rules,
        axes=direction.axes,
        typicality=direction.typicality,
        candidates=SYSTEM_DIRECTION_CANDIDATES,
    )


def context_design_system(context: Mapping[str, object]) -> DesignSystem | None:
    view = context.get("design_system")
    if view is None:
        return None
    name = view.get("name") if isinstance(view, Mapping) else None
    for system in DESIGN_SYSTEMS.values():
        if system.name == name:
            return system
    raise ValueError("the context names an unknown design system")


def is_system_colour(system: DesignSystem, colour: str) -> bool:
    return any(
        colour_distance(colour, value) <= SYSTEM_COLOUR_TOLERANCE
        for value in system.system_colours.values()
    )


__all__ = [
    "APPLE_HIG",
    "DESIGN_SYSTEMS",
    "DESIGN_SYSTEM_ENV",
    "MAX_DESIGN_SYSTEM_INSTRUCTION_LENGTH",
    "NEUTRAL_ROLES",
    "SYSTEM_ALTERNATIVE_CODE",
    "SYSTEM_COLOUR_TOLERANCE",
    "SYSTEM_DIRECTION_CANDIDATES",
    "DesignSystem",
    "SystemDirection",
    "context_design_system",
    "design_system",
    "design_system_view",
    "is_system_colour",
    "system_direction",
]
