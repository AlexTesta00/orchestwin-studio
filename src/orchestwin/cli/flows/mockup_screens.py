from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final

from orchestwin.cli.shapes import collapsed as _normalized
from orchestwin.cli.shapes import shortened as clipped

SCREEN_ID: Final = re.compile(r"SCR-[0-9]{3}")
ELEMENT_MARK: Final = "data-elm"
ZONE_MARK: Final = "data-ot-zone"
ZONE: Final = "zone"
HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4"})
CAPTIONS: Final = frozenset({"legend", "caption", "summary", "figcaption"})
LABEL_LIMIT: Final = 120
HTML_LIMIT: Final = 2048
PIN_CLASS: Final = "ot-pin"
NAME_ATTRIBUTES: Final = ("value", "placeholder", "title", "alt")
VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
SILENT_TAGS: Final = frozenset(
    {"script", "style", "template", "noscript", "select", "textarea", "svg"}
)
BLOCK_TAGS: Final = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "br",
        "caption",
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
        "h5",
        "h6",
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


@dataclass(frozen=True, slots=True)
class MockupElement:
    code: str
    kind: str
    text: str
    html: str
    holds: tuple[str, ...] = ()
    depth: int = 0

    @property
    def label(self) -> str:
        return self.text or self.code

    @property
    def zone(self) -> bool:
        return self.kind == ZONE


@dataclass(frozen=True, slots=True)
class MockupScreen:
    code: str
    title: str
    html: str
    elements: tuple[MockupElement, ...] = ()

    @property
    def label(self) -> str:
        return clipped(self.title, LABEL_LIMIT) or self.code

    def element(self, code: str) -> MockupElement | None:
        return next((item for item in self.elements if item.code == code), None)


@dataclass(slots=True, eq=False)
class _Node:
    tag: str
    attributes: dict[str, str]
    parent: _Node | None
    start: int
    end: int = -1
    children: list[_Node | str] = field(default_factory=list)


class _MockupParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.lines = [
            0,
            *(index + 1 for index, character in enumerate(source) if character == "\n"),
        ]
        self.root = _Node("", {}, None, 0, len(source))
        self.stack: list[_Node] = [self.root]
        self.labels: list[_Node] = []
        self.ids: dict[str, _Node] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self.opened(tag, attrs)
        if tag in VOID_TAGS:
            node.end = node.start + len(self.get_starttag_text() or "")
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self.opened(tag, attrs)
        node.end = node.start + len(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag != tag:
                continue
            closing = self.source.find(">", self.position())
            end = len(self.source) if closing < 0 else closing + 1
            for node in self.stack[depth:]:
                node.end = end
            del self.stack[depth:]
            return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def opened(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        parent = self.stack[-1]
        attributes: dict[str, str] = {}
        for name, value in attrs:
            attributes.setdefault(name, value or "")
        node = _Node(tag, attributes, parent, self.position())
        parent.children.append(node)
        if tag == "label":
            self.labels.append(node)
        identifier = attributes.get("id")
        if identifier:
            self.ids.setdefault(identifier, node)
        return node

    def position(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def finish(self) -> None:
        self.close()
        for node in self.stack[1:]:
            node.end = len(self.source)
        del self.stack[1:]


def document_screens(document: Mapping[str, object] | None) -> tuple[MockupScreen, ...]:
    html = None if document is None else document.get("html")
    return mockup_screens(html) if isinstance(html, str) else ()


def mockup_screens(html: str) -> tuple[MockupScreen, ...]:
    parser = _MockupParser(html)
    parser.feed(html)
    parser.finish()
    return tuple(_screen(parser, node) for node in _descendants(parser.root) if _is_screen(node))


def _screen(parser: _MockupParser, node: _Node) -> MockupScreen:
    parts: dict[str, MockupElement] = {}
    for part in _parts(parser, node):
        parts.setdefault(part.code, part)
    return MockupScreen(
        code=node.attributes["id"],
        title=_normalized(node.attributes.get("aria-label", "")),
        html=_outer(parser, node),
        elements=tuple(parts.values()),
    )


def _parts(parser: _MockupParser, screen: _Node) -> Iterator[MockupElement]:
    for node in _descendants(screen):
        element = node.attributes.get(ELEMENT_MARK)
        code = element or node.attributes.get(ZONE_MARK)
        if not code or _closest_screen(node) is not screen:
            continue
        depth = sum(ZONE_MARK in item.attributes for item in _ancestors(node))
        html = _outer(parser, node)
        if element:
            yield MockupElement(code, node.tag, _first(_names(parser, node)), html, depth=depth)
        else:
            text = _first(_zone_names(parser, node))
            yield MockupElement(code, ZONE, text, html, _held(node), depth)


def _held(node: _Node) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            code for item in _descendants(node) if (code := item.attributes.get(ELEMENT_MARK))
        )
    )


def _outer(parser: _MockupParser, node: _Node) -> str:
    return clipped(parser.source[node.start : node.end], HTML_LIMIT)


def _descendants(node: _Node) -> Iterator[_Node]:
    pending = [child for child in reversed(node.children) if isinstance(child, _Node)]
    while pending:
        current = pending.pop()
        yield current
        pending.extend(child for child in reversed(current.children) if isinstance(child, _Node))


def _ancestors(node: _Node) -> Iterator[_Node]:
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def _is_screen(node: _Node) -> bool:
    return node.tag == "section" and SCREEN_ID.fullmatch(node.attributes.get("id", "")) is not None


def _closest(node: _Node, tag: str) -> _Node | None:
    return next((item for item in (node, *_ancestors(node)) if item.tag == tag), None)


def _closest_screen(node: _Node) -> _Node | None:
    return next((item for item in _ancestors(node) if _is_screen(item)), None)


def _first(texts: Iterator[str]) -> str:
    return clipped(next((text for text in texts if text), ""), LABEL_LIMIT)


def _names(parser: _MockupParser, node: _Node) -> Iterator[str]:
    yield _own_text(node)
    yield _referenced_text(parser, node)
    yield _normalized(node.attributes.get("aria-label", ""))
    yield _label_text(parser, node)
    for name in NAME_ATTRIBUTES:
        yield _normalized(node.attributes.get(name, ""))


def _zone_names(parser: _MockupParser, node: _Node) -> Iterator[str]:
    yield _normalized(node.attributes.get("aria-label", ""))
    yield _referenced_text(parser, node)
    for child in node.children:
        if isinstance(child, _Node) and child.tag in CAPTIONS:
            yield _own_text(child)
    for item in _descendants(node):
        if item.tag in HEADINGS:
            yield _own_text(item)
    yield _own_text(node)


def _referenced_text(parser: _MockupParser, node: _Node) -> str:
    references = node.attributes.get("aria-labelledby", "").split()
    return _normalized(
        " ".join(_own_text(parser.ids[name]) for name in references if name in parser.ids)
    )


def _label_text(parser: _MockupParser, node: _Node) -> str:
    identifier = node.attributes.get("id")
    labels = [
        label
        for label in parser.labels
        if identifier is not None and label.attributes.get("for") == identifier
    ]
    owner = _closest(node, "label")
    if owner is not None:
        labels.append(owner)
    return _normalized(" ".join(_own_text(label) for label in labels))


def _own_text(node: _Node) -> str:
    if node.tag == "select":
        options = [item for item in _descendants(node) if item.tag == "option"]
        selected = next(
            (item for item in options if "selected" in item.attributes),
            options[0] if options else None,
        )
        return "" if selected is None else _normalized(_content(selected))
    if node.tag == "textarea":
        return _normalized(_content(node))
    parts: list[str] = []
    _collect(node, parts)
    return _normalized("".join(parts))


def _collect(node: _Node, parts: list[str]) -> None:
    after_element = False
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
            after_element = False
            continue
        if after_element:
            parts.append(" ")
        after_element = True
        if _silent(child):
            continue
        spacer = " " if child.tag in BLOCK_TAGS else ""
        parts.append(spacer)
        _collect(child, parts)
        parts.append(spacer)


def _silent(node: _Node) -> bool:
    return (
        node.tag in SILENT_TAGS
        or "hidden" in node.attributes
        or PIN_CLASS in node.attributes.get("class", "").split()
    )


def _content(node: _Node) -> str:
    return "".join(child if isinstance(child, str) else _content(child) for child in node.children)
