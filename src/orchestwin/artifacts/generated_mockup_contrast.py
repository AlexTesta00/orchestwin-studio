from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from orchestwin.artifacts.generated_mockup_repair import RepairNote
from orchestwin.artifacts.generated_mockup_review import (
    CONTROL_BORDER_THRESHOLD,
    MAX_SELECTOR_DETAIL,
    Resolver,
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
class _Change:
    rule: int
    declaration: int
    node: int
    code: str
    token: str
    ratio: float


def _palette(tokens: Mapping[str, str]) -> dict[str, str]:
    palette: dict[str, str] = {}
    for name in REPLACEMENT_TOKENS:
        value = tokens.get(f"--vl-color-{name}")
        if value is not None and is_hex_colour(value):
            palette[name] = value
    return palette


def _text_choice(
    palette: Mapping[str, str], original: str, backgrounds: Sequence[str], threshold: float
) -> tuple[str, float] | None:
    chosen: tuple[tuple[float, float], str, float] | None = None
    for name, value in palette.items():
        ratio = max(contrast_ratio(value, background) for background in backgrounds)
        if ratio < threshold:
            continue
        key = (colour_distance(original, value), -ratio)
        if chosen is None or key < chosen[0]:
            chosen = (key, name, ratio)
    return None if chosen is None else (chosen[1], chosen[2])


def _border_choice(
    palette: Mapping[str, str], surfaces: Sequence[str], ui_threshold: float
) -> tuple[str, float] | None:
    muted = palette.get("text-muted")
    if muted is not None:
        ratios = [contrast_ratio(muted, surface) for surface in surfaces]
        if min(ratios) >= max(ui_threshold, CONTROL_BORDER_THRESHOLD):
            return "text-muted", max(ratios)
    text = palette.get("text")
    if text is not None:
        best = max(contrast_ratio(text, surface) for surface in surfaces)
        if best >= CONTROL_BORDER_THRESHOLD:
            return "text", best
    return None


def _changes(
    sheet: StyleSheet,
    tokens: Mapping[str, str],
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> list[_Change]:
    resolver = Resolver(sheet, tokens)
    rules = [rule for rule in sheet.rules if not rule.in_keyframes]
    candidates = background_candidates(rules, resolver, tokens)
    palette = _palette(tokens)
    background = tokens.get("--vl-color-background")
    surface = tokens.get("--vl-color-surface")
    border = (
        _border_choice(palette, (background, surface), ui_threshold)
        if background is not None
        and surface is not None
        and is_hex_colour(background)
        and is_hex_colour(surface)
        else None
    )
    changes: list[_Change] = []
    for position, rule in enumerate(sheet.rules):
        if rule.in_keyframes:
            continue
        measured = text_contrast(rule, resolver, candidates)
        threshold = large_text_threshold if is_large_text(rule, tokens) else text_threshold
        if measured is not None and measured.ratio < threshold:
            choice = _text_choice(palette, measured.colour, measured.backgrounds, threshold)
            if choice is not None:
                changes.append(_Change(position, measured.index, 0, TEXT_COLOUR_REPLACED, *choice))
        if border is not None:
            changes.extend(
                _Change(position, weak.index, weak.node, CONTROL_BORDER_REPLACED, *border)
                for weak in weak_control_borders(rule, resolver, tokens)
            )
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


def _notes(entries: Iterable[tuple[str, str]]) -> tuple[RepairNote, ...]:
    counted = Counter(entries)
    notes = (RepairNote(code, None, name, number) for (code, name), number in counted.items())
    return tuple(sorted(notes, key=lambda note: (note.code, note.name)))


def repair_contrast(
    styles: str,
    tokens: Mapping[str, str],
    *,
    text_threshold: float,
    large_text_threshold: float,
    ui_threshold: float,
) -> tuple[str, tuple[RepairNote, ...]]:
    try:
        sheet = parse_style_sheet(styles)
    except GeneratedMockupError:
        return styles, ()
    changes = _changes(sheet, tokens, text_threshold, large_text_threshold, ui_threshold)
    if not changes:
        return styles, ()
    text = normalize_styles(styles)
    stream = tokenize_styles(text)
    locator = _Locator(stream)
    locator.rule_list()
    if [[name for name, _start, _end in found] for found in locator.rules] != [
        [declaration.name for declaration in rule.declarations] for rule in sheet.rules
    ]:
        return styles, ()
    offsets = [0]
    for token in stream:
        offsets.append(offsets[-1] + len(token.text))
    edits: list[tuple[int, int, str]] = []
    entries: list[tuple[str, str]] = []
    for change in changes:
        rule = sheet.rules[change.rule]
        _name, start, end = locator.rules[change.rule][change.declaration]
        ranges = _node_ranges(stream, start, _value_end(stream, start, end))
        if len(ranges) != len(significant(rule.declarations[change.declaration].nodes)):
            return styles, ()
        begin, stop = ranges[change.node]
        replacement = f"var(--vl-color-{change.token})"
        old = _PRINTABLE.sub("?", text_of_tokens(stream[begin:stop]))[:MAX_SELECTOR_DETAIL]
        edits.append((offsets[begin], offsets[stop], replacement))
        entries.append(
            (change.code, f"{selector_detail(rule)} {old}→{replacement} {change.ratio:.2f}")
        )
    repaired = _spliced(text, edits)
    if len(repaired) > MAX_STYLES_LENGTH:
        return styles, ()
    return repaired, _notes(entries)


__all__ = [
    "CONTRAST_NOTE_CODES",
    "CONTROL_BORDER_REPLACED",
    "REPLACEMENT_TOKENS",
    "TEXT_COLOUR_REPLACED",
    "repair_contrast",
]
