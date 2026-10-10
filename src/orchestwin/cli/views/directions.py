from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

from orchestwin.cli.messages import known

AXES: Final = ("layout", "shape", "type", "colour", "density")
SYSTEM_KEYS: Final = MappingProxyType({"apple-hig": "design.system_apple_hig"})


def axes_of(direction: Mapping[str, object]) -> Mapping[str, object]:
    axes = direction.get("axes")
    return axes if isinstance(axes, Mapping) else {}


def axis_label(text: Callable[..., str], axis: str) -> str:
    return text(f"design.axis_{axis}")


def value_label(text: Callable[..., str], axis: str, value: object) -> str:
    if not isinstance(value, str) or not value:
        return "-"
    key = f"design.direction_{axis}_{value}"
    if known(key):
        return text(key)
    return value.replace("_", " ").lower()


def value_labels(text: Callable[..., str], axes: Mapping[str, object]) -> list[str]:
    return [value_label(text, axis, axes.get(axis)) for axis in AXES]


def system_name(text: Callable[..., str], identifier: object) -> str | None:
    key = SYSTEM_KEYS.get(identifier) if isinstance(identifier, str) else None
    return None if key is None else text(key)
