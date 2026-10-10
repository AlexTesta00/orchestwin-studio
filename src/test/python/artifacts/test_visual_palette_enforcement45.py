from __future__ import annotations

import itertools
import math
import random

import pytest

from orchestwin.artifacts.visual_catalog import (
    DARK_BACKGROUND_LUMINANCE,
    MODES,
    PALETTE_ROLES,
    PRIMARY_CHROMA_SEPARATION,
    PRIMARY_HUE_SEPARATION_DEGREES,
    ColorMode,
    ColorScheme,
    HueFamily,
    Saturation,
    SurfaceTone,
    enforce_palette_contrast,
    palette_contrast_pairs,
    primaries_are_distinct,
    require_distinct_primaries,
    resolve_palette,
)
from orchestwin.artifacts.visual_color import (
    contrast_ratio,
    hex_to_oklab,
    hue_difference,
    is_hex_colour,
    oklch_to_hex,
    relative_luminance,
)

PALETTE_SPACE = tuple(itertools.product(HueFamily, ColorScheme, ColorMode, Saturation, SurfaceTone))
RANDOM_PALETTES = 60
SEED = 45
HUE_TOLERANCE = 1.0
CHROMATIC = 0.1


def oklch(colour: str) -> tuple[float, float, float]:
    lightness, a, b = hex_to_oklab(colour)
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def light_palette(**changes: str) -> dict[str, str]:
    palette = resolve_palette(
        HueFamily.FOREST,
        ColorScheme.COMPLEMENTARY,
        ColorMode.LIGHT,
        Saturation.BALANCED,
        SurfaceTone.WARM,
    )
    return {**palette, **changes}


def unmet_pairs(palette: dict[str, str], mode: ColorMode) -> list[str]:
    return [
        f"{first} on {second}"
        for first, second, threshold in palette_contrast_pairs(mode)
        if contrast_ratio(palette[first], palette[second]) < threshold
    ]


def random_palette(generator: random.Random, mode: ColorMode) -> dict[str, str]:
    dark = MODES[mode].dark
    hue = generator.uniform(0, 360)

    def ground(low: float, high: float) -> str:
        return oklch_to_hex(generator.uniform(low, high), generator.uniform(0, 0.03), hue)

    palette = {
        role: oklch_to_hex(
            generator.uniform(0.05, 0.98), generator.uniform(0, 0.25), generator.uniform(0, 360)
        )
        for role in PALETTE_ROLES
    }
    if dark:
        palette.update(
            background=ground(0.08, 0.25), surface=ground(0.1, 0.3), surface_alt=ground(0.12, 0.32)
        )
    else:
        palette.update(
            background=ground(0.93, 1.0), surface=ground(0.92, 1.0), surface_alt=ground(0.9, 0.99)
        )
    return palette


def test_the_pairs_are_the_ones_that_the_instruction_promises_with_the_thresholds_of_the_mode():
    for mode in ColorMode:
        spec = MODES[mode]
        text, ui = spec.text_threshold, spec.ui_threshold
        assert palette_contrast_pairs(mode) == (
            ("text", "background", text),
            ("text", "surface", text),
            ("text", "surface_alt", text),
            ("text_muted", "background", text),
            ("text_muted", "surface", text),
            ("text_muted", "surface_alt", text),
            ("primary", "background", ui),
            ("primary", "surface", ui),
            ("on_primary", "primary", text),
            ("accent", "background", ui),
            ("accent", "surface", ui),
            ("on_accent", "accent", text),
            ("text", "primary_soft", text),
            ("success", "background", text),
            ("success", "surface", text),
            ("danger", "background", text),
            ("danger", "surface", text),
            ("success", "success_soft", text),
            ("danger", "danger_soft", text),
        )
    assert DARK_BACKGROUND_LUMINANCE == 0.18


def test_every_palette_of_the_catalog_passes_unchanged():
    for combination in PALETTE_SPACE:
        palette = resolve_palette(*combination)
        final, changed = enforce_palette_contrast(palette, combination[2])
        assert (final, changed) == (palette, ()), combination
        assert tuple(final) == PALETTE_ROLES


def test_a_colour_that_fails_keeps_its_hue_and_its_chroma_and_moves_only_its_lightness():
    primary = oklch_to_hex(0.82, 0.14, 140)
    muted = oklch_to_hex(0.74, 0.11, 300)
    palette = light_palette(primary=primary, text_muted=muted)

    final, changed = enforce_palette_contrast(palette, ColorMode.LIGHT)

    assert changed == ("text_muted", "primary")
    assert {role: final[role] for role in PALETTE_ROLES if role not in changed} == {
        role: palette[role] for role in PALETTE_ROLES if role not in changed
    }
    assert unmet_pairs(final, ColorMode.LIGHT) == []
    for role in changed:
        before, after = oklch(palette[role]), oklch(final[role])
        assert after[0] < before[0]
        assert abs(after[1] - before[1]) <= 0.01
        assert hue_difference(before[2], after[2]) <= HUE_TOLERANCE
    assert final["on_primary"] == palette["on_primary"] == "#ffffff"


def test_a_dark_label_stays_on_a_bright_primary_when_a_darker_primary_reaches_it():
    palette = resolve_palette(
        HueFamily.AMBER,
        ColorScheme.MONOCHROME,
        ColorMode.LIGHT,
        Saturation.VIVID,
        SurfaceTone.NEUTRAL,
    )
    bright = {**palette, "primary": oklch_to_hex(0.92, 0.16, 95)}
    assert relative_luminance(bright["on_primary"]) < DARK_BACKGROUND_LUMINANCE

    final, changed = enforce_palette_contrast(bright, ColorMode.LIGHT)

    assert changed == ("primary",)
    assert final["on_primary"] == bright["on_primary"]
    assert unmet_pairs(final, ColorMode.LIGHT) == []
    before, after = oklch(bright["primary"]), oklch(final["primary"])
    assert after[0] < before[0] and after[1] >= CHROMATIC
    assert hue_difference(before[2], after[2]) <= HUE_TOLERANCE


def test_the_label_becomes_white_in_a_light_mode_only_when_no_lightness_is_enough():
    palette = resolve_palette(
        HueFamily.COBALT,
        ColorScheme.MONOCHROME,
        ColorMode.HIGH_CONTRAST_LIGHT,
        Saturation.BALANCED,
        SurfaceTone.NEUTRAL,
    )
    written = {**palette, "primary": oklch_to_hex(0.5, 0.15, 255), "on_primary": "#222222"}

    final, changed = enforce_palette_contrast(written, ColorMode.HIGH_CONTRAST_LIGHT)

    assert changed == ("primary", "on_primary")
    assert final["on_primary"] == "#ffffff"
    assert unmet_pairs(final, ColorMode.HIGH_CONTRAST_LIGHT) == []
    before, after = oklch(written["primary"]), oklch(final["primary"])
    assert after[0] < before[0]
    assert hue_difference(before[2], after[2]) <= HUE_TOLERANCE


def test_the_label_becomes_ink_in_a_dark_mode_only_when_no_lightness_is_enough():
    palette = resolve_palette(
        HueFamily.VIOLET,
        ColorScheme.MONOCHROME,
        ColorMode.HIGH_CONTRAST_DARK,
        Saturation.BALANCED,
        SurfaceTone.NEUTRAL,
    )
    written = {**palette, "primary": oklch_to_hex(0.45, 0.15, 300), "on_primary": "#ffffff"}

    final, changed = enforce_palette_contrast(written, ColorMode.HIGH_CONTRAST_DARK)

    assert changed == ("primary", "on_primary")
    assert relative_luminance(final["on_primary"]) < DARK_BACKGROUND_LUMINANCE
    assert unmet_pairs(final, ColorMode.HIGH_CONTRAST_DARK) == []
    before, after = oklch(written["primary"]), oklch(final["primary"])
    assert after[0] > before[0]
    assert hue_difference(before[2], after[2]) <= HUE_TOLERANCE


def test_a_failing_label_is_replaced_by_the_one_that_moves_the_primary_least():
    blue = oklch_to_hex(0.5, 0.15, 260)
    written = light_palette(primary=blue, on_primary=blue)

    final, changed = enforce_palette_contrast(written, ColorMode.LIGHT)

    assert changed == ("on_primary",)
    assert (final["primary"], final["on_primary"]) == (blue, "#ffffff")
    assert unmet_pairs(final, ColorMode.LIGHT) == []


def test_a_light_label_stays_when_a_lighter_primary_reaches_both_grounds_and_label():
    palette = resolve_palette(
        HueFamily.OCEAN, ColorScheme.ANALOGOUS, ColorMode.DARK, Saturation.VIVID, SurfaceTone.COOL
    )
    written = {**palette, "primary": oklch_to_hex(0.42, 0.13, 220), "on_primary": "#ffffff"}

    final, changed = enforce_palette_contrast(written, ColorMode.DARK)

    assert changed == ("primary",)
    assert final["on_primary"] == "#ffffff"
    assert unmet_pairs(final, ColorMode.DARK) == []


@pytest.mark.parametrize("mode", list(ColorMode))
def test_random_palettes_of_every_mode_reach_every_pair_and_keep_their_hues(mode):
    generator = random.Random(f"{SEED}-{mode.value}")
    for _ in range(RANDOM_PALETTES):
        palette = random_palette(generator, mode)
        final, changed = enforce_palette_contrast(palette, mode)
        assert unmet_pairs(final, mode) == [], palette
        assert all(is_hex_colour(value) for value in final.values())
        assert changed == tuple(role for role in PALETTE_ROLES if final[role] != palette[role])
        for role in changed:
            if role in ("on_primary", "on_accent"):
                continue
            before, after = oklch(palette[role]), oklch(final[role])
            if min(before[1], after[1]) >= CHROMATIC:
                assert hue_difference(before[2], after[2]) <= HUE_TOLERANCE, (role, palette)


@pytest.mark.parametrize(
    ("mode", "background"),
    [
        (ColorMode.LIGHT, "#101418"),
        (ColorMode.HIGH_CONTRAST_LIGHT, "#2a2a2a"),
        (ColorMode.DARK, "#fafafa"),
        (ColorMode.HIGH_CONTRAST_DARK, "#9aa0a6"),
    ],
)
def test_a_palette_against_the_colour_mode_is_refused(mode, background):
    palette = {**light_palette(), "background": background}
    if MODES[mode].dark:
        assert relative_luminance(background) >= DARK_BACKGROUND_LUMINANCE
    else:
        assert relative_luminance(background) < DARK_BACKGROUND_LUMINANCE
    with pytest.raises(ValueError, match=r"^palette does not match the colour mode$"):
        enforce_palette_contrast(palette, mode)


def test_a_contrast_that_no_lightness_reaches_is_refused_with_the_pair():
    palette = light_palette(surface_alt="#3a3a3a")
    unreachable = r"^palette cannot reach the contrast of the colour mode: text on surface_alt$"

    with pytest.raises(ValueError, match=unreachable):
        enforce_palette_contrast(palette, ColorMode.LIGHT)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda palette: {k: v for k, v in palette.items() if k != "danger_soft"}, "every role"),
        (lambda palette: {**palette, "shadow": "#000000"}, "every role"),
        (lambda palette: {**palette, "primary": "#2F7D5B"}, "lowercase hex"),
        (lambda palette: {**palette, "primary": "#2f7d5"}, "lowercase hex"),
        (lambda palette: {**palette, "primary": "green"}, "lowercase hex"),
    ],
)
def test_a_palette_needs_every_role_once_in_lowercase_hex(change, message):
    with pytest.raises(ValueError, match=message):
        enforce_palette_contrast(change(light_palette()), ColorMode.LIGHT)


def test_the_primaries_must_differ_in_hue_or_in_chroma():
    base = oklch_to_hex(0.55, 0.12, 260)
    assert PRIMARY_HUE_SEPARATION_DEGREES == 30.0
    assert PRIMARY_CHROMA_SEPARATION == 0.06
    assert not primaries_are_distinct(base, base)
    assert primaries_are_distinct(base, oklch_to_hex(0.55, 0.12, 295))
    assert not primaries_are_distinct(base, oklch_to_hex(0.55, 0.12, 280))
    assert primaries_are_distinct(oklch_to_hex(0.55, 0.04, 260), base)
    assert not primaries_are_distinct(oklch_to_hex(0.55, 0.09, 260), base)
    assert not primaries_are_distinct(base, oklch_to_hex(0.35, 0.12, 260))
    require_distinct_primaries((base, oklch_to_hex(0.55, 0.12, 20)))
    with pytest.raises(ValueError, match="clearly different primary colours"):
        require_distinct_primaries((base, oklch_to_hex(0.55, 0.12, 20), base))
