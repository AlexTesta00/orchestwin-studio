from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final

from orchestwin.artifacts.generated_mockup_review import is_dated_background
from orchestwin.artifacts.generated_mockup_styles import (
    MAX_BLOCK_DEPTH,
    GeneratedMockupError,
    StyleSheet,
    has_forbidden_character,
    parse_style_sheet,
)
from orchestwin.artifacts.generated_mockups import (
    _CLASS,
    _HREF,
    _IDENTIFIER,
    _REQUIREMENTS,
    ALLOWED_ELEMENTS,
    BOOLEAN_ATTRIBUTES,
    INPUT_TYPES,
    MAX_DEPTH,
    REFERENCE_ATTRIBUTES,
    SVG_ELEMENTS,
    MarkupElement,
    MarkupNode,
    MarkupText,
    _allowed_attribute,
    _Context,
    _value_rule,
    parse_markup,
    serialize_markup,
)

ELEMENT_REMOVED: Final = "ELEMENT_REMOVED"
ELEMENT_UNWRAPPED: Final = "ELEMENT_UNWRAPPED"
ATTRIBUTE_REMOVED: Final = "ATTRIBUTE_REMOVED"
LINK_REMOVED: Final = "LINK_REMOVED"
REQUIREMENT_CODE_REMOVED: Final = "REQUIREMENT_CODE_REMOVED"
REQUIREMENT_INHERITED: Final = "REQUIREMENT_INHERITED"
STYLE_DECLARATION_REMOVED: Final = "STYLE_DECLARATION_REMOVED"
STYLE_RULE_REMOVED: Final = "STYLE_RULE_REMOVED"
STYLE_REST_REMOVED: Final = "STYLE_REST_REMOVED"
REPAIR_NOTE_CODES: Final = (
    ELEMENT_REMOVED,
    ELEMENT_UNWRAPPED,
    ATTRIBUTE_REMOVED,
    LINK_REMOVED,
    REQUIREMENT_CODE_REMOVED,
    REQUIREMENT_INHERITED,
    STYLE_DECLARATION_REMOVED,
    STYLE_RULE_REMOVED,
    STYLE_REST_REMOVED,
)
MAX_NOTE_NAME_LENGTH: Final = 80
MAX_READ_DEPTH: Final = 4 * MAX_DEPTH
REMOVED_ELEMENTS: Final = frozenset(
    {
        "animate",
        "animatemotion",
        "animatetransform",
        "applet",
        "area",
        "audio",
        "base",
        "basefont",
        "bgsound",
        "canvas",
        "datalist",
        "dialog",
        "discard",
        "embed",
        "fencedframe",
        "foreignobject",
        "frame",
        "frameset",
        "iframe",
        "image",
        "img",
        "link",
        "map",
        "meta",
        "mpath",
        "noembed",
        "noframes",
        "noscript",
        "object",
        "param",
        "picture",
        "portal",
        "script",
        "set",
        "slot",
        "source",
        "style",
        "template",
        "title",
        "track",
        "use",
        "video",
    }
)
NOTED_ATTRIBUTES: Final = frozenset(
    {
        "style",
        "src",
        "srcset",
        "action",
        "formaction",
        "target",
        "download",
        "ping",
        "srcdoc",
        "xlink:href",
    }
)
_VOID_TAGS: Final = frozenset(
    {
        "area",
        "base",
        "basefont",
        "bgsound",
        "br",
        "col",
        "embed",
        "frame",
        "hr",
        "image",
        "img",
        "input",
        "keygen",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_TRACED: Final = frozenset({"a", "button", "input", "select", "textarea"})
_RULE_LISTS: Final = frozenset({"media", "supports", "container", "layer", "keyframes"})
_ASCII_SPACE: Final = re.compile(r"[ \t\n\f\r]+")
_CODE_SEPARATOR: Final = re.compile(r"[\s,;]+")
_UNPRINTABLE: Final = re.compile(r"[^\x20-\x7e]")
_AT_NAME: Final = re.compile(r"-?[A-Za-z_\u0080-\U0010ffff][A-Za-z0-9_\-\u0080-\U0010ffff]*")
_CUSTOM_NAME: Final = re.compile(r"--m-[a-z0-9]+(?:-[a-z0-9]+)*")
_CSS_BLANK: Final = " \t\n"
_EMPTY_NAME: Final = "(empty)"

Entry = tuple[str, str | None, str]


@dataclass(frozen=True, slots=True)
class RepairNote:
    code: str
    screen_code: str | None
    name: str
    count: int

    @property
    def detail(self) -> str:
        return self.name if self.count == 1 else f"{self.name} ({self.count})"

    def to_snapshot(self) -> dict[str, object]:
        return {"code": self.code, "screen_code": self.screen_code, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class MockupRepair:
    styles: str
    markups: tuple[str, ...]
    notes: tuple[RepairNote, ...]


def _name(value: object) -> str:
    text = _UNPRINTABLE.sub("?", " ".join(str(value or "").split()))
    return text[:MAX_NOTE_NAME_LENGTH] or _EMPTY_NAME


def _notes(entries: Iterable[Entry]) -> tuple[RepairNote, ...]:
    counted = Counter(entries)
    notes = (
        RepairNote(code, screen_code, name, number)
        for (code, screen_code, name), number in counted.items()
    )
    return tuple(sorted(notes, key=lambda note: (note.screen_code or "", note.code, note.name)))


def _tokens(value: str) -> list[str]:
    return [token for token in _ASCII_SPACE.split(value) if token]


class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str, list[tuple[str, str | None]], bool]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append(("start", tag, attrs, False))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.events.append(("start", tag, attrs, True))

    def handle_endtag(self, tag: str) -> None:
        self.events.append(("end", tag, [], False))

    def handle_data(self, data: str) -> None:
        self.events.append(("data", data, [], False))


class _Node:
    __slots__ = ("attributes", "children", "name")

    def __init__(self, name: str, attributes: list[tuple[str, str | None]]) -> None:
        self.name = name
        self.attributes = attributes
        self.children: list[_Node | str] = []

    def get(self, name: str) -> str | None:
        return next((value for key, value in self.attributes if key == name), None)

    def put(self, name: str, value: str) -> None:
        self.drop(name)
        self.attributes.append((name, value))

    def drop(self, name: str) -> None:
        self.attributes = [(key, value) for key, value in self.attributes if key != name]


def _read(markup: str) -> list[_Node | str] | None:
    reader = _Reader()
    try:
        reader.feed(markup)
        reader.close()
    except AssertionError:
        return None
    root = _Node("", [])
    stack = [root]
    for kind, value, attributes, closed in reader.events:
        parent = stack[-1]
        if kind == "data":
            parent.children.append(value)
        elif kind == "start":
            node = _Node(value, attributes)
            parent.children.append(node)
            if not closed and value not in _VOID_TAGS:
                if len(stack) > MAX_READ_DEPTH:
                    return None
                stack.append(node)
        elif value in _VOID_TAGS:
            continue
        elif len(stack) > 1 and parent.name == value:
            stack.pop()
        else:
            return None
    return root.children if len(stack) == 1 else None


def _hidden_input(node: _Node) -> bool:
    kind = next((value for key, value in node.attributes if key == "type"), None)
    return node.name == "input" and kind is not None and kind.lower() == "hidden"


class _ScreenCleaner:
    def __init__(
        self,
        screen_code: str,
        screen_codes: frozenset[str],
        known: frozenset[str],
        token_names: frozenset[str],
        entries: list[Entry],
    ) -> None:
        self.screen_code = screen_code
        self.screen_codes = screen_codes
        self.known = known
        self.context = _Context(screen_code, screen_codes, token_names)
        self.entries = entries

    def note(self, code: str, name: object) -> None:
        self.entries.append((code, self.screen_code, _name(name)))

    def nodes(self, children: Iterable[_Node | str], svg: bool) -> list[_Node | str]:
        result: list[_Node | str] = []
        for child in children:
            if isinstance(child, str):
                result.append(child)
            elif (
                (svg and child.name not in SVG_ELEMENTS)
                or child.name in REMOVED_ELEMENTS
                or _hidden_input(child)
            ):
                self.note(ELEMENT_REMOVED, child.name)
            elif child.name not in ALLOWED_ELEMENTS:
                self.note(ELEMENT_UNWRAPPED, child.name)
                result.extend(self.nodes(child.children, svg))
            else:
                node = _Node(child.name, self.attributes(child))
                node.children = self.nodes(child.children, svg or child.name == "svg")
                result.append(node)
        return result

    def attributes(self, node: _Node) -> list[tuple[str, str | None]]:
        kept: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        for name, value in node.attributes:
            if name in seen:
                continue
            seen.add(name)
            if not _allowed_attribute(node.name, name):
                if name in NOTED_ATTRIBUTES or name.startswith("on"):
                    self.note(ATTRIBUTE_REMOVED, name)
                continue
            accepted, cleaned = self.value(node.name, name, value)
            if accepted:
                kept.append((name, cleaned))
        return kept

    def value(self, element: str, name: str, value: str | None) -> tuple[bool, str | None]:
        if name in BOOLEAN_ATTRIBUTES:
            return True, None
        if value is None or has_forbidden_character(value):
            return self.refused(name, value)
        if name == "id":
            valid = _IDENTIFIER.fullmatch(value) is not None and not value.startswith("ot-")
            return valid, value
        if name == "class":
            tokens = [
                token
                for token in _tokens(value)
                if _CLASS.fullmatch(token) is not None and not token.startswith("ot-")
            ]
            return bool(tokens), " ".join(tokens)
        if name == "data-req":
            return self.requirements(value)
        if name == "href":
            match = _HREF.fullmatch(value)
            if match is not None and match.group(1) in self.screen_codes:
                return True, value
            return self.refused(name, value)
        if name in REFERENCE_ATTRIBUTES:
            identifiers = _tokens(value)
            valid = (
                bool(identifiers)
                and all(_IDENTIFIER.fullmatch(identifier) for identifier in identifiers)
                and (name != "for" or len(identifiers) == 1)
            )
            return valid, value
        if name == "type" and element == "input":
            return True, value if value in INPUT_TYPES else "text"
        if name == "type" and element == "button":
            return True, "button"
        rule = _value_rule(element, name)
        return rule is None or rule(value, self.context), value

    def refused(self, name: str, value: str | None) -> tuple[bool, None]:
        if name == "href":
            self.note(LINK_REMOVED, value)
        elif name == "data-req":
            self.note(REQUIREMENT_CODE_REMOVED, value)
        return False, None

    def requirements(self, value: str) -> tuple[bool, str]:
        codes: list[str] = []
        for token in _CODE_SEPARATOR.split(value):
            if not token:
                continue
            if token in self.known and _REQUIREMENTS.fullmatch(token) is not None:
                if token not in codes:
                    codes.append(token)
            else:
                self.note(REQUIREMENT_CODE_REMOVED, token)
        if not value.strip():
            self.note(REQUIREMENT_CODE_REMOVED, None)
        return bool(codes), " ".join(codes)


def _elements(nodes: Iterable[_Node | str]) -> Iterator[_Node]:
    for node in nodes:
        if isinstance(node, _Node):
            yield node
            yield from _elements(node.children)


def _traced(nodes: Iterable[_Node | str], codes: str | None) -> Iterator[tuple[_Node, str | None]]:
    for node in nodes:
        if isinstance(node, _Node):
            own = node.get("data-req") or codes
            yield node, own
            yield from _traced(node.children, own)


def _fresh(identifier: str, taken: set[str]) -> str:
    number = 2
    while (candidate := f"{identifier[: 63 - len(str(number))]}-{number}") in taken:
        number += 1
    return candidate


def _identify(trees: Sequence[list[_Node | str] | None]) -> None:
    taken = {
        identifier
        for tree in trees
        if tree is not None
        for node in _elements(tree)
        if (identifier := node.get("id")) is not None
    }
    used: set[str] = set()
    for tree in trees:
        if tree is None:
            continue
        local: dict[str, str] = {}
        for node in _elements(tree):
            identifier = node.get("id")
            if identifier is None:
                continue
            if identifier in local:
                node.drop("id")
            elif identifier in used:
                renamed = _fresh(identifier, taken)
                taken.add(renamed)
                used.add(renamed)
                local[identifier] = renamed
                node.put("id", renamed)
            else:
                used.add(identifier)
                local[identifier] = identifier
        for node in _elements(tree):
            for name in sorted(REFERENCE_ATTRIBUTES):
                value = node.get(name)
                if value is None:
                    continue
                identifiers = _tokens(value)
                mapped = [local[item] for item in identifiers if item in local]
                if not mapped:
                    node.drop(name)
                elif mapped != identifiers:
                    node.put(name, " ".join(mapped))


def _named_codes(tree: list[_Node | str]) -> tuple[str, ...]:
    return tuple(
        sorted({code for node in _elements(tree) for code in (node.get("data-req") or "").split()})
    )


def _trace(
    trees: Sequence[list[_Node | str] | None],
    screen_codes: Sequence[str],
    declared: Sequence[str],
    entries: list[Entry],
) -> None:
    named = [() if tree is None else _named_codes(tree) for tree in trees]
    for code, tree, codes in zip(screen_codes, trees, named, strict=True):
        if tree is None or not codes:
            continue
        joined = " ".join(codes)
        for node, own in list(_traced(tree, None)):
            if node.name in _TRACED and own is None:
                node.put("data-req", joined)
                entries.append((REQUIREMENT_INHERITED, code, _name(joined)))
    for code, tree, codes in zip(screen_codes, trees, named, strict=True):
        if tree is None or codes:
            continue
        incoming = {
            item
            for other in trees
            if other is not None and other is not tree
            for node, own in _traced(other, None)
            if node.name == "a" and node.get("href") == f"#{code}" and own
            for item in own.split()
        }
        inherited = sorted(incoming) or list(declared)
        if not inherited:
            continue
        joined = " ".join(inherited)
        for node in tree:
            if isinstance(node, _Node):
                node.put("data-req", joined)
                entries.append((REQUIREMENT_INHERITED, code, _name(joined)))


def _frozen(nodes: Iterable[_Node | str]) -> tuple[MarkupNode, ...]:
    result: list[MarkupNode] = []
    for node in nodes:
        if isinstance(node, str):
            if not node:
                continue
            if result and isinstance(result[-1], MarkupText):
                result[-1] = MarkupText(result[-1].text + node)
            else:
                result.append(MarkupText(node))
        else:
            attributes = tuple(sorted(node.attributes, key=lambda item: item[0]))
            result.append(MarkupElement(node.name, attributes, _frozen(node.children)))
    return tuple(result)


def _written(
    code: str,
    markup: str,
    tree: list[_Node | str] | None,
    screen_codes: frozenset[str],
    token_names: frozenset[str],
) -> str:
    if tree is None:
        return markup
    repaired = serialize_markup(_frozen(tree))
    try:
        stored = serialize_markup(
            parse_markup(
                markup, screen_code=code, screen_codes=screen_codes, token_names=token_names
            )
        )
    except GeneratedMockupError:
        return repaired
    return markup if stored == repaired else repaired


class _Unreadable(Exception):
    def __init__(self, position: int) -> None:
        super().__init__(position)
        self.position = position


@dataclass(eq=False, slots=True)
class _Item:
    start: int
    stop: int
    nested: bool
    text: str
    removed: bool = False

    @property
    def property(self) -> str:
        return self.text.split(":", 1)[0].strip()


@dataclass(eq=False, slots=True)
class _Statement:
    start: int
    stop: int
    kind: str
    prelude: str = ""
    name: str = ""
    block: bool = False
    silent: bool = False
    items: list[_Item] = field(default_factory=list)
    children: list[_Statement] = field(default_factory=list)
    removed: bool = False

    def sheet(self) -> str:
        return f"@{self.name}{self.prelude}" + ("{}" if self.block else ";")


class _SheetReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.comments: set[tuple[int, int]] = set()

    def string_end(self, index: int, end: int) -> int:
        quote = self.text[index]
        position = index + 1
        while position < end:
            character = self.text[position]
            if character == "\\":
                position += 2
            elif character == quote:
                return position + 1
            elif character == "\n":
                return position
            else:
                position += 1
        return end

    def comment_end(self, index: int) -> int:
        close = self.text.find("*/", index + 2)
        if close < 0:
            raise _Unreadable(index)
        self.comments.add((index, close + 2))
        return close + 2

    def blank(self, position: int, end: int, *, semicolons: bool = False) -> int:
        while position < end:
            character = self.text[position]
            if character in _CSS_BLANK or (semicolons and character == ";"):
                position += 1
            elif self.text.startswith("/*", position):
                position = self.comment_end(position)
            else:
                break
        return position

    def scan(self, position: int, end: int, stops: str) -> tuple[int, str | None]:
        depth = 0
        text = self.text
        while position < end:
            character = text[position]
            if character in "\"'":
                position = self.string_end(position, end)
                continue
            if text.startswith("/*", position):
                position = self.comment_end(position)
                continue
            if character == "\\":
                position += 2
                continue
            if character in "([":
                depth += 1
            elif character in ")]":
                depth = max(depth - 1, 0)
            elif character in stops and (character != ";" or depth == 0):
                return position, character
            position += 1
        return end, None

    def block_end(self, index: int) -> int | None:
        depth = 0
        position = index
        text = self.text
        try:
            while position < len(text):
                character = text[position]
                if character in "\"'":
                    position = self.string_end(position, len(text))
                    continue
                if text.startswith("/*", position):
                    position = self.comment_end(position)
                    continue
                if character == "\\":
                    position += 2
                    continue
                if character == "{":
                    depth += 1
                elif character == "}":
                    depth -= 1
                    if depth == 0:
                        return position
                position += 1
        except _Unreadable:
            return None
        return None

    def rules(self, start: int, end: int, depth: int) -> tuple[list[_Statement], int | None]:
        statements: list[_Statement] = []
        position = start
        while True:
            try:
                position = self.blank(position, end)
            except _Unreadable as error:
                return statements, error.position
            if position >= end:
                return statements, None
            try:
                statement = self.statement(position, end, depth)
            except _Unreadable:
                return statements, position
            statements.append(statement)
            position = statement.stop

    def statement(self, position: int, end: int, depth: int) -> _Statement:
        text = self.text
        if text[position] in "};":
            return _Statement(position, position + 1, "junk", silent=True)
        match = _AT_NAME.match(text, position + 1) if text[position] == "@" else None
        if match is not None:
            return self.at_rule(position, match.end(), end, depth)
        stop, found = self.scan(position, end, "{};")
        if found == "{":
            close = self.block_end(stop)
            if close is None:
                raise _Unreadable(position)
            statement = _Statement(position, close + 1, "rule", prelude=text[position:stop])
            statement.items = self.items(stop + 1, close)
            return statement
        if found is None:
            return _Statement(position, end, "junk", prelude=text[position:end])
        return _Statement(position, stop + 1, "junk", prelude=text[position:stop])

    def at_rule(self, position: int, name_end: int, end: int, depth: int) -> _Statement:
        text = self.text
        name = text[position + 1 : name_end].lower()
        stop, found = self.scan(name_end, end, "{};")
        prelude = text[name_end:stop]
        if found == "}":
            return _Statement(position, stop + 1, "junk", prelude=text[position:stop])
        if found != "{":
            closing = stop if found is None else stop + 1
            return _Statement(position, closing, "at", prelude=prelude, name=name)
        close = self.block_end(stop)
        if close is None:
            raise _Unreadable(position)
        statement = _Statement(position, close + 1, "at", prelude=prelude, name=name, block=True)
        if name in _RULE_LISTS and depth < MAX_BLOCK_DEPTH:
            statement.children, rest = self.rules(stop + 1, close, depth + 1)
            if rest is not None:
                statement.children.append(_Statement(rest, close, "junk", prelude=text[rest:close]))
        return statement

    def items(self, start: int, end: int) -> list[_Item]:
        items: list[_Item] = []
        position = start
        while True:
            position = self.blank(position, end, semicolons=True)
            if position >= end:
                return items
            stop, found = self.scan(position, end, "{;")
            if found == "{":
                close = self.block_end(stop)
                closing = end if close is None or close >= end else close + 1
                items.append(_Item(position, closing, True, self.text[position:stop]))
                position = closing
            elif found == ";":
                items.append(_Item(position, stop + 1, False, self.text[position:stop]))
                position = stop + 1
            else:
                items.append(_Item(position, end, False, self.text[position:end]))
                position = end


def _cut(text: str, spans: Iterable[tuple[int, int]]) -> str:
    pieces: list[str] = []
    position = 0
    for start, stop in sorted(spans):
        if stop <= position:
            continue
        if start > position:
            pieces.append(text[position:start])
        position = stop
    pieces.append(text[position:])
    return "".join(pieces)


class _StyleRepair:
    def __init__(self, text: str, token_names: frozenset[str]) -> None:
        self.text = text
        self.token_names = token_names
        self.reader = _SheetReader(text)
        self.entries: list[Entry] = []
        self.declarations: list[_Item] = []
        self.results: dict[tuple[str, frozenset[str]], bool] = {}

    def note(self, code: str, name: object) -> None:
        self.entries.append((code, None, _name(name)))

    def accepts(self, sheet: str) -> StyleSheet | None:
        try:
            return parse_style_sheet(sheet, token_names=self.token_names)
        except GeneratedMockupError:
            return None

    def run(self) -> str:
        statements, rest = self.reader.rules(0, len(self.text), 0)
        for statement in statements:
            self.check(statement, keyframes=False, depth=0)
        self.settle_declarations()
        self.settle(statements)
        spans = set(self.reader.comments)
        self.spans(statements, spans)
        if rest is not None:
            spans.add((rest, len(self.text)))
            self.note(STYLE_REST_REMOVED, self.text[rest : rest + MAX_NOTE_NAME_LENGTH])
        return _cut(self.text, spans)

    def check(self, statement: _Statement, *, keyframes: bool, depth: int) -> None:
        if statement.kind == "junk":
            statement.removed = True
            if not statement.silent:
                self.note(STYLE_RULE_REMOVED, statement.prelude)
            return
        if statement.kind == "at":
            if (
                keyframes
                or (statement.block and depth >= MAX_BLOCK_DEPTH)
                or self.accepts(statement.sheet()) is None
            ):
                statement.removed = True
                self.note(STYLE_RULE_REMOVED, f"@{statement.name}")
                return
            for child in statement.children:
                self.check(child, keyframes=statement.name == "keyframes", depth=depth + 1)
            return
        selector = (
            f"@keyframes k{{{statement.prelude}{{}}}}" if keyframes else f"{statement.prelude}{{}}"
        )
        if self.accepts(selector) is None:
            statement.removed = True
            self.note(STYLE_RULE_REMOVED, statement.prelude)
            return
        for item in statement.items:
            if item.nested:
                item.removed = True
                self.note(STYLE_RULE_REMOVED, item.text)
            else:
                self.declarations.append(item)

    def valid(self, item: _Item, declared: frozenset[str]) -> bool:
        wanted = frozenset(_CUSTOM_NAME.findall(item.text)) & declared
        key = (item.text, wanted)
        if key not in self.results:
            definitions = "".join(f"{name}:0;" for name in sorted(wanted))
            sheet = self.accepts(".m{" + definitions + item.text + "}")
            found = () if sheet is None else sheet.rules[0].declarations
            self.results[key] = bool(found) and not is_dated_background(found[-1])
        return self.results[key]

    def settle_declarations(self) -> None:
        declared = frozenset(
            item.property for item in self.declarations if item.property.startswith("--")
        )
        while True:
            for item in self.declarations:
                item.removed = not self.valid(item, declared)
            current = frozenset(
                item.property
                for item in self.declarations
                if not item.removed and item.property.startswith("--")
            )
            if current == declared:
                break
            declared = current
        for item in self.declarations:
            if item.removed:
                self.note(STYLE_DECLARATION_REMOVED, item.property)

    def settle(self, statements: Iterable[_Statement]) -> bool:
        kept = False
        for statement in statements:
            if statement.removed:
                continue
            if statement.kind == "rule" and statement.items:
                statement.removed = all(item.removed for item in statement.items)
            elif statement.kind == "at" and statement.children:
                statement.removed = not self.settle(statement.children)
            kept = kept or not statement.removed
        return kept

    def spans(self, statements: Iterable[_Statement], spans: set[tuple[int, int]]) -> None:
        for statement in statements:
            if statement.removed:
                spans.add((statement.start, statement.stop))
            elif statement.kind == "rule":
                spans.update((item.start, item.stop) for item in statement.items if item.removed)
            else:
                self.spans(statement.children, spans)


def _accepted_sheet(styles: str, token_names: frozenset[str]) -> bool:
    try:
        sheet = parse_style_sheet(styles, token_names=token_names)
    except GeneratedMockupError:
        return False
    return not any(
        is_dated_background(declaration)
        for rule in sheet.rules
        for declaration in rule.declarations
    )


def _repair_styles(styles: str, token_names: frozenset[str]) -> tuple[str, list[Entry]]:
    if _accepted_sheet(styles, token_names):
        return styles, []
    repair = _StyleRepair(styles.replace("\r\n", "\n").replace("\r", "\n"), token_names)
    return repair.run(), repair.entries


def repair_styles(styles: str, *, token_names: Iterable[str]) -> tuple[str, tuple[RepairNote, ...]]:
    text, entries = _repair_styles(styles, frozenset(token_names))
    return text, _notes(entries)


def repair_generated_mockup(
    *,
    styles: str,
    screens: Sequence[tuple[str, str]],
    requirement_codes: Iterable[str],
    token_names: Iterable[str],
    declared_codes: Iterable[str] = (),
) -> MockupRepair:
    names = frozenset(token_names)
    known = frozenset(requirement_codes)
    declared = sorted(
        {code for code in declared_codes if code in known and _REQUIREMENTS.fullmatch(code)}
    )
    codes = [code for code, _markup in screens]
    screen_codes = frozenset(codes)
    repaired_styles, entries = _repair_styles(styles, names)
    trees: list[list[_Node | str] | None] = []
    for code, markup in screens:
        read = _read(markup.replace("\r\n", "\n").replace("\r", "\n"))
        cleaner = _ScreenCleaner(code, screen_codes, known, names, entries)
        trees.append(None if read is None else cleaner.nodes(read, False))
    _identify(trees)
    _trace(trees, codes, declared, entries)
    markups = tuple(
        _written(code, markup, tree, screen_codes, names)
        for (code, markup), tree in zip(screens, trees, strict=True)
    )
    return MockupRepair(styles=repaired_styles, markups=markups, notes=_notes(entries))


__all__ = [
    "ATTRIBUTE_REMOVED",
    "ELEMENT_REMOVED",
    "ELEMENT_UNWRAPPED",
    "LINK_REMOVED",
    "MAX_NOTE_NAME_LENGTH",
    "MAX_READ_DEPTH",
    "NOTED_ATTRIBUTES",
    "REMOVED_ELEMENTS",
    "REPAIR_NOTE_CODES",
    "REQUIREMENT_CODE_REMOVED",
    "REQUIREMENT_INHERITED",
    "STYLE_DECLARATION_REMOVED",
    "STYLE_REST_REMOVED",
    "STYLE_RULE_REMOVED",
    "MockupRepair",
    "RepairNote",
    "repair_generated_mockup",
    "repair_styles",
]
