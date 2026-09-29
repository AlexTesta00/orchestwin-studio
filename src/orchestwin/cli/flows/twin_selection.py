from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from orchestwin.cli.console import Choice

if TYPE_CHECKING:
    from orchestwin.cli.context import CommandContext

OBSERVATION_PREFIX: Final = "user_twin."
TEXT_VALUE: Final = "TEXT"
ITEMS_VALUE: Final = "ITEMS"


@dataclass(frozen=True, slots=True)
class Twin:
    number: int
    twin_id: str
    version_id: str
    version_number: int | None
    name: str
    observations: tuple[Mapping[str, object], ...]

    def observation(self, field: str) -> Mapping[str, object] | None:
        key = f"{OBSERVATION_PREFIX}{field}"
        return next(
            (item for item in self.observations if item.get("observation_key") == key), None
        )

    def values(self, field: str) -> tuple[str, ...]:
        found = self.observation(field)
        return () if found is None else observation_values(found)

    @property
    def role(self) -> str | None:
        found = self.values("role")
        return found[0] if found else None

    @property
    def wants(self) -> str | None:
        found = self.values("goals")
        return found[0] if found else None


def observation_values(observation: Mapping[str, object]) -> tuple[str, ...]:
    value = observation.get("value")
    if not isinstance(value, Mapping):
        return ()
    kind = value.get("kind")
    if kind == TEXT_VALUE:
        text = value.get("text")
        return (text.strip(),) if isinstance(text, str) and text.strip() else ()
    items = value.get("items")
    if kind == ITEMS_VALUE and isinstance(items, list | tuple):
        return tuple(item.strip() for item in items if isinstance(item, str) and item.strip())
    return ()


def twins_from(versions: Sequence[Mapping[str, object]]) -> tuple[Twin, ...]:
    found: list[Twin] = []
    for version in versions:
        profile = version.get("profile")
        twin_id = version.get("twin_id")
        name = profile.get("name") if isinstance(profile, Mapping) else None
        if not isinstance(twin_id, str) or not twin_id or not isinstance(name, str):
            continue
        if not name.strip():
            continue
        observations = profile.get("observations")
        items = observations if isinstance(observations, list | tuple) else ()
        found.append(
            Twin(
                number=len(found) + 1,
                twin_id=twin_id,
                version_id=str(version.get("id") or ""),
                version_number=_integer(version.get("version_number")),
                name=" ".join(name.split()),
                observations=tuple(item for item in items if isinstance(item, Mapping)),
            )
        )
    return tuple(found)


def folded(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    plain = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(plain.split())


def matching(twins: Sequence[Twin], value: str) -> tuple[Twin, ...]:
    wanted = value.strip()
    if wanted.isdecimal():
        numbered = tuple(twin for twin in twins if twin.number == int(wanted))
        if numbered:
            return numbered
    key = folded(wanted)
    if not key:
        return ()
    exact = tuple(twin for twin in twins if folded(twin.name) == key)
    if exact:
        return exact
    return tuple(twin for twin in twins if folded(twin.name).startswith(key))


def select(context: CommandContext, twins: Sequence[Twin], value: str) -> Twin | None:
    found = matching(twins, value)
    if not found:
        return None
    if len(found) == 1:
        return found[0]
    options = [Choice(twin.twin_id, choice_label(twin)) for twin in found]
    chosen = context.console.choose("twins.which", options, value=value.strip())
    return next(twin for twin in found if twin.twin_id == chosen.key)


def choice_label(twin: Twin) -> str:
    role = twin.role
    if role is None or folded(role) == folded(twin.name):
        return twin.name
    return f"{twin.name} - {role}"


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
