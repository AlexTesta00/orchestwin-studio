from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.colour_names import colour_name_key
from orchestwin.artifacts.generated_mockup_repair import RepairNote
from orchestwin.artifacts.generated_mockup_review import (
    CONTROL_BORDER_THRESHOLD,
    MAX_SELECTOR_DETAIL,
    Resolver,
    WeakBorder,
    background_candidates,
    is_large_text,
    selector_detail,
    text_contrast,
    weak_control_borders,
)
from orchestwin.artifacts.generated_mockup_styles import (
    MAX_STYLES_LENGTH,
    CssToken,
    GeneratedMockupError,
    StyleRule,
    StyleSheet,
    normalize_styles,
    parse_style_sheet,
    significant,
    text_of_tokens,
    tokenize_styles,
)
from orchestwin.artifacts.visual_color import colour_distance, contrast_ratio, is_hex_colour

TEXT_COLOUR_REPLACED: Final = "TEXT_COLOUR_REPLACED"
CONTROL_BORDER_REPLACED: Final = "CONTROL_BORDER_REPLACED"
CONTRAST_NOTE_CODES: Final = (CONTROL_BORDER_REPLACED, TEXT_COLOUR_REPLACED)
REPLACEMENT_TOKENS: Final = (
    "text",
    "text-muted",
    "on-primary",
    "on-accent",
    "background",
    "surface",
    "surface-alt",
)
_PROPERTIES: Final = MappingProxyType(
    {TEXT_COLOUR_REPLACED: "color", CONTROL_BORDER_REPLACED: "border-color"}
)
_CONTROL_SURFACES: Final = ("background", "surface")
_INHERITED_BACKGROUND: Final = "UNREADABLE_TEXT_COLOUR"
_RATIO_DIGITS: Final = 2
_OPENERS: Final = frozenset({"function", "(", "["})
_CLOSERS: Final = frozenset({")", "]"})
_BLANK: Final = frozenset({"whitespace"})
_SEPARATORS: Final = frozenset({"whitespace", "semicolon"})
_BLOCK_STOPS: Final = frozenset({"{", "semicolon"})
_FRAME_STOPS: Final = frozenset({"{"})
_VALUE_STOPS: Final = frozenset({"semicolon", "}"})
_PRINTABLE: Final = re.compile(r"[^\x20-\x7e]")

_Located = tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class ContrastCorrection:
    code: str
    selector: str
    property: str
    before_value: str
    before_hex: str
    before_ratio: float
    after_token: str
    after_hex: str
    after_ratio: float
    background_hex: str
    inherited_background: bool
    threshold: float
    large_text: bool
    count: int

    def to_snapshot(self) -> dict[str, object]:
        return {
            "code": self.code,
            "selector": self.selector,
            "property": self.property,
            "before": {
                "value": self.before_value,
                "hex": self.before_hex,
                "ratio": round(self.before_ratio, _RATIO_DIGITS),
                "name": colour_name_key(self.before_hex),
            },
            "after": {
                "token": self.after_token,
                "hex": self.after_hex,
                "ratio": round(self.after_ratio, _RATIO_DIGITS),
                "name": colour_name_key(self.after_hex),
            },
            "background": {
                "hex": self.background_hex,
                "name": colour_name_key(self.background_hex),
                "inherited": self.inherited_background,
            },
            "threshold": self.threshold,
            "large_text": self.large_text,
            "count": self.count,
        }


@dataclass(frozen=True, slots=True)
class _Change:
    rule: int
    declaration: int
    node: int
    code: str
    token: str
    before: str
    after: str
    backgrounds: tuple[str, ...]
    inherited: bool
    threshold: float
    large_text: bool

    @property
    def background(self) -> str:
        return max(self.backgrounds, key=lambda background: contrast_ratio(self.after, background))

    @property
    def ratio(self) -> float:
        return contrast_ratio(self.after, self.background)


@dataclass(frozen=True, slots=True)
class _Context:
    tokens: Mapping[str, str]
    resolver: Resolver
    candidates: tuple[str, ...]
    palette: Mapping[str, str]
    surfaces: tuple[str, ...]
    border: str | None
    text_threshold: float
    large_text_threshold: float


def _palette(tokens: Mapping[str, str]) -> dict[str, str]:
    palette: dict[str, str] = {}
    for name in REPLACEMENT_TOKENS:
        value = tokens.get(f"--vl-color-{name}")
        if value is not None and is_hex_colour(value):
            palette[name] = value
    return palette


def _surfaces(tokens: Mapping[str, str]) -> tuple[str, ...]:
    values = tuple(tokens.get(f"--vl-color-{name}", "") for name in _CONTROL_SURFACES)
    return values if all(is_hex_colour(value) for value in values) else ()


def _text_choice(
    palette: Mapping[str, str], original: str, backgrounds: Sequence[str], threshold: float
) -> str | None:
    chosen: tuple[tuple[float, float], str] | None = None
    for name, value in palette.items():
        ratio = max(contrast_ratio(value, background) for background in backgrounds)
        if ratio < threshold:
            continue
        key = (colour_distance(original, value), -ratio)
        if chosen is None or key < chosen[0]:
            chosen = (key, name)
    return None if chosen is None else chosen[1]


def _border_choice(
    palette: Mapping[str, str], surfaces: Sequence[str], ui_threshold: float
) -> str | None:
    muted = palette.get("text-muted")
    floor = max(ui_threshold, CONTROL_BORDER_THRESHOLD)
    if muted is not None and all(contrast_ratio(muted, surface) >= floor for surface in surfaces):
        return "text-muted"
    text = palette.get("text")
    if text is not None and any(
        contrast_ratio(text, surface) >= CONTROL_BORDER_THRESHOLD for surface in surfaces
    ):
        return "text"
    return None


def _context(
    sheet: StyleSheet,
    tokens: Mapping[str, str],
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> _Context:
    resolver = Resolver(sheet, tokens)
    rules = [rule for rule in sheet.rules if not rule.in_keyframes]
    palette = _palette(tokens)
    surfaces = _surfaces(tokens)
    return _Context(
        tokens=tokens,
        resolver=resolver,
        candidates=tuple(background_candidates(rules, resolver, tokens)),
        palette=palette,
        surfaces=surfaces,
        border=_border_choice(palette, surfaces, ui_threshold) if surfaces else None,
        text_threshold=text_threshold,
        large_text_threshold=large_text_threshold,
    )


def _text_change(context: _Context, position: int, rule: StyleRule) -> _Change | None:
    measured = text_contrast(rule, context.resolver, context.candidates)
    large = is_large_text(rule, context.tokens)
    threshold = context.large_text_threshold if large else context.text_threshold
    if measured is None or measured.ratio >= threshold:
        return None
    token = _text_choice(context.palette, measured.colour, measured.backgrounds, threshold)
    if token is None:
        return None
    return _Change(
        rule=position,
        declaration=measured.index,
        node=0,
        code=TEXT_COLOUR_REPLACED,
        token=token,
        before=measured.colour,
        after=context.palette[token],
        backgrounds=measured.backgrounds,
        inherited=measured.code == _INHERITED_BACKGROUND,
        threshold=threshold,
        large_text=large,
    )


def _weak_colour(resolver: Resolver, rule: StyleRule, weak: WeakBorder) -> str:
    colour = resolver.colour(significant(rule.declarations[weak.index].nodes)[weak.node])
    assert colour is not None
    return colour.hex


def _border_changes(context: _Context, position: int, rule: StyleRule) -> list[_Change]:
    token = context.border
    if token is None:
        return []
    return [
        _Change(
            rule=position,
            declaration=weak.index,
            node=weak.node,
            code=CONTROL_BORDER_REPLACED,
            token=token,
            before=_weak_colour(context.resolver, rule, weak),
            after=context.palette[token],
            backgrounds=context.surfaces,
            inherited=False,
            threshold=CONTROL_BORDER_THRESHOLD,
            large_text=False,
        )
        for weak in weak_control_borders(rule, context.resolver, context.tokens)
    ]


def _changes(
    sheet: StyleSheet,
    tokens: Mapping[str, str],
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> list[_Change]:
    context = _context(sheet, tokens, text_threshold, large_text_threshold, ui_threshold)
    changes: list[_Change] = []
    for position, rule in enumerate(sheet.rules):
        if rule.in_keyframes:
            continue
        text = _text_change(context, position, rule)
        if text is not None:
            changes.append(text)
        changes.extend(_border_changes(context, position, rule))
    return changes


class _Locator:
    def __init__(self, stream: Sequence[CssToken]) -> None:
        self.stream = stream
        self.index = 0
        self.rules: list[list[_Located]] = []

    def kind(self, skipped: frozenset[str] = _BLANK) -> str | None:
        while self.index < len(self.stream) and self.stream[self.index].kind in skipped:
            self.index += 1
        return self.stream[self.index].kind if self.index < len(self.stream) else None

    def until(self, stops: frozenset[str]) -> int:
        depth = 0
        position = self.index
        while position < len(self.stream):
            kind = self.stream[position].kind
            if not depth and kind in stops:
                break
            if kind in _OPENERS:
                depth += 1
            elif kind in _CLOSERS and depth:
                depth -= 1
            position += 1
        return position

    def rule_list(self) -> None:
        while (kind := self.kind()) is not None:
            if kind == "}":
                self.index += 1
                return
            name = self.stream[self.index].value if kind == "at-keyword" else ""
            self.index = self.until(_BLOCK_STOPS)
            opened = self.index < len(self.stream) and self.stream[self.index].kind == "{"
            self.index += 1
            if not opened:
                continue
            if name == "keyframes":
                self.frames()
            elif name:
                self.rule_list()
            else:
                self.declarations()

    def frames(self) -> None:
        while (kind := self.kind()) is not None:
            if kind == "}":
                self.index += 1
                return
            self.index = self.until(_FRAME_STOPS) + 1
            self.declarations()

    def declarations(self) -> None:
        found: list[_Located] = []
        self.rules.append(found)
        while (kind := self.kind(_SEPARATORS)) is not None:
            if kind == "}":
                self.index += 1
                return
            name = self.stream[self.index].value
            self.index += 1
            self.kind()
            self.index += 1
            end = self.until(_VALUE_STOPS)
            found.append((name, self.index, end))
            self.index = end


def _value_end(stream: Sequence[CssToken], start: int, end: int) -> int:
    position = end
    while position > start and stream[position - 1].kind == "whitespace":
        position -= 1
    last = stream[position - 1] if position > start else None
    if last is None or last.kind != "ident" or last.value.lower() != "important":
        return position
    mark = position - 1
    while mark > start and stream[mark - 1].kind == "whitespace":
        mark -= 1
    if mark > start and stream[mark - 1].kind == "delim" and stream[mark - 1].value == "!":
        return mark - 1
    return position


def _node_ranges(stream: Sequence[CssToken], start: int, end: int) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    depth = 0
    begin = start
    for position in range(start, end):
        kind = stream[position].kind
        if not depth:
            begin = position
        if kind in _OPENERS:
            depth += 1
        elif kind in _CLOSERS and depth:
            depth -= 1
        if not depth and kind != "whitespace":
            ranges.append((begin, position + 1))
    return ranges


def _spliced(text: str, edits: Iterable[tuple[int, int, str]]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, stop, replacement in sorted(edits):
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        cursor = stop
    pieces.append(text[cursor:])
    return "".join(pieces)


def _replacement(token: str) -> str:
    return f"var(--vl-color-{token})"


def _correction(change: _Change, selector: str, value: str) -> ContrastCorrection:
    background = change.background
    return ContrastCorrection(
        code=change.code,
        selector=selector,
        property=_PROPERTIES[change.code],
        before_value=value,
        before_hex=change.before.upper(),
        before_ratio=contrast_ratio(change.before, background),
        after_token=change.token,
        after_hex=change.after.upper(),
        after_ratio=change.ratio,
        background_hex=background.upper(),
        inherited_background=change.inherited,
        threshold=change.threshold,
        large_text=change.large_text,
        count=1,
    )


def _note_name(correction: ContrastCorrection) -> str:
    replacement = _replacement(correction.after_token)
    return (
        f"{correction.selector} {correction.before_value}→{replacement} "
        f"{correction.after_ratio:.2f}"
    )


def _notes(entries: Iterable[tuple[str, str]]) -> tuple[RepairNote, ...]:
    counted = Counter(entries)
    notes = (RepairNote(code, None, name, number) for (code, name), number in counted.items())
    return tuple(sorted(notes, key=lambda note: (note.code, note.name)))


def _merged(corrections: Iterable[ContrastCorrection]) -> tuple[ContrastCorrection, ...]:
    counted = Counter(corrections)
    merged = (replace(correction, count=number) for correction, number in counted.items())
    return tuple(sorted(merged, key=lambda correction: (correction.code, _note_name(correction))))


def _rewritten(
    styles: str, sheet: StyleSheet, changes: Sequence[_Change]
) -> tuple[str, list[ContrastCorrection]] | None:
    text = normalize_styles(styles)
    stream = tokenize_styles(text)
    locator = _Locator(stream)
    locator.rule_list()
    if [[name for name, _start, _end in found] for found in locator.rules] != [
        [declaration.name for declaration in rule.declarations] for rule in sheet.rules
    ]:
        return None
    offsets = [0]
    for token in stream:
        offsets.append(offsets[-1] + len(token.text))
    edits: list[tuple[int, int, str]] = []
    corrections: list[ContrastCorrection] = []
    for change in changes:
        rule = sheet.rules[change.rule]
        _name, start, end = locator.rules[change.rule][change.declaration]
        ranges = _node_ranges(stream, start, _value_end(stream, start, end))
        if len(ranges) != len(significant(rule.declarations[change.declaration].nodes)):
            return None
        begin, stop = ranges[change.node]
        old = _PRINTABLE.sub("?", text_of_tokens(stream[begin:stop]))[:MAX_SELECTOR_DETAIL]
        edits.append((offsets[begin], offsets[stop], _replacement(change.token)))
        corrections.append(_correction(change, selector_detail(rule), old))
    repaired = _spliced(text, edits)
    return None if len(repaired) > MAX_STYLES_LENGTH else (repaired, corrections)


def repair_contrast_with_corrections(
    styles: str,
    tokens: Mapping[str, str],
    *,
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> tuple[str, tuple[RepairNote, ...], tuple[ContrastCorrection, ...]]:
    try:
        sheet = parse_style_sheet(styles)
    except GeneratedMockupError:
        return styles, (), ()
    changes = _changes(sheet, tokens, text_threshold, large_text_threshold, ui_threshold)
    rewritten = _rewritten(styles, sheet, changes) if changes else None
    if rewritten is None:
        return styles, (), ()
    repaired, corrections = rewritten
    notes = _notes((correction.code, _note_name(correction)) for correction in corrections)
    return repaired, notes, _merged(corrections)


def repair_contrast(
    styles: str,
    tokens: Mapping[str, str],
    *,
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> tuple[str, tuple[RepairNote, ...]]:
    repaired, notes, _corrections = repair_contrast_with_corrections(
        styles,
        tokens,
        text_threshold=text_threshold,
        large_text_threshold=large_text_threshold,
        ui_threshold=ui_threshold,
    )
    return repaired, notes


__all__ = [
    "CONTRAST_NOTE_CODES",
    "CONTROL_BORDER_REPLACED",
    "REPLACEMENT_TOKENS",
    "TEXT_COLOUR_REPLACED",
    "ContrastCorrection",
    "repair_contrast",
    "repair_contrast_with_corrections",
]
