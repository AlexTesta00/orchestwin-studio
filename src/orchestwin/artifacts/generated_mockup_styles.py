from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from orchestwin.artifacts.visual_language import _TOKEN_NAME

MAX_STYLES_LENGTH: Final = 60_000
MAX_DETAIL_NAME_LENGTH: Final = 40
MAX_NESTING: Final = 32
MAX_BLOCK_DEPTH: Final = 16
FORBIDDEN_CHARACTERS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f\ud800-\udfff]")
_SPACED_FUNCTION: Final = re.compile(r"(url|image-set|src|expression|env)\s+\(", re.IGNORECASE)

_FORBIDDEN_CONSTRUCTS: Final = (
    "\\",
    "url(",
    "image-set(",
    "src(",
    "expression(",
    "env(",
    "<",
    "javascript:",
    "-moz-binding",
    "@import",
    "@font-face",
    "@namespace",
    "@charset",
    "@document",
    "@page",
    "@property",
    "@counter-style",
    "@font-feature-values",
)
_FORBIDDEN_PROPERTIES: Final = frozenset({"behavior", "-ms-behavior"})
_ALLOWED_AT_RULES: Final = frozenset({"media", "supports", "keyframes", "container", "layer"})
_WHITESPACE: Final = " \t\n\r\f"
_DIGITS: Final = frozenset("0123456789")
_SINGLE: Final = {
    "(": "(",
    ")": ")",
    "[": "[",
    "]": "]",
    "{": "{",
    "}": "}",
    ",": "comma",
    ";": "semicolon",
    ":": "colon",
}
_NAME: Final = re.compile(r"[A-Za-z0-9_\-\u0080-\U0010ffff]+")
_NUMBER: Final = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_INTEGER: Final = re.compile(r"[+-]?[0-9]+")
_CUSTOM_PROPERTY: Final = re.compile(r"--m-[a-z0-9]+(?:-[a-z0-9]+)*")
_PROPERTY: Final = re.compile(r"-?[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_DETAIL: Final = re.compile(r"[^A-Za-z0-9:_#.\-]")

COLOUR_FUNCTIONS: Final = frozenset(
    {
        "rgb",
        "rgba",
        "hsl",
        "hsla",
        "hwb",
        "lab",
        "lch",
        "oklab",
        "oklch",
        "color",
        "device-cmyk",
        "light-dark",
        "color-contrast",
        "contrast-color",
    }
)
GRADIENT_FUNCTIONS: Final = frozenset(
    {
        "linear-gradient",
        "radial-gradient",
        "conic-gradient",
        "repeating-linear-gradient",
        "repeating-radial-gradient",
        "repeating-conic-gradient",
    }
)
VALUE_FUNCTIONS: Final = frozenset(
    {
        "var",
        "calc",
        "min",
        "max",
        "clamp",
        "round",
        "mod",
        "rem",
        "abs",
        "sign",
        "pow",
        "sqrt",
        "hypot",
        "log",
        "exp",
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "atan2",
        "color-mix",
        "translate",
        "translatex",
        "translatey",
        "translatez",
        "translate3d",
        "rotate",
        "rotatex",
        "rotatey",
        "rotatez",
        "rotate3d",
        "scale",
        "scalex",
        "scaley",
        "scalez",
        "scale3d",
        "skew",
        "skewx",
        "skewy",
        "matrix",
        "matrix3d",
        "perspective",
        "cubic-bezier",
        "steps",
        "linear",
        "repeat",
        "minmax",
        "fit-content",
        "attr",
        "counter",
        "counters",
        "blur",
        "brightness",
        "contrast",
        "drop-shadow",
        "grayscale",
        "hue-rotate",
        "invert",
        "opacity",
        "saturate",
        "sepia",
        "inset",
        "circle",
        "ellipse",
        "polygon",
        "rect",
        "xywh",
        "calc-size",
        "anchor",
        "anchor-size",
        "view",
        "scroll",
    }
    | GRADIENT_FUNCTIONS
)
_COLOUR_ARGUMENT_FUNCTIONS: Final = GRADIENT_FUNCTIONS | {"drop-shadow"}
NAMED_COLOURS: Final = frozenset(
    {
        "aliceblue",
        "antiquewhite",
        "aqua",
        "aquamarine",
        "azure",
        "beige",
        "bisque",
        "black",
        "blanchedalmond",
        "blue",
        "blueviolet",
        "brown",
        "burlywood",
        "cadetblue",
        "chartreuse",
        "chocolate",
        "coral",
        "cornflowerblue",
        "cornsilk",
        "crimson",
        "cyan",
        "darkblue",
        "darkcyan",
        "darkgoldenrod",
        "darkgray",
        "darkgreen",
        "darkgrey",
        "darkkhaki",
        "darkmagenta",
        "darkolivegreen",
        "darkorange",
        "darkorchid",
        "darkred",
        "darksalmon",
        "darkseagreen",
        "darkslateblue",
        "darkslategray",
        "darkslategrey",
        "darkturquoise",
        "darkviolet",
        "deeppink",
        "deepskyblue",
        "dimgray",
        "dimgrey",
        "dodgerblue",
        "firebrick",
        "floralwhite",
        "forestgreen",
        "fuchsia",
        "gainsboro",
        "ghostwhite",
        "gold",
        "goldenrod",
        "gray",
        "green",
        "greenyellow",
        "grey",
        "honeydew",
        "hotpink",
        "indianred",
        "indigo",
        "ivory",
        "khaki",
        "lavender",
        "lavenderblush",
        "lawngreen",
        "lemonchiffon",
        "lightblue",
        "lightcoral",
        "lightcyan",
        "lightgoldenrodyellow",
        "lightgray",
        "lightgreen",
        "lightgrey",
        "lightpink",
        "lightsalmon",
        "lightseagreen",
        "lightskyblue",
        "lightslategray",
        "lightslategrey",
        "lightsteelblue",
        "lightyellow",
        "lime",
        "limegreen",
        "linen",
        "magenta",
        "maroon",
        "mediumaquamarine",
        "mediumblue",
        "mediumorchid",
        "mediumpurple",
        "mediumseagreen",
        "mediumslateblue",
        "mediumspringgreen",
        "mediumturquoise",
        "mediumvioletred",
        "midnightblue",
        "mintcream",
        "mistyrose",
        "moccasin",
        "navajowhite",
        "navy",
        "oldlace",
        "olive",
        "olivedrab",
        "orange",
        "orangered",
        "orchid",
        "palegoldenrod",
        "palegreen",
        "paleturquoise",
        "palevioletred",
        "papayawhip",
        "peachpuff",
        "peru",
        "pink",
        "plum",
        "powderblue",
        "purple",
        "rebeccapurple",
        "red",
        "rosybrown",
        "royalblue",
        "saddlebrown",
        "salmon",
        "sandybrown",
        "seagreen",
        "seashell",
        "sienna",
        "silver",
        "skyblue",
        "slateblue",
        "slategray",
        "slategrey",
        "snow",
        "springgreen",
        "steelblue",
        "tan",
        "teal",
        "thistle",
        "tomato",
        "turquoise",
        "violet",
        "wheat",
        "white",
        "whitesmoke",
        "yellow",
        "yellowgreen",
        "accentcolor",
        "accentcolortext",
        "activetext",
        "buttonborder",
        "buttonface",
        "buttontext",
        "canvas",
        "canvastext",
        "field",
        "fieldtext",
        "graytext",
        "highlight",
        "highlighttext",
        "linktext",
        "mark",
        "marktext",
        "selecteditem",
        "selecteditemtext",
        "visitedtext",
        "activeborder",
        "activecaption",
        "appworkspace",
        "background",
        "buttonhighlight",
        "buttonshadow",
        "captiontext",
        "inactiveborder",
        "inactivecaption",
        "inactivecaptiontext",
        "infobackground",
        "infotext",
        "menu",
        "menutext",
        "scrollbar",
        "threeddarkshadow",
        "threedface",
        "threedhighlight",
        "threedlightshadow",
        "threedshadow",
        "window",
        "windowframe",
        "windowtext",
    }
)
_GENERIC_FAMILIES: Final = frozenset({"monospace", "serif", "sans-serif", "system-ui"})
_FONT_TOKENS: Final = frozenset({"--vl-font-heading", "--vl-font-body", "--vl-font-mono"})
_FONT_KEYWORDS: Final = frozenset(
    {
        "inherit",
        "initial",
        "unset",
        "revert",
        "revert-layer",
        "normal",
        "italic",
        "oblique",
        "bold",
        "bolder",
        "lighter",
        "small-caps",
        "all-small-caps",
        "petite-caps",
        "all-petite-caps",
        "unicase",
        "titling-caps",
        "ultra-condensed",
        "extra-condensed",
        "condensed",
        "semi-condensed",
        "semi-expanded",
        "expanded",
        "extra-expanded",
        "ultra-expanded",
        "xx-small",
        "x-small",
        "small",
        "medium",
        "large",
        "x-large",
        "xx-large",
        "xxx-large",
        "larger",
        "smaller",
        "caption",
        "icon",
        "menu",
        "message-box",
        "small-caption",
        "status-bar",
    }
    | _GENERIC_FAMILIES
)
_Z_INDEX_KEYWORDS: Final = frozenset(
    {"auto", "inherit", "initial", "unset", "revert", "revert-layer"}
)
_COLOUR_PROPERTIES: Final = frozenset(
    {
        "box-shadow",
        "text-shadow",
        "fill",
        "stroke",
        "filter",
        "backdrop-filter",
        "text-emphasis",
        "-webkit-text-stroke",
    }
)
_COLOUR_PROPERTY_PREFIXES: Final = (
    "background",
    "border",
    "outline",
    "text-decoration",
    "column-rule",
)
_SELECTOR_ROOTS: Final = frozenset({"root", "host", "scope"})
_SELECTOR_ROOT_FUNCTIONS: Final = frozenset({"host", "host-context"})
_PROTECTED_ATTRIBUTES: Final = frozenset({"class", "id", "data-elm", "data-entry"})


class GeneratedMockupError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def detail_name(value: object) -> str:
    return _DETAIL.sub("?", str(value))[:MAX_DETAIL_NAME_LENGTH]


def has_forbidden_character(value: str) -> bool:
    return FORBIDDEN_CHARACTERS.search(value) is not None


@dataclass(frozen=True, slots=True)
class CssToken:
    kind: str
    text: str
    value: str


@dataclass(frozen=True, slots=True)
class CssBlock:
    opener: CssToken
    children: tuple[CssToken | CssBlock, ...]


CssNode = CssToken | CssBlock


@dataclass(frozen=True, slots=True)
class StyleDeclaration:
    name: str
    value: tuple[CssToken, ...]
    important: bool

    @property
    def nodes(self) -> tuple[CssNode, ...]:
        return group_tokens(self.value)


@dataclass(frozen=True, slots=True)
class StyleRule:
    selector: str
    declarations: tuple[StyleDeclaration, ...]
    in_keyframes: bool


@dataclass(frozen=True, slots=True)
class StyleSheet:
    rules: tuple[StyleRule, ...]
    media_conditions: tuple[str, ...]


def _fail(code: str, detail: str) -> GeneratedMockupError:
    return GeneratedMockupError(code, f"styles: {detail}")


def _name_start(character: str) -> bool:
    return not character.isascii() or character.isalpha() or character == "_"


def _starts_identifier(text: str, index: int) -> bool:
    if index >= len(text):
        return False
    character = text[index]
    if character == "-":
        following = text[index + 1 : index + 2]
        return following == "-" or (following != "" and _name_start(following))
    return _name_start(character)


def _starts_number(text: str, index: int) -> bool:
    first = text[index]
    second = text[index + 1 : index + 2]
    third = text[index + 2 : index + 3]
    if first in _DIGITS:
        return True
    if first in "+-":
        return second in _DIGITS or (second == "." and third in _DIGITS)
    return first == "." and second in _DIGITS


def _string_end(text: str, index: int) -> int:
    quote = text[index]
    end = index + 1
    while end < len(text) and text[end] != quote:
        if text[end] in "\n\r\f":
            raise _fail("STYLES_SYNTAX", "line break inside a string")
        if text[end] == "\\":
            raise _fail("STYLES_FORBIDDEN", "backslash")
        end += 1
    if end >= len(text):
        raise _fail("STYLES_SYNTAX", "unterminated string")
    return end + 1


def _number_token(text: str, index: int) -> tuple[CssToken, int]:
    match = _NUMBER.match(text, index)
    assert match is not None
    end = match.end()
    number = match.group()
    if _starts_identifier(text, end):
        unit = _NAME.match(text, end)
        assert unit is not None
        return CssToken("dimension", text[index : unit.end()], number), unit.end()
    if text.startswith("%", end):
        return CssToken("percentage", text[index : end + 1], number), end + 1
    return CssToken("number", number, number), end


def _next_token(text: str, index: int) -> tuple[CssToken, int]:
    character = text[index]
    if character in _WHITESPACE:
        end = index + 1
        while end < len(text) and text[end] in _WHITESPACE:
            end += 1
        return CssToken("whitespace", text[index:end], " "), end
    if text.startswith("/*", index):
        close = text.find("*/", index + 2)
        if close < 0:
            raise _fail("STYLES_SYNTAX", "unterminated comment")
        return CssToken("comment", text[index : close + 2], ""), close + 2
    if character in "\"'":
        end = _string_end(text, index)
        return CssToken("string", text[index:end], text[index + 1 : end - 1]), end
    if character in _SINGLE:
        return CssToken(_SINGLE[character], character, character), index + 1
    if character == "#":
        match = _NAME.match(text, index + 1)
        if match is not None:
            return CssToken("hash", text[index : match.end()], match.group()), match.end()
        return CssToken("delim", character, character), index + 1
    if _starts_number(text, index):
        return _number_token(text, index)
    if text.startswith("-->", index):
        raise _fail("STYLES_SYNTAX", "comment closer -->")
    if _starts_identifier(text, index):
        match = _NAME.match(text, index)
        assert match is not None
        end = match.end()
        if text.startswith("(", end):
            return CssToken("function", text[index : end + 1], match.group().lower()), end + 1
        return CssToken("ident", match.group(), match.group()), end
    if character == "@" and _starts_identifier(text, index + 1):
        match = _NAME.match(text, index + 1)
        assert match is not None
        return CssToken("at-keyword", text[index : match.end()], match.group().lower()), match.end()
    return CssToken("delim", character, character), index + 1


def tokenize_styles(text: str) -> tuple[CssToken, ...]:
    tokens: list[CssToken] = []
    index = 0
    while index < len(text):
        token, index = _next_token(text, index)
        tokens.append(token)
    return tuple(tokens)


def group_tokens(tokens: Iterable[CssToken]) -> tuple[CssNode, ...]:
    stack: list[list[CssNode]] = [[]]
    openers: list[CssToken] = []
    for token in tokens:
        if token.kind in {"function", "(", "["}:
            openers.append(token)
            stack.append([])
        elif token.kind in {")", "]"} and openers:
            children = stack.pop()
            stack[-1].append(CssBlock(openers.pop(), tuple(children)))
        else:
            stack[-1].append(token)
    while openers:
        children = stack.pop()
        stack[-1].append(CssBlock(openers.pop(), tuple(children)))
    return tuple(stack[0])


def split_commas(nodes: Iterable[CssNode]) -> list[list[CssNode]]:
    parts: list[list[CssNode]] = [[]]
    for node in nodes:
        if isinstance(node, CssToken) and node.kind == "comma":
            parts.append([])
        else:
            parts[-1].append(node)
    return parts


def significant(nodes: Iterable[CssNode]) -> list[CssNode]:
    return [
        node for node in nodes if not (isinstance(node, CssToken) and node.kind == "whitespace")
    ]


def is_function(node: CssNode, *names: str) -> bool:
    return (
        isinstance(node, CssBlock)
        and node.opener.kind == "function"
        and (not names or node.opener.value in names)
    )


def variable_reference(node: CssNode) -> str | None:
    if not is_function(node, "var"):
        return None
    assert isinstance(node, CssBlock)
    head = significant(split_commas(node.children)[0])
    if len(head) == 1 and isinstance(head[0], CssToken) and head[0].kind == "ident":
        return head[0].value
    return None


def text_of_tokens(tokens: Iterable[CssToken]) -> str:
    return " ".join("".join(token.text for token in tokens).split())


def _reject_forbidden(text: str) -> None:
    lowered = text.lower()
    for construct in _FORBIDDEN_CONSTRUCTS:
        if construct in lowered:
            raise _fail("STYLES_FORBIDDEN", construct)
    spaced = _SPACED_FUNCTION.search(text)
    if spaced is not None:
        raise _fail("STYLES_FORBIDDEN", f"{spaced.group(1).lower()}(")


def _signature(tokens: Iterable[CssToken]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for token in tokens:
        if token.kind == "whitespace":
            if not result or result[-1] != ("whitespace", " "):
                result.append(("whitespace", " "))
        else:
            result.append((token.kind, token.text))
    return result


def normalize_styles(styles: str) -> str:
    if not isinstance(styles, str):
        raise _fail("STYLES_SYNTAX", "the styles must be text")
    return _normalize(styles)


@lru_cache(maxsize=64)
def _normalize(styles: str) -> str:
    if len(styles) > MAX_STYLES_LENGTH:
        raise _fail("STYLES_TOO_LONG", f"{len(styles)} characters")
    if has_forbidden_character(styles):
        raise _fail("STYLES_CONTROL_CHARACTER", "control character")
    text = styles.replace("\r\n", "\n").replace("\r", "\n")
    _reject_forbidden(text)
    kept = [token for token in tokenize_styles(text) if token.kind != "comment"]
    normalized = "".join(token.text for token in kept)
    _reject_forbidden(normalized)
    if _signature(tokenize_styles(normalized)) != _signature(kept):
        raise _fail("STYLES_COMMENT", "a comment joins two tokens")
    return normalized


class _SheetParser:
    def __init__(self, tokens: Sequence[CssToken]) -> None:
        self.tokens = tokens
        self.index = 0
        self.depth = 0
        self.rules: list[StyleRule] = []
        self.media: list[str] = []

    def enter(self) -> None:
        self.depth += 1
        if self.depth > MAX_BLOCK_DEPTH:
            raise _fail("STYLES_SYNTAX", f"at-rules nested deeper than {MAX_BLOCK_DEPTH} levels")

    def peek(self) -> CssToken | None:
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self) -> CssToken:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def skip(self, kinds: frozenset[str] = frozenset({"whitespace"})) -> None:
        while (token := self.peek()) is not None and token.kind in kinds:
            self.index += 1

    def rule_list(self, *, nested: bool) -> None:
        while True:
            self.skip()
            token = self.peek()
            if token is None:
                if nested:
                    raise _fail("STYLES_SYNTAX", "unclosed block")
                return
            if token.kind == "}":
                if not nested:
                    raise _fail("STYLES_SYNTAX", "unexpected closing brace")
                self.index += 1
                return
            if token.kind == "at-keyword":
                self.at_rule()
            else:
                self.qualified_rule()

    def prelude(self, stops: frozenset[str]) -> tuple[CssToken, ...]:
        start = self.index
        closers: list[str] = []
        while True:
            token = self.peek()
            if token is None:
                raise _fail("STYLES_SYNTAX", "unexpected end of the styles")
            if not closers and token.kind in stops:
                return tuple(self.tokens[start : self.index])
            if token.kind in {"{", "}", "semicolon"}:
                raise _fail("STYLES_SYNTAX", f"unexpected {token.text}")
            _track(closers, token)
            self.index += 1

    def at_rule(self) -> None:
        name = self.take().value
        prelude = self.prelude(frozenset({"{", "semicolon"}))
        terminator = self.take()
        if name not in _ALLOWED_AT_RULES:
            raise _fail("STYLES_AT_RULE", f"@{detail_name(name)}")
        for token in prelude:
            if token.kind == "function" and token.value == "attr":
                raise _fail("STYLES_FORBIDDEN", "attr( in an at-rule")
        condition = text_of_tokens(prelude)
        if terminator.kind == "semicolon":
            if name != "layer" or not condition:
                raise _fail("STYLES_AT_RULE", f"@{name} needs a block")
            _check_layer_names(prelude)
            return
        self.enter()
        if name == "keyframes":
            names = significant(prelude)
            if len(names) != 1 or names[0].kind not in {"ident", "string"}:
                raise _fail("STYLES_SYNTAX", "keyframes need one name")
            self.keyframes()
        else:
            if name == "layer":
                _check_layer_names(prelude)
            if name == "media":
                self.media.append(condition)
            self.rule_list(nested=True)
        self.depth -= 1

    def qualified_rule(self) -> None:
        prelude = self.prelude(frozenset({"{"}))
        self.take()
        selector = text_of_tokens(prelude)
        if not selector:
            raise _fail("STYLES_SYNTAX", "empty selector")
        _check_selector(prelude, selector)
        self.rules.append(StyleRule(selector, self.declarations(), False))

    def keyframes(self) -> None:
        while True:
            self.skip()
            token = self.peek()
            if token is None:
                raise _fail("STYLES_SYNTAX", "unclosed keyframes")
            if token.kind == "}":
                self.index += 1
                return
            prelude = self.prelude(frozenset({"{"}))
            self.take()
            _check_keyframe_selector(prelude)
            self.rules.append(StyleRule(text_of_tokens(prelude), self.declarations(), True))

    def declarations(self) -> tuple[StyleDeclaration, ...]:
        found: list[StyleDeclaration] = []
        while True:
            self.skip(frozenset({"whitespace", "semicolon"}))
            token = self.peek()
            if token is None:
                raise _fail("STYLES_SYNTAX", "unclosed block")
            if token.kind == "}":
                self.index += 1
                return tuple(found)
            if token.kind != "ident":
                raise _fail("STYLES_SYNTAX", f"declaration starting with {detail_name(token.text)}")
            name = self.take().value
            self.skip()
            colon = self.peek()
            if colon is None or colon.kind != "colon":
                raise _fail("STYLES_SYNTAX", f"property {detail_name(name)} without a colon")
            self.index += 1
            found.append(self.declaration(name))

    def declaration(self, name: str) -> StyleDeclaration:
        start = self.index
        closers: list[str] = []
        while True:
            token = self.peek()
            if token is None:
                raise _fail("STYLES_SYNTAX", "unclosed block")
            if not closers and token.kind in {"semicolon", "}"}:
                break
            if token.kind in {"{", "}", "semicolon", "at-keyword"}:
                raise _fail("STYLES_SYNTAX", f"property {detail_name(name)} holds a block")
            _track(closers, token)
            self.index += 1
        value = list(self.tokens[start : self.index])
        important = _strip_important(value)
        while value and value[0].kind == "whitespace":
            value.pop(0)
        while value and value[-1].kind == "whitespace":
            value.pop()
        if not value:
            raise _fail("STYLES_SYNTAX", f"property {detail_name(name)} without a value")
        if any(token.kind == "delim" and token.value == "!" for token in value):
            raise _fail("STYLES_SYNTAX", f"misplaced ! in {detail_name(name)}")
        return StyleDeclaration(name, tuple(value), important)


def _track(closers: list[str], token: CssToken) -> None:
    if token.kind in {"function", "("}:
        closers.append(")")
    elif token.kind == "[":
        closers.append("]")
    elif token.kind in {")", "]"} and (not closers or closers.pop() != token.kind):
        raise _fail("STYLES_SYNTAX", "unbalanced brackets or parentheses")
    if len(closers) > MAX_NESTING:
        raise _fail("STYLES_SYNTAX", f"brackets nested deeper than {MAX_NESTING} levels")


def _strip_important(value: list[CssToken]) -> bool:
    end = len(value)
    while end and value[end - 1].kind == "whitespace":
        end -= 1
    if not end or value[end - 1].kind != "ident" or value[end - 1].value.lower() != "important":
        return False
    position = end - 1
    while position and value[position - 1].kind == "whitespace":
        position -= 1
    if not position or value[position - 1].kind != "delim" or value[position - 1].value != "!":
        return False
    del value[position - 1 :]
    return True


def _check_layer_names(prelude: Sequence[CssToken]) -> None:
    for token in prelude:
        if token.kind not in {"whitespace", "ident", "comma"} and not (
            token.kind == "delim" and token.value == "."
        ):
            raise _fail("STYLES_SYNTAX", "layer names")


def _check_keyframe_selector(prelude: Sequence[CssToken]) -> None:
    for part in split_commas(prelude):
        items = significant(part)
        if len(items) != 1:
            raise _fail("STYLES_SYNTAX", "keyframe selector")
        item = items[0]
        assert isinstance(item, CssToken)
        if not (
            item.kind == "percentage"
            or (item.kind == "ident" and item.value.lower() in {"from", "to"})
        ):
            raise _fail("STYLES_SYNTAX", f"keyframe selector {detail_name(item.text)}")


def _check_selector(prelude: Sequence[CssToken], selector: str) -> None:
    for position, token in enumerate(prelude):
        previous = prelude[position - 1] if position else None
        value = token.value.lower()
        rejected = (
            (token.kind == "ident" and (value in {"html", "body"} or value.startswith("scr-")))
            or (token.kind == "hash" and value.startswith("scr-"))
            or (token.kind == "delim" and token.value == "&")
            or (
                previous is not None
                and previous.kind == "colon"
                and (
                    (token.kind == "ident" and value in _SELECTOR_ROOTS)
                    or (token.kind == "function" and value in _SELECTOR_ROOT_FUNCTIONS)
                )
            )
            or (
                token.kind == "ident"
                and previous is not None
                and previous.kind == "delim"
                and previous.value == "."
                and value.startswith("ot-")
            )
            or (token.kind == "[" and _protected_attribute(prelude, position))
        )
        if rejected:
            raise _fail("STYLES_SELECTOR", f"selector {detail_name(selector)}")
        if token.kind == "function" and value == "attr":
            raise _fail("STYLES_FORBIDDEN", "attr( in a selector")


def _protected_attribute(prelude: Sequence[CssToken], position: int) -> bool:
    for token in prelude[position + 1 :]:
        if token.kind == "whitespace":
            continue
        if token.kind != "ident":
            return False
        name = token.value.lower()
        return name in _PROTECTED_ATTRIBUTES or name.startswith("data-ot")
    return False


def _is_percentage(node: CssNode) -> bool:
    return isinstance(node, CssToken) and node.kind == "percentage"


def is_colour_property(name: str) -> bool:
    return (
        name.startswith("--m-")
        or "color" in name
        or name in _COLOUR_PROPERTIES
        or name.startswith(_COLOUR_PROPERTY_PREFIXES)
    )


class _ValueChecker:
    def __init__(self, declared: frozenset[str], token_names: frozenset[str] | None) -> None:
        self.declared = declared
        self.token_names = token_names

    def check(self, declaration: StyleDeclaration) -> None:
        name = declaration.name
        nodes = declaration.nodes
        self.walk(nodes, name, colour=is_colour_property(name))
        if name == "font-family":
            self.font_family(nodes)
        elif name == "font":
            self.font(nodes)
        elif name == "z-index":
            self.z_index(nodes)

    def walk(self, nodes: Iterable[CssNode], name: str, *, colour: bool) -> None:
        for node in nodes:
            if isinstance(node, CssBlock):
                self.block(node, name, colour=colour)
            elif node.kind == "hash":
                raise _fail("STYLES_COLOUR", f"hexadecimal colour in {name}")
            elif node.kind == "ident" and colour and node.value.lower() in NAMED_COLOURS:
                raise _fail("STYLES_COLOUR", f"named colour {detail_name(node.value)} in {name}")

    def block(self, block: CssBlock, name: str, *, colour: bool) -> None:
        if block.opener.kind != "function":
            self.walk(block.children, name, colour=colour)
            return
        function = block.opener.value
        if function in COLOUR_FUNCTIONS:
            raise _fail("STYLES_COLOUR", f"{function}() in {name}")
        if function == "attr":
            if name != "content":
                raise _fail("STYLES_FORBIDDEN", f"attr( in {name}")
            self.walk(block.children, name, colour=False)
            return
        if function == "var":
            self.variable(block, name, colour=colour)
            return
        if function == "color-mix":
            self.colour_mix(block, name)
            return
        if function not in VALUE_FUNCTIONS:
            raise _fail("STYLES_FUNCTION", f"{detail_name(function)}() in {name}")
        self.walk(block.children, name, colour=colour or function in _COLOUR_ARGUMENT_FUNCTIONS)

    def variable(self, block: CssBlock, name: str, *, colour: bool) -> None:
        reference = variable_reference(block)
        if reference is None:
            raise _fail("STYLES_CUSTOM_PROPERTY", f"var() in {name}")
        self.reference(reference)
        for part in split_commas(block.children)[1:]:
            self.walk(part, name, colour=colour)

    def reference(self, reference: str) -> None:
        if reference.startswith("--vl-"):
            if _TOKEN_NAME.fullmatch(reference) is None or (
                self.token_names is not None and reference not in self.token_names
            ):
                raise _fail("STYLES_CUSTOM_PROPERTY", f"unknown token {detail_name(reference)}")
        elif reference.startswith("--m-"):
            if reference not in self.declared:
                raise _fail(
                    "STYLES_CUSTOM_PROPERTY", f"undefined property {detail_name(reference)}"
                )
        else:
            raise _fail("STYLES_CUSTOM_PROPERTY", f"var({detail_name(reference)})")

    def colour_mix(self, block: CssBlock, name: str) -> None:
        parts = split_commas(block.children)
        space = significant(parts[0])
        if (
            len(parts) != 3
            or len(space) != 2
            or not all(isinstance(item, CssToken) and item.kind == "ident" for item in space)
            or [item.value.lower() for item in space if isinstance(item, CssToken)]
            != ["in", "srgb"]
        ):
            raise _fail("STYLES_COLOUR", f"color-mix() in {name} must mix in srgb")
        total = 0.0
        for part in parts[1:]:
            items = significant(part)
            weights = [item for item in items if _is_percentage(item)]
            colours = [item for item in items if not _is_percentage(item)]
            if len(weights) > 1 or len(colours) != 1:
                raise _fail("STYLES_COLOUR", f"color-mix() in {name}")
            if weights:
                weight = float(weights[0].value)
                if not 0 <= weight <= 100:
                    raise _fail("STYLES_COLOUR", f"color-mix() percentage in {name}")
                total += weight
            else:
                total += 1
            self.colour_atom(colours[0], name)
        if total <= 0:
            raise _fail("STYLES_COLOUR", f"color-mix() weights in {name}")

    def colour_atom(self, node: CssNode, name: str) -> None:
        if isinstance(node, CssToken):
            if node.kind == "ident" and node.value.lower() in {"transparent", "currentcolor"}:
                return
            raise _fail("STYLES_COLOUR", f"color-mix() in {name}")
        if is_function(node, "color-mix"):
            self.colour_mix(node, name)
            return
        reference = variable_reference(node)
        if (
            reference is not None
            and len(split_commas(node.children)) == 1
            and (reference.startswith("--vl-color-") or reference.startswith("--m-"))
        ):
            self.reference(reference)
            return
        raise _fail("STYLES_COLOUR", f"color-mix() in {name}")

    def font_family(self, nodes: Sequence[CssNode]) -> None:
        parts = split_commas(nodes)
        for part in parts:
            items = significant(part)
            if len(items) != 1:
                raise _fail("STYLES_FONT", "font-family")
            item = items[0]
            if isinstance(item, CssToken) and item.kind == "ident":
                keyword = item.value.lower()
                if keyword in _GENERIC_FAMILIES or (keyword == "inherit" and len(parts) == 1):
                    continue
            elif (
                variable_reference(item) in _FONT_TOKENS
                and isinstance(item, CssBlock)
                and len(split_commas(item.children)) == 1
            ):
                continue
            raise _fail("STYLES_FONT", "font-family")

    def font(self, nodes: Iterable[CssNode]) -> None:
        for node in nodes:
            if isinstance(node, CssBlock):
                if is_function(node, "var"):
                    reference = variable_reference(node)
                    if reference is None or not reference.startswith("--vl-"):
                        raise _fail("STYLES_FONT", "font")
                    continue
                self.font(node.children)
            elif node.kind == "string" or (
                node.kind == "ident" and node.value.lower() not in _FONT_KEYWORDS
            ):
                raise _fail("STYLES_FONT", "font")

    def z_index(self, nodes: Sequence[CssNode]) -> None:
        items = significant(nodes)
        if len(items) == 1 and isinstance(items[0], CssToken):
            token = items[0]
            if token.kind == "ident" and token.value.lower() in _Z_INDEX_KEYWORDS:
                return
            if (
                token.kind == "number"
                and _INTEGER.fullmatch(token.value) is not None
                and int(token.value) < 1000
            ):
                return
        raise _fail("STYLES_Z_INDEX", "z-index must be an integer below 1000")


def parse_style_sheet(styles: str, *, token_names: Iterable[str] | None = None) -> StyleSheet:
    text = normalize_styles(styles)
    return _parse_sheet(text, None if token_names is None else frozenset(token_names))


@lru_cache(maxsize=64)
def _parse_sheet(text: str, names: frozenset[str] | None) -> StyleSheet:
    parser = _SheetParser(
        tuple(token for token in tokenize_styles(text) if token.kind != "comment")
    )
    parser.rule_list(nested=False)
    declared: set[str] = set()
    for rule in parser.rules:
        for declaration in rule.declarations:
            if declaration.name.lower() in _FORBIDDEN_PROPERTIES:
                raise _fail("STYLES_FORBIDDEN", f"property {detail_name(declaration.name)}")
            if declaration.name.startswith("--"):
                if _CUSTOM_PROPERTY.fullmatch(declaration.name) is None:
                    raise _fail(
                        "STYLES_CUSTOM_PROPERTY",
                        f"custom property {detail_name(declaration.name)}",
                    )
                declared.add(declaration.name)
            elif _PROPERTY.fullmatch(declaration.name) is None:
                raise _fail("STYLES_PROPERTY", f"property {detail_name(declaration.name)}")
    checker = _ValueChecker(frozenset(declared), names)
    for rule in parser.rules:
        for declaration in rule.declarations:
            checker.check(declaration)
    return StyleSheet(tuple(parser.rules), tuple(parser.media))


__all__ = [
    "COLOUR_FUNCTIONS",
    "FORBIDDEN_CHARACTERS",
    "GRADIENT_FUNCTIONS",
    "MAX_BLOCK_DEPTH",
    "MAX_NESTING",
    "MAX_STYLES_LENGTH",
    "NAMED_COLOURS",
    "VALUE_FUNCTIONS",
    "CssBlock",
    "CssNode",
    "CssToken",
    "GeneratedMockupError",
    "StyleDeclaration",
    "StyleRule",
    "StyleSheet",
    "detail_name",
    "group_tokens",
    "has_forbidden_character",
    "is_colour_property",
    "is_function",
    "normalize_styles",
    "parse_style_sheet",
    "significant",
    "split_commas",
    "text_of_tokens",
    "tokenize_styles",
    "variable_reference",
]
