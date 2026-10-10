from __future__ import annotations

import itertools
import random

from orchestwin.artifacts.visual_catalog import (
    MODES,
    ColorMode,
    ColorScheme,
    HueFamily,
    Saturation,
    SurfaceTone,
    resolve_palette,
)
from orchestwin.artifacts.visual_color import contrast_ratio

Combination = tuple[HueFamily, ColorScheme, ColorMode, Saturation, SurfaceTone]

DIMENSIONS = (HueFamily, ColorScheme, ColorMode, Saturation, SurfaceTone)
TEXT_PAIRS = (
    ("text", "background"),
    ("text", "surface"),
    ("text", "surface_alt"),
    ("text_muted", "background"),
    ("text_muted", "surface"),
    ("text_muted", "surface_alt"),
    ("text", "primary_soft"),
    ("on_primary", "primary"),
    ("on_accent", "accent"),
    ("success", "background"),
    ("success", "surface"),
    ("success", "success_soft"),
    ("danger", "background"),
    ("danger", "surface"),
    ("danger", "danger_soft"),
)
CONTROL_PAIRS = (
    ("primary", "background"),
    ("primary", "surface"),
    ("accent", "background"),
    ("accent", "surface"),
)
FIXED_GRID: tuple[Combination, ...] = tuple(
    (hue, ColorScheme.COMPLEMENTARY, mode, saturation, SurfaceTone.NEUTRAL)
    for hue, mode, saturation in itertools.product(HueFamily, ColorMode, Saturation)
)
RANDOM_COMBINATIONS = 300
SEED = 45


def random_combinations() -> tuple[Combination, ...]:
    generator = random.Random(SEED)
    return tuple(
        (
            generator.choice(tuple(HueFamily)),
            generator.choice(tuple(ColorScheme)),
            generator.choice(tuple(ColorMode)),
            generator.choice(tuple(Saturation)),
            generator.choice(tuple(SurfaceTone)),
        )
        for _ in range(RANDOM_COMBINATIONS)
    )


def shortfalls(combination: Combination) -> list[str]:
    palette = resolve_palette(*combination)
    mode = MODES[combination[2]]
    found = []
    for pairs, threshold in (
        (TEXT_PAIRS, mode.text_threshold),
        (CONTROL_PAIRS, mode.ui_threshold),
    ):
        for foreground, ground in pairs:
            ratio = contrast_ratio(palette[foreground], palette[ground])
            if ratio < threshold:
                found.append(f"{foreground} on {ground}: {ratio:.3f} < {threshold}")
    return found


def failures(combinations: tuple[Combination, ...]) -> dict[str, list[str]]:
    return {
        "/".join(item.value for item in combination): found
        for combination in combinations
        if (found := shortfalls(combination))
    }


def test_the_thresholds_of_every_mode_reach_at_least_the_aa_level() -> None:
    assert set(MODES) == set(ColorMode)
    assert all(spec.text_threshold >= 4.5 for spec in MODES.values())
    assert all(spec.ui_threshold >= 3.0 for spec in MODES.values())


def test_every_hue_mode_and_saturation_keeps_the_pairs_that_the_instruction_promises() -> None:
    assert len(FIXED_GRID) == len(HueFamily) * len(ColorMode) * len(Saturation) == 228
    assert len(set(FIXED_GRID)) == len(FIXED_GRID)
    assert failures(FIXED_GRID) == {}


def test_random_complete_combinations_keep_the_pairs_that_the_instruction_promises() -> None:
    combinations = random_combinations()

    assert len(combinations) == RANDOM_COMBINATIONS
    assert random_combinations() == combinations
    for index, dimension in enumerate(DIMENSIONS):
        assert {combination[index] for combination in combinations} == set(dimension)
    assert failures(combinations) == {}
