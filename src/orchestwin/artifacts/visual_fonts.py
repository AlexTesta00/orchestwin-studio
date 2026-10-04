from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.visual_catalog import FontFamily, VisualChoices

FONT_PACKAGE: Final = "orchestwin.artifacts"
FONT_DIRECTORY: Final = "fonts"
FONT_LICENCE: Final = "OFL-1.1"
MONO_FALLBACK: Final = "ui-monospace, Consolas, monospace"
HEADING_TOKEN: Final = "--vl-font-heading"
BODY_TOKEN: Final = "--vl-font-body"
MONO_TOKEN: Final = "--vl-font-mono"
FONT_TOKENS: Final = (HEADING_TOKEN, BODY_TOKEN, MONO_TOKEN)
_GEIST: Final = "Geist"
_GEIST_MONO: Final = "Geist Mono"
_IBM_PLEX_MONO: Final = "IBM Plex Mono"
_LIBRE_FRANKLIN: Final = "Libre Franklin"
_LEXEND_ZETTA: Final = "Lexend Zetta"


@dataclass(frozen=True, slots=True)
class BundledFont:
    family: str
    package: str
    weights: tuple[int, ...]
    licence: str

    def file_name(self, weight: int) -> str:
        return f"{self.package}-{weight}.woff2"

    @property
    def file_names(self) -> tuple[str, ...]:
        return tuple(self.file_name(weight) for weight in self.weights)

    @property
    def licence_file(self) -> str:
        return f"{self.package}-LICENSE.txt"


BUNDLED_FONTS: Final = MappingProxyType(
    {
        font.family: font
        for font in (
            BundledFont(_GEIST, "geist", (400, 600, 800), FONT_LICENCE),
            BundledFont(_GEIST_MONO, "geist-mono", (400, 600), FONT_LICENCE),
            BundledFont(_IBM_PLEX_MONO, "ibm-plex-mono", (400, 600), FONT_LICENCE),
            BundledFont(_LIBRE_FRANKLIN, "libre-franklin", (400, 700, 900), FONT_LICENCE),
            BundledFont(_LEXEND_ZETTA, "lexend-zetta", (500, 800), FONT_LICENCE),
        )
    }
)
HEADING_FONTS: Final = MappingProxyType(
    {
        FontFamily.GEOMETRIC_SANS: _GEIST,
        FontFamily.GROTESQUE_SANS: _LIBRE_FRANKLIN,
        FontFamily.DISPLAY_HEAVY: _LIBRE_FRANKLIN,
        FontFamily.WIDE_SANS: _LEXEND_ZETTA,
    }
)
BODY_FONTS: Final = MappingProxyType(
    {FontFamily.GEOMETRIC_SANS: _GEIST, FontFamily.GROTESQUE_SANS: _LIBRE_FRANKLIN}
)
FONT_FILE_HASHES: Final = MappingProxyType(
    {
        "geist-400.woff2": "ead637fd0b6b887d829b3ce3f25fdc242b1de0cfb69c0d97987933675d1315ba",
        "geist-600.woff2": "edde7cc4e2719898f981a6d970a756030fff75a8ed36dd6a457a60181b889ebf",
        "geist-800.woff2": "4def20882cb74bf7e9cf2994058ed8d1236f6a53045cda277472bbc553714995",
        "geist-mono-400.woff2": "3f98383b122fe015a48536cd4a1cda855a201718923ffe74931a01597107b9b5",
        "geist-mono-600.woff2": "8b111a81bab818cf5393b81149c69d6a1756f3acc3a846decafef01974d12bd3",
        "ibm-plex-mono-400.woff2": (
            "3c5a451f9ec27a354b0c2bcca636c6ec17a651281aabf29f8427e210a1d31e85"
        ),
        "ibm-plex-mono-600.woff2": (
            "c4d3deb734a27e6d0dc7a6b464779f70ba1c272e26287860a14e35e85acb5b76"
        ),
        "libre-franklin-400.woff2": (
            "50a24a85106ad722ab9d1353977c1f7b3b3d18465a807c0d6f1551b57a705f41"
        ),
        "libre-franklin-700.woff2": (
            "8ef7121d145d9e99857854efd61831391e1a8b0a91ff255f18907a1f5b9d6943"
        ),
        "libre-franklin-900.woff2": (
            "f8386fc03ba814a07ec894149767443c12c0745b11cab042ae76ac66c18f2955"
        ),
        "lexend-zetta-500.woff2": (
            "f6b53a0a9ba910515be0c46530d4f14e8cbbb7f83b8995db828fe11ba2e3cd19"
        ),
        "lexend-zetta-800.woff2": (
            "3bb5466840816d0defc1079c594f62d134bd5f82cfc792af04f5ae111d4f0bbb"
        ),
    }
)


def _quoted(family: str) -> str:
    return f'"{family}"'


def bundled_font_tokens(choices: VisualChoices, tokens: Mapping[str, str]) -> dict[str, str]:
    heading = HEADING_FONTS.get(choices.heading_family)
    body = BODY_FONTS.get(choices.body_family)
    fonts: dict[str, str] = {}
    for name, family in ((HEADING_TOKEN, heading), (BODY_TOKEN, body)):
        if family is None:
            continue
        stack = tokens.get(name)
        if not isinstance(stack, str):
            raise ValueError(f"the bundled fonts need the {name} token of the language")
        fonts[name] = f"{_quoted(family)}, {stack}"
    mono = _GEIST_MONO if _GEIST in (heading, body) else _IBM_PLEX_MONO
    fonts[MONO_TOKEN] = f"{_quoted(mono)}, {MONO_FALLBACK}"
    return fonts


def bundled_families(tokens: Mapping[str, str]) -> tuple[str, ...]:
    values = [value for name in FONT_TOKENS if isinstance(value := tokens.get(name), str)]
    return tuple(
        family
        for family in BUNDLED_FONTS
        if any(value.startswith(_quoted(family)) for value in values)
    )


@cache
def _font_data(name: str) -> str:
    content = (files(FONT_PACKAGE) / FONT_DIRECTORY / name).read_bytes()
    if hashlib.sha256(content).hexdigest() != FONT_FILE_HASHES[name]:
        raise RuntimeError(f"the bundled font file {name} does not match its recorded hash")
    return base64.b64encode(content).decode("ascii")


def font_faces(tokens: Mapping[str, str]) -> str:
    return "".join(
        f"@font-face{{font-family:{_quoted(family)};font-style:normal;font-weight:{weight};"
        "font-display:swap;src:url(data:font/woff2;base64,"
        f'{_font_data(BUNDLED_FONTS[family].file_name(weight))}) format("woff2")}}'
        for family in bundled_families(tokens)
        for weight in BUNDLED_FONTS[family].weights
    )


__all__ = [
    "BODY_FONTS",
    "BODY_TOKEN",
    "BUNDLED_FONTS",
    "FONT_DIRECTORY",
    "FONT_FILE_HASHES",
    "FONT_LICENCE",
    "FONT_PACKAGE",
    "FONT_TOKENS",
    "HEADING_FONTS",
    "HEADING_TOKEN",
    "MONO_FALLBACK",
    "MONO_TOKEN",
    "BundledFont",
    "bundled_families",
    "bundled_font_tokens",
    "font_faces",
]
