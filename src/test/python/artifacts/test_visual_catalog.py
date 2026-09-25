from __future__ import annotations

import itertools
from dataclasses import replace

import pytest

from orchestwin.artifacts.prototypes import PrototypeElementKind, PrototypeScreenState
from orchestwin.artifacts.visual_catalog import (
    ARCHETYPES,
    DISTINCT_VISUAL_DIMENSIONS,
    FONTS,
    HUES,
    MODES,
    PALETTE_ROLES,
    VISUAL_CATALOG_CONTENT_HASH,
    VISUAL_CATALOG_VERSION,
    VISUAL_DIMENSION_NAMES,
    VISUAL_DIMENSIONS,
    BackgroundTreatment,
    BorderWeight,
    ButtonStyle,
    ColorMode,
    ColorScheme,
    CornerStyle,
    Density,
    DesignTone,
    Elevation,
    Emphasis,
    FontFamily,
    HeaderStyle,
    HeadingCase,
    HeadingWeight,
    HueFamily,
    InputStyle,
    LayoutArchetype,
    NavigationPattern,
    Saturation,
    SurfaceTone,
    TypeScale,
    VisualChoices,
    hue_families_are_distinct,
    require_distinct_visual_choices,
    resolve_palette,
    resolve_typography,
    resolve_visual_tokens,
    visual_catalog_content_hash,
    visual_catalog_snapshot,
    visual_catalog_summary,
    visual_differences,
)
from orchestwin.artifacts.visual_color import colour_distance, contrast_ratio, is_hex_colour

PALETTE_SPACE = tuple(itertools.product(HueFamily, ColorScheme, ColorMode, Saturation, SurfaceTone))


def choices(**overrides) -> VisualChoices:
    values = {
        "archetype": LayoutArchetype.DASHBOARD,
        "hue_family": HueFamily.COBALT,
        "color_scheme": ColorScheme.NEUTRAL_ACCENT,
        "color_mode": ColorMode.LIGHT,
        "saturation": Saturation.BALANCED,
        "surface_tone": SurfaceTone.TINTED,
        "heading_family": FontFamily.HUMANIST_SANS,
        "body_family": FontFamily.SYSTEM_UI,
        "type_scale": TypeScale.REGULAR,
        "heading_case": HeadingCase.SENTENCE,
        "heading_weight": HeadingWeight.SEMIBOLD,
        "corners": CornerStyle.SOFT,
        "density": Density.COMFORTABLE,
        "buttons": ButtonStyle.FILLED,
        "inputs": InputStyle.BOXED,
        "elevation": Elevation.SUBTLE,
        "borders": BorderWeight.HAIRLINE,
        "navigation": NavigationPattern.SIDE_RAIL,
        "header": HeaderStyle.COMPACT_BAR,
        "background": BackgroundTreatment.PLAIN,
        "emphasis": Emphasis.BALANCED,
        "tone": DesignTone.INSTITUTIONAL,
    }
    values.update(overrides)
    return VisualChoices(**values)


def second_choices() -> VisualChoices:
    return choices(
        archetype=LayoutArchetype.GUIDED_STEPS,
        hue_family=HueFamily.TERRACOTTA,
        color_scheme=ColorScheme.ANALOGOUS,
        color_mode=ColorMode.DARK,
        surface_tone=SurfaceTone.WARM,
        heading_family=FontFamily.OLD_STYLE_SERIF,
        corners=CornerStyle.ROUND,
        navigation=NavigationPattern.NONE,
        tone=DesignTone.WARM,
    )


def test_every_palette_in_the_catalog_meets_its_contrast_thresholds():
    assert len(PALETTE_SPACE) == 19 * 6 * 4 * 3 * 4
    for family, scheme, mode, saturation, tone in PALETTE_SPACE:
        palette = resolve_palette(family, scheme, mode, saturation, tone)
        spec = MODES[mode]
        text, ui = spec.text_threshold, spec.ui_threshold
        label = f"{family.value}/{scheme.value}/{mode.value}/{saturation.value}/{tone.value}"
        assert tuple(palette) == PALETTE_ROLES, label
        assert all(is_hex_colour(value) for value in palette.values()), label
        for surface in ("background", "surface", "surface_alt"):
            assert contrast_ratio(palette["text"], palette[surface]) >= text, label
            assert contrast_ratio(palette["text_muted"], palette[surface]) >= text, label
        assert contrast_ratio(palette["on_primary"], palette["primary"]) >= text, label
        assert contrast_ratio(palette["primary"], palette["background"]) >= ui, label
        assert contrast_ratio(palette["on_accent"], palette["accent"]) >= text, label
        assert contrast_ratio(palette["accent"], palette["background"]) >= ui, label
        assert contrast_ratio(palette["text"], palette["primary_soft"]) >= text, label
        for status in ("success", "danger"):
            assert contrast_ratio(palette[status], palette["surface"]) >= text, label
            assert contrast_ratio(palette[status], palette["background"]) >= text, label
            assert contrast_ratio(palette[status], palette[f"{status}_soft"]) >= text, label
        if spec.high_contrast:
            assert contrast_ratio(palette["border"], palette["background"]) >= ui, label


def test_palette_resolution_is_deterministic_and_mode_aware():
    first = resolve_palette(
        HueFamily.TEAL, ColorScheme.ANALOGOUS, ColorMode.DARK, Saturation.VIVID, SurfaceTone.COOL
    )
    second = resolve_palette(
        HueFamily.TEAL, ColorScheme.ANALOGOUS, ColorMode.DARK, Saturation.VIVID, SurfaceTone.COOL
    )
    assert first == second
    light = resolve_palette(
        HueFamily.TEAL, ColorScheme.ANALOGOUS, ColorMode.LIGHT, Saturation.VIVID, SurfaceTone.COOL
    )
    assert contrast_ratio(light["background"], "#000000") > contrast_ratio(
        first["background"], "#000000"
    )
    high = resolve_palette(
        HueFamily.TEAL,
        ColorScheme.ANALOGOUS,
        ColorMode.HIGH_CONTRAST_LIGHT,
        Saturation.VIVID,
        SurfaceTone.COOL,
    )
    assert contrast_ratio(high["text"], high["background"]) >= 7.0
    assert high["background"] == "#ffffff"
    complementary = resolve_palette(
        HueFamily.TEAL,
        ColorScheme.COMPLEMENTARY,
        ColorMode.LIGHT,
        Saturation.VIVID,
        SurfaceTone.COOL,
    )
    assert complementary["primary"] == light["primary"]
    assert complementary["accent"] != light["accent"]


def test_distinct_hue_families_produce_clearly_different_primaries():
    reference = {
        family: resolve_palette(
            family,
            ColorScheme.NEUTRAL_ACCENT,
            ColorMode.LIGHT,
            Saturation.BALANCED,
            SurfaceTone.NEUTRAL,
        )["primary"]
        for family in HueFamily
    }
    distinct_pairs = 0
    for first, second in itertools.combinations(HueFamily, 2):
        if hue_families_are_distinct(first, second):
            distinct_pairs += 1
            assert colour_distance(reference[first], reference[second]) >= 0.03, (first, second)
    assert distinct_pairs >= 120
    assert not hue_families_are_distinct(HueFamily.CRIMSON, HueFamily.CORAL)
    assert not hue_families_are_distinct(HueFamily.COBALT, HueFamily.COBALT)
    assert hue_families_are_distinct(HueFamily.COBALT, HueFamily.SLATE)
    assert hue_families_are_distinct(HueFamily.AMBER, HueFamily.SAND)
    assert not hue_families_are_distinct(HueFamily.GRAPHITE, HueFamily.SAND)


def test_bright_families_keep_dark_ink_on_the_primary_in_light_modes():
    amber = resolve_palette(
        HueFamily.AMBER,
        ColorScheme.MONOCHROME,
        ColorMode.LIGHT,
        Saturation.VIVID,
        SurfaceTone.NEUTRAL,
    )
    cobalt = resolve_palette(
        HueFamily.COBALT,
        ColorScheme.MONOCHROME,
        ColorMode.LIGHT,
        Saturation.VIVID,
        SurfaceTone.NEUTRAL,
    )
    assert amber["on_primary"] != "#ffffff"
    assert cobalt["on_primary"] == "#ffffff"
    amber_high = resolve_palette(
        HueFamily.AMBER,
        ColorScheme.MONOCHROME,
        ColorMode.HIGH_CONTRAST_LIGHT,
        Saturation.VIVID,
        SurfaceTone.NEUTRAL,
    )
    assert amber_high["on_primary"] == "#ffffff"


def test_visual_choices_normalize_strings_and_round_trip_through_snapshots():
    value = choices()
    snapshot = value.to_snapshot()
    assert tuple(snapshot) == VISUAL_DIMENSION_NAMES
    assert snapshot["archetype"] == "DASHBOARD"
    assert VisualChoices.from_snapshot(snapshot) == value
    assert VisualChoices(**snapshot) == value
    with pytest.raises(ValueError, match="require color_mode"):
        VisualChoices.from_snapshot(
            {key: item for key, item in snapshot.items() if key != "color_mode"}
        )
    with pytest.raises(ValueError, match="unknown visual choice for tone"):
        VisualChoices.from_snapshot({**snapshot, "tone": "SPARKLY"})
    with pytest.raises(ValueError, match="unknown visual choice dimensions"):
        VisualChoices.from_snapshot({**snapshot, "mood": "CALM"})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        (
            {"navigation": NavigationPattern.SIDE_RAIL, "archetype": LayoutArchetype.FOCUS_MODE},
            "navigation",
        ),
        ({"body_family": FontFamily.SCRIPT}, "not readable as a body family"),
        ({"body_family": FontFamily.DISPLAY_HEAVY}, "not readable as a body family"),
        ({"body_family": FontFamily.MONOSPACE}, "not readable as a body family"),
        ({"heading_family": FontFamily.SCRIPT}, "script headings require"),
        (
            {
                "heading_family": FontFamily.SCRIPT,
                "tone": DesignTone.PLAYFUL,
                "heading_case": HeadingCase.UPPERCASE,
            },
            "sentence case",
        ),
        ({"heading_family": FontFamily.DISPLAY_HEAVY}, "heavy display headings require"),
        (
            {"color_mode": ColorMode.HIGH_CONTRAST_LIGHT, "buttons": ButtonStyle.GHOST},
            "filled or outlined buttons",
        ),
        (
            {"color_mode": ColorMode.HIGH_CONTRAST_DARK, "borders": BorderWeight.NONE},
            "visible borders",
        ),
        (
            {
                "color_mode": ColorMode.HIGH_CONTRAST_DARK,
                "heading_family": FontFamily.SCRIPT,
                "tone": DesignTone.PLAYFUL,
            },
            "exclude script",
        ),
    ],
)
def test_incoherent_visual_choices_are_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        choices(**overrides)


def test_coherent_special_cases_are_accepted():
    assert choices(body_family=FontFamily.MONOSPACE, tone=DesignTone.TECHNICAL)
    assert choices(heading_family=FontFamily.SCRIPT, tone=DesignTone.ARTISANAL)
    assert choices(heading_family=FontFamily.DISPLAY_HEAVY, tone=DesignTone.ENERGETIC)
    assert choices(
        color_mode=ColorMode.HIGH_CONTRAST_LIGHT,
        buttons=ButtonStyle.OUTLINED,
        borders=BorderWeight.BOLD,
    )


def test_alternatives_must_be_clearly_distinct():
    first = choices()
    second = second_choices()
    require_distinct_visual_choices((first, second))
    assert "archetype" in visual_differences(first, second)
    with pytest.raises(ValueError, match="different layout archetypes"):
        require_distinct_visual_choices(
            (
                first,
                replace(second, archetype=first.archetype, navigation=NavigationPattern.SIDE_RAIL),
            )
        )
    with pytest.raises(ValueError, match="clearly different hue families"):
        require_distinct_visual_choices((first, replace(second, hue_family=HueFamily.INDIGO)))
    barely = choices(
        archetype=LayoutArchetype.LIST_DETAIL,
        hue_family=HueFamily.EMERALD,
        corners=CornerStyle.ROUND,
        density=Density.SPACIOUS,
    )
    with pytest.raises(ValueError, match=f"at least {DISTINCT_VISUAL_DIMENSIONS} further"):
        require_distinct_visual_choices((first, barely))
    require_distinct_visual_choices((first, replace(barely, tone=DesignTone.CALM)))
    require_distinct_visual_choices((first, second, replace(barely, tone=DesignTone.CALM)))


def test_tokens_cover_palette_typography_and_shape():
    tokens = resolve_visual_tokens(choices())
    assert all(isinstance(value, str) and value for value in tokens.values())
    for role in PALETTE_ROLES:
        assert is_hex_colour(tokens[f"--vl-color-{role.replace('_', '-')}"])
    typography = resolve_typography(choices())
    assert (
        tokens["--vl-font-heading"]
        == typography["heading_stack"]
        == FONTS[FontFamily.HUMANIST_SANS].stack
    )
    assert tokens["--vl-font-body"] == FONTS[FontFamily.SYSTEM_UI].stack
    assert tokens["--vl-heading-weight"] == "700"
    assert tokens["--vl-size-body"] == "16px"
    assert tokens["--vl-radius-control"] == "8px"
    assert tokens["--vl-control-height"] == "44px"
    assert tokens["--vl-border-width"] == "1px"
    assert tokens["--vl-shadow"].startswith("0 1px 2px")
    dark = resolve_visual_tokens(second_choices())
    assert dark["--vl-shadow"] != tokens["--vl-shadow"]
    assert dark["--vl-radius-control"] == "14px"
    uppercase = resolve_visual_tokens(choices(heading_case=HeadingCase.SMALL_CAPS))
    assert uppercase["--vl-heading-variant"] == "small-caps"


def test_archetype_specs_are_complete_and_coherent():
    assert set(ARCHETYPES) == set(LayoutArchetype)
    for archetype, spec in ARCHETYPES.items():
        assert 2 <= spec.minimum_screens <= spec.maximum_screens <= 4, archetype
        assert spec.navigation and len(set(spec.navigation)) == len(spec.navigation), archetype
        assert "SCR-001" in spec.recipe and PrototypeScreenState.SUCCESS.value in spec.recipe
        assert any(kind.value in spec.recipe for kind in PrototypeElementKind), archetype
        assert spec.minimum_workflow_steps >= 1 and spec.minimum_information_areas >= 1
    assert set(HUES) == set(HueFamily)
    assert set(MODES) == set(ColorMode)
    assert set(FONTS) == set(FontFamily)
    assert all(spec.stack.strip() for spec in FONTS.values())


def test_summary_and_snapshot_expose_every_dimension():
    summary = visual_catalog_summary()
    assert len(summary) < 3400
    for name in VISUAL_DIMENSIONS:
        assert name in summary
    for item in (*LayoutArchetype, *FontFamily):
        assert item.value in summary, item
    assert "a workflow of at least 3 steps" in summary
    assert "at least 2 information areas" in summary
    snapshot = visual_catalog_snapshot()
    assert snapshot["version"] == VISUAL_CATALOG_VERSION
    assert set(snapshot["dimensions"]) == set(VISUAL_DIMENSIONS)
    assert visual_catalog_content_hash() == VISUAL_CATALOG_CONTENT_HASH
    assert len(VISUAL_CATALOG_CONTENT_HASH) == 64
