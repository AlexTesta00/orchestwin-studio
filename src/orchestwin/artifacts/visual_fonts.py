from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
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


class BundledFamily(StrEnum):
    GEIST = "Geist"
    GEIST_MONO = "Geist Mono"
    IBM_PLEX_MONO = "IBM Plex Mono"
    LIBRE_FRANKLIN = "Libre Franklin"
    LEXEND_ZETTA = "Lexend Zetta"
    SOURCE_SANS_3 = "Source Sans 3"
    NUNITO = "Nunito"
    ARCHIVO_NARROW = "Archivo Narrow"
    SOURCE_SERIF_4 = "Source Serif 4"
    LORA = "Lora"
    PLAYFAIR_DISPLAY = "Playfair Display"
    ZILLA_SLAB = "Zilla Slab"
    BRICOLAGE_GROTESQUE = "Bricolage Grotesque"
    CAVEAT = "Caveat"


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
        family: BundledFont(family, package, weights, FONT_LICENCE)
        for family, package, weights in (
            (BundledFamily.GEIST, "geist", (400, 600, 800)),
            (BundledFamily.GEIST_MONO, "geist-mono", (400, 600)),
            (BundledFamily.IBM_PLEX_MONO, "ibm-plex-mono", (400, 600)),
            (BundledFamily.LIBRE_FRANKLIN, "libre-franklin", (400, 700, 900)),
            (BundledFamily.LEXEND_ZETTA, "lexend-zetta", (500, 800)),
            (BundledFamily.SOURCE_SANS_3, "source-sans-3", (400, 600, 700)),
            (BundledFamily.NUNITO, "nunito", (400, 700, 900)),
            (BundledFamily.ARCHIVO_NARROW, "archivo-narrow", (400, 700)),
            (BundledFamily.SOURCE_SERIF_4, "source-serif-4", (400, 600, 700)),
            (BundledFamily.LORA, "lora", (400, 600, 700)),
            (BundledFamily.PLAYFAIR_DISPLAY, "playfair-display", (400, 700, 900)),
            (BundledFamily.ZILLA_SLAB, "zilla-slab", (400, 600, 700)),
            (BundledFamily.BRICOLAGE_GROTESQUE, "bricolage-grotesque", (400, 700, 800)),
            (BundledFamily.CAVEAT, "caveat", (500, 700)),
        )
    }
)
HEADING_FONTS: Final = MappingProxyType(
    {
        FontFamily.HUMANIST_SANS: BundledFamily.SOURCE_SANS_3,
        FontFamily.GEOMETRIC_SANS: BundledFamily.GEIST,
        FontFamily.GROTESQUE_SANS: BundledFamily.LIBRE_FRANKLIN,
        FontFamily.SOFT_SANS: BundledFamily.NUNITO,
        FontFamily.NARROW_SANS: BundledFamily.ARCHIVO_NARROW,
        FontFamily.WIDE_SANS: BundledFamily.LEXEND_ZETTA,
        FontFamily.TRANSITIONAL_SERIF: BundledFamily.SOURCE_SERIF_4,
        FontFamily.OLD_STYLE_SERIF: BundledFamily.LORA,
        FontFamily.MODERN_SERIF: BundledFamily.PLAYFAIR_DISPLAY,
        FontFamily.SLAB_SERIF: BundledFamily.ZILLA_SLAB,
        FontFamily.MONOSPACE: BundledFamily.GEIST_MONO,
        FontFamily.DISPLAY_HEAVY: BundledFamily.BRICOLAGE_GROTESQUE,
        FontFamily.SCRIPT: BundledFamily.CAVEAT,
    }
)
BODY_FONTS: Final = MappingProxyType(
    {
        **HEADING_FONTS,
        FontFamily.WIDE_SANS: BundledFamily.GEIST,
        FontFamily.MODERN_SERIF: BundledFamily.LORA,
        FontFamily.MONOSPACE: BundledFamily.IBM_PLEX_MONO,
        FontFamily.DISPLAY_HEAVY: BundledFamily.LIBRE_FRANKLIN,
        FontFamily.SCRIPT: BundledFamily.NUNITO,
    }
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
        "source-sans-3-400.woff2": (
            "0f73f35e08cde0a2f10c109c6e01d71459d97e4099ecd9a50f1b6c0209e4de2b"
        ),
        "source-sans-3-600.woff2": (
            "14527d193b0e30bc32ef931549a246cdfd286573bb12869b7e052b8101a39d38"
        ),
        "source-sans-3-700.woff2": (
            "ae35266f2ab0d5314ff9a04127931eb26c793e4f1269bb240046d4d2db4b7bb1"
        ),
        "nunito-400.woff2": "a5906e15ceb68f73d3b2c2076b4057c3f6ed401186d56283b45ce12944ca0735",
        "nunito-700.woff2": "fa89300b9bbb3bd0f60d6991aa055965d98e2ccca27bf8688fe0c39cdc796846",
        "nunito-900.woff2": "9ca32f5d8334579387361096944286df451272a557bb09bd906254a623aba99e",
        "archivo-narrow-400.woff2": (
            "50e835187413b9d25833ccd7c9638673e64112aafd64004f48fc613ace27e354"
        ),
        "archivo-narrow-700.woff2": (
            "062eae97e718b8a39ff5861d08046755eaf4c6f27f9a0fe861116d9d1305d6bf"
        ),
        "source-serif-4-400.woff2": (
            "02194deb92d3975dd30e11a3824a1f1db32b48c93654e60560cb81ce8e7b5f95"
        ),
        "source-serif-4-600.woff2": (
            "f2b7e1cf1d277b7608231868135648f8ad8e2b58d8e97ca088bee15dc357bee7"
        ),
        "source-serif-4-700.woff2": (
            "7691c51bc286a9014db0048277d2c3f2ad0a90b533dc8adfb16cb22a95390d39"
        ),
        "lora-400.woff2": "ac079950fd9885261c0f73d9e87233f31b5427333ce0eb20e26c119458493c40",
        "lora-600.woff2": "7bbfe9f3c9e9d6d07e17da4d5229a42b042cc2e16024993cb687dc08cc762557",
        "lora-700.woff2": "c05fd5289492ed310ed882259b944ca5287e76e572a65d92d3941f9f44f0342a",
        "playfair-display-400.woff2": (
            "1fe9ad5d8b2ebd8ecb8fbd05bed1e3fdfa52dae3f1a04e1c219918442fe9394d"
        ),
        "playfair-display-700.woff2": (
            "28453852ea165c47b5a941be00e418402e1407002ed87507f062a1e316328fe6"
        ),
        "playfair-display-900.woff2": (
            "2772c56b28bec10f310634732b0554dd6cced8ad0f723bbdf73f6abc53829ad0"
        ),
        "zilla-slab-400.woff2": "ab2607313bc04e82a53aca235853a0b83463e99b3ae88b17cc963e371f8fe91c",
        "zilla-slab-600.woff2": "fd78ed94061d91a141bf6be05559398e21a3d8aab8f7e21594d434573fcf3305",
        "zilla-slab-700.woff2": "896b6ebb8cd10aca90bdff88a5a1b648cbc0d50751740bd5a6d012007aef9ebe",
        "bricolage-grotesque-400.woff2": (
            "826772cb1251f09b4c9d76fc6266993d67b03507bee337ea2eac0fb3e0879de3"
        ),
        "bricolage-grotesque-700.woff2": (
            "4c373ce3c1cca41c864eb3e27c059a59fc6310547ab9c9b6cd780d387ba24206"
        ),
        "bricolage-grotesque-800.woff2": (
            "3e1b5f0a56ee995b7c1445bc54e6ec98c5dffb585ef5c4baf86731cf68e27c61"
        ),
        "caveat-500.woff2": "edbfb1a768829d4e85127cd327e59faaec9701cb043e96430938f1f66acf009f",
        "caveat-700.woff2": "15f9638095ad5ec9816f93d66805ca1a87e71dc5a76b596bfce1c78d4704c405",
    }
)


def _quoted(family: str) -> str:
    return f'"{family}"'


def bundled_font_tokens(
    choices: VisualChoices, tokens: Mapping[str, str], pair: tuple[str, str] | None = None
) -> dict[str, str]:
    if pair is None:
        heading = HEADING_FONTS.get(choices.heading_family)
        body = BODY_FONTS.get(choices.body_family)
    else:
        heading, body = (BundledFamily(family) for family in pair)
    fonts: dict[str, str] = {}
    for name, family in ((HEADING_TOKEN, heading), (BODY_TOKEN, body)):
        if family is None:
            continue
        stack = tokens.get(name)
        if not isinstance(stack, str):
            raise ValueError(f"the bundled fonts need the {name} token of the language")
        fonts[name] = f"{_quoted(family)}, {stack}"
    mono = (
        BundledFamily.GEIST_MONO
        if BundledFamily.GEIST in (heading, body)
        else BundledFamily.IBM_PLEX_MONO
    )
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
    "BundledFamily",
    "BundledFont",
    "bundled_families",
    "bundled_font_tokens",
    "font_faces",
]
