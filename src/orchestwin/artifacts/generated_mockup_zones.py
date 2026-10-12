from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from orchestwin.artifacts.generated_mockup_structure import (
    DerivedElement,
    ElementPosition,
    ScreenIndex,
    bounded,
    derive_elements,
    first_role,
    node_text,
    normalize,
    walk_elements,
)
from orchestwin.artifacts.generated_mockups import GeneratedMockup, MarkupElement, screen_trees

ZONE_CODE_PREFIX: Final = "ZON"
ZONE_CODE_PATTERN: Final = r"^ZON-[0-9]{3,6}$"
ZONE_ATTRIBUTE: Final = "data-ot-zone"
MIN_ZONE_ELEMENTS: Final = 2
MAX_ZONE_LABEL_LENGTH: Final = 120
_CARDS_KIND: Final = "cards"
_TAG_KINDS: Final = MappingProxyType(
    {
        "nav": "navigation",
        "header": "header",
        "main": "main",
        "footer": "footer",
        "aside": "aside",
        "section": "section",
        "form": "form",
        "ul": "list",
        "ol": "list",
        "dl": "list",
        "table": "table",
        "details": "details",
        "figure": "figure",
        "fieldset": "group",
    }
)
_ROLE_KINDS: Final = MappingProxyType(
    {
        "navigation": "navigation",
        "banner": "header",
        "main": "main",
        "contentinfo": "footer",
        "complementary": "aside",
        "region": "section",
        "form": "form",
        "search": "form",
        "list": "list",
        "tablist": "group",
        "group": "group",
        "toolbar": "group",
        "radiogroup": "group",
    }
)
ZONE_KINDS: Final = (*dict.fromkeys((*_TAG_KINDS.values(), *_ROLE_KINDS.values())), _CARDS_KIND)
_CARD_TAGS: Final = frozenset({"article", "section", "figure"})
_MIN_CARDS: Final = 2
_SEALED: Final = frozenset({"article", "a", "button", "label", "select", "svg"})
_CAPTIONS: Final = frozenset({"legend", "caption", "summary", "figcaption"})
_HEADINGS: Final = frozenset({"h1", "h2", "h3", "h4"})


@dataclass(frozen=True, slots=True)
class DerivedZone:
    code: str
    screen_code: str
    path: tuple[int, ...]
    node_name: str
    kind: str
    label: str
    element_codes: tuple[str, ...]
    parent_code: str | None

    @property
    def position(self) -> ElementPosition:
        return ElementPosition(self.screen_code, self.path)


@dataclass(frozen=True, slots=True)
class _Draft:
    screen_code: str
    path: tuple[int, ...]
    node_name: str
    kind: str
    label: str
    element_codes: tuple[str, ...]
    parent_path: tuple[int, ...] | None


def _inside(path: tuple[int, ...], container: tuple[int, ...]) -> bool:
    return len(path) > len(container) and path[: len(container)] == container


def _kind(node: MarkupElement) -> str | None:
    if node.name != "div":
        return _TAG_KINDS.get(node.name)
    role = _ROLE_KINDS.get(first_role(node))
    if role is not None:
        return role
    cards = sum(child.name in _CARD_TAGS for child in node.elements)
    return _CARDS_KIND if cards >= _MIN_CARDS else None


def _label_texts(screen: ScreenIndex, node: MarkupElement) -> Iterator[str]:
    yield screen.referenced_text(node.attribute("aria-labelledby"))
    yield normalize(node.attribute("aria-label") or "")
    caption = next((child for child in node.elements if child.name in _CAPTIONS), None)
    if caption is not None:
        yield node_text(caption)
    heading = next(
        (item for item, _path, _chain in walk_elements(node.children) if item.name in _HEADINGS),
        None,
    )
    if heading is not None:
        yield node_text(heading)
    yield node_text(node)


def _label(screen: ScreenIndex, node: MarkupElement, kind: str) -> str:
    text = next((text for text in _label_texts(screen, node) if text), "")
    return bounded(text, MAX_ZONE_LABEL_LENGTH) or kind


def _screen_drafts(screen: ScreenIndex, held: Sequence[DerivedElement]) -> list[_Draft]:
    taken = {element.path for element in held}
    kept: list[_Draft] = []
    for node, path, ancestors in walk_elements(screen.nodes):
        kind = _kind(node)
        if (
            kind is None
            or path in taken
            or node.has("hidden")
            or any(item.name in _SEALED for item in ancestors)
        ):
            continue
        codes = tuple(element.code for element in held if _inside(element.path, path))
        parent = next((draft for draft in reversed(kept) if _inside(path, draft.path)), None)
        if not MIN_ZONE_ELEMENTS <= len(codes) < len(held) or (
            parent is not None and parent.element_codes == codes
        ):
            continue
        label = _label(screen, node, kind)
        parent_path = None if parent is None else parent.path
        kept.append(_Draft(screen.code, path, node.name, kind, label, codes, parent_path))
    return kept


def derive_zones(mockup: GeneratedMockup) -> tuple[DerivedZone, ...]:
    trees = screen_trees(mockup)
    elements = derive_elements(mockup)
    drafts = [
        draft
        for screen in mockup.screens
        for draft in _screen_drafts(
            ScreenIndex(screen.code, trees[screen.code]),
            [element for element in elements if element.screen_code == screen.code],
        )
    ]
    width = max(3, len(str(len(drafts))))
    codes = {
        (draft.screen_code, draft.path): f"{ZONE_CODE_PREFIX}-{number:0{width}d}"
        for number, draft in enumerate(drafts, start=1)
    }
    return tuple(
        DerivedZone(
            code=codes[(draft.screen_code, draft.path)],
            screen_code=draft.screen_code,
            path=draft.path,
            node_name=draft.node_name,
            kind=draft.kind,
            label=draft.label,
            element_codes=draft.element_codes,
            parent_code=None
            if draft.parent_path is None
            else codes[(draft.screen_code, draft.parent_path)],
        )
        for draft in drafts
    )


def zone_positions(mockup: GeneratedMockup) -> dict[str, ElementPosition]:
    return {zone.code: zone.position for zone in derive_zones(mockup)}


def zone_by_code(zones: Iterable[DerivedZone], code: str) -> DerivedZone | None:
    return next((zone for zone in zones if zone.code == code), None)


__all__ = [
    "MAX_ZONE_LABEL_LENGTH",
    "MIN_ZONE_ELEMENTS",
    "ZONE_ATTRIBUTE",
    "ZONE_CODE_PATTERN",
    "ZONE_CODE_PREFIX",
    "ZONE_KINDS",
    "DerivedZone",
    "derive_zones",
    "zone_by_code",
    "zone_positions",
]
