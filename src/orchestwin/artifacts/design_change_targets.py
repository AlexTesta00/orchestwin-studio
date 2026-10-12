from __future__ import annotations

from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final

from orchestwin.artifacts.generated_mockup_document import code_attributes
from orchestwin.artifacts.generated_mockup_structure import (
    DerivedElement,
    bounded,
    derive_elements,
    locate,
)
from orchestwin.artifacts.generated_mockup_zones import (
    MAX_ZONE_LABEL_LENGTH,
    DerivedZone,
    derive_zones,
)
from orchestwin.artifacts.generated_mockups import (
    GeneratedMockup,
    MarkupNode,
    screen_trees,
    serialize_markup,
)

DESIGN_CHANGE_TARGET_INVALID: Final = "DESIGN_CHANGE_TARGET_INVALID"
ELEMENT_PART_KIND: Final = "element"
MAX_PART_LABEL_LENGTH: Final = MAX_ZONE_LABEL_LENGTH
MAX_PART_HTML_LENGTH: Final = 2048
MAX_ZONE_HTML_LENGTH: Final = 6000

_Part = DerivedElement | DerivedZone


class DesignChangeTargetError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Screen:
    code: str
    nodes: tuple[MarkupNode, ...]
    parts: Mapping[str, _Part]
    attributes: Mapping[tuple[int, ...], tuple[tuple[str, str], ...]]

    def markup(self, path: tuple[int, ...], limit: int) -> str:
        node = locate(self.nodes, path)
        marks = {
            (0, *key[len(path) :]): value
            for key, value in self.attributes.items()
            if key[: len(path)] == path
        }

        def written(count: int) -> str:
            shortened = replace(node, children=node.children[:count])
            return serialize_markup((shortened,), attributes=marks)

        counts = range(len(node.children) + 1)
        fitting = bisect_right(counts, limit, key=lambda count: len(written(count)))
        return written(max(fitting - 1, 0))


def _parts(target: Mapping[str, object]) -> tuple[Mapping[str, object], ...]:
    parts = target.get("elements")
    return tuple(parts) if isinstance(parts, list | tuple) else ()


def target_codes(target: Mapping[str, object]) -> tuple[str, ...]:
    parts = _parts(target)
    if parts:
        return tuple(str(part["element_code"]) for part in parts)
    code = target.get("element_code")
    return () if code is None else (str(code),)


def _screen(target: Mapping[str, object], mockup: GeneratedMockup) -> _Screen:
    code = target.get("screen_code")
    trees = screen_trees(mockup)
    if not isinstance(code, str) or code not in trees:
        raise DesignChangeTargetError(DESIGN_CHANGE_TARGET_INVALID)
    elements = [item for item in derive_elements(mockup) if item.screen_code == code]
    zones = [item for item in derive_zones(mockup) if item.screen_code == code]
    parts = {item.code: item for item in (*elements, *zones)}
    return _Screen(code, trees[code], parts, code_attributes(elements, zones, code))


def _chosen(target: Mapping[str, object], screen: _Screen) -> tuple[_Part, ...]:
    codes = target_codes(target)
    if len(set(codes)) != len(codes) or any(code not in screen.parts for code in codes):
        raise DesignChangeTargetError(DESIGN_CHANGE_TARGET_INVALID)
    return tuple(screen.parts[code] for code in codes)


def validate_target(target: Mapping[str, object], mockup: GeneratedMockup) -> None:
    _chosen(target, _screen(target, mockup))


def _element_texts(
    values: Mapping[str, object], element: DerivedElement, screen: _Screen
) -> dict[str, object]:
    return {
        "label": values.get("label") or bounded(element.content, MAX_PART_LABEL_LENGTH),
        "html": values.get("html") or screen.markup(element.path, MAX_PART_HTML_LENGTH),
    }


def _zone_view(zone: DerivedZone, screen: _Screen) -> dict[str, object]:
    return {
        "element_code": zone.code,
        "kind": zone.kind,
        "label": zone.label,
        "html": screen.markup(zone.path, MAX_ZONE_HTML_LENGTH),
        "holds": list(zone.element_codes),
    }


def _part_view(values: Mapping[str, object], part: _Part, screen: _Screen) -> dict[str, object]:
    if isinstance(part, DerivedZone):
        return _zone_view(part, screen)
    return {
        "element_code": part.code,
        "kind": ELEMENT_PART_KIND,
        **_element_texts(values, part, screen),
    }


def describe_target(target: Mapping[str, object], mockup: GeneratedMockup) -> dict[str, object]:
    screen = _screen(target, mockup)
    chosen = _chosen(target, screen)
    parts = _parts(target)
    if parts:
        ordered = sorted(zip(parts, chosen, strict=True), key=lambda pair: pair[1].path)
        views = [_part_view(values, part, screen) for values, part in ordered]
        return {"screen_code": screen.code, "elements": views}
    if not chosen:
        return dict(target)
    [part] = chosen
    if isinstance(part, DerivedZone):
        return {"screen_code": screen.code, **_zone_view(part, screen)}
    return {
        "screen_code": screen.code,
        "element_code": part.code,
        **_element_texts(target, part, screen),
    }


__all__ = [
    "DESIGN_CHANGE_TARGET_INVALID",
    "ELEMENT_PART_KIND",
    "MAX_PART_HTML_LENGTH",
    "MAX_PART_LABEL_LENGTH",
    "MAX_ZONE_HTML_LENGTH",
    "DesignChangeTargetError",
    "describe_target",
    "target_codes",
    "validate_target",
]
