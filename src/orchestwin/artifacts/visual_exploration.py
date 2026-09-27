from __future__ import annotations

import hashlib
import random
from collections.abc import Mapping, Sequence
from typing import Final
from uuid import UUID

from orchestwin.artifacts.visual_catalog import (
    FONTS,
    BackgroundTreatment,
    ColorMode,
    ColorScheme,
    CornerStyle,
    FontFamily,
    HeaderStyle,
    HueFamily,
    VisualChoices,
    hue_families_are_distinct,
)

VISUAL_EXPLORATION_VERSION: Final = 1
EXPLORED_ALTERNATIVES: Final = ("DES-001", "DES-002")
EXPLORED_DIMENSIONS: Final = (
    "hue_family",
    "heading_family",
    "body_family",
    "color_scheme",
    "background",
    "corners",
    "header",
)
HUE_GROUP_SIZE: Final = 5
HEADING_GROUP_SIZE: Final = 3
PAIR_GROUP_SIZE: Final = 2
NON_LIGHT_PROJECT_SHARE: Final = 3
NON_LIGHT_MODES: Final = (
    ColorMode.DARK,
    ColorMode.HIGH_CONTRAST_LIGHT,
    ColorMode.HIGH_CONTRAST_DARK,
)
_HUE_ATTEMPTS: Final = 64


def _generator(project_id: UUID) -> random.Random:
    seed = f"orchestwin-visual-exploration-v{VISUAL_EXPLORATION_VERSION}:{project_id}"
    return random.Random(hashlib.sha256(seed.encode("utf-8")).hexdigest())


def _split(generator: random.Random, values: Sequence, size: int) -> tuple[tuple, tuple]:
    shuffled = generator.sample(list(values), len(values))
    return tuple(shuffled[:size]), tuple(shuffled[size : 2 * size])


def _hue_groups(generator: random.Random) -> tuple[tuple[HueFamily, ...], tuple[HueFamily, ...]]:
    hues = list(HueFamily)
    for _ in range(_HUE_ATTEMPTS):
        shuffled = generator.sample(hues, len(hues))
        first = tuple(shuffled[:HUE_GROUP_SIZE])
        second = tuple(
            hue
            for hue in shuffled[HUE_GROUP_SIZE:]
            if all(hue_families_are_distinct(hue, other) for other in first)
        )[:HUE_GROUP_SIZE]
        if len(second) == HUE_GROUP_SIZE:
            return first, second
    raise RuntimeError("the hue catalog cannot be split into two distinct groups")


def visual_exploration(project_id: UUID) -> dict[str, dict[str, tuple[str, ...]]]:
    generator = _generator(project_id)
    readable = [family for family, spec in FONTS.items() if spec.body_safe]
    groups = {
        "hue_family": _hue_groups(generator),
        "heading_family": _split(generator, list(FontFamily), HEADING_GROUP_SIZE),
        "body_family": _split(generator, readable, PAIR_GROUP_SIZE),
        "color_scheme": _split(generator, list(ColorScheme), PAIR_GROUP_SIZE),
        "background": _split(generator, list(BackgroundTreatment), PAIR_GROUP_SIZE),
        "corners": _split(generator, list(CornerStyle), PAIR_GROUP_SIZE),
        "header": _split(generator, list(HeaderStyle), PAIR_GROUP_SIZE),
    }
    exploration = {
        code: {
            name: tuple(item.value for item in groups[name][index]) for name in EXPLORED_DIMENSIONS
        }
        for index, code in enumerate(EXPLORED_ALTERNATIVES)
    }
    if generator.randrange(NON_LIGHT_PROJECT_SHARE) == 0:
        exploration[EXPLORED_ALTERNATIVES[1]]["color_mode"] = tuple(
            item.value for item in NON_LIGHT_MODES
        )
    return exploration


def require_explored_choices(
    code: str,
    choices: VisualChoices,
    exploration: Mapping[str, Mapping[str, Sequence[str]]],
) -> None:
    for name, allowed in exploration.get(code, {}).items():
        value = getattr(choices, name).value
        if value not in allowed:
            raise ValueError(
                f"{code} must choose {name} inside the visual exploration of the project, "
                f"not {value}"
            )


def exploration_bindings(
    exploration: Mapping[str, Mapping[str, Sequence[str]]], code: str
) -> dict[str, object]:
    dimensions = exploration.get(code, {})
    if not dimensions:
        return {}
    return {
        "visual": {
            "properties": {name: {"enum": list(values)} for name, values in dimensions.items()}
        }
    }


__all__ = [
    "EXPLORED_ALTERNATIVES",
    "EXPLORED_DIMENSIONS",
    "HEADING_GROUP_SIZE",
    "HUE_GROUP_SIZE",
    "NON_LIGHT_MODES",
    "NON_LIGHT_PROJECT_SHARE",
    "PAIR_GROUP_SIZE",
    "VISUAL_EXPLORATION_VERSION",
    "exploration_bindings",
    "require_explored_choices",
    "visual_exploration",
]
