from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from orchestwin.artifacts.generated_mockup_structure import derive_elements, locate
from orchestwin.artifacts.generated_mockup_styles import (
    GeneratedMockupError,
    has_forbidden_character,
)
from orchestwin.artifacts.generated_mockups import (
    MAX_TITLE_LENGTH,
    GeneratedMockup,
    screen_trees,
    serialize_markup,
)
from orchestwin.artifacts.visual_language import _TOKEN_NAME, _plain_css_value

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
    "form-action 'none'; base-uri 'none'"
)
PIN_BACKGROUND: Final = "#6b4f8a"
PIN_FOREGROUND: Final = "#ffffff"
PIN_SIZE: Final = "22px"
PIN_LAYER: Final = 1000
DEFAULT_ENTRY_SCREEN: Final = "SCR-001"
SHRINKING_ELEMENTS: Final = (
    "article",
    "aside",
    "details",
    "div",
    "dl",
    "fieldset",
    "figure",
    "footer",
    "form",
    "header",
    "li",
    "main",
    "nav",
    "ol",
    "section",
    "ul",
)
SCREEN_ITEM_RULE: Final = (
    f":where(.ot-screen) :where({','.join(SHRINKING_ELEMENTS)}){{min-width:0}}"
)
BASE_RULES: Final = (
    "*,*::before,*::after{box-sizing:border-box}"
    "body{margin:0;background:var(--vl-color-background);color:var(--vl-color-text);"
    "font-family:var(--vl-font-body);font-size:var(--vl-size-body);"
    "line-height:var(--vl-line-height)}"
    ".ot-screen{display:none}"
    ".ot-screen:target{display:block}"
    "body:not(:has(.ot-screen:target)) .ot-screen[data-entry]{display:block}"
    ":focus-visible{outline:2px solid var(--vl-color-primary);outline-offset:2px}"
    "@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;"
    "transition:none!important;scroll-behavior:auto!important}}"
    f".ot-pin{{position:relative;z-index:{PIN_LAYER};display:inline-flex;align-items:center;"
    f"justify-content:center;width:{PIN_SIZE};height:{PIN_SIZE};min-width:{PIN_SIZE};"
    "margin-inline:4px;padding:0;border:2px solid #ffffff;border-radius:50%;"
    f"background:{PIN_BACKGROUND};color:{PIN_FOREGROUND};font:700 11px/1 system-ui,sans-serif;"
    "vertical-align:middle}" + SCREEN_ITEM_RULE
)
_ELEMENT_CODE: Final = re.compile(r"ELM-[0-9]{3,6}")
_LANGUAGE: Final = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8}){0,7}")
_INSIDE: Final = frozenset({"caption", "summary"})


def _fail(code: str, detail: str) -> GeneratedMockupError:
    return GeneratedMockupError(code, f"document: {detail}")


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    return _escape_text(value).replace('"', "&quot;")


@dataclass(frozen=True, slots=True)
class MockupPin:
    element_code: str
    number: int
    label: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.element_code, str)
            or _ELEMENT_CODE.fullmatch(self.element_code) is None
        ):
            raise _fail("DOCUMENT_PIN", "pin element code")
        if type(self.number) is not int or self.number < 1:
            raise _fail("DOCUMENT_PIN", "pin number")
        if (
            not isinstance(self.label, str)
            or has_forbidden_character(self.label)
            or " ".join(self.label.split()) != self.label
            or not 1 <= len(self.label) <= MAX_TITLE_LENGTH
        ):
            raise _fail("DOCUMENT_PIN", "pin label")

    @property
    def html(self) -> str:
        return (
            f'<span class="ot-pin" aria-label="{_escape_attribute(self.label)}">'
            f"{_escape_text(str(self.number))}</span>"
        )


def _root_rule(tokens: object) -> str:
    if not isinstance(tokens, Mapping):
        raise _fail("DOCUMENT_TOKEN", "tokens must be a mapping")
    declarations = []
    for name, value in sorted(tokens.items(), key=lambda item: str(item[0])):
        if not isinstance(name, str) or _TOKEN_NAME.fullmatch(name) is None:
            raise _fail("DOCUMENT_TOKEN", "token name")
        if not _plain_css_value(value):
            raise _fail("DOCUMENT_TOKEN", f"value of {name}")
        declarations.append(f"{name}:{value}")
    return ":root{" + ";".join(declarations) + "}"


def mockup_document(
    mockup: GeneratedMockup,
    *,
    tokens: Mapping[str, str],
    language: str,
    pins: Iterable[MockupPin] = (),
    entry_screen: str | None = None,
) -> str:
    if not isinstance(mockup, GeneratedMockup):
        raise _fail("DOCUMENT_UNSAFE", "a generated mockup is required")
    if not isinstance(language, str) or _LANGUAGE.fullmatch(language) is None:
        raise _fail("DOCUMENT_LANGUAGE", "language tag")
    root = _root_rule(tokens)
    entry = DEFAULT_ENTRY_SCREEN if entry_screen is None else entry_screen
    if entry not in {screen.code for screen in mockup.screens}:
        raise _fail("DOCUMENT_ENTRY_SCREEN", "entry screen")
    derived = {element.code: element for element in derive_elements(mockup)}
    if isinstance(pins, str | bytes | Mapping) or not isinstance(pins, Iterable):
        raise _fail("DOCUMENT_PIN", "pins must be a sequence")
    chosen = list(pins)
    for pin in chosen:
        if not isinstance(pin, MockupPin) or pin.element_code not in derived:
            raise _fail("DOCUMENT_PIN", "pin on an unknown element")
    trees = screen_trees(mockup)
    sections = []
    for screen in mockup.screens:
        nodes = trees[screen.code]
        attributes = {
            element.path: (("data-elm", element.code),)
            for element in derived.values()
            if element.screen_code == screen.code
        }
        after: dict[tuple[int, ...], str] = {}
        append: dict[tuple[int, ...], str] = {}
        for pin in chosen:
            element = derived[pin.element_code]
            if element.screen_code != screen.code:
                continue
            node = locate(nodes, element.path)
            if node.name == "tr":
                place, slot = append, (*element.path, 0)
            elif node.name in _INSIDE:
                place, slot = append, element.path
            else:
                place, slot = after, element.path
            place[slot] = place.get(slot, "") + pin.html
        body = serialize_markup(nodes, attributes=attributes, after=after, append=append)
        marker = " data-entry" if screen.code == entry else ""
        sections.append(
            f'<section class="ot-screen" id="{screen.code}" data-state="{screen.state.value}" '
            f'aria-label="{_escape_attribute(screen.title)}"{marker}>{body}</section>'
        )
    style = root + BASE_RULES + mockup.styles
    if "<" in style:
        raise _fail("DOCUMENT_UNSAFE", "the style element would contain a tag")
    document = (
        f'<!doctype html><html lang="{language}"><head><meta charset="utf-8">'
        f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_escape_text(mockup.title)}</title><style>{style}</style></head>"
        f'<body class="ot-mockup">{"".join(sections)}</body></html>'
    )
    lowered = document.lower()
    if "<script" in lowered or lowered.count("</style") != 1:
        raise _fail("DOCUMENT_UNSAFE", "unexpected script or style boundary")
    return document


__all__ = [
    "BASE_RULES",
    "CONTENT_SECURITY_POLICY",
    "DEFAULT_ENTRY_SCREEN",
    "PIN_BACKGROUND",
    "PIN_FOREGROUND",
    "PIN_LAYER",
    "PIN_SIZE",
    "SCREEN_ITEM_RULE",
    "SHRINKING_ELEMENTS",
    "MockupPin",
    "mockup_document",
]
