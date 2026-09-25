from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.prototypes import PrototypeElementKind
from orchestwin.artifacts.visual_catalog import LayoutArchetype

HEADING: Final = PrototypeElementKind.HEADING.value
TEXT: Final = PrototypeElementKind.TEXT.value
TEXT_INPUT: Final = PrototypeElementKind.TEXT_INPUT.value
SELECT: Final = PrototypeElementKind.SELECT.value
BUTTON: Final = PrototypeElementKind.BUTTON.value
LINK: Final = PrototypeElementKind.LINK.value
LIST: Final = PrototypeElementKind.LIST.value
CARD: Final = PrototypeElementKind.CARD.value
STATUS: Final = PrototypeElementKind.STATUS.value

MAIN_ZONE: Final = "main"
COLUMN_ZONE: Final = "column"
SEARCH_ZONE: Final = "search"

ZONE_RULES: Final = MappingProxyType(
    {
        LayoutArchetype.GUIDED_STEPS: (),
        LayoutArchetype.SINGLE_CARD: (),
        LayoutArchetype.FOCUS_MODE: (),
        LayoutArchetype.LIST_DETAIL: (("aside", frozenset({LIST, CARD})),),
        LayoutArchetype.DASHBOARD: (("tiles", frozenset({STATUS, CARD})),),
        LayoutArchetype.SPLIT_SCREEN: (
            (MAIN_ZONE, frozenset({HEADING, TEXT_INPUT, SELECT, BUTTON, LINK})),
            ("aside", frozenset({TEXT, CARD, STATUS, LIST})),
        ),
        LayoutArchetype.CONVERSATIONAL: (
            (MAIN_ZONE, frozenset({HEADING})),
            ("thread", frozenset({TEXT, STATUS, CARD, LIST})),
            ("composer", frozenset({TEXT_INPUT, SELECT, BUTTON, LINK})),
        ),
        LayoutArchetype.TABLE_FIRST: (
            ("intro", frozenset({HEADING, TEXT})),
            ("table", frozenset({LIST})),
        ),
        LayoutArchetype.CARD_GALLERY: (
            ("intro", frozenset({HEADING, TEXT})),
            ("gallery", frozenset({CARD})),
        ),
        LayoutArchetype.FEED_TIMELINE: (
            ("intro", frozenset({HEADING})),
            ("composer", frozenset({TEXT_INPUT, SELECT, BUTTON})),
            ("timeline", frozenset({CARD, TEXT})),
        ),
        LayoutArchetype.KANBAN_BOARD: (),
        LayoutArchetype.SEARCH_FIRST: (("intro", frozenset({HEADING, TEXT})),),
    }
)


def _kind(element: Mapping[str, object]) -> str:
    return str(element["kind"])


def _kanban_zones(elements: Sequence[Mapping[str, object]]) -> list[tuple[str, tuple]]:
    zones: list[tuple[str, list]] = []
    main: list = []
    column: list | None = None
    for element in elements:
        kind = _kind(element)
        if kind == HEADING:
            column = [element]
            zones.append((COLUMN_ZONE, column))
        elif kind in {CARD, LIST, TEXT} and column is not None:
            column.append(element)
        else:
            main.append(element)
    if main:
        zones.append((MAIN_ZONE, main))
    return [(name, tuple(items)) for name, items in zones]


def _search_zones(elements: Sequence[Mapping[str, object]]) -> list[tuple[str, tuple]]:
    intro: list = []
    search: list = []
    main: list = []
    seen_input = False
    seen_button = False
    for element in elements:
        kind = _kind(element)
        if kind in {HEADING, TEXT} and not search:
            intro.append(element)
        elif kind == TEXT_INPUT and not seen_input:
            search.append(element)
            seen_input = True
        elif kind == BUTTON and seen_input and not seen_button:
            search.append(element)
            seen_button = True
        else:
            main.append(element)
    zones = []
    if intro:
        zones.append(("intro", tuple(intro)))
    if search:
        zones.append((SEARCH_ZONE, tuple(search)))
    if main:
        zones.append((MAIN_ZONE, tuple(main)))
    return zones


def layout_zones(
    archetype: LayoutArchetype,
    elements: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, tuple[Mapping[str, object], ...]], ...]:
    if archetype is LayoutArchetype.KANBAN_BOARD:
        return tuple(_kanban_zones(elements))
    if archetype is LayoutArchetype.SEARCH_FIRST:
        return tuple(_search_zones(elements))
    rules = ZONE_RULES[archetype]
    buckets: dict[str, list] = {name: [] for name, _ in rules}
    buckets.setdefault(MAIN_ZONE, [])
    for element in elements:
        kind = _kind(element)
        target = next((name for name, kinds in rules if kind in kinds), MAIN_ZONE)
        buckets[target].append(element)
    ordered = [name for name, _ in rules]
    if MAIN_ZONE not in ordered:
        ordered.append(MAIN_ZONE)
    return tuple((name, tuple(buckets[name])) for name in ordered if buckets[name])


__all__ = [
    "COLUMN_ZONE",
    "MAIN_ZONE",
    "SEARCH_ZONE",
    "ZONE_RULES",
    "layout_zones",
]
