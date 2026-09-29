from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from html.entities import html5
from html.parser import HTMLParser
from types import MappingProxyType
from typing import Final
from uuid import UUID

from orchestwin.artifacts.generated_mockup_styles import (
    MAX_STYLES_LENGTH,
    GeneratedMockupError,
    detail_name,
    has_forbidden_character,
    normalize_styles,
    parse_style_sheet,
)
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.artifacts.visual_language import _TOKEN_NAME
from orchestwin.projects.requirements_primitives import canonical_json, snapshot_content_hash

MOCKUP_CONTRACT_VERSION: Final = 1
MIN_SCREENS: Final = 2
MAX_SCREENS: Final = 8
MAX_TITLE_LENGTH: Final = 200
MAX_MARKUP_LENGTH: Final = 40_000
MAX_MOCKUP_LENGTH: Final = 250_000
MAX_DEPTH: Final = 40
MAX_ELEMENTS: Final = 1500
MAX_SVG_VALUE_LENGTH: Final = 4000

HTML_ELEMENTS: Final = frozenset(
    {
        "a",
        "abbr",
        "article",
        "aside",
        "b",
        "blockquote",
        "br",
        "button",
        "caption",
        "code",
        "col",
        "colgroup",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "em",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "header",
        "hr",
        "i",
        "input",
        "kbd",
        "label",
        "legend",
        "li",
        "main",
        "mark",
        "meter",
        "nav",
        "ol",
        "optgroup",
        "option",
        "output",
        "p",
        "progress",
        "section",
        "select",
        "small",
        "span",
        "strong",
        "sub",
        "summary",
        "sup",
        "table",
        "tbody",
        "td",
        "textarea",
        "tfoot",
        "th",
        "thead",
        "time",
        "tr",
        "ul",
    }
)
SVG_ELEMENTS: Final = frozenset(
    {"svg", "g", "path", "circle", "ellipse", "line", "polyline", "polygon", "rect"}
)
SVG_SHAPES: Final = SVG_ELEMENTS - {"svg", "g"}
ALLOWED_ELEMENTS: Final = HTML_ELEMENTS | SVG_ELEMENTS
VOID_ELEMENTS: Final = frozenset({"br", "col", "hr", "input"})
PHRASING_ELEMENTS: Final = frozenset(
    {
        "p",
        "h1",
        "h2",
        "h3",
        "h4",
        "a",
        "abbr",
        "b",
        "button",
        "code",
        "em",
        "i",
        "kbd",
        "label",
        "mark",
        "meter",
        "output",
        "progress",
        "small",
        "span",
        "strong",
        "sub",
        "sup",
        "time",
    }
)
BLOCK_ELEMENTS: Final = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "caption",
        "col",
        "colgroup",
        "dd",
        "details",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "header",
        "hr",
        "legend",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "summary",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)
INTERACTIVE_ELEMENTS: Final = frozenset({"a", "button", "label", "select", "input", "textarea"})
GLOBAL_ATTRIBUTES: Final = frozenset(
    {"class", "id", "lang", "dir", "role", "hidden", "tabindex", "title", "data-req"}
)
SVG_NAMESPACE: Final = "http://www.w3.org/2000/svg"
BUTTON_TYPES: Final = frozenset({"button", "submit", "reset"})
_OPTION_ATTRIBUTES: Final = frozenset({"value", "selected", "disabled", "label"})
_CELL_ATTRIBUTES: Final = frozenset({"colspan", "rowspan", "scope", "headers"})
_GAUGE_ATTRIBUTES: Final = frozenset({"value", "min", "max", "low", "high", "optimum"})
ELEMENT_ATTRIBUTES: Final = MappingProxyType(
    {
        "a": frozenset({"href"}),
        "input": frozenset(
            {
                "type",
                "name",
                "value",
                "placeholder",
                "checked",
                "disabled",
                "readonly",
                "required",
                "min",
                "max",
                "step",
                "maxlength",
                "minlength",
            }
        ),
        "select": frozenset({"name", "disabled", "required"}),
        "option": _OPTION_ATTRIBUTES,
        "optgroup": _OPTION_ATTRIBUTES,
        "textarea": frozenset(
            {"name", "rows", "cols", "placeholder", "disabled", "readonly", "required"}
        ),
        "button": frozenset({"type", "disabled", "name", "value"}),
        "label": frozenset({"for"}),
        "td": _CELL_ATTRIBUTES,
        "th": _CELL_ATTRIBUTES,
        "col": frozenset({"span"}),
        "colgroup": frozenset({"span"}),
        "time": frozenset({"datetime"}),
        "meter": _GAUGE_ATTRIBUTES,
        "progress": _GAUGE_ATTRIBUTES,
        "details": frozenset({"open"}),
        "ol": frozenset({"start", "reversed"}),
    }
)
SVG_ATTRIBUTES: Final = frozenset(
    {
        "viewbox",
        "width",
        "height",
        "fill",
        "stroke",
        "stroke-width",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-dasharray",
        "d",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "points",
        "transform",
        "opacity",
        "focusable",
    }
)
BOOLEAN_ATTRIBUTES: Final = frozenset(
    {"hidden", "checked", "disabled", "readonly", "required", "selected", "open", "reversed"}
)
REFERENCE_ATTRIBUTES: Final = frozenset(
    {"for", "headers", "aria-labelledby", "aria-describedby", "aria-controls"}
)
INPUT_TYPES: Final = frozenset(
    {
        "text",
        "search",
        "email",
        "tel",
        "url",
        "number",
        "date",
        "time",
        "datetime-local",
        "month",
        "week",
        "password",
        "checkbox",
        "radio",
        "range",
    }
)
_KEYWORDS: Final = MappingProxyType(
    {
        "dir": frozenset({"ltr", "rtl", "auto"}),
        "scope": frozenset({"row", "col", "rowgroup", "colgroup"}),
        "stroke-linecap": frozenset({"butt", "round", "square"}),
        "stroke-linejoin": frozenset({"miter", "round", "bevel", "arcs", "miter-clip"}),
        "focusable": frozenset({"true", "false", "auto"}),
    }
)
_SVG_NUMBER_ATTRIBUTES: Final = frozenset(
    {
        "viewbox",
        "width",
        "height",
        "stroke-width",
        "stroke-dasharray",
        "cx",
        "cy",
        "r",
        "rx",
        "ry",
        "x",
        "y",
        "x1",
        "y1",
        "x2",
        "y2",
        "points",
        "opacity",
    }
)
_PARENTS: Final = MappingProxyType(
    {
        "li": ("ul", "ol"),
        "dt": ("dl",),
        "dd": ("dl",),
        "option": ("select", "optgroup"),
        "optgroup": ("select",),
        "tr": ("thead", "tbody", "tfoot"),
        "td": ("tr",),
        "th": ("tr",),
        "thead": ("table",),
        "tbody": ("table",),
        "tfoot": ("table",),
        "caption": ("table",),
        "colgroup": ("table",),
        "col": ("colgroup",),
        "summary": ("details",),
        "legend": ("fieldset",),
    }
)
_CHILDREN: Final = MappingProxyType(
    {
        "table": frozenset({"caption", "colgroup", "thead", "tbody", "tfoot"}),
        "thead": frozenset({"tr"}),
        "tbody": frozenset({"tr"}),
        "tfoot": frozenset({"tr"}),
        "tr": frozenset({"td", "th"}),
        "colgroup": frozenset({"col"}),
        "select": frozenset({"option", "optgroup"}),
        "optgroup": frozenset({"option"}),
        "option": frozenset(),
        "svg": SVG_ELEMENTS,
        "g": SVG_ELEMENTS,
        **{shape: frozenset() for shape in SVG_SHAPES},
    }
)
_WHITESPACE_ONLY: Final = (
    frozenset({"table", "thead", "tbody", "tfoot", "tr", "colgroup", "select", "optgroup"})
    | SVG_ELEMENTS
)
_ATTRIBUTE_SPELLING: Final = MappingProxyType({"viewbox": "viewBox"})
_ASCII_WHITESPACE: Final = " \t\n\f\r"
_SPLIT: Final = re.compile(r"[ \t\n\f\r]+")
_LINE: Final = re.compile(r"\n")
_SCREEN_CODE: Final = re.compile(r"SCR-[0-9]{3}")
_ARIA: Final = re.compile(r"aria-[a-z]+")
_IDENTIFIER: Final = re.compile(r"[a-z][a-z0-9-]{0,63}")
_CLASS: Final = re.compile(r"[a-z][a-z0-9_-]{0,63}")
_REQUIREMENTS: Final = re.compile(r"[A-Z]{2,5}-[0-9]{3}(?: [A-Z]{2,5}-[0-9]{3})*")
_LANGUAGE: Final = re.compile(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*")
_ROLE: Final = re.compile(r"[a-z]+(?: [a-z]+)*")
_HREF: Final = re.compile(r"#(SCR-[0-9]{3})")
_POSITIVE: Final = re.compile(r"[1-9][0-9]{0,3}")
_LENGTH: Final = re.compile(r"[0-9]{1,6}")
_INTEGER: Final = re.compile(r"-?[0-9]{1,9}")
_DECIMAL: Final = re.compile(r"-?(?:[0-9]{1,9}(?:\.[0-9]{1,6})?|\.[0-9]{1,6})")
_SVG_NUMBER: Final = re.compile(r"[0-9 ,.+\-\t\n]+")
_SVG_PATH: Final = re.compile(r"[0-9 ,.+\-\t\nMmLlHhVvCcSsQqTtAaZz]+")
_SVG_TRANSFORM: Final = re.compile(
    r"[ ,\t\n]*(?:(?:matrix|translate|scale|rotate|skewX|skewY)\([0-9 ,.+\-\t\n]*\)[ ,\t\n]*)+"
)
_SVG_PAINT: Final = re.compile(r"var\((--vl-color-[a-z0-9]+(?:-[a-z0-9]+)*)\)")
_VALUE_SOURCE: Final = r"(?:[ \t\n]*=[ \t\n]*(?:\"[^\"]*\"|'[^']*'|[^ \t\n\"'=<>`]+))?"
_RAW_ATTRIBUTE: Final = re.compile(r"[ \t\n]+([A-Za-z][A-Za-z0-9-]*)" + _VALUE_SOURCE)
_START_TAG: Final = re.compile(
    r"<([A-Za-z][A-Za-z0-9]*)((?:[ \t\n]+[A-Za-z][A-Za-z0-9-]*"
    + _VALUE_SOURCE
    + r")*)[ \t\n]*(/?)>"
)
_END_TAG: Final = re.compile(r"</([A-Za-z][A-Za-z0-9]*)>")
_COMMENT: Final = re.compile(r"<!--(?!-?>)(?:(?!--).)*-?-->", re.DOTALL)
_AMPERSAND: Final = re.compile(r"&(?=[A-Za-z0-9#])")
_REFERENCE: Final = re.compile(
    r"&(?:#([0-9]{1,7});|#[xX]([0-9A-Fa-f]{1,6});|([A-Za-z][A-Za-z0-9]{1,31});)"
)
_SNAPSHOT_KEYS: Final = frozenset(
    {"contract_version", "design_alternative_id", "title", "styles", "screens"}
)
_SCREEN_KEYS: Final = frozenset({"code", "title", "state", "markup"})


@dataclass(frozen=True, slots=True)
class MarkupText:
    text: str


@dataclass(frozen=True, slots=True)
class MarkupElement:
    name: str
    attributes: tuple[tuple[str, str | None], ...]
    children: tuple[MarkupText | MarkupElement, ...]

    def attribute(self, name: str) -> str | None:
        for key, value in self.attributes:
            if key == name:
                return value
        return None

    def has(self, name: str) -> bool:
        return any(key == name for key, _ in self.attributes)

    @property
    def elements(self) -> tuple[MarkupElement, ...]:
        return tuple(child for child in self.children if isinstance(child, MarkupElement))


MarkupNode = MarkupText | MarkupElement


@dataclass(frozen=True, slots=True)
class _Context:
    screen_code: str
    screen_codes: frozenset[str]
    token_names: frozenset[str] | None

    def fail(self, code: str, detail: str) -> GeneratedMockupError:
        return GeneratedMockupError(code, f"{self.screen_code}: {detail}")


@dataclass(frozen=True, slots=True)
class _Event:
    kind: str
    start: int
    value: str
    attributes: tuple[tuple[str, str | None], ...] = ()
    raw: str = ""
    closed: bool = False


class _Recorder(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.line_starts = [0, *(match.end() for match in _LINE.finditer(text))]
        self.events: list[_Event] = []

    def position(self) -> int:
        line, offset = self.getpos()
        return self.line_starts[line - 1] + offset

    def record(self, kind: str, value: str, **extra: object) -> None:
        self.events.append(_Event(kind, self.position(), value, **extra))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.record("start", tag, attributes=tuple(attrs), raw=self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.record(
            "start",
            tag,
            attributes=tuple(attrs),
            raw=self.get_starttag_text() or "",
            closed=True,
        )

    def handle_endtag(self, tag: str) -> None:
        self.record("end", tag)

    def handle_data(self, data: str) -> None:
        self.record("data", data)

    def handle_comment(self, data: str) -> None:
        self.record("comment", data)

    def handle_decl(self, decl: str) -> None:
        self.record("declaration", decl)

    def handle_pi(self, data: str) -> None:
        self.record("instruction", data)

    def unknown_decl(self, data: str) -> None:
        self.record("unknown", data)

    def handle_charref(self, name: str) -> None:
        self.record("reference", name)

    def handle_entityref(self, name: str) -> None:
        self.record("reference", name)


class _Builder:
    __slots__ = ("attributes", "children", "name")

    def __init__(self, name: str, attributes: tuple[tuple[str, str | None], ...]) -> None:
        self.name = name
        self.attributes = attributes
        self.children: list[MarkupNode] = []

    def add_text(self, text: str) -> None:
        if not text:
            return
        if self.children and isinstance(self.children[-1], MarkupText):
            self.children[-1] = MarkupText(self.children[-1].text + text)
        else:
            self.children.append(MarkupText(text))

    def freeze(self) -> MarkupElement:
        return MarkupElement(self.name, self.attributes, tuple(self.children))


def _allowed_code_point(code: int) -> bool:
    if code in (0x9, 0xA):
        return True
    if code < 0x20 or 0x7F <= code <= 0x9F or 0xD800 <= code <= 0xDFFF or code > 0x10FFFF:
        return False
    return not (0xFDD0 <= code <= 0xFDEF or (code & 0xFFFE) == 0xFFFE)


def _prepare(markup: str, context: _Context) -> str:
    text = markup.replace("\r\n", "\n").replace("\r", "\n")
    if has_forbidden_character(text):
        raise context.fail("MARKUP_CONTROL_CHARACTER", "control character")
    for match in _AMPERSAND.finditer(text):
        reference = _REFERENCE.match(text, match.start())
        if reference is None:
            raise context.fail("MARKUP_CHARACTER_REFERENCE", "incomplete character reference")
        decimal, hexadecimal, name = reference.groups()
        if name is not None:
            valid = f"{name};" in html5
        else:
            valid = _allowed_code_point(
                int(decimal) if decimal is not None else int(hexadecimal, 16)
            )
        if not valid:
            raise context.fail("MARKUP_CHARACTER_REFERENCE", "unknown or unsafe reference")
    return text


def _accepted_comment(text: str, event: _Event) -> bool:
    written = f"<!--{event.value}-->"
    return text.startswith(written, event.start) and _COMMENT.fullmatch(written) is not None


def _either(names: tuple[str, ...]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " or " + names[-1]


def _identifiers(value: str) -> tuple[str, ...]:
    stripped = value.strip(_ASCII_WHITESPACE)
    return tuple(_SPLIT.split(stripped)) if stripped else ()


def _paint(value: str, context: _Context) -> bool:
    if value == "none" or value.lower() == "currentcolor":
        return True
    match = _SVG_PAINT.fullmatch(value)
    return match is not None and (
        context.token_names is None or match.group(1) in context.token_names
    )


def _bounded(pattern: re.Pattern[str]) -> Callable[[str, _Context], bool]:
    return lambda value, _context: (
        len(value) <= MAX_SVG_VALUE_LENGTH and pattern.fullmatch(value) is not None
    )


def _matches(pattern: re.Pattern[str]) -> Callable[[str, _Context], bool]:
    return lambda value, _context: pattern.fullmatch(value) is not None


def _among(values: frozenset[str]) -> Callable[[str, _Context], bool]:
    return lambda value, _context: value in values


def _value_rule(element: str, name: str) -> Callable[[str, _Context], bool] | None:
    if name == "tabindex":
        return _among(frozenset({"0", "-1"}))
    if name == "lang":
        return _matches(_LANGUAGE)
    if name == "role":
        return lambda value, _context: len(value) <= 64 and _ROLE.fullmatch(value) is not None
    if name in _KEYWORDS:
        return _among(_KEYWORDS[name])
    if name == "title":
        return lambda value, _context: 1 <= len(value) <= MAX_TITLE_LENGTH
    if name == "xmlns":
        return _among(frozenset({SVG_NAMESPACE}))
    if name == "type":
        return _among(INPUT_TYPES if element == "input" else BUTTON_TYPES)
    if name in {"colspan", "rowspan", "span", "rows", "cols"}:
        return _matches(_POSITIVE)
    if name in {"maxlength", "minlength"}:
        return _matches(_LENGTH)
    if name == "start":
        return _matches(_INTEGER)
    if element in {"meter", "progress"} and name in _GAUGE_ATTRIBUTES:
        return _matches(_DECIMAL)
    if element in SVG_ELEMENTS:
        if name in {"fill", "stroke"}:
            return _paint
        if name == "d":
            return _bounded(_SVG_PATH)
        if name == "transform":
            return _bounded(_SVG_TRANSFORM)
        if name in _SVG_NUMBER_ATTRIBUTES:
            return _bounded(_SVG_NUMBER)
    return None


def _allowed_attribute(element: str, name: str) -> bool:
    return (
        name in GLOBAL_ATTRIBUTES
        or _ARIA.fullmatch(name) is not None
        or name in ELEMENT_ATTRIBUTES.get(element, frozenset())
        or (element in SVG_ELEMENTS and name in SVG_ATTRIBUTES)
        or (element == "svg" and name == "xmlns")
    )


class _TreeBuilder:
    def __init__(self, text: str, context: _Context) -> None:
        self.text = text
        self.context = context
        self.root = _Builder("", ())
        self.stack: list[_Builder] = []
        self.count = 0
        self.ids: set[str] = set()
        self.references: list[tuple[str, str, tuple[str, ...]]] = []

    def fail(self, code: str, detail: str) -> GeneratedMockupError:
        return self.context.fail(code, detail)

    def container(self) -> _Builder:
        return self.stack[-1] if self.stack else self.root

    def apply(self, event: _Event) -> None:
        if event.kind == "start":
            self.open(event)
        elif event.kind == "end":
            self.close(event)
        elif event.kind == "data":
            self.data(event)
        elif event.kind == "comment":
            head = self.text[event.start : event.start + 4]
            if head == "<!--":
                if not _accepted_comment(self.text, event):
                    raise self.fail("MARKUP_COMMENT", "comment in a form that is not accepted")
                return
            if head.startswith("</"):
                raise self.fail("MARKUP_SYNTAX", "malformed end tag")
            raise self.fail("MARKUP_DECLARATION", "declaration")
        elif event.kind == "declaration":
            if event.value.lower().startswith("doctype"):
                raise self.fail("MARKUP_DOCTYPE", "doctype")
            raise self.fail("MARKUP_DECLARATION", "declaration")
        elif event.kind == "instruction":
            raise self.fail("MARKUP_PROCESSING_INSTRUCTION", "processing instruction")
        elif event.kind == "unknown":
            if event.value.upper().startswith("CDATA["):
                raise self.fail("MARKUP_CDATA", "CDATA section")
            raise self.fail("MARKUP_DECLARATION", "declaration")
        else:
            raise self.fail("MARKUP_CHARACTER_REFERENCE", "character reference")

    def open(self, event: _Event) -> None:
        name = event.value
        if name not in ALLOWED_ELEMENTS:
            raise self.fail("ELEMENT_FORBIDDEN", f"element {detail_name(name)}")
        names = [key for key, _ in event.attributes]
        for index, key in enumerate(names):
            if key in names[:index]:
                raise self.fail("ATTRIBUTE_DUPLICATED", f"attribute {detail_name(key)} on {name}")
        for key in names:
            if not _allowed_attribute(name, key):
                raise self.fail("ATTRIBUTE_FORBIDDEN", f"attribute {detail_name(key)} on {name}")
        match = _START_TAG.fullmatch(event.raw)
        if (
            match is None
            or match.group(1).lower() != name
            or [item.group(1).lower() for item in _RAW_ATTRIBUTE.finditer(match.group(2))] != names
            or bool(match.group(3)) != event.closed
        ):
            raise self.fail("MARKUP_SYNTAX", f"start tag of {name}")
        values = {key: self.value(name, key, value) for key, value in event.attributes}
        values.pop("xmlns", None)
        if name == "button":
            values["type"] = "button"
        attributes = tuple(sorted(values.items(), key=lambda item: item[0]))
        self.structure(name)
        if event.closed and name not in VOID_ELEMENTS and name not in SVG_ELEMENTS:
            raise self.fail("SELF_CLOSING", f"{name} written as a self-closing tag")
        builder = _Builder(name, attributes)
        if name in VOID_ELEMENTS or event.closed:
            self.container().children.append(builder.freeze())
        else:
            self.stack.append(builder)

    def value(self, element: str, name: str, value: str | None) -> str | None:
        if name in BOOLEAN_ATTRIBUTES:
            if value is None or value == "" or value.lower() == name:
                return None
            raise self.fail("ATTRIBUTE_VALUE", f"{name} on {element} is a boolean attribute")
        if value is None:
            raise self.fail("ATTRIBUTE_VALUE", f"{name} on {element} needs a value")
        if has_forbidden_character(value):
            raise self.fail("MARKUP_CONTROL_CHARACTER", f"{name} on {element}")
        if name == "id":
            if _IDENTIFIER.fullmatch(value) is None or value.startswith("ot-"):
                raise self.fail("ID_INVALID", f"identifier {detail_name(value)}")
            if value in self.ids:
                raise self.fail("ID_DUPLICATED", f"identifier {value}")
            self.ids.add(value)
            return value
        if name == "class":
            tokens = _identifiers(value)
            if not tokens or any(
                _CLASS.fullmatch(token) is None or token.startswith("ot-") for token in tokens
            ):
                raise self.fail("CLASS_INVALID", f"class on {element}")
            return " ".join(tokens)
        if name == "data-req":
            codes = value.split(" ")
            if _REQUIREMENTS.fullmatch(value) is None or len(set(codes)) != len(codes):
                raise self.fail("DATA_REQ_INVALID", f"data-req on {element}")
            return value
        if name == "href":
            match = _HREF.fullmatch(value)
            if match is None or match.group(1) not in self.context.screen_codes:
                raise self.fail("LINK_TARGET", f"link on {element} names no screen of this mockup")
            return value
        if name in REFERENCE_ATTRIBUTES:
            identifiers = _identifiers(value)
            if (
                not identifiers
                or (name == "for" and len(identifiers) != 1)
                or any(_IDENTIFIER.fullmatch(identifier) is None for identifier in identifiers)
            ):
                raise self.fail("ID_REFERENCE", f"{name} on {element}")
            self.references.append((element, name, identifiers))
            return value
        rule = _value_rule(element, name)
        if rule is not None and not rule(value, self.context):
            raise self.fail("ATTRIBUTE_VALUE", f"{name} on {element}")
        return value

    def structure(self, name: str) -> None:
        parent = self.stack[-1].name if self.stack else None
        ancestors = [builder.name for builder in self.stack]
        if name in SVG_ELEMENTS:
            if name != "svg" and parent not in {"svg", "g"}:
                raise self.fail("CONTENT_RULE", f"{name} must be inside svg or g")
        elif parent in SVG_ELEMENTS:
            raise self.fail("CONTENT_RULE", f"{name} cannot be inside {parent}")
        required = _PARENTS.get(name)
        if required is not None and parent not in required:
            raise self.fail("CONTENT_RULE", f"{name} must be a direct child of {_either(required)}")
        allowed = None if parent is None else _CHILDREN.get(parent)
        if allowed is not None and name not in allowed:
            raise self.fail("CONTENT_RULE", f"{name} cannot be inside {parent}")
        if name in {"summary", "legend"} and any(
            isinstance(child, MarkupElement) or child.text.strip(_ASCII_WHITESPACE)
            for child in self.stack[-1].children
        ):
            raise self.fail("CONTENT_RULE", f"{name} must be the first child of {parent}")
        if name in BLOCK_ELEMENTS:
            holder = next((item for item in reversed(ancestors) if item in PHRASING_ELEMENTS), None)
            if holder is not None:
                raise self.fail("CONTENT_RULE", f"{name} cannot be inside {holder}")
        if name in INTERACTIVE_ELEMENTS:
            holder = next((item for item in reversed(ancestors) if item in {"a", "button"}), None)
            if holder is not None:
                raise self.fail("CONTENT_RULE", f"{name} cannot be inside {holder}")
        if name == "form" and "form" in ancestors:
            raise self.fail("CONTENT_RULE", "form cannot be inside form")
        if len(self.stack) >= MAX_DEPTH:
            raise self.fail("MARKUP_TOO_DEEP", f"more than {MAX_DEPTH} levels")
        self.count += 1
        if self.count > MAX_ELEMENTS:
            raise self.fail("TOO_MANY_ELEMENTS", f"more than {MAX_ELEMENTS} elements")

    def close(self, event: _Event) -> None:
        name = event.value
        if name in VOID_ELEMENTS:
            raise self.fail("UNEXPECTED_END_TAG", f"end tag of the void element {name}")
        if not self.stack:
            raise self.fail(
                "UNEXPECTED_END_TAG", f"end tag of {detail_name(name)} without an open element"
            )
        current = self.stack[-1]
        if current.name != name:
            raise self.fail(
                "MISNESTED_ELEMENT", f"end tag of {detail_name(name)} while {current.name} is open"
            )
        self.stack.pop()
        self.container().children.append(current.freeze())

    def data(self, event: _Event) -> None:
        text = event.value
        if has_forbidden_character(text):
            raise self.fail("MARKUP_CONTROL_CHARACTER", "text")
        container = self.container()
        if self.stack:
            if container.name in _WHITESPACE_ONLY and text.strip(_ASCII_WHITESPACE):
                raise self.fail("CONTENT_RULE", f"text cannot be inside {container.name}")
            if container.name == "textarea" and not container.children and text.startswith("\n"):
                raise self.fail("CONTENT_RULE", "textarea content starts with a line break")
        container.add_text(text)

    def finish(self, events: list[_Event]) -> tuple[tuple[MarkupNode, ...], frozenset[str]]:
        if self.stack:
            raise self.fail("UNCLOSED_ELEMENT", f"{self.stack[-1].name} is not closed")
        self.spans(events)
        for element, name, identifiers in self.references:
            for identifier in identifiers:
                if identifier not in self.ids:
                    raise self.fail(
                        "ID_REFERENCE",
                        f"{name} on {element} names {detail_name(identifier)}, absent here",
                    )
        return tuple(self.root.children), frozenset(self.ids)

    def spans(self, events: list[_Event]) -> None:
        if not self.text:
            return
        if not events or events[0].start != 0:
            raise self.fail("MARKUP_SYNTAX", "content that is neither a tag nor text")
        for index, event in enumerate(events):
            end = events[index + 1].start if index + 1 < len(events) else len(self.text)
            raw = self.text[event.start : end]
            if event.kind == "start":
                valid = raw == event.raw
            elif event.kind == "end":
                match = _END_TAG.fullmatch(raw)
                valid = match is not None and match.group(1).lower() == event.value
            elif event.kind == "comment":
                valid = raw == f"<!--{event.value}-->"
            else:
                valid = "<" not in raw
            if not valid:
                place = {"data": "text", "comment": "comment"}.get(
                    event.kind, f"tag of {event.value}"
                )
                raise self.fail("MARKUP_SYNTAX", f"{place} is not in the only accepted form")


def _parse(
    markup: str,
    screen_code: str,
    screen_codes: frozenset[str],
    token_names: frozenset[str] | None,
) -> tuple[tuple[MarkupNode, ...], frozenset[str]]:
    context = _Context(screen_code, screen_codes, token_names)
    text = _prepare(markup, context)
    recorder = _Recorder(text)
    try:
        recorder.feed(text)
        recorder.close()
    except AssertionError as error:
        raise context.fail("MARKUP_SYNTAX", "markup the parser cannot read") from error
    builder = _TreeBuilder(text, context)
    for event in recorder.events:
        builder.apply(event)
    return builder.finish(recorder.events)


_parse_cached = lru_cache(maxsize=64)(_parse)


def _escape_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attribute(value: str) -> str:
    return _escape_text(value).replace('"', "&quot;")


def _write(
    nodes: Iterable[MarkupNode],
    prefix: tuple[int, ...],
    parts: list[str],
    extra: Mapping[tuple[int, ...], tuple[tuple[str, str | None], ...]],
    after: Mapping[tuple[int, ...], str],
    append: Mapping[tuple[int, ...], str],
) -> None:
    index = 0
    for node in nodes:
        if isinstance(node, MarkupText):
            parts.append(_escape_text(node.text))
            continue
        path = (*prefix, index)
        index += 1
        parts.append("<" + node.name)
        attributes = dict((*node.attributes, *extra.get(path, ())))
        attributes.pop("xmlns", None)
        if node.name == "button":
            attributes["type"] = "button"
        for name, value in sorted(attributes.items(), key=lambda item: item[0]):
            parts.append(" " + _ATTRIBUTE_SPELLING.get(name, name))
            if value is not None:
                parts.append(f'="{_escape_attribute(value)}"')
        parts.append(">")
        if node.name not in VOID_ELEMENTS:
            _write(node.children, path, parts, extra, after, append)
            parts.append(append.get(path, ""))
            parts.append(f"</{node.name}>")
        parts.append(after.get(path, ""))


def serialize_markup(
    nodes: Iterable[MarkupNode],
    *,
    attributes: Mapping[tuple[int, ...], tuple[tuple[str, str | None], ...]] | None = None,
    after: Mapping[tuple[int, ...], str] | None = None,
    append: Mapping[tuple[int, ...], str] | None = None,
) -> str:
    parts: list[str] = []
    _write(nodes, (), parts, attributes or {}, after or {}, append or {})
    return "".join(parts)


def _token_names(value: object) -> frozenset[str]:
    if isinstance(value, str | bytes) or not isinstance(value, Iterable):
        raise GeneratedMockupError("TOKEN_NAMES", "token names must be a collection")
    names = frozenset(value)
    for name in names:
        if not isinstance(name, str) or _TOKEN_NAME.fullmatch(name) is None:
            raise GeneratedMockupError("TOKEN_NAMES", f"token name {detail_name(name)}")
    return names


def parse_markup(
    markup: str,
    *,
    screen_code: str,
    screen_codes: Iterable[str],
    token_names: Iterable[str] | None = None,
) -> tuple[MarkupNode, ...]:
    if not isinstance(markup, str):
        raise GeneratedMockupError("SCREEN_INVALID", f"{screen_code}: markup must be text")
    if len(markup) > MAX_MARKUP_LENGTH:
        raise GeneratedMockupError("MARKUP_TOO_LONG", f"{screen_code}: {len(markup)} characters")
    names = None if token_names is None else _token_names(token_names)
    return _parse_cached(markup, screen_code, frozenset(screen_codes), names)[0]


def _require_title(value: object, place: str) -> None:
    if (
        not isinstance(value, str)
        or has_forbidden_character(value)
        or " ".join(value.split()) != value
        or not 1 <= len(value) <= MAX_TITLE_LENGTH
    ):
        raise GeneratedMockupError("TITLE_INVALID", f"{place}: title")


def _normalize_title(value: object, place: str) -> str:
    if not isinstance(value, str) or has_forbidden_character(value):
        raise GeneratedMockupError("TITLE_INVALID", f"{place}: title")
    normalized = " ".join(value.split())
    if not 1 <= len(normalized) <= MAX_TITLE_LENGTH:
        raise GeneratedMockupError(
            "TITLE_INVALID", f"{place}: title of {len(normalized)} characters"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class GeneratedScreen:
    code: str
    title: str
    state: PrototypeScreenState
    markup: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or _SCREEN_CODE.fullmatch(self.code) is None:
            raise GeneratedMockupError("SCREEN_CODE", f"screen code {detail_name(self.code)}")
        _require_title(self.title, self.code)
        if not isinstance(self.state, PrototypeScreenState):
            raise GeneratedMockupError("SCREEN_STATE", f"{self.code}: state")
        if not isinstance(self.markup, str):
            raise GeneratedMockupError("SCREEN_INVALID", f"{self.code}: markup must be text")
        if len(self.markup) > MAX_MARKUP_LENGTH:
            raise GeneratedMockupError(
                "MARKUP_TOO_LONG", f"{self.code}: {len(self.markup)} characters"
            )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "title": self.title,
            "state": self.state.value,
            "markup": self.markup,
        }


@dataclass(frozen=True, slots=True)
class GeneratedMockup:
    contract_version: int
    design_alternative_id: UUID
    title: str
    styles: str
    screens: tuple[GeneratedScreen, ...]

    def __post_init__(self) -> None:
        _validate_mockup(self)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "design_alternative_id": str(self.design_alternative_id),
            "title": self.title,
            "styles": self.styles,
            "screens": [screen.to_snapshot() for screen in self.screens],
        }

    def canonical_json(self) -> str:
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        return snapshot_content_hash(self.to_snapshot())


def _check_screens(screens: object) -> tuple[GeneratedScreen, ...]:
    if not isinstance(screens, tuple) or not all(
        isinstance(screen, GeneratedScreen) for screen in screens
    ):
        raise GeneratedMockupError("SCREEN_INVALID", "screens must be a tuple of screens")
    if not MIN_SCREENS <= len(screens) <= MAX_SCREENS:
        raise GeneratedMockupError("SCREEN_COUNT", f"{len(screens)} screens")
    for index, screen in enumerate(screens, start=1):
        if screen.code != f"SCR-{index:03d}":
            raise GeneratedMockupError("SCREEN_CODE", f"screen {index} must be SCR-{index:03d}")
    return screens


def _validate_mockup(mockup: GeneratedMockup) -> None:
    version = mockup.contract_version
    if type(version) is not int or version != MOCKUP_CONTRACT_VERSION:
        raise GeneratedMockupError("CONTRACT_VERSION", "unsupported contract version")
    if not isinstance(mockup.design_alternative_id, UUID):
        raise GeneratedMockupError("ALTERNATIVE_ID", "design alternative identifier")
    _require_title(mockup.title, "mockup")
    screens = _check_screens(mockup.screens)
    if not isinstance(mockup.styles, str):
        raise GeneratedMockupError("STYLES_SYNTAX", "styles: the styles must be text")
    if len(mockup.styles) > MAX_STYLES_LENGTH:
        raise GeneratedMockupError("STYLES_TOO_LONG", f"styles: {len(mockup.styles)} characters")
    total = (
        len(mockup.title)
        + len(mockup.styles)
        + sum(len(screen.title) + len(screen.markup) for screen in screens)
    )
    if total > MAX_MOCKUP_LENGTH:
        raise GeneratedMockupError("MOCKUP_TOO_LONG", f"{total} characters")
    if normalize_styles(mockup.styles) != mockup.styles:
        raise GeneratedMockupError("NOT_CANONICAL", "styles are not in their stored form")
    parse_style_sheet(mockup.styles)
    codes = frozenset(screen.code for screen in screens)
    owners: dict[str, str] = {}
    for screen in screens:
        nodes, identifiers = _parse_cached(screen.markup, screen.code, codes, None)
        if serialize_markup(nodes) != screen.markup:
            raise GeneratedMockupError(
                "NOT_CANONICAL", f"{screen.code}: markup is not in its stored form"
            )
        for identifier in sorted(identifiers):
            if identifier in owners:
                raise GeneratedMockupError(
                    "ID_DUPLICATED",
                    f"{screen.code}: identifier {identifier} is also used in {owners[identifier]}",
                )
            owners[identifier] = screen.code


def _screen_state(value: object, code: str) -> PrototypeScreenState:
    if isinstance(value, PrototypeScreenState):
        return value
    try:
        return PrototypeScreenState(value)
    except ValueError as error:
        raise GeneratedMockupError("SCREEN_STATE", f"{code}: state") from error


def _screen_entries(screens: object) -> list[tuple[object, object, object, object]]:
    if isinstance(screens, str | bytes | Mapping) or not isinstance(screens, Iterable):
        raise GeneratedMockupError("SCREEN_INVALID", "screens must be a sequence")
    entries: list[tuple[object, object, object, object]] = []
    for item in screens:
        if len(entries) == MAX_SCREENS:
            raise GeneratedMockupError("SCREEN_COUNT", f"more than {MAX_SCREENS} screens")
        if isinstance(item, GeneratedScreen):
            entries.append((item.code, item.title, item.state, item.markup))
        elif isinstance(item, Mapping) and set(item) == _SCREEN_KEYS:
            entries.append((item["code"], item["title"], item["state"], item["markup"]))
        else:
            raise GeneratedMockupError(
                "SCREEN_INVALID", "screen entries need code, title, state, markup"
            )
    return entries


def create_generated_mockup(
    *,
    design_alternative_id: UUID,
    title: str,
    styles: str,
    screens: Iterable[GeneratedScreen | Mapping[str, object]],
    token_names: Iterable[str],
) -> GeneratedMockup:
    names = _token_names(token_names)
    if not isinstance(design_alternative_id, UUID):
        raise GeneratedMockupError("ALTERNATIVE_ID", "design alternative identifier")
    mockup_title = _normalize_title(title, "mockup")
    entries = _screen_entries(screens)
    if not MIN_SCREENS <= len(entries) <= MAX_SCREENS:
        raise GeneratedMockupError("SCREEN_COUNT", f"{len(entries)} screens")
    validated: list[tuple[str, object, object, str]] = []
    for index, (code, raw_title, raw_state, markup) in enumerate(entries, start=1):
        expected = f"SCR-{index:03d}"
        if code != expected:
            raise GeneratedMockupError("SCREEN_CODE", f"screen {index} must be {expected}")
        if not isinstance(markup, str):
            raise GeneratedMockupError("SCREEN_INVALID", f"{expected}: markup must be text")
        if len(markup) > MAX_MARKUP_LENGTH:
            raise GeneratedMockupError("MARKUP_TOO_LONG", f"{expected}: {len(markup)} characters")
        validated.append((expected, raw_title, raw_state, markup))
    if not isinstance(styles, str):
        raise GeneratedMockupError("STYLES_SYNTAX", "styles: the styles must be text")
    if len(styles) > MAX_STYLES_LENGTH:
        raise GeneratedMockupError("STYLES_TOO_LONG", f"styles: {len(styles)} characters")
    total = len(mockup_title) + len(styles) + sum(len(item[3]) for item in validated)
    if total > MAX_MOCKUP_LENGTH:
        raise GeneratedMockupError("MOCKUP_TOO_LONG", f"{total} characters")
    stored_styles = normalize_styles(styles)
    parse_style_sheet(stored_styles, token_names=names)
    codes = frozenset(item[0] for item in validated)
    built: list[GeneratedScreen] = []
    for code, raw_title, raw_state, markup in validated:
        screen_title = _normalize_title(raw_title, code)
        state = _screen_state(raw_state, code)
        nodes, _identifiers = _parse_cached(markup, code, codes, names)
        stored = serialize_markup(nodes)
        if len(stored) > MAX_MARKUP_LENGTH:
            raise GeneratedMockupError(
                "MARKUP_TOO_LONG", f"{code}: {len(stored)} characters once written"
            )
        built.append(GeneratedScreen(code, screen_title, state, stored))
    return GeneratedMockup(
        contract_version=MOCKUP_CONTRACT_VERSION,
        design_alternative_id=design_alternative_id,
        title=mockup_title,
        styles=stored_styles,
        screens=tuple(built),
    )


def generated_mockup_from_snapshot(
    payload: Mapping[str, object], *, token_names: Iterable[str]
) -> GeneratedMockup:
    if not isinstance(payload, Mapping) or set(payload) != _SNAPSHOT_KEYS:
        raise GeneratedMockupError("SNAPSHOT_INVALID", "snapshot keys")
    version = payload["contract_version"]
    if type(version) is not int or version != MOCKUP_CONTRACT_VERSION:
        raise GeneratedMockupError("CONTRACT_VERSION", "unsupported contract version")
    identifier, title, styles, screens = (
        payload["design_alternative_id"],
        payload["title"],
        payload["styles"],
        payload["screens"],
    )
    if not all(isinstance(value, str) for value in (identifier, title, styles)):
        raise GeneratedMockupError("SNAPSHOT_INVALID", "snapshot values must be text")
    if not isinstance(screens, list | tuple) or not all(
        isinstance(screen, Mapping)
        and set(screen) == _SCREEN_KEYS
        and all(isinstance(screen[key], str) for key in _SCREEN_KEYS)
        for screen in screens
    ):
        raise GeneratedMockupError("SNAPSHOT_INVALID", "snapshot screens")
    try:
        alternative = UUID(str(identifier))
    except ValueError as error:
        raise GeneratedMockupError("ALTERNATIVE_ID", "design alternative identifier") from error
    mockup = create_generated_mockup(
        design_alternative_id=alternative,
        title=str(title),
        styles=str(styles),
        screens=[dict(screen) for screen in screens],
        token_names=token_names,
    )
    expected = {**payload, "screens": [dict(screen) for screen in screens]}
    if mockup.to_snapshot() != expected:
        raise GeneratedMockupError("SNAPSHOT_NOT_CANONICAL", "snapshot is not in its stored form")
    return mockup


def screen_trees(mockup: GeneratedMockup) -> dict[str, tuple[MarkupNode, ...]]:
    codes = frozenset(screen.code for screen in mockup.screens)
    return {
        screen.code: _parse_cached(screen.markup, screen.code, codes, None)[0]
        for screen in mockup.screens
    }


__all__ = [
    "ALLOWED_ELEMENTS",
    "BLOCK_ELEMENTS",
    "BOOLEAN_ATTRIBUTES",
    "BUTTON_TYPES",
    "ELEMENT_ATTRIBUTES",
    "GLOBAL_ATTRIBUTES",
    "HTML_ELEMENTS",
    "INPUT_TYPES",
    "INTERACTIVE_ELEMENTS",
    "MAX_DEPTH",
    "MAX_ELEMENTS",
    "MAX_MARKUP_LENGTH",
    "MAX_MOCKUP_LENGTH",
    "MAX_SCREENS",
    "MAX_STYLES_LENGTH",
    "MAX_TITLE_LENGTH",
    "MIN_SCREENS",
    "MOCKUP_CONTRACT_VERSION",
    "PHRASING_ELEMENTS",
    "SVG_ATTRIBUTES",
    "SVG_ELEMENTS",
    "SVG_NAMESPACE",
    "SVG_SHAPES",
    "VOID_ELEMENTS",
    "GeneratedMockup",
    "GeneratedMockupError",
    "GeneratedScreen",
    "MarkupElement",
    "MarkupNode",
    "MarkupText",
    "create_generated_mockup",
    "generated_mockup_from_snapshot",
    "parse_markup",
    "screen_trees",
    "serialize_markup",
]
