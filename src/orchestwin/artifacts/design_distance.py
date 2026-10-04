from __future__ import annotations

import math
import re
import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from types import MappingProxyType
from typing import Final
from uuid import UUID

from orchestwin.artifacts.design import DesignAlternative
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.generated_mockups import VOID_ELEMENTS, GeneratedMockup
from orchestwin.artifacts.visual_catalog import VISUAL_DIMENSION_NAMES, visual_differences
from orchestwin.artifacts.visual_color import colour_distance
from orchestwin.artifacts.visual_directions import (
    DIRECTION_AXES,
    DirectionColour,
    DirectionLayout,
    DirectionShape,
    DirectionType,
    VisualDirection,
    differing_axes,
)

DESIGN_DISTANCE_VERSION: Final = 1
STYLES_CLOSE: Final = 45
CHOICES_TOTAL: Final = len(VISUAL_DIMENSION_NAMES)
OUTLINE_DEPTH: Final = 3
SEMANTIC_ELEMENTS: Final = frozenset(
    {
        "header",
        "nav",
        "main",
        "aside",
        "footer",
        "section",
        "article",
        "form",
        "fieldset",
        "table",
        "ul",
        "ol",
        "dl",
        "details",
        "figure",
        "h1",
        "h2",
        "h3",
    }
)
DEFAULT_BODY_SIZE: Final = 16.0
_FONT_UNIT: Final = 16.0
_SQUARE_RADIUS: Final = 3.0
_PILL_RADIUS: Final = 100.0
_PILL_PERCENTAGE: Final = 50.0
_THICK_BORDER: Final = 2.5
_MIN_CONTAINER: Final = 480.0
_MAX_CONTAINER: Final = 2000.0
_FIELD_SHARE: Final = 0.6
_READING_SIZE: Final = 17.0
_DISPLAY_RATIO: Final = 3.0
_READING_RATIO: Final = 4.0
_STAGE_CONTAINER: Final = 800
_WORKBENCH_CONTAINER: Final = 1400
_SIZE_BODY: Final = "--vl-size-body"
_FONT_MONO: Final = "--vl-font-mono"
_TOKEN_PREFIX: Final = "--vl-"
_PRIMARY_COLOURS: Final = frozenset({"--vl-color-primary", "--vl-color-accent"})
_TINT_TOKENS: Final = ("--vl-color-primary-soft", "--vl-color-surface-alt")
_BACKGROUNDS: Final = frozenset({"background", "background-color"})
_BORDER_SIDES: Final = (
    "",
    "-top",
    "-right",
    "-bottom",
    "-left",
    "-block",
    "-inline",
    "-block-start",
    "-block-end",
    "-inline-start",
    "-inline-end",
)
_BORDERS: Final = frozenset(
    {f"border{side}" for side in _BORDER_SIDES} | {f"border{side}-width" for side in _BORDER_SIDES}
)
_BORDER_KEYWORDS: Final = MappingProxyType({"thin": 1.0, "medium": 3.0, "thick": 5.0})
_NO_BORDER: Final = frozenset({"none", "hidden"})
_BORDER_STYLES: Final = frozenset(
    {"none", "hidden", "dotted", "dashed", "solid", "double", "groove", "ridge", "inset", "outset"}
)
_MEDIUM_BORDER: Final = 3.0
_SIDE_INDEXES: Final = MappingProxyType(
    {
        "top": (0,),
        "right": (1,),
        "bottom": (2,),
        "left": (3,),
        "block": (0, 2),
        "inline": (3, 1),
        "block-start": (0,),
        "block-end": (2,),
        "inline-start": (3,),
        "inline-end": (1,),
    }
)
_ALL_SIDES: Final = (0, 1, 2, 3)
_OPEN_BOXES: Final = 3
_OPEN_SIDE_RULES: Final = 3
_RULED_SHARE: Final = 2
_TITLE: Final = re.compile(r"(?<![\w.#-])h1(?![\w-])", re.IGNORECASE)
_SIZE_DISPLAY: Final = "--vl-size-display"
_FONT_SIZES: Final = frozenset({"font-size", "font"})
_FONT_FAMILIES: Final = frozenset({"font-family", "font"})
_SPACINGS: Final = frozenset({"padding", "gap", "row-gap", "column-gap"})
_GRID_PLACEMENTS: Final = frozenset({"grid-column", "grid-row"})
_TRACK_KEYWORDS: Final = frozenset(
    {"none", "subgrid", "masonry", "inherit", "initial", "unset", "revert", "revert-layer"}
)
_UNITS: Final = MappingProxyType({"px": 1.0, "rem": _FONT_UNIT, "em": _FONT_UNIT})
_ZERO: Final = re.compile(r"[+-]?(?:0+(?:\.0*)?|\.0+)")
_QUANTITY: Final = re.compile(
    r"(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)(?P<unit>%|[a-z]+)?", re.IGNORECASE
)
_PERCENTAGE: Final = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)%")
_FUNCTION: Final = re.compile(r"([a-z][a-z0-9-]*)\(", re.IGNORECASE)
_VARIABLE: Final = re.compile(r"(?<![\w-])var\(", re.IGNORECASE)
_GRADIENT: Final = re.compile(r"(?<![\w-])[a-z-]*gradient\(", re.IGNORECASE)
_COLOUR_MIX: Final = re.compile(r"(?<![\w-])color-mix\(", re.IGNORECASE)
_AT_RULE: Final = re.compile(r"@([-\w]+)")
_IMPORTANT: Final = re.compile(r"\s*!\s*important$", re.IGNORECASE)
_NARROW: Final = re.compile(r"max-width|(?<![\w-])width\s*<", re.IGNORECASE)
_SPAN: Final = re.compile(r"(?<![\w-])span(?![\w-])", re.IGNORECASE)
_SPACE: Final = " \t\n\r\f"
_OPENERS: Final = "(["
_CLOSERS: Final = ")]"


class RadiusClass(StrEnum):
    SQUARE = "SQUARE"
    ROUNDED = "ROUNDED"
    PILL = "PILL"


class BorderClass(StrEnum):
    NONE = "NONE"
    THIN = "THIN"
    THICK = "THICK"


class ShadowClass(StrEnum):
    NONE = "NONE"
    SOFT = "SOFT"
    HARD = "HARD"


class BoxingClass(StrEnum):
    BOXED = "BOXED"
    RULED = "RULED"
    OPEN = "OPEN"


class ColumnsClass(StrEnum):
    NONE = "NONE"
    ONE = "ONE"
    TWO_EVEN = "TWO_EVEN"
    TWO_UNEVEN = "TWO_UNEVEN"
    MANY = "MANY"


class NavigationPlacement(StrEnum):
    HEADER = "HEADER"
    SIDE = "SIDE"
    TOP = "TOP"
    OTHER = "OTHER"
    NONE = "NONE"


class DistanceVerdict(StrEnum):
    FAR = "FAR"
    CLOSE = "CLOSE"
    UNKNOWN = "UNKNOWN"


class AdherenceStatus(StrEnum):
    FOLLOWED = "FOLLOWED"
    NOT_FOLLOWED = "NOT_FOLLOWED"
    NOT_CHECKED = "NOT_CHECKED"


class StyleDifference(StrEnum):
    BOXING = "BOXING"
    TITLE_SCALE = "TITLE_SCALE"
    CONTAINER = "CONTAINER"
    BORDER = "BORDER"
    RADIUS = "RADIUS"
    COLUMNS = "COLUMNS"
    SHADOW = "SHADOW"
    UPPERCASE = "UPPERCASE"
    MONOSPACE = "MONOSPACE"
    GRADIENT = "GRADIENT"
    COLOUR_FIELDS = "COLOUR_FIELDS"
    TINTS = "TINTS"


class StructureDifference(StrEnum):
    OUTLINE = "OUTLINE"
    TAGS = "TAGS"
    TABLE = "TABLE"
    CARDS = "CARDS"
    SIDE_COLUMN = "SIDE_COLUMN"
    NAVIGATION = "NAVIGATION"
    FORMS = "FORMS"


STYLE_WEIGHTS: Final[Mapping[StyleDifference, int]] = MappingProxyType(
    {
        StyleDifference.BOXING: 18,
        StyleDifference.TITLE_SCALE: 14,
        StyleDifference.CONTAINER: 12,
        StyleDifference.BORDER: 10,
        StyleDifference.RADIUS: 10,
        StyleDifference.COLUMNS: 8,
        StyleDifference.SHADOW: 8,
        StyleDifference.UPPERCASE: 6,
        StyleDifference.MONOSPACE: 4,
        StyleDifference.GRADIENT: 4,
        StyleDifference.COLOUR_FIELDS: 4,
        StyleDifference.TINTS: 2,
    }
)
STRUCTURE_WEIGHTS: Final[Mapping[StructureDifference, int]] = MappingProxyType(
    {
        StructureDifference.OUTLINE: 30,
        StructureDifference.TAGS: 25,
        StructureDifference.TABLE: 10,
        StructureDifference.CARDS: 10,
        StructureDifference.SIDE_COLUMN: 10,
        StructureDifference.NAVIGATION: 10,
        StructureDifference.FORMS: 5,
    }
)
_RADIUS_ORDER: Final = (RadiusClass.PILL, RadiusClass.ROUNDED, RadiusClass.SQUARE)
_COLUMNS_ORDER: Final = (
    ColumnsClass.TWO_UNEVEN,
    ColumnsClass.MANY,
    ColumnsClass.TWO_EVEN,
    ColumnsClass.ONE,
)


@dataclass(frozen=True, slots=True)
class StyleProfile:
    radius: RadiusClass
    border: BorderClass
    shadow: ShadowClass
    boxes: int
    side_rules: int
    boxing: BoxingClass
    title_ratio: float
    type_ratio: float
    uppercase: int
    colour_fields: int
    tints: int
    gradients: int
    container: int | None
    columns: ColumnsClass
    spans: int
    spacing: int
    monospace: bool
    uneven_grids: int
    largest_font: float
    body_size: float
    properties: Counter[str]


@dataclass(frozen=True, slots=True)
class StructureProfile:
    tags: Counter[str]
    outline: frozenset[str]
    tables: int
    cards: int
    asides: int
    forms: int
    navigation: NavigationPlacement
    screens: int


@dataclass(frozen=True, slots=True)
class _Declaration:
    rule: int
    name: str
    value: str
    narrow: bool
    selector: str


@dataclass(frozen=True, slots=True)
class _Block:
    kind: str
    narrow: bool
    rule: int
    selector: str = ""


def _collapsed(value: str) -> str:
    return " ".join(value.split())


def _string_end(text: str, index: int) -> int:
    close = text.find(text[index], index + 1)
    return len(text) if close < 0 else close + 1


def _closing(text: str, opening: int) -> int:
    depth = 0
    index = opening
    while index < len(text):
        character = text[index]
        if character in "\"'":
            index = _string_end(text, index)
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _split_top(text: str, separators: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\"'":
            index = _string_end(text, index)
            continue
        if character in _OPENERS:
            depth += 1
        elif character in _CLOSERS:
            depth = max(0, depth - 1)
        elif depth == 0 and character in separators:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return parts


def _components(value: str) -> list[str]:
    return [part.strip() for part in _split_top(value, _SPACE + "/,") if part.strip()]


def _call(text: str) -> tuple[str, str] | None:
    match = _FUNCTION.match(text)
    if match is None or _closing(text, match.end() - 1) != len(text) - 1:
        return None
    return match.group(1).lower(), text[match.end() : -1]


class _Expression:
    __slots__ = ("index", "text")

    def __init__(self, text: str) -> None:
        self.text = text
        self.index = 0

    def peek(self) -> str:
        while self.index < len(self.text) and self.text[self.index] in _SPACE:
            self.index += 1
        return self.text[self.index] if self.index < len(self.text) else ""

    def parse(self) -> tuple[float, bool] | None:
        result = self.sum()
        return result if result is not None and self.peek() == "" else None

    def sum(self) -> tuple[float, bool] | None:
        left = self.product()
        while left is not None and self.peek() in {"+", "-"}:
            operator = self.text[self.index]
            self.index += 1
            right = self.product()
            if right is None or right[1] != left[1]:
                return None
            left = (left[0] + right[0] if operator == "+" else left[0] - right[0], left[1])
        return left

    def product(self) -> tuple[float, bool] | None:
        left = self.unary()
        while left is not None and self.peek() in {"*", "/"}:
            operator = self.text[self.index]
            self.index += 1
            right = self.unary()
            if right is None:
                return None
            if operator == "*":
                if left[1] and right[1]:
                    return None
                left = (left[0] * right[0], left[1] or right[1])
            else:
                if right[1] or right[0] == 0:
                    return None
                left = (left[0] / right[0], left[1])
        return left

    def unary(self) -> tuple[float, bool] | None:
        sign = self.peek()
        if sign in {"+", "-"}:
            self.index += 1
            operand = self.unary()
            if operand is None:
                return None
            return (-operand[0] if sign == "-" else operand[0], operand[1])
        return self.atom()

    def atom(self) -> tuple[float, bool] | None:
        if self.peek() == "(":
            self.index += 1
            inner = self.sum()
            if inner is None or self.peek() != ")":
                return None
            self.index += 1
            return inner
        quantity = _QUANTITY.match(self.text, self.index)
        if quantity is not None:
            self.index = quantity.end()
            number = float(quantity.group("number"))
            unit = quantity.group("unit")
            if unit is None:
                return (number, False)
            scale = _UNITS.get(unit.lower())
            return None if scale is None else (number * scale, True)
        function = _FUNCTION.match(self.text, self.index)
        if function is None:
            return None
        closing = _closing(self.text, function.end() - 1)
        if closing < 0:
            return None
        self.index = closing + 1
        return _function_value(function.group(1).lower(), self.text[function.end() : closing])


def _evaluate(text: str) -> tuple[float, bool] | None:
    return _Expression(text).parse()


def _function_value(name: str, inner: str) -> tuple[float, bool] | None:
    if name == "calc":
        return _evaluate(inner)
    arguments = _split_top(inner, ",")
    if name == "clamp":
        return _evaluate(arguments[2]) if len(arguments) == 3 else None
    if name in {"min", "max"}:
        lengths = [
            found[0]
            for argument in arguments
            if (found := _evaluate(argument)) is not None and found[1]
        ]
        if not lengths:
            return None
        return (min(lengths) if name == "min" else max(lengths), True)
    return None


def _length(text: str) -> float | None:
    stripped = text.strip()
    if _ZERO.fullmatch(stripped) is not None:
        return 0.0
    found = _evaluate(stripped)
    return found[0] if found is not None and found[1] else None


def _first_length(value: str) -> float | None:
    for component in _components(value):
        found = _length(component)
        if found is not None:
            return found
    return None


def _percentage(text: str) -> float | None:
    return float(text[:-1]) if _PERCENTAGE.fullmatch(text) is not None else None


def _variable_parts(inner: str) -> tuple[str, str | None]:
    head = _split_top(inner, ",")[0]
    if len(head) == len(inner):
        return inner.strip(), None
    return head.strip(), inner[len(head) + 1 :].strip()


def _replace_variables(value: str, values: Mapping[str, str], *, tokens_only: bool) -> str:
    parts: list[str] = []
    index = 0
    while (match := _VARIABLE.search(value, index)) is not None:
        closing = _closing(value, match.end() - 1)
        if closing < 0:
            break
        parts.append(value[index : match.start()])
        name, fallback = _variable_parts(value[match.end() : closing])
        found = values.get(name)
        if name.startswith(_TOKEN_PREFIX) != tokens_only:
            parts.append(value[match.start() : closing + 1])
        elif isinstance(found, str):
            parts.append(found)
        elif fallback is not None:
            parts.append(_replace_variables(fallback, values, tokens_only=tokens_only))
        else:
            parts.append(value[match.start() : closing + 1])
        index = closing + 1
    parts.append(value[index:])
    return "".join(parts)


def _declaration(text: str, block: _Block) -> _Declaration | None:
    name, colon, value = text.partition(":")
    property_name = name.strip().lower()
    cleaned = _IMPORTANT.sub("", _collapsed(value))
    if not colon or not property_name or not cleaned:
        return None
    return _Declaration(block.rule, property_name, cleaned, block.narrow, block.selector)


def _opened(prelude: str, parent: _Block, rule: int) -> _Block:
    if parent.kind == "skip":
        return _Block("skip", parent.narrow, -1)
    if not prelude.startswith("@"):
        return _Block("rule", parent.narrow, rule, prelude)
    match = _AT_RULE.match(prelude)
    name = "" if match is None else match.group(1).lower()
    if name.endswith("keyframes"):
        return _Block("skip", parent.narrow, -1)
    narrow = name == "media" and _NARROW.search(prelude) is not None
    return _Block("group", parent.narrow or narrow, -1)


def _declarations(styles: str) -> tuple[_Declaration, ...]:
    found: list[_Declaration] = []
    outer = _Block("group", False, -1)
    stack: list[_Block] = []
    buffer: list[str] = []
    rules = 0
    index = 0
    while index < len(styles):
        character = styles[index]
        if styles.startswith("/*", index):
            close = styles.find("*/", index + 2)
            index = len(styles) if close < 0 else close + 2
            continue
        if character in "\"'":
            end = _string_end(styles, index)
            buffer.append(styles[index:end])
            index = end
            continue
        current = stack[-1] if stack else outer
        if character == "{":
            block = _opened(_collapsed("".join(buffer)), current, rules)
            buffer.clear()
            if block.kind == "rule":
                rules += 1
            stack.append(block)
        elif character in "};":
            if current.kind == "rule":
                declaration = _declaration("".join(buffer), current)
                if declaration is not None:
                    found.append(declaration)
            buffer.clear()
            if character == "}" and stack:
                stack.pop()
        else:
            buffer.append(character)
        index += 1
    return tuple(found)


def _aliases(declarations: Sequence[_Declaration]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for item in declarations:
        if item.name.startswith("--") and item.name not in aliases:
            aliases[item.name] = _replace_variables(item.value, aliases, tokens_only=False)
    return aliases


def _classify_radius(value: float) -> RadiusClass:
    if value <= _SQUARE_RADIUS:
        return RadiusClass.SQUARE
    if value < _PILL_RADIUS:
        return RadiusClass.ROUNDED
    return RadiusClass.PILL


def _radius(value: str) -> RadiusClass | None:
    for component in _components(value):
        percentage = _percentage(component)
        if percentage is not None:
            if percentage >= _PILL_PERCENTAGE:
                return RadiusClass.PILL
            continue
        found = _length(component)
        if found is not None:
            return _classify_radius(found)
    return None


def _border_width(value: str) -> float | None:
    components = [item.lower() for item in _components(value)]
    if any(item in _NO_BORDER for item in components):
        return 0.0
    found = _first_length(value)
    if found is not None:
        return found
    return next((_BORDER_KEYWORDS[item] for item in components if item in _BORDER_KEYWORDS), None)


def _shadow(value: str) -> ShadowClass | None:
    if value.strip().lower() == "none":
        return None
    layer = _split_top(value, ",")[0]
    lengths = [found for item in _components(layer) if (found := _length(item)) is not None]
    if len(lengths) < 2:
        return None
    blur = lengths[2] if len(lengths) > 2 else 0.0
    if blur == 0 and (lengths[0] != 0 or lengths[1] != 0):
        return ShadowClass.HARD
    return ShadowClass.SOFT


def _tracks(value: str) -> ColumnsClass | None:
    if value.strip().lower() in _TRACK_KEYWORDS:
        return None
    tracks: list[str] = []
    for component in _components(value):
        if component.startswith("["):
            continue
        call = _call(component)
        if call is None or call[0] != "repeat":
            tracks.append(component)
            continue
        count, _comma, listed = call[1].partition(",")
        if count.strip().lower().startswith("auto-"):
            return ColumnsClass.MANY
        if not count.strip().isdigit():
            return None
        repeated = [item for item in _components(listed) if not item.startswith("[")]
        tracks.extend(repeated * int(count.strip()))
    if not tracks:
        return None
    if len(tracks) == 1:
        return ColumnsClass.ONE
    if len(tracks) == 2:
        first, second = ("".join(item.lower().split()) for item in tracks)
        return ColumnsClass.TWO_EVEN if first == second else ColumnsClass.TWO_UNEVEN
    return ColumnsClass.MANY


def _without_gradients(value: str) -> str:
    parts: list[str] = []
    index = 0
    while (match := _GRADIENT.search(value, index)) is not None:
        closing = _closing(value, match.end() - 1)
        if closing < 0:
            break
        parts.append(value[index : match.start()])
        index = closing + 1
    parts.append(value[index:])
    return "".join(parts)


def _colour_share(text: str) -> float:
    call = _call(text.strip())
    if call is None:
        return 0.0
    name, inner = call
    if name == "var":
        return 1.0 if _variable_parts(inner)[0] in _PRIMARY_COLOURS else 0.0
    if name == "color-mix":
        return _mix_share(inner)
    return 0.0


def _mix_weights(first: float | None, second: float | None) -> tuple[float, float]:
    if first is None:
        return (50.0, 50.0) if second is None else (100.0 - second, second)
    return (first, 100.0 - first) if second is None else (first, second)


def _mix_share(inner: str) -> float:
    parts = _split_top(inner, ",")
    if len(parts) != 3:
        return 0.0
    weights: list[float | None] = []
    shares: list[float] = []
    for part in parts[1:]:
        weight: float | None = None
        share = 0.0
        for component in _components(part):
            percentage = _percentage(component)
            if percentage is None:
                share = _colour_share(component)
            else:
                weight = percentage
        weights.append(weight)
        shares.append(share)
    first, second = _mix_weights(weights[0], weights[1])
    total = first + second
    return (first * shares[0] + second * shares[1]) / total if total > 0 else 0.0


def _is_field(value: str) -> bool:
    return any(
        _colour_share(component) >= _FIELD_SHARE
        for component in _components(_without_gradients(value))
    )


def _is_tint(value: str) -> bool:
    if any(token in value for token in _TINT_TOKENS):
        return True
    for match in _COLOUR_MIX.finditer(value):
        closing = _closing(value, match.end() - 1)
        if closing >= 0 and 0 < _mix_share(value[match.end() : closing]) < _FIELD_SHARE:
            return True
    return False


def _most_frequent[Kind](votes: Counter[Kind], order: Sequence[Kind], default: Kind) -> Kind:
    if not votes:
        return default
    best = max(votes.values())
    return next(item for item in order if votes[item] == best)


def _border_class(widths: Sequence[float]) -> BorderClass:
    visible = [width for width in widths if width > 0]
    if len(visible) <= 2:
        return BorderClass.NONE
    thick = sum(1 for width in visible if width >= _THICK_BORDER)
    return BorderClass.THICK if 10 * thick >= 3 * len(visible) else BorderClass.THIN


def _shadow_class(shadows: Counter[ShadowClass]) -> ShadowClass:
    if not shadows:
        return ShadowClass.NONE
    if shadows[ShadowClass.HARD] >= shadows[ShadowClass.SOFT]:
        return ShadowClass.HARD
    return ShadowClass.SOFT


def _body_size(tokens: Mapping[str, str]) -> float:
    value = tokens.get(_SIZE_BODY)
    size = _length(value) if isinstance(value, str) else None
    return size if size is not None and size > 0 else DEFAULT_BODY_SIZE


def _border_sides(name: str) -> tuple[tuple[int, ...], str] | None:
    if name == "border":
        return _ALL_SIDES, "shorthand"
    if name in {"border-width", "border-style"}:
        return _ALL_SIDES, name.removeprefix("border-")
    if not name.startswith("border-"):
        return None
    rest = name.removeprefix("border-")
    if rest in _SIDE_INDEXES:
        return _SIDE_INDEXES[rest], "shorthand"
    side, _dash, part = rest.rpartition("-")
    if part in {"width", "style"} and side in _SIDE_INDEXES:
        return _SIDE_INDEXES[side], part
    return None


def _border_part(component: str) -> float | None:
    found = _length(component)
    return _BORDER_KEYWORDS.get(component) if found is None else found


def _per_side[Item](values: Sequence[Item], count: int) -> list[Item] | None:
    if not 1 <= len(values) <= count:
        return None
    if count == len(_ALL_SIDES):
        patterns = ((0, 0, 0, 0), (0, 1, 0, 1), (0, 1, 2, 1), (0, 1, 2, 3))
        return [values[index] for index in patterns[len(values) - 1]]
    return [values[0], values[-1]] if count == 2 else [values[0]]


def _apply_border(
    state: tuple[list[float], list[str]], sides: tuple[int, ...], part: str, value: str
) -> None:
    widths, styles = state
    components = [item.lower() for item in _components(value)]
    if part == "shorthand":
        width = next(
            (found for item in components if (found := _border_part(item)) is not None),
            _MEDIUM_BORDER,
        )
        style = next((item for item in components if item in _BORDER_STYLES), "none")
        for side in sides:
            widths[side], styles[side] = width, style
        return
    if part == "width":
        sizes = [_border_part(item) for item in components]
        expanded_widths = None if None in sizes else _per_side(sizes, len(sides))
        for side, size in zip(sides, expanded_widths or (), strict=False):
            widths[side] = size
        return
    known = all(item in _BORDER_STYLES for item in components)
    expanded_styles = _per_side(components, len(sides)) if known else None
    for side, style in zip(sides, expanded_styles or (), strict=False):
        styles[side] = style


def _box_counts(states: Mapping[int, tuple[list[float], list[str]]]) -> tuple[int, int]:
    boxes = side_rules = 0
    for widths, styles in states.values():
        visible = sum(
            1
            for width, style in zip(widths, styles, strict=True)
            if width > 0 and style not in _NO_BORDER
        )
        if visible == len(_ALL_SIDES):
            boxes += 1
        elif visible:
            side_rules += 1
    return boxes, side_rules


def _boxing(boxes: int, side_rules: int) -> BoxingClass:
    if boxes <= _OPEN_BOXES and side_rules <= _OPEN_SIDE_RULES:
        return BoxingClass.OPEN
    if side_rules >= _RULED_SHARE * boxes:
        return BoxingClass.RULED
    return BoxingClass.BOXED


class _FirstTitle(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.classes: frozenset[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1" and self.classes is None:
            self.classes = frozenset((dict(attrs).get("class") or "").split())


def _title_classes(markups: Sequence[str]) -> frozenset[str] | None:
    if not markups:
        return frozenset()
    parser = _FirstTitle()
    parser.feed(markups[0])
    parser.close()
    return parser.classes


def _names_title(selector: str, classes: frozenset[str]) -> bool:
    return _TITLE.search(selector) is not None or any(
        re.search(rf"\.{re.escape(name)}(?![\w-])", selector) is not None for name in classes
    )


def _fallback_title(tokens: Mapping[str, str], body_size: float) -> float:
    value = tokens.get(_SIZE_DISPLAY)
    size = _length(value) if isinstance(value, str) else None
    return size if size is not None and size > 0 else body_size


def style_profile(
    styles: str, tokens: Mapping[str, str], *, markups: Sequence[str] = ()
) -> StyleProfile:
    declarations = _declarations(styles)
    aliases = _aliases(declarations)
    body_size = _body_size(tokens)
    title_classes = _title_classes(markups)
    title_size: float | None = None
    states: dict[int, tuple[list[float], list[str]]] = {}
    radii: Counter[RadiusClass] = Counter()
    shadows: Counter[ShadowClass] = Counter()
    columns: Counter[ColumnsClass] = Counter()
    properties: Counter[str] = Counter()
    widths: list[float] = []
    sizes: list[float] = []
    containers: list[float] = []
    spacings: list[float] = []
    field_rules: set[int] = set()
    tint_rules: set[int] = set()
    uppercase = gradients = spans = uneven = 0
    monospace = False
    for item in declarations:
        if item.name.startswith("--"):
            continue
        properties[item.name] += 1
        expanded = _replace_variables(item.value, aliases, tokens_only=False)
        resolved = _replace_variables(expanded, tokens, tokens_only=True)
        lowered = resolved.lower()
        if "gradient(" in lowered:
            gradients += 1
        if item.name in _BACKGROUNDS:
            if _is_field(expanded):
                field_rules.add(item.rule)
            if _is_tint(expanded):
                tint_rules.add(item.rule)
        if item.name in _FONT_FAMILIES and (
            "monospace" in lowered or _FONT_MONO in item.value.lower()
        ):
            monospace = True
        if item.name in _GRID_PLACEMENTS and (_SPAN.search(resolved) or "/" in resolved):
            spans += 1
        if _VARIABLE.search(resolved) is not None:
            continue
        sides = _border_sides(item.name)
        if sides is not None:
            state = states.setdefault(item.rule, ([_MEDIUM_BORDER] * 4, ["none"] * 4))
            _apply_border(state, *sides, resolved)
        if (
            title_classes is not None
            and not item.narrow
            and item.name in _FONT_SIZES
            and _names_title(item.selector, title_classes)
        ):
            size = _first_length(resolved)
            if size is not None and size > 0:
                title_size = size
        if item.name == "text-transform" and lowered == "uppercase":
            uppercase += 1
        elif item.name == "border-radius":
            radius = _radius(resolved)
            if radius is not None:
                radii[radius] += 1
        elif item.name == "box-shadow":
            shadow = _shadow(resolved)
            if shadow is not None:
                shadows[shadow] += 1
        elif item.name == "max-width":
            width = _first_length(resolved)
            if width is not None and _MIN_CONTAINER <= width <= _MAX_CONTAINER:
                containers.append(width)
        elif item.name == "grid-template-columns":
            tracks = _tracks(resolved)
            if tracks is ColumnsClass.TWO_UNEVEN:
                uneven += 1
            if tracks is not None and not item.narrow:
                columns[tracks] += 1
        if item.name in _BORDERS:
            width = _border_width(resolved)
            if width is not None:
                widths.append(width)
        if item.name in _FONT_SIZES:
            size = _first_length(resolved)
            if size is not None and size > 0:
                sizes.append(size)
        if item.name in _SPACINGS:
            spacing = _first_length(resolved)
            if spacing is not None and spacing > 0:
                spacings.append(spacing)
    largest = max(sizes, default=0.0)
    boxes, side_rules = _box_counts(states)
    title = _fallback_title(tokens, body_size) if title_size is None else title_size
    return StyleProfile(
        radius=_most_frequent(radii, _RADIUS_ORDER, RadiusClass.SQUARE),
        border=_border_class(widths),
        shadow=_shadow_class(shadows),
        boxes=boxes,
        side_rules=side_rules,
        boxing=_boxing(boxes, side_rules),
        title_ratio=round(title / body_size, 2),
        type_ratio=round(largest / body_size, 2) if sizes else 1.0,
        uppercase=uppercase,
        colour_fields=len(field_rules),
        tints=len(tint_rules),
        gradients=gradients,
        container=round(max(containers)) if containers else None,
        columns=_most_frequent(columns, _COLUMNS_ORDER, ColumnsClass.NONE),
        spans=spans,
        spacing=round(statistics.median(spacings)) if spacings else 0,
        monospace=monospace,
        uneven_grids=uneven,
        largest_font=largest,
        body_size=body_size,
        properties=properties,
    )


def _placement(ancestors: Sequence[str]) -> NavigationPlacement:
    if "header" in ancestors:
        return NavigationPlacement.HEADER
    if "aside" in ancestors:
        return NavigationPlacement.SIDE
    if not ancestors or ancestors[-1] == "main":
        return NavigationPlacement.TOP
    return NavigationPlacement.OTHER


class _Outline(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.tags: Counter[str] = Counter()
        self.paths: set[str] = set()
        self.navigation: NavigationPlacement | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.element(tag, closed=tag in VOID_ELEMENTS)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.element(tag, closed=True)

    def handle_endtag(self, tag: str) -> None:
        if tag in self.stack:
            del self.stack[len(self.stack) - 1 - self.stack[::-1].index(tag) :]

    def element(self, tag: str, *, closed: bool) -> None:
        self.tags[tag] += 1
        if tag in SEMANTIC_ELEMENTS:
            ancestors = [item for item in self.stack if item in SEMANTIC_ELEMENTS]
            if len(ancestors) < OUTLINE_DEPTH:
                self.paths.add(">".join((*ancestors, tag)))
        if tag == "nav" and self.navigation is None:
            self.navigation = _placement(self.stack)
        if not closed:
            self.stack.append(tag)


def structure_profile_from_markup(markups: Sequence[str]) -> StructureProfile:
    tags: Counter[str] = Counter()
    outline: frozenset[str] = frozenset()
    navigation = NavigationPlacement.NONE
    for index, markup in enumerate(markups):
        parser = _Outline()
        parser.feed(markup)
        parser.close()
        tags.update(parser.tags)
        if index == 0:
            outline = frozenset(parser.paths)
            navigation = parser.navigation or NavigationPlacement.NONE
    return StructureProfile(
        tags=tags,
        outline=outline,
        tables=tags["table"],
        cards=tags["article"],
        asides=tags["aside"],
        forms=tags["form"] + tags["fieldset"],
        navigation=navigation,
        screens=len(markups),
    )


def structure_profile(mockup: GeneratedMockup) -> StructureProfile:
    return structure_profile_from_markup([screen.markup for screen in mockup.screens])


def _share(difference: float, scale: float) -> float:
    return min(1.0, difference / scale)


def _differs(first: object, second: object) -> float:
    return 1.0 if first != second else 0.0


def style_parts(first: StyleProfile, second: StyleProfile) -> dict[StyleDifference, float]:
    if first.container is None or second.container is None:
        container = _differs(first.container is None, second.container is None)
    else:
        container = _share(abs(first.container - second.container), 400)
    fractions = {
        StyleDifference.BOXING: _differs(first.boxing, second.boxing),
        StyleDifference.TITLE_SCALE: _share(abs(first.title_ratio - second.title_ratio), 2.0),
        StyleDifference.CONTAINER: container,
        StyleDifference.BORDER: _differs(first.border, second.border),
        StyleDifference.RADIUS: _differs(first.radius, second.radius),
        StyleDifference.COLUMNS: _differs(first.columns, second.columns),
        StyleDifference.SHADOW: _differs(
            first.shadow is ShadowClass.HARD, second.shadow is ShadowClass.HARD
        ),
        StyleDifference.UPPERCASE: _differs(first.uppercase >= 3, second.uppercase >= 3),
        StyleDifference.MONOSPACE: _differs(first.monospace, second.monospace),
        StyleDifference.GRADIENT: _differs(first.gradients > 0, second.gradients > 0),
        StyleDifference.COLOUR_FIELDS: _share(abs(first.colour_fields - second.colour_fields), 5),
        StyleDifference.TINTS: _share(abs(first.tints - second.tints), 5),
    }
    return {key: STYLE_WEIGHTS[key] * value for key, value in fractions.items()}


def _cosine_distance(first: Counter[str], second: Counter[str]) -> float:
    if not first and not second:
        return 0.0
    norm = math.sqrt(sum(value * value for value in first.values())) * math.sqrt(
        sum(value * value for value in second.values())
    )
    if norm == 0:
        return 1.0
    dot = sum(first[key] * second[key] for key in first.keys() & second.keys())
    return max(0.0, 1.0 - dot / norm)


def _jaccard_distance(first: frozenset[str], second: frozenset[str]) -> float:
    union = first | second
    return 1.0 - len(first & second) / len(union) if union else 0.0


def structure_parts(
    first: StructureProfile, second: StructureProfile
) -> dict[StructureDifference, float]:
    cards = abs(first.cards - second.cards)
    fractions = {
        StructureDifference.OUTLINE: _jaccard_distance(first.outline, second.outline),
        StructureDifference.TAGS: _share(_cosine_distance(first.tags, second.tags), 0.4),
        StructureDifference.TABLE: _differs(first.tables > 0, second.tables > 0),
        StructureDifference.CARDS: (
            _share(cards, max(first.cards, second.cards, 1)) if cards >= 3 else 0.0
        ),
        StructureDifference.SIDE_COLUMN: _differs(first.asides > 0, second.asides > 0),
        StructureDifference.NAVIGATION: _differs(first.navigation, second.navigation),
        StructureDifference.FORMS: _differs(first.forms > 0, second.forms > 0),
    }
    return {key: STRUCTURE_WEIGHTS[key] * value for key, value in fractions.items()}


def _score[Part: StrEnum](parts: Mapping[Part, float]) -> int:
    return min(100, round(sum(parts.values())))


def _measured[Part: StrEnum](
    parts: Mapping[Part, float], weights: Mapping[Part, int]
) -> dict[str, object]:
    return {
        "available": True,
        "score": _score(parts),
        "differences": [key.value for key, value in parts.items() if value >= weights[key] / 2],
    }


def _unavailable() -> dict[str, object]:
    return {"available": False, "score": None, "differences": []}


def styles_distance(first: StyleProfile, second: StyleProfile) -> dict[str, object]:
    return _measured(style_parts(first, second), STYLE_WEIGHTS)


def structure_distance(first: StructureProfile, second: StructureProfile) -> dict[str, object]:
    return _measured(structure_parts(first, second), STRUCTURE_WEIGHTS)


def declared_distance(first: DesignAlternative, second: DesignAlternative) -> dict[str, object]:
    first_language, second_language = first.visual_language, second.visual_language
    if first_language is None or second_language is None:
        return {
            "score": None,
            "axes_different": None,
            "axes": [],
            "choices_different": None,
            "choices_total": CHOICES_TOTAL,
            "primary_colour_distance": None,
        }
    choices = len(visual_differences(first_language.choices, second_language.choices))
    colour = colour_distance(
        first_language.palette_roles["primary"], second_language.palette_roles["primary"]
    )
    first_direction, second_direction = first_language.direction, second_language.direction
    axes: tuple[str, ...] = ()
    different: int | None = None
    if first_direction is None or second_direction is None:
        score = round(100 * choices / CHOICES_TOTAL)
    else:
        axes = differing_axes(first_direction.axes, second_direction.axes)
        different = len(axes)
        score = round(100 * different / len(DIRECTION_AXES))
    return {
        "score": score,
        "axes_different": different,
        "axes": list(axes),
        "choices_different": choices,
        "choices_total": CHOICES_TOTAL,
        "primary_colour_distance": round(colour, 2),
    }


_LAYOUT_CHECKS: Final[Mapping[DirectionLayout, Callable[[StyleProfile], bool]]] = MappingProxyType(
    {
        DirectionLayout.STAGE: lambda profile: (
            profile.container is not None and profile.container <= _STAGE_CONTAINER
        ),
        DirectionLayout.WORKBENCH: lambda profile: (
            profile.container is None or profile.container >= _WORKBENCH_CONTAINER
        ),
        DirectionLayout.EDITORIAL: lambda profile: (
            profile.columns is ColumnsClass.TWO_UNEVEN or profile.uneven_grids >= 1
        ),
        DirectionLayout.MOSAIC: lambda profile: profile.spans >= 2,
        DirectionLayout.PANELS: lambda profile: profile.columns is not ColumnsClass.NONE,
    }
)
_SHAPE_CHECKS: Final[Mapping[DirectionShape, Callable[[StyleProfile], bool]]] = MappingProxyType(
    {
        DirectionShape.ROUNDED_OUTLINE: lambda profile: (
            profile.radius is RadiusClass.ROUNDED and profile.border is not BorderClass.NONE
        ),
        DirectionShape.SQUARE_RULES: lambda profile: (
            profile.radius is RadiusClass.SQUARE and profile.boxing is not BoxingClass.BOXED
        ),
        DirectionShape.HEAVY_FRAME: lambda profile: (
            profile.border is BorderClass.THICK or profile.shadow is ShadowClass.HARD
        ),
        DirectionShape.SOFT_FILL: lambda profile: (
            profile.boxing is BoxingClass.OPEN or profile.border is BorderClass.NONE
        ),
        DirectionShape.PILL: lambda profile: (
            profile.radius in {RadiusClass.PILL, RadiusClass.ROUNDED}
        ),
    }
)
_TYPE_CHECKS: Final[Mapping[DirectionType, Callable[[StyleProfile], bool]]] = MappingProxyType(
    {
        DirectionType.EVEN: lambda profile: profile.title_ratio < _DISPLAY_RATIO,
        DirectionType.DISPLAY: lambda profile: profile.title_ratio >= _DISPLAY_RATIO,
        DirectionType.CAPS_LABELS: lambda profile: profile.uppercase >= 3,
        DirectionType.READING: lambda profile: (
            (profile.largest_font >= _READING_SIZE or profile.body_size >= _READING_SIZE)
            and profile.type_ratio < _READING_RATIO
        ),
    }
)
_COLOUR_CHECKS: Final[Mapping[DirectionColour, Callable[[StyleProfile], bool]]] = MappingProxyType(
    {
        DirectionColour.ACCENT_ONLY: lambda profile: profile.colour_fields <= 4,
        DirectionColour.FIELDS: lambda profile: profile.colour_fields >= 2,
        DirectionColour.INK: lambda profile: (
            profile.colour_fields <= 3 and profile.gradients == 0 and profile.tints <= 2
        ),
        DirectionColour.TINTED: lambda profile: profile.tints >= 3,
    }
)


def _status(check: Callable[[StyleProfile], bool] | None, profile: StyleProfile) -> str:
    if check is None:
        return AdherenceStatus.NOT_CHECKED.value
    return (AdherenceStatus.FOLLOWED if check(profile) else AdherenceStatus.NOT_FOLLOWED).value


def _axes_adherence(direction: VisualDirection, profile: StyleProfile) -> dict[str, str]:
    axes = direction.axes
    checks = {
        "layout": _LAYOUT_CHECKS.get(axes.layout),
        "shape": _SHAPE_CHECKS.get(axes.shape),
        "type": _TYPE_CHECKS.get(axes.type),
        "colour": _COLOUR_CHECKS.get(axes.colour),
        "density": None,
    }
    return {axis: _status(checks[axis], profile) for axis in DIRECTION_AXES}


def _direction(alternative: DesignAlternative) -> VisualDirection | None:
    language = alternative.visual_language
    return None if language is None else language.direction


def _direction_name(alternative: DesignAlternative) -> str | None:
    direction = _direction(alternative)
    return None if direction is None else direction.name


def _tokens(alternative: DesignAlternative) -> dict[str, str]:
    language = alternative.visual_language
    return {} if language is None else language.token_values


def _profiles(
    alternative: DesignAlternative, mockup: GeneratedMockup | None
) -> tuple[StyleProfile, StructureProfile] | None:
    if mockup is None:
        return None
    markups = [screen.markup for screen in mockup.screens]
    return (
        style_profile(mockup.styles, _tokens(alternative), markups=markups),
        structure_profile_from_markup(markups),
    )


def _adherence(
    alternative: DesignAlternative, profiles: tuple[StyleProfile, StructureProfile] | None
) -> dict[str, object]:
    direction = _direction(alternative)
    if direction is None or profiles is None:
        return {"available": False, "axes": {}}
    return {"available": True, "axes": _axes_adherence(direction, profiles[0])}


def direction_adherence(
    alternative: DesignAlternative, mockup: GeneratedMockup | None
) -> dict[str, object]:
    if _direction(alternative) is None:
        return {"available": False, "axes": {}}
    return _adherence(alternative, _profiles(alternative, mockup))


def _pair(
    first: DesignAlternative,
    second: DesignAlternative,
    first_profiles: tuple[StyleProfile, StructureProfile] | None,
    second_profiles: tuple[StyleProfile, StructureProfile] | None,
) -> dict[str, object]:
    styles, structure = _unavailable(), _unavailable()
    verdict = DistanceVerdict.UNKNOWN
    if first_profiles is not None and second_profiles is not None:
        style = style_parts(first_profiles[0], second_profiles[0])
        styles = _measured(style, STYLE_WEIGHTS)
        structure = structure_distance(first_profiles[1], second_profiles[1])
        close = _score(style) < STYLES_CLOSE
        verdict = DistanceVerdict.CLOSE if close else DistanceVerdict.FAR
    return {
        "first": first.code,
        "second": second.code,
        "declared": declared_distance(first, second),
        "styles": styles,
        "structure": structure,
        "verdict": verdict.value,
    }


def design_distance(
    first: DesignAlternative,
    second: DesignAlternative,
    *,
    first_mockup: GeneratedMockup | None = None,
    second_mockup: GeneratedMockup | None = None,
) -> dict[str, object]:
    return _pair(first, second, _profiles(first, first_mockup), _profiles(second, second_mockup))


def design_distance_report(
    version: DesignPackageVersion, mockups: Mapping[UUID, GeneratedMockup]
) -> dict[str, object]:
    alternatives = version.package.alternatives
    profiles = {item.id: _profiles(item, mockups.get(item.id)) for item in alternatives}
    return {
        "distance_version": DESIGN_DISTANCE_VERSION,
        "design_version_id": str(version.id),
        "design_content_hash": version.content_hash,
        "pairs": [
            _pair(first, second, profiles[first.id], profiles[second.id])
            for index, first in enumerate(alternatives)
            for second in alternatives[index + 1 :]
        ],
        "alternatives": [
            {
                "code": item.code,
                "direction": _direction_name(item),
                "adherence": _adherence(item, profiles[item.id]),
            }
            for item in alternatives
        ],
    }


__all__ = [
    "CHOICES_TOTAL",
    "DEFAULT_BODY_SIZE",
    "DESIGN_DISTANCE_VERSION",
    "OUTLINE_DEPTH",
    "SEMANTIC_ELEMENTS",
    "STRUCTURE_WEIGHTS",
    "STYLES_CLOSE",
    "STYLE_WEIGHTS",
    "AdherenceStatus",
    "BorderClass",
    "BoxingClass",
    "ColumnsClass",
    "DistanceVerdict",
    "NavigationPlacement",
    "RadiusClass",
    "ShadowClass",
    "StructureDifference",
    "StructureProfile",
    "StyleDifference",
    "StyleProfile",
    "declared_distance",
    "design_distance",
    "design_distance_report",
    "direction_adherence",
    "structure_distance",
    "structure_parts",
    "structure_profile",
    "structure_profile_from_markup",
    "style_parts",
    "style_profile",
    "styles_distance",
]
