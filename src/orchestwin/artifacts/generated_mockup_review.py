from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from orchestwin.artifacts.generated_mockup_structure import (
    DerivedElement,
    ScreenIndex,
    derive_elements,
    node_text,
    nodes_text,
    normalize,
    requirement_codes_of,
    walk_elements,
)
from orchestwin.artifacts.generated_mockup_styles import (
    CssBlock,
    CssNode,
    CssToken,
    StyleDeclaration,
    StyleRule,
    StyleSheet,
    is_function,
    parse_style_sheet,
    significant,
    split_commas,
    tokenize_styles,
    variable_reference,
)
from orchestwin.artifacts.generated_mockups import (
    SVG_SHAPES,
    GeneratedMockup,
    MarkupElement,
    MarkupNode,
    MarkupText,
    screen_trees,
)
from orchestwin.artifacts.prototypes import PrototypeScreenState
from orchestwin.artifacts.visual_color import contrast_ratio, format_hex, is_hex_colour, parse_hex

MIN_VISIBLE_TEXT: Final = 150
MIN_DERIVED_ELEMENTS: Final = 6
MIN_TABLE_ROWS: Final = 3
RECOMMENDED_TABLE_ROWS: Final = 6
MIN_SELECT_OPTIONS: Final = 2
MIN_LIST_ITEMS: Final = 2
CONTROL_BORDER_THRESHOLD: Final = 3.0
CONTRAST_FLOOR: Final = 3.0
STRICT_CONTRAST_FLOOR: Final = 4.5
STRICT_CONTRAST_THRESHOLD: Final = 7.0
_ENTRY: Final = "SCR-001"
_ACTIONS: Final = frozenset({"a", "button"})
_TRACED: Final = frozenset({"a", "button", "input", "select", "textarea"})
_LABELLED: Final = frozenset({"input", "select", "textarea", "meter", "progress"})
_CONTROLS: Final = frozenset({"button", "input", "select", "textarea"})
_CELL_CONTROLS: Final = frozenset(
    {"a", "button", "input", "select", "textarea", "meter", "progress", "output"}
)
_FILLERS: Final = (
    frozenset(
        {
            "a",
            "button",
            "input",
            "select",
            "textarea",
            "option",
            "optgroup",
            "hr",
            "br",
            "col",
            "td",
            "progress",
            "meter",
        }
    )
    | SVG_SHAPES
)
_HEADING_LEVELS: Final = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_PLACEHOLDER: Final = re.compile(
    r"(?<!\w)(lorem\s+ipsum|dolor\s+sit\s+amet|placeholder\s+text|testo\s+di\s+esempio"
    r"|todo|tbd|xxx|foo\s+bar)(?!\w)",
    re.IGNORECASE,
)
_PLACEHOLDER_ATTRIBUTES: Final = frozenset(
    {"aria-label", "aria-description", "aria-placeholder", "placeholder", "value", "label"}
)
DATED_BACKGROUND_FUNCTIONS: Final = frozenset(
    {
        "repeating-linear-gradient",
        "repeating-radial-gradient",
        "repeating-conic-gradient",
        "conic-gradient",
    }
)
_STRONG_BACKGROUNDS: Final = frozenset({"primary", "accent", "success", "danger"})
_WIDTH_FEATURES: Final = frozenset({"width", "min-width", "max-width"})
_CONTROL_SELECTORS: Final = frozenset({"input", "select", "textarea", "button"})
_BORDER_SHORTHANDS: Final = frozenset(
    {
        "border",
        "border-top",
        "border-right",
        "border-bottom",
        "border-left",
        "border-block",
        "border-inline",
        "border-block-start",
        "border-block-end",
        "border-inline-start",
        "border-inline-end",
    }
)
_CANDIDATE_TOKENS: Final = ("background", "surface", "surface-alt")
_BACKGROUNDS: Final = frozenset({"background", "background-color"})
_PRINTABLE: Final = re.compile(r"[^\x20-\x7e]")
MAX_SELECTOR_DETAIL: Final = 80


class MockupIssueSeverity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True)
class MockupIssue:
    code: str
    severity: MockupIssueSeverity
    screen_code: str | None
    detail: str

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "screen_code": self.screen_code,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MockupScreenSummary:
    screen_code: str
    element_count: int
    control_count: int
    link_count: int
    text_length: int
    requirement_codes: tuple[str, ...]

    def to_snapshot(self) -> dict[str, object]:
        return {
            "screen_code": self.screen_code,
            "element_count": self.element_count,
            "control_count": self.control_count,
            "link_count": self.link_count,
            "text_length": self.text_length,
            "requirement_codes": list(self.requirement_codes),
        }


@dataclass(frozen=True, slots=True)
class MockupReport:
    issues: tuple[MockupIssue, ...]
    covered_requirement_codes: tuple[str, ...]
    screens: tuple[MockupScreenSummary, ...]
    is_acceptable: bool

    def __post_init__(self) -> None:
        errors = any(issue.severity is MockupIssueSeverity.ERROR for issue in self.issues)
        if self.is_acceptable is errors:
            raise ValueError("a mockup report is acceptable exactly when it has no error")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "issues": [issue.to_snapshot() for issue in self.issues],
            "covered_requirement_codes": list(self.covered_requirement_codes),
            "screens": [screen.to_snapshot() for screen in self.screens],
            "is_acceptable": self.is_acceptable,
        }


@dataclass(slots=True)
class _Issues:
    found: set[MockupIssue] = field(default_factory=set)

    def error(self, code: str, screen_code: str | None, detail: str) -> None:
        self.found.add(MockupIssue(code, MockupIssueSeverity.ERROR, screen_code, detail))

    def warning(self, code: str, screen_code: str | None, detail: str) -> None:
        self.found.add(MockupIssue(code, MockupIssueSeverity.WARNING, screen_code, detail))

    def ordered(self) -> tuple[MockupIssue, ...]:
        return tuple(
            sorted(
                self.found,
                key=lambda issue: (issue.screen_code or "", issue.code, issue.detail),
            )
        )


def _describe(node: MarkupElement, ordinal: int) -> str:
    identifier = node.attribute("id")
    return f"{node.name} #{identifier}" if identifier else f"{node.name} {ordinal}"


def _placeholders(values: Iterable[str]) -> set[str]:
    found: set[str] = set()
    for value in values:
        found.update(normalize(match.group(0)).lower() for match in _PLACEHOLDER.finditer(value))
    return found


def _texts(nodes: Iterable[MarkupNode]) -> Iterable[str]:
    for node in nodes:
        if isinstance(node, MarkupText):
            yield node.text
        else:
            for name, value in node.attributes:
                if name in _PLACEHOLDER_ATTRIBUTES and value:
                    yield value
            yield from _texts(node.children)


def _owned(table: MarkupElement, name: str) -> list[MarkupElement]:
    found: list[MarkupElement] = []

    def visit(nodes: Iterable[MarkupNode]) -> None:
        for node in nodes:
            if isinstance(node, MarkupElement) and node.name != "table":
                if node.name == name:
                    found.append(node)
                visit(node.children)

    visit(table.children)
    return found


def _review_screen(
    screen_code: str,
    state: PrototypeScreenState,
    title: str,
    nodes: tuple[MarkupNode, ...],
    derived: Sequence[DerivedElement],
    known: frozenset[str],
    issues: _Issues,
) -> tuple[MockupScreenSummary, set[str]]:
    index = ScreenIndex(screen_code, nodes)
    ordinals: dict[str, int] = {}
    counts = {"element": 0, "control": 0, "link": 0, "h1": 0}
    heading_level = 0
    targets: set[str] = set()
    for node, _path, ancestors in walk_elements(nodes):
        name = node.name
        ordinals[name] = ordinals.get(name, 0) + 1
        place = _describe(node, ordinals[name])
        counts["element"] += 1
        counts["control"] += name in _CONTROLS
        counts["link"] += name == "a"
        for code in (node.attribute("data-req") or "").split():
            if code not in known:
                issues.warning("UNKNOWN_REQUIREMENT", screen_code, f"requirement {code}")
        if name == "a" and node.attribute("href"):
            target = str(node.attribute("href"))[1:]
            targets.add(target)
            if target == screen_code and node.attribute("aria-current") != "page":
                issues.warning("SELF_LINK", screen_code, place)
        if name in _TRACED and not requirement_codes_of(node, ancestors):
            issues.error("UNTRACED_CONTROL", screen_code, place)
        if name in _LABELLED and not index.label(node, ancestors):
            issues.warning("UNLABELLED_CONTROL", screen_code, place)
        if name in _ACTIONS and not (
            node_text(node) or normalize(node.attribute("aria-label") or "")
        ):
            issues.warning("UNNAMED_ACTION", screen_code, place)
        if name == "table":
            if not _owned(node, "th"):
                issues.warning("TABLE_WITHOUT_HEADERS", screen_code, place)
            rows = [row for body in _owned(node, "tbody") for row in body.elements]
            if state is not PrototypeScreenState.EMPTY and len(rows) < RECOMMENDED_TABLE_ROWS:
                record = issues.error if len(rows) < MIN_TABLE_ROWS else issues.warning
                record("TABLE_TOO_SHORT", screen_code, f"{place} has {len(rows)} rows")
        if (
            name == "td"
            and not node_text(node)
            and not any(
                item.name in _CELL_CONTROLS for item, _p, _a in walk_elements(node.children)
            )
        ):
            issues.warning("EMPTY_CELL", screen_code, place)
        if name == "select":
            options = [
                item
                for item, _p, _a in walk_elements(node.children)
                if item.name == "option"
                and (normalize(item.attribute("label") or "") or node_text(item))
            ]
            if len(options) < MIN_SELECT_OPTIONS:
                issues.warning(
                    "SELECT_TOO_SHORT", screen_code, f"{place} has {len(options)} options"
                )
        if name in _HEADING_LEVELS:
            level = _HEADING_LEVELS[name]
            counts["h1"] += level == 1
            if level > heading_level + 1:
                issues.warning(
                    "HEADING_LEVEL_SKIPPED", screen_code, f"{place} after h{heading_level}"
                )
            heading_level = level
        if (
            name in {"ul", "ol"}
            and not any(item.name == "nav" for item in ancestors)
            and len([item for item in node.elements if item.name == "li"]) < MIN_LIST_ITEMS
        ):
            issues.warning("LIST_TOO_SHORT", screen_code, place)
        if (
            name not in _FILLERS
            and not node.elements
            and not any(
                isinstance(child, MarkupText) and child.text.strip() for child in node.children
            )
        ):
            issues.warning("EMPTY_CONTAINER", screen_code, place)
        if (
            name == "svg"
            and not any(item.name == "svg" for item in ancestors)
            and node.attribute("aria-hidden") != "true"
            and not normalize(node.attribute("aria-label") or "")
        ):
            issues.warning("DECORATIVE_ICON_EXPOSED", screen_code, place)
    if counts["h1"] != 1:
        issues.warning("HEADING_COUNT", screen_code, f"{counts['h1']} main headings")
    text_length = len(nodes_text(nodes))
    if text_length < MIN_VISIBLE_TEXT or len(derived) < MIN_DERIVED_ELEMENTS:
        issues.error(
            "SCREEN_TOO_EMPTY",
            screen_code,
            f"{text_length} characters of text and {len(derived)} derived elements",
        )
    traced = {code for element in derived for code in element.requirement_codes}
    if not traced:
        issues.error("UNTRACED_SCREEN", screen_code, "no derived element names a requirement")
    for phrase in sorted(_placeholders((title, *_texts(nodes)))):
        issues.error("PLACEHOLDER_TEXT", screen_code, phrase)
    covered = tuple(sorted(traced & known))
    summary = MockupScreenSummary(
        screen_code=screen_code,
        element_count=counts["element"],
        control_count=counts["control"],
        link_count=counts["link"],
        text_length=text_length,
        requirement_codes=covered,
    )
    return summary, targets


@dataclass(frozen=True, slots=True)
class _Colour:
    red: float
    green: float
    blue: float
    alpha: float

    @property
    def opaque(self) -> bool:
        return self.alpha >= 1 - 1e-9

    @property
    def hex(self) -> str:
        return format_hex((self.red, self.green, self.blue))


_TRANSPARENT: Final = _Colour(0.0, 0.0, 0.0, 0.0)


class _Resolver:
    def __init__(self, sheet: StyleSheet, tokens: Mapping[str, str]) -> None:
        self.tokens = tokens
        definitions: dict[str, set[tuple[CssToken, ...]]] = {}
        for rule in sheet.rules:
            for declaration in rule.declarations:
                if declaration.name.startswith("--m-"):
                    definitions.setdefault(declaration.name, set()).add(declaration.value)
        self.definitions = {
            name: values.pop() for name, values in definitions.items() if len(values) == 1
        }

    def custom(self, name: str, seen: frozenset[str]) -> tuple[CssNode, ...] | None:
        value = self.definitions.get(name)
        if value is None or name in seen:
            return None
        return tuple(significant(StyleDeclaration(name, value, False).nodes))

    def token_name(self, node: CssNode, seen: frozenset[str] = frozenset()) -> str | None:
        reference = variable_reference(node)
        if reference is None or not isinstance(node, CssBlock):
            return None
        if len(split_commas(node.children)) != 1:
            return None
        if reference.startswith("--vl-color-"):
            return reference.removeprefix("--vl-color-")
        if reference.startswith("--m-"):
            value = self.custom(reference, seen)
            if value is not None and len(value) == 1:
                return self.token_name(value[0], seen | {reference})
        return None

    def colour(self, node: CssNode, seen: frozenset[str] = frozenset()) -> _Colour | None:
        if isinstance(node, CssToken):
            if node.kind == "ident" and node.value.lower() == "transparent":
                return _TRANSPARENT
            return None
        reference = variable_reference(node)
        if reference is not None:
            if len(split_commas(node.children)) != 1:
                return None
            if reference.startswith("--vl-color-"):
                value = self.tokens.get(reference)
                if value is None or not is_hex_colour(value):
                    return None
                red, green, blue = parse_hex(value)
                return _Colour(red, green, blue, 1.0)
            if reference.startswith("--m-"):
                value = self.custom(reference, seen)
                if value is not None and len(value) == 1:
                    return self.colour(value[0], seen | {reference})
            return None
        if is_function(node, "color-mix"):
            return self.mix(node, seen)
        return None

    def mix(self, node: CssBlock, seen: frozenset[str]) -> _Colour | None:
        parts = split_commas(node.children)[1:]
        if len(parts) != 2:
            return None
        colours: list[_Colour] = []
        weights: list[float | None] = []
        for part in parts:
            items = significant(part)
            percentages = [
                float(item.value)
                for item in items
                if isinstance(item, CssToken) and item.kind == "percentage"
            ]
            others = [
                item
                for item in items
                if not (isinstance(item, CssToken) and item.kind == "percentage")
            ]
            if len(others) != 1:
                return None
            colour = self.colour(others[0], seen)
            if colour is None:
                return None
            colours.append(colour)
            weights.append(percentages[0] if percentages else None)
        first, second = weights
        if first is None and second is None:
            first, second = 50.0, 50.0
        elif first is None:
            first = 100.0 - float(second or 0.0)
        elif second is None:
            second = 100.0 - first
        total = first + float(second)
        if total <= 0:
            return None
        share, other = first / total, float(second) / total
        multiplier = min(total, 100.0) / 100.0
        alpha = colours[0].alpha * share + colours[1].alpha * other
        if alpha <= 0:
            return _TRANSPARENT
        channels = [
            (
                getattr(colours[0], name) * colours[0].alpha * share
                + getattr(colours[1], name) * colours[1].alpha * other
            )
            / alpha
            for name in ("red", "green", "blue")
        ]
        return _Colour(channels[0], channels[1], channels[2], alpha * multiplier)

    def value(self, declaration: StyleDeclaration) -> _Colour | None:
        items = significant(declaration.nodes)
        return self.colour(items[0]) if len(items) == 1 else None

    def background(self, declaration: StyleDeclaration) -> tuple[str, _Colour | None]:
        items = significant(declaration.nodes)
        if declaration.name == "background-color":
            colour = self.value(declaration)
        else:
            if any(isinstance(item, CssToken) and item.kind == "comma" for item in items) or any(
                isinstance(item, CssBlock) and not is_function(item, "var", "color-mix")
                for item in items
            ):
                return "unknown", None
            colours = [
                item
                for item in items
                if isinstance(item, CssBlock)
                or (isinstance(item, CssToken) and item.value.lower() == "transparent")
            ]
            if not colours:
                return "transparent", _TRANSPARENT
            colour = self.colour(colours[0]) if len(colours) == 1 else None
        if colour is None:
            return "unknown", None
        if colour.opaque:
            return "opaque", colour
        if colour.alpha <= 0:
            return "transparent", colour
        return "unknown", None


def _last(rule: StyleRule, names: frozenset[str]) -> StyleDeclaration | None:
    chosen: StyleDeclaration | None = None
    for declaration in rule.declarations:
        if declaration.name in names and (
            chosen is None or declaration.important or not chosen.important
        ):
            chosen = declaration
    return chosen


def _functions(nodes: Iterable[CssNode]) -> Iterable[str]:
    for node in nodes:
        if isinstance(node, CssBlock):
            if node.opener.kind == "function":
                yield node.opener.value
            yield from _functions(node.children)


def _targets_controls(selector: str) -> bool:
    tokens = [token for token in tokenize_styles(selector) if token.kind != "whitespace"]
    brackets = 0
    negations: list[int] = []
    depth = 0
    for position, token in enumerate(tokens):
        previous = tokens[position - 1] if position else None
        if token.kind == "[":
            brackets += 1
        elif token.kind == "]":
            brackets -= 1
        elif token.kind in {"function", "("}:
            depth += 1
            if token.kind == "function" and token.value == "not":
                negations.append(depth)
        elif token.kind == ")":
            if negations and negations[-1] == depth:
                negations.pop()
            depth -= 1
        elif (
            token.kind == "ident"
            and not brackets
            and not negations
            and token.value.lower() in _CONTROL_SELECTORS
            and not (
                previous is not None
                and (
                    previous.kind == "colon"
                    or (previous.kind == "delim" and previous.value in ".#")
                )
            )
        ):
            return True
    return False


def _selector(rule: StyleRule) -> str:
    return _PRINTABLE.sub("?", rule.selector)[:MAX_SELECTOR_DETAIL]


def _candidates(
    rules: Sequence[StyleRule], resolver: _Resolver, tokens: Mapping[str, str]
) -> list[str]:
    candidates = [
        tokens[f"--vl-color-{name}"]
        for name in _CANDIDATE_TOKENS
        if is_hex_colour(tokens.get(f"--vl-color-{name}"))
    ]
    for rule in rules:
        declaration = _last(rule, _BACKGROUNDS)
        if declaration is None:
            continue
        state, fill = resolver.background(declaration)
        if state == "opaque" and fill is not None:
            candidates.append(fill.hex)
    return candidates


def is_dated_background(declaration: StyleDeclaration) -> bool:
    return declaration.name.startswith(("background", "--m-")) and bool(
        set(_functions(declaration.nodes)) & DATED_BACKGROUND_FUNCTIONS
    )


def contrast_floor(threshold: float) -> float:
    floor = STRICT_CONTRAST_FLOOR if threshold >= STRICT_CONTRAST_THRESHOLD else CONTRAST_FLOOR
    return min(floor, threshold)


def _review_styles(
    sheet: StyleSheet,
    tokens: Mapping[str, str],
    threshold: float,
    issues: _Issues,
) -> None:
    resolver = _Resolver(sheet, tokens)
    rules = [rule for rule in sheet.rules if not rule.in_keyframes]
    candidates = _candidates(rules, resolver, tokens)
    floor = contrast_floor(threshold)
    for rule in sheet.rules:
        if any(is_dated_background(declaration) for declaration in rule.declarations):
            issues.error("DATED_BACKGROUND", None, _selector(rule))
    for rule in rules:
        selector = _selector(rule)
        text = _last(rule, frozenset({"color"}))
        background = _last(rule, _BACKGROUNDS)
        state, fill = ("absent", None) if background is None else resolver.background(background)
        colour = None if text is None else resolver.value(text)
        if colour is not None and colour.opaque:
            if state == "opaque" and fill is not None:
                ratio = contrast_ratio(colour.hex, fill.hex)
                if ratio < threshold:
                    record = issues.error if ratio < floor else issues.warning
                    record("LOW_CONTRAST", None, f"{selector} {ratio:.2f}")
            elif state in {"absent", "transparent"} and candidates:
                best = max(contrast_ratio(colour.hex, candidate) for candidate in candidates)
                if best < threshold:
                    record = issues.error if best < floor else issues.warning
                    record("UNREADABLE_TEXT_COLOUR", None, f"{selector} {best:.2f}")
        if background is not None and text is None:
            items = significant(background.nodes)
            strong = next(
                (
                    name
                    for item in items
                    if (name := resolver.token_name(item)) in _STRONG_BACKGROUNDS
                ),
                None,
            )
            if strong is not None:
                issues.warning("BACKGROUND_WITHOUT_TEXT_COLOUR", None, f"{selector} {strong}")
        _review_border(rule, resolver, tokens, issues)
    if not any(
        token.kind == "ident" and token.value.lower() in _WIDTH_FEATURES
        for condition in sheet.media_conditions
        for token in tokenize_styles(condition)
    ):
        issues.warning("NO_RESPONSIVE_RULE", None, "no media query on the width")


def _review_border(
    rule: StyleRule, resolver: _Resolver, tokens: Mapping[str, str], issues: _Issues
) -> None:
    background = tokens.get("--vl-color-background")
    surface = tokens.get("--vl-color-surface")
    if not (
        background is not None
        and surface is not None
        and is_hex_colour(background)
        and is_hex_colour(surface)
        and _targets_controls(rule.selector)
    ):
        return
    weakest: float | None = None
    for declaration in rule.declarations:
        name = declaration.name
        if not (
            name in _BORDER_SHORTHANDS or (name.startswith("border") and name.endswith("-color"))
        ):
            continue
        for item in significant(declaration.nodes):
            colour = resolver.colour(item)
            if colour is None or not colour.opaque:
                continue
            best = max(contrast_ratio(colour.hex, background), contrast_ratio(colour.hex, surface))
            if best < CONTROL_BORDER_THRESHOLD and (weakest is None or best < weakest):
                weakest = best
    if weakest is not None:
        issues.warning("WEAK_CONTROL_BORDER", None, f"{_selector(rule)} {weakest:.2f}")


def review_generated_mockup(
    mockup: GeneratedMockup,
    *,
    tokens: Mapping[str, str],
    requirement_codes: Iterable[str],
    text_contrast_threshold: float = 4.5,
) -> MockupReport:
    known = frozenset(requirement_codes)
    trees = screen_trees(mockup)
    derived = derive_elements(mockup)
    issues = _Issues()
    summaries: list[MockupScreenSummary] = []
    links: dict[str, set[str]] = {}
    for screen in mockup.screens:
        summary, targets = _review_screen(
            screen.code,
            screen.state,
            screen.title,
            trees[screen.code],
            [element for element in derived if element.screen_code == screen.code],
            known,
            issues,
        )
        summaries.append(summary)
        links[screen.code] = targets
    if not any(links.values()):
        issues.error("NO_TRANSITION", None, "no link between screens")
    reached = {_ENTRY}
    frontier = [_ENTRY]
    while frontier:
        for target in links.get(frontier.pop(), set()):
            if target not in reached:
                reached.add(target)
                frontier.append(target)
    for screen in mockup.screens:
        if screen.code not in reached:
            issues.error(
                "UNREACHABLE_SCREEN", screen.code, f"{screen.code} has no path from {_ENTRY}"
            )
    for phrase in sorted(_placeholders((mockup.title,))):
        issues.error("PLACEHOLDER_TEXT", None, phrase)
    _review_styles(parse_style_sheet(mockup.styles), tokens, text_contrast_threshold, issues)
    if all(screen.state is PrototypeScreenState.DEFAULT for screen in mockup.screens):
        issues.warning("SINGLE_STATE", None, "every screen shows the default state")
    ordered = issues.ordered()
    return MockupReport(
        issues=ordered,
        covered_requirement_codes=tuple(
            sorted({code for summary in summaries for code in summary.requirement_codes})
        ),
        screens=tuple(summaries),
        is_acceptable=not any(issue.severity is MockupIssueSeverity.ERROR for issue in ordered),
    )


__all__ = [
    "CONTRAST_FLOOR",
    "CONTROL_BORDER_THRESHOLD",
    "DATED_BACKGROUND_FUNCTIONS",
    "MIN_DERIVED_ELEMENTS",
    "MIN_LIST_ITEMS",
    "MIN_SELECT_OPTIONS",
    "MIN_TABLE_ROWS",
    "MIN_VISIBLE_TEXT",
    "RECOMMENDED_TABLE_ROWS",
    "STRICT_CONTRAST_FLOOR",
    "STRICT_CONTRAST_THRESHOLD",
    "MockupIssue",
    "MockupIssueSeverity",
    "MockupReport",
    "MockupScreenSummary",
    "contrast_floor",
    "is_dated_background",
    "review_generated_mockup",
]
