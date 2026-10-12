from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.visual_color import (
    hex_to_oklab,
    hue_difference,
    parse_hex,
    relative_luminance,
)


@dataclass(frozen=True, slots=True)
class NamedColour:
    hex: str
    italian: tuple[str, ...]
    english: tuple[str, ...]
    shades: tuple[str, ...] = ()


NAMED_COLOURS: Final = MappingProxyType(
    {
        "red": NamedColour(
            "#FF0000",
            ("rosso", "rossa", "rossi", "rosse"),
            ("red",),
            ("#FF3B30", "#FF383C", "#DC143C"),
        ),
        "orange": NamedColour(
            "#FFA500", ("arancione", "arancioni", "arancio"), ("orange",), ("#FF9500", "#FF8D28")
        ),
        "yellow": NamedColour(
            "#FFFF00", ("giallo", "gialla", "gialli", "gialle"), ("yellow",), ("#FFCC00",)
        ),
        "green": NamedColour("#008000", ("verde", "verdi"), ("green",), ("#34C759",)),
        "teal": NamedColour(
            "#008080",
            ("turchese", "turchesi", "ciano"),
            ("teal", "turquoise", "cyan"),
            ("#30B0C7", "#00C3D0"),
        ),
        "blue": NamedColour(
            "#0000FF",
            ("blu", "azzurro", "azzurra", "azzurri", "azzurre", "celeste", "celesti"),
            ("blue", "light blue"),
            ("#007AFF", "#0088FF", "#5AC8FA"),
        ),
        "purple": NamedColour("#800080", ("viola",), ("purple", "violet"), ("#AF52DE", "#CB30E0")),
        "pink": NamedColour("#FFC0CB", ("rosa",), ("pink",), ("#FF2D55", "#FF1493", "#FF69B4")),
        "brown": NamedColour("#8B4513", ("marrone", "marroni"), ("brown",)),
        "grey": NamedColour("#808080", ("grigio", "grigia", "grigi", "grigie"), ("grey", "gray")),
        "black": NamedColour("#000000", ("nero", "nera", "neri", "nere"), ("black",)),
        "white": NamedColour("#FFFFFF", ("bianco", "bianca", "bianchi", "bianche"), ("white",)),
    }
)
COLOUR_NAME_KEYS: Final = tuple(NAMED_COLOURS)
_BLACK_LUMINANCE: Final = 0.04
_WHITE_LUMINANCE: Final = 0.9
_GREY_SATURATION: Final = 0.12
_PINK_LIGHTNESS: Final = 0.75
_MUTED_CHROMA: Final = 0.09
_MUTED_LIGHTNESS: Final = 0.8
_DARK_LIGHTNESS: Final = 0.55
_RULED: Final = frozenset({"brown", "grey", "black", "white"})
_WARM: Final = frozenset({"red", "orange"})
_HEX: Final = re.compile(r"#(?:[0-9a-f]{6}|[0-9a-f]{3})", re.IGNORECASE)


def _lch(value: str) -> tuple[float, float, float]:
    lightness, a, b = hex_to_oklab(value)
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


_HUES: Final = MappingProxyType(
    {
        key: tuple(_lch(shade)[2] for shade in (entry.hex, *entry.shades))
        for key, entry in NAMED_COLOURS.items()
        if key not in _RULED
    }
)
_WORDS: Final = MappingProxyType(
    {
        word: entry.hex
        for entry in NAMED_COLOURS.values()
        for word in (*entry.italian, *entry.english)
    }
)
_MENTION: Final = re.compile(
    r"\b(?:"
    + "|".join(
        r"\s+".join(map(re.escape, word.split())) for word in sorted(_WORDS, key=len, reverse=True)
    )
    + r")\b|"
    + _HEX.pattern
    + r"\b",
    re.IGNORECASE,
)


def _full_hex(value: str) -> str:
    if not isinstance(value, str) or _HEX.fullmatch(value) is None:
        raise ValueError(f"invalid hex colour: {value!r}")
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    return "#" + digits.upper()


def _family_name(family: str, lightness: float, chroma: float) -> str:
    if family == "red" and lightness >= _PINK_LIGHTNESS:
        return "pink"
    muted = chroma < _MUTED_CHROMA and lightness < _MUTED_LIGHTNESS
    if (family in _WARM and muted) or (family == "orange" and lightness < _DARK_LIGHTNESS):
        return "brown"
    return family


def colour_name_key(value: str) -> str:
    colour = _full_hex(value)
    channels = parse_hex(colour)
    luminance = relative_luminance(colour)
    if luminance < _BLACK_LUMINANCE:
        return "black"
    if max(channels) - min(channels) < _GREY_SATURATION:
        return "white" if luminance > _WHITE_LUMINANCE else "grey"
    lightness, chroma, hue = _lch(colour)
    family = min(_HUES, key=lambda key: min(hue_difference(hue, anchor) for anchor in _HUES[key]))
    return _family_name(family, lightness, chroma)


def named_colours_in(text: str) -> tuple[tuple[str, str], ...]:
    found: dict[str, str] = {}
    for match in _MENTION.finditer(text):
        written = match.group()
        colour = (
            _full_hex(written)
            if written.startswith("#")
            else _WORDS[" ".join(written.lower().split())]
        )
        found.setdefault(colour, written)
    return tuple((written, colour) for colour, written in found.items())


__all__ = [
    "COLOUR_NAME_KEYS",
    "NAMED_COLOURS",
    "NamedColour",
    "colour_name_key",
    "named_colours_in",
]
