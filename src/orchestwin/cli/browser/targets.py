from __future__ import annotations

import unicodedata
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

from orchestwin.cli.browser.page import TEST_ROLES, Element, PageSnapshot

INTERACTIVE_ROLES: Final = (
    "button",
    "link",
    "textbox",
    "checkbox",
    "radio",
    "combobox",
    "option",
    "slider",
    "spinbutton",
    "switch",
    "tab",
)
CLICKABLE_AREAS: Final = ("text", "image", "listitem", "cell", "heading")
TYPE_ROLES: Final = ("textbox", "spinbutton", "combobox", "slider")
SELECT_ROLES: Final = ("combobox",)
ACTION_ROLES: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "CLICK": frozenset((*INTERACTIVE_ROLES, *CLICKABLE_AREAS)),
        "TYPE": frozenset(TYPE_ROLES),
        "SELECT": frozenset(SELECT_ROLES),
    }
)
MIN_CONTAINED_NAME_LENGTH: Final = 3


def normalized(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(stripped.lower().split())


def matches_text(page_text: str, wanted: str) -> bool:
    return normalized(wanted) in normalized(page_text)


def resolve_target(
    snapshot: PageSnapshot, target: Mapping[str, object], *, action: str | None = None
) -> Element | None:
    role = target.get("role")
    name = target.get("name")
    if not isinstance(name, str) or (role is not None and role not in TEST_ROLES):
        return None
    wanted = normalized(name)
    if not wanted:
        return None
    allowed = ACTION_ROLES.get(action) if action is not None else None
    candidates = [
        (element, normalized(element.name))
        for element in snapshot.elements
        if (role is None or element.role == role) and (allowed is None or element.role in allowed)
    ]
    rules: tuple[Callable[[str], bool], ...] = (
        lambda found: found == wanted,
        lambda found: found.startswith(wanted),
        lambda found: wanted in found,
        lambda found: len(found) >= MIN_CONTAINED_NAME_LENGTH and found in wanted,
    )
    for rule in rules:
        for element, found in candidates:
            if found and rule(found):
                return element
    return None
