from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Final
from xml.etree import ElementTree

ICON_PACKAGE: Final = "orchestwin.artifacts"
ICON_DIRECTORY: Final = "icons"
ICON_LICENCE: Final = "ISC"
MANIFEST_FILE: Final = "MANIFEST.json"
MANIFEST_HASH: Final = "55a5986828eaf1d33434484d41346a771c68f5d1741515a4dcbb84c2fe618226"
ICON_NAME: Final = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
MAX_ICON_NAME_LENGTH: Final = 48
FALLBACK_ICON: Final = "circle"
FALLBACK_PICTURE: Final = "image"
ICON_VIEWBOX: Final = "0 0 24 24"
ICON_ATTRIBUTES: Final = (
    ("viewbox", ICON_VIEWBOX),
    ("fill", "none"),
    ("stroke", "currentColor"),
    ("stroke-width", "2"),
    ("stroke-linecap", "round"),
    ("stroke-linejoin", "round"),
)
ICON_ELEMENTS: Final = frozenset(
    {"path", "circle", "rect", "line", "polyline", "polygon", "ellipse"}
)
PICTURE_VIEWBOX: Final = "0 0 400 300"
PICTURE_ASPECT: Final = "xMidYMid slice"
PICTURE_TONES: Final = ("primary", "accent", "neutral", "success", "danger")
DEFAULT_PICTURE_TONE: Final = "primary"
PICTURE_COLOURS: Final = MappingProxyType(
    {
        "primary": "primary",
        "accent": "accent",
        "neutral": "text-muted",
        "success": "success",
        "danger": "danger",
    }
)
_SVG: Final = "{http://www.w3.org/2000/svg}"
_SUFFIX: Final = ".svg"
_DIGEST: Final = re.compile(r"[0-9a-f]{64}")
_BLANK: Final = " \t\n\r"


def _read(name: str) -> bytes:
    return (files(ICON_PACKAGE) / ICON_DIRECTORY / name).read_bytes()


def _named(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_ICON_NAME_LENGTH
        and ICON_NAME.fullmatch(value) is not None
    )


@cache
def _manifest() -> Mapping[str, str]:
    try:
        content = _read(MANIFEST_FILE)
    except FileNotFoundError as error:
        raise RuntimeError("the icons are not bundled") from error
    if hashlib.sha256(content).hexdigest() != MANIFEST_HASH:
        raise RuntimeError("the icon manifest does not match its recorded hash")
    try:
        manifest = json.loads(content.decode("utf-8"))
    except ValueError as error:
        raise RuntimeError("the icon manifest cannot be read") from error
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, dict) or not entries or manifest.get("licence") != ICON_LICENCE:
        raise RuntimeError("the icon manifest cannot be read")
    digests: dict[str, str] = {}
    for file_name, digest in entries.items():
        name = file_name.removesuffix(_SUFFIX)
        if (
            not file_name.endswith(_SUFFIX)
            or not _named(name)
            or not isinstance(digest, str)
            or _DIGEST.fullmatch(digest) is None
        ):
            raise RuntimeError("the icon manifest names a file that is not an icon")
        digests[name] = digest
    return MappingProxyType(digests)


@cache
def icon_names() -> tuple[str, ...]:
    return tuple(sorted(_manifest()))


def is_bundled_icon(value: object) -> bool:
    return _named(value) and value in _manifest()


def _broken(name: str) -> RuntimeError:
    return RuntimeError(f"the bundled icon {name} is not a plain line drawing")


def _drawing(name: str, content: bytes) -> str:
    from orchestwin.artifacts.generated_mockups import (
        SVG_ATTRIBUTES,
        GeneratedMockupError,
        MarkupElement,
        parse_markup,
        serialize_markup,
    )

    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as error:
        raise _broken(name) from error
    frame = {key.lower(): value for key, value in root.attrib.items()}
    if (
        root.tag != f"{_SVG}svg"
        or (root.text or "").strip(_BLANK)
        or any(frame.get(key) != value for key, value in ICON_ATTRIBUTES)
    ):
        raise _broken(name)
    shapes: list[MarkupElement] = []
    for child in root:
        tag = child.tag.removeprefix(_SVG) if child.tag.startswith(_SVG) else ""
        if (
            tag not in ICON_ELEMENTS
            or len(child)
            or (child.text or "").strip(_BLANK)
            or (child.tail or "").strip(_BLANK)
            or not child.attrib.keys() <= SVG_ATTRIBUTES
        ):
            raise _broken(name)
        shapes.append(MarkupElement(tag, tuple(sorted(child.attrib.items())), ()))
    body = serialize_markup(shapes)
    try:
        parse_markup(f"<svg>{body}</svg>", screen_code=name, screen_codes=())
    except GeneratedMockupError as error:
        raise _broken(name) from error
    return body


@cache
def icon_body(name: str) -> str:
    digest = _manifest().get(name) if _named(name) else None
    if digest is None:
        raise KeyError(name)
    try:
        content = _read(name + _SUFFIX)
    except FileNotFoundError as error:
        raise RuntimeError(f"the bundled icon {name} is missing") from error
    if hashlib.sha256(content).hexdigest() != digest:
        raise RuntimeError(f"the bundled icon {name} does not match its recorded hash")
    return _drawing(name, content)


def picture_body(name: str, tone: str, index: int) -> str:
    base = PICTURE_COLOURS[tone]
    if type(index) is not int or index < 1:
        raise ValueError("the index of a picture is a positive whole number")
    drawing = icon_body(name)
    return (
        '<rect width="400" height="300" style="fill:color-mix(in srgb, '
        f'var(--vl-color-{base}) 14%, var(--vl-color-surface))"></rect>'
        '<g transform="translate(128 78) scale(6)" '
        f'style="stroke:var(--vl-color-{base})" fill="none" stroke-width="1.5" '
        f'stroke-linecap="round" stroke-linejoin="round">{drawing}</g>'
    )


def mockup_resources() -> dict[str, object]:
    return {"icons": list(icon_names()), "tones": list(PICTURE_TONES)}


__all__ = [
    "DEFAULT_PICTURE_TONE",
    "FALLBACK_ICON",
    "FALLBACK_PICTURE",
    "ICON_ATTRIBUTES",
    "ICON_DIRECTORY",
    "ICON_ELEMENTS",
    "ICON_LICENCE",
    "ICON_NAME",
    "ICON_PACKAGE",
    "ICON_VIEWBOX",
    "MANIFEST_FILE",
    "MANIFEST_HASH",
    "MAX_ICON_NAME_LENGTH",
    "PICTURE_ASPECT",
    "PICTURE_COLOURS",
    "PICTURE_TONES",
    "PICTURE_VIEWBOX",
    "icon_body",
    "icon_names",
    "is_bundled_icon",
    "mockup_resources",
    "picture_body",
]
