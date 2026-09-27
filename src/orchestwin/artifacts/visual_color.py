from __future__ import annotations

import math
from typing import Final

_HEX_DIGITS: Final = frozenset("0123456789abcdef")
_GAMUT_TOLERANCE: Final = 1e-6
_GAMUT_STEPS: Final = 20


def parse_hex(value: str) -> tuple[float, float, float]:
    text = value.strip().lower()
    if len(text) != 7 or text[0] != "#" or any(ch not in _HEX_DIGITS for ch in text[1:]):
        raise ValueError(f"invalid hex colour: {value!r}")
    return (
        int(text[1:3], 16) / 255,
        int(text[3:5], 16) / 255,
        int(text[5:7], 16) / 255,
    )


def format_hex(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(min(1.0, max(0.0, channel)) * 255):02x}" for channel in rgb)


def is_hex_colour(value: object) -> bool:
    try:
        parse_hex(str(value))
    except ValueError:
        return False
    return isinstance(value, str) and value == value.strip().lower()


def _to_linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _to_gamma(channel: float) -> float:
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * channel ** (1 / 2.4) - 0.055


def relative_luminance(hex_value: str) -> float:
    red, green, blue = (_to_linear(channel) for channel in parse_hex(hex_value))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def oklab_to_linear_srgb(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    long_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    medium_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    short_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    long_cone = long_**3
    medium_cone = medium_**3
    short_cone = short_**3
    return (
        4.0767416621 * long_cone - 3.3077115913 * medium_cone + 0.2309699292 * short_cone,
        -1.2684380046 * long_cone + 2.6097574011 * medium_cone - 0.3413193965 * short_cone,
        -0.0041960863 * long_cone - 0.7034186147 * medium_cone + 1.7076147010 * short_cone,
    )


def linear_srgb_to_oklab(red: float, green: float, blue: float) -> tuple[float, float, float]:
    long_cone = 0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue
    medium_cone = 0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue
    short_cone = 0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue
    long_, medium_, short_ = (
        math.copysign(abs(value) ** (1 / 3), value)
        for value in (long_cone, medium_cone, short_cone)
    )
    return (
        0.2104542553 * long_ + 0.7936177850 * medium_ - 0.0040720468 * short_,
        1.9779984951 * long_ - 2.4285922050 * medium_ + 0.4505937099 * short_,
        0.0259040371 * long_ + 0.7827717662 * medium_ - 0.8086757660 * short_,
    )


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    return all(-_GAMUT_TOLERANCE <= channel <= 1 + _GAMUT_TOLERANCE for channel in rgb)


def _oklch_to_linear(
    lightness: float, chroma: float, hue_degrees: float
) -> tuple[float, float, float]:
    radians = math.radians(hue_degrees)
    return oklab_to_linear_srgb(lightness, chroma * math.cos(radians), chroma * math.sin(radians))


def oklch_to_hex(lightness: float, chroma: float, hue_degrees: float) -> str:
    level = min(1.0, max(0.0, lightness))
    rgb = _oklch_to_linear(level, chroma, hue_degrees)
    if not _in_gamut(rgb):
        low, high = 0.0, chroma
        for _ in range(_GAMUT_STEPS):
            middle = (low + high) / 2
            if _in_gamut(_oklch_to_linear(level, middle, hue_degrees)):
                low = middle
            else:
                high = middle
        rgb = _oklch_to_linear(level, low, hue_degrees)
    return format_hex(tuple(_to_gamma(min(1.0, max(0.0, channel))) for channel in rgb))


def hex_to_oklab(hex_value: str) -> tuple[float, float, float]:
    return linear_srgb_to_oklab(*(_to_linear(channel) for channel in parse_hex(hex_value)))


def colour_distance(first: str, second: str) -> float:
    return math.dist(hex_to_oklab(first), hex_to_oklab(second))


def hue_difference(first_degrees: float, second_degrees: float) -> float:
    delta = abs(first_degrees - second_degrees) % 360
    return min(delta, 360 - delta)


__all__ = [
    "colour_distance",
    "contrast_ratio",
    "format_hex",
    "hex_to_oklab",
    "hue_difference",
    "is_hex_colour",
    "linear_srgb_to_oklab",
    "oklab_to_linear_srgb",
    "oklch_to_hex",
    "parse_hex",
    "relative_luminance",
]
