from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import replace
from uuid import UUID

import pytest

from orchestwin.artifacts import design_distance as distance_module
from orchestwin.artifacts.design import DesignApproach
from orchestwin.artifacts.design_distance import (
    CHOICES_TOTAL,
    DESIGN_DISTANCE_VERSION,
    SEMANTIC_ELEMENTS,
    STRUCTURE_WEIGHTS,
    STYLE_WEIGHTS,
    STYLES_CLOSE,
    BorderClass,
    BoxingClass,
    ColumnsClass,
    NavigationPlacement,
    RadiusClass,
    ShadowClass,
    StructureDifference,
    StyleDifference,
    declared_distance,
    design_distance,
    design_distance_report,
    direction_adherence,
    structure_distance,
    structure_parts,
    structure_profile,
    structure_profile_from_markup,
    style_parts,
    style_profile,
    styles_distance,
)
from orchestwin.artifacts.generated_mockups import create_generated_mockup
from orchestwin.artifacts.visual_catalog import (
    NEUTRAL_VISUAL_CHOICES,
    VISUAL_DIMENSION_NAMES,
    visual_differences,
)
from orchestwin.artifacts.visual_color import colour_distance
from orchestwin.artifacts.visual_directions import DIRECTION_AXES, DIRECTION_AXIS_VALUES
from orchestwin.artifacts.visual_language import create_visual_language

from . import design_fixtures
from .test_visual_directions import axes, directed_language, direction

TOKENS = {
    "--vl-size-body": "16px",
    "--vl-space": "12px",
    "--vl-radius-panel": "12px",
    "--vl-border-width": "1px",
    "--vl-shadow": "none",
    "--vl-heading-transform": "uppercase",
    "--vl-font-body": "Georgia, serif",
    "--vl-color-primary": "#1d4ed8",
    "--vl-color-text": "#111827",
    "--vl-color-border": "#d1d5db",
}
PACKAGE = design_fixtures.design_package()
PLAIN = create_visual_language(
    choices=NEUTRAL_VISUAL_CHOICES,
    product_name="Reservation desk",
    rationale="A quiet neutral language keeps the guided reservation flow calm.",
)
FIRST_AXES = axes("EDITORIAL", "SQUARE_RULES", "DISPLAY", "INK", "SPACIOUS")
SECOND_AXES = axes("WORKBENCH", "PILL", "CAPS_LABELS", "TINTED", "SPACIOUS")
BASE_AXES = axes("PANELS", "ROUNDED_OUTLINE", "EVEN", "ACCENT_ONLY", "COMFORTABLE")
SCREENS = (
    '<header class="bar"><nav aria-label="Sezioni"><a href="#SCR-002">Prenotazioni</a></nav>'
    "</header><main><h1>Prenota una camera</h1><p>Scegli le date del soggiorno.</p></main>",
    '<main><h1>Prenotazione registrata</h1><p><a href="#SCR-001">Torna all\'inizio</a></p></main>',
)
OTHER_SCREENS = (
    '<div class="intro"><span>Prenota una camera</span><b>Scegli le date</b></div>',
    '<div class="done"><span><a href="#SCR-001">Torna all\'inizio</a></span></div>',
)


def rules(prefix: str, declaration: str, count: int) -> str:
    return "".join(f".{prefix}{index}{{{declaration}}}" for index in range(count))


THIN = rules("b", "border:1px solid var(--vl-color-border)", 3)
THICK = rules("b", "border:3px solid var(--vl-color-text)", 4)
BOXES = rules("x", "border:1px solid var(--vl-color-border)", 4)
RULES = rules("l", "border-bottom:1px solid var(--vl-color-border)", 4)
HARD = ".s{box-shadow:6px 6px 0 var(--vl-color-text)}"
SOFT = ".s{box-shadow:0 8px 24px var(--vl-color-border)}"
TWO_TINTS = rules("n", "background:var(--vl-color-primary-soft)", 2)
THREE_TINTS = rules("n", "background:var(--vl-color-primary-soft)", 3)
GRADIENT = ".g{background:linear-gradient(var(--vl-color-surface), var(--vl-color-background))}"


def fields(count: int) -> str:
    return rules("f", "background:var(--vl-color-primary)", count)


STRONG = (
    ".a{border-radius:0}"
    + THICK
    + HARD
    + "h1{font-size:72px}"
    + rules("u", "text-transform:uppercase", 3)
    + fields(5)
    + ".c{max-width:640px}.k{display:grid;grid-template-columns:2fr 1fr;gap:8px}"
    + ".m{font-family:monospace}"
)
GENTLE = (
    ".a{border-radius:999px}.s{box-shadow:0 12px 32px var(--vl-color-border)}"
    + "h1{font-size:24px}"
    + rules("n", "background:var(--vl-color-primary-soft)", 5)
    + GRADIENT
    + ".k{display:grid;grid-template-columns:repeat(3, 1fr);gap:32px}"
)


def directed(chosen, name: str = "Printed register", language=PLAIN):
    return directed_language(language, direction(name=name, axes=chosen))


def pair(first_language=PLAIN, second_language=None):
    first, second = PACKAGE.alternatives
    return (
        replace(first, visual_language=first_language),
        second if second_language is None else replace(second, visual_language=second_language),
    )


def version_of(*alternatives):
    return design_fixtures.design_version(package=replace(PACKAGE, alternatives=alternatives))


def mockup(alternative, styles: str = "", screens=SCREENS):
    return create_generated_mockup(
        design_alternative_id=alternative.id,
        title="Prenotazioni",
        styles=styles,
        screens=[
            {
                "code": f"SCR-{index:03d}",
                "title": f"Schermata {index}",
                "state": "DEFAULT" if index == 1 else "SUCCESS",
                "markup": markup,
            }
            for index, markup in enumerate(screens, start=1)
        ],
        token_names=alternative.visual_language.token_values,
    )


def test_declarations_count_inside_conditional_blocks_but_not_inside_keyframes() -> None:
    profile = style_profile(
        "@media (min-width: 900px){.a{font-size:40px}}"
        "@supports (display: grid){.b{font-size:24px}}"
        "@container (min-width: 400px){.c{text-transform:uppercase}}"
        "@layer base{.d{text-transform:uppercase}.e{text-transform:uppercase}}"
        "@keyframes pulse{from{font-size:200px}to{font-size:300px}}",
        TOKENS,
    )

    assert profile.type_ratio == 2.5
    assert profile.largest_font == 40
    assert profile.uppercase == 3
    assert profile.properties == Counter({"text-transform": 3, "font-size": 2})


def test_custom_properties_resolve_in_one_pass_and_the_first_declaration_wins() -> None:
    profile = style_profile(
        ".a{--m-gap:20px;--m-gap:40px;--m-pad:var(--m-gap);--m-late:var(--m-after)}"
        ".b{padding:var(--m-pad)}.c{gap:var(--m-gap)}.d{row-gap:var(--m-late)}"
        ".e{--m-after:99px}.f{column-gap:var(--vl-space)}",
        TOKENS,
    )

    assert profile.spacing == 20
    assert profile.properties == Counter({"padding": 1, "gap": 1, "row-gap": 1, "column-gap": 1})


def test_a_variable_fallback_is_used_only_when_the_name_is_unknown() -> None:
    profile = style_profile(
        ".a{padding:var(--m-missing, 18px)}.b{gap:var(--vl-missing, 2rem)}"
        ".c{row-gap:var(--vl-space, 99px)}.d{column-gap:var(--m-unknown)}"
        ".e{gap:var(--m-unknown) 500px}",
        TOKENS,
    )

    assert profile.spacing == 18


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("24px", 1.5),
        ("1.5rem", 1.5),
        ("2em", 2.0),
        ("clamp(20px, 4vw, 48px)", 3.0),
        ("min(100%, 40px)", 2.5),
        ("min(48px, 2rem)", 2.0),
        ("max(1rem, 3vw, 40px)", 2.5),
        ("max(20px, 3rem)", 3.0),
        ("calc(var(--vl-space) * 4)", 3.0),
        ("var(--m-unknown)", 1.0),
        ("0", 1.0),
        ("120%", 1.0),
        ("2vw", 1.0),
        ("larger", 1.0),
    ],
)
def test_font_sizes_are_read_as_lengths(value: str, expected: float) -> None:
    assert style_profile(f".a{{font-size:{value}}}", TOKENS).type_ratio == expected


def test_comments_strings_and_important_do_not_break_the_walk() -> None:
    profile = style_profile(
        '/* .x{font-size:900px} { */.a::before{content:"}{;"}'
        ".b{font-size:40px !important}.c{text-transform:UPPERCASE}",
        TOKENS,
    )

    assert profile.type_ratio == 2.5
    assert profile.uppercase == 1


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((), RadiusClass.SQUARE),
        (("3px",), RadiusClass.SQUARE),
        (("0",), RadiusClass.SQUARE),
        (("4px",), RadiusClass.ROUNDED),
        (("var(--vl-radius-panel)",), RadiusClass.ROUNDED),
        (("40px",), RadiusClass.ROUNDED),
        (("99px",), RadiusClass.ROUNDED),
        (("100px",), RadiusClass.PILL),
        (("50%",), RadiusClass.PILL),
        (("10% 30px",), RadiusClass.ROUNDED),
        (("min(999px, 20px)",), RadiusClass.ROUNDED),
        (("0", "12px", "12px", "20px"), RadiusClass.ROUNDED),
        (("2px", "2px", "12px"), RadiusClass.SQUARE),
        (("2px", "8px"), RadiusClass.ROUNDED),
        (("2px", "999px"), RadiusClass.PILL),
        (("12px", "999px"), RadiusClass.PILL),
    ],
)
def test_the_radius_is_the_most_frequent_class(values: tuple[str, ...], expected) -> None:
    sheet = "".join(f".r{index}{{border-radius:{value}}}" for index, value in enumerate(values))

    assert style_profile(sheet, TOKENS).radius is expected


@pytest.mark.parametrize(
    ("declarations", "expected"),
    [
        ((), BorderClass.NONE),
        (("border:1px solid #000", "border-top:1px solid #000"), BorderClass.NONE),
        (("border:1px solid #000",) * 3, BorderClass.THIN),
        (
            (
                "border:none",
                "border:0",
                "border-bottom:var(--vl-border-width) solid #000",
                "border-left-width:1px",
                "border-width:thin",
            ),
            BorderClass.THIN,
        ),
        (
            (
                "border:3px solid #000",
                "border-top:1px solid #000",
                "border-bottom:1px solid #000",
                "border-left:1px solid #000",
            ),
            BorderClass.THIN,
        ),
        (
            (
                "border:3px solid #000",
                "border-block-end:2.5px solid #000",
                "border-inline-start:thick solid #000",
                "border-bottom:1px solid #000",
                "border-left:1px solid #000",
                "border-right:1px solid #000",
                "border-top:1px solid #000",
                "border:1px solid #000",
                "border:1px solid #000",
                "border:1px solid #000",
            ),
            BorderClass.THICK,
        ),
        (("border:solid #000", "border:1px none", "border:1px solid #000"), BorderClass.NONE),
    ],
)
def test_the_border_counts_the_visible_widths(declarations: tuple[str, ...], expected) -> None:
    sheet = "".join(f".b{index}{{{value}}}" for index, value in enumerate(declarations))

    assert style_profile(sheet, TOKENS).border is expected


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((), ShadowClass.NONE),
        (("none", "var(--vl-shadow)"), ShadowClass.NONE),
        (("6px 6px 0 #000",), ShadowClass.HARD),
        (("4px 4px #000",), ShadowClass.HARD),
        (("inset 0 -2px 0 #000",), ShadowClass.HARD),
        (("0 1px 2px rgba(0, 0, 0, 0.1)",), ShadowClass.SOFT),
        (("0 0 0 3px #000",), ShadowClass.SOFT),
        (("6px 6px 0 #000, 0 8px 24px #000",), ShadowClass.HARD),
        (("6px 6px 0 #000", "0 4px 8px #000"), ShadowClass.HARD),
        (("6px 6px 0 #000", "0 4px 8px #000", "0 2px 4px #000"), ShadowClass.SOFT),
    ],
)
def test_the_shadow_compares_hard_and_soft_shadows(values: tuple[str, ...], expected) -> None:
    sheet = "".join(f".s{index}{{box-shadow:{value}}}" for index, value in enumerate(values))

    assert style_profile(sheet, TOKENS).shadow is expected


def test_the_type_ratio_divides_the_largest_size_by_the_body_token() -> None:
    sheet = ".a{font-size:45px}.b{font-size:var(--vl-size-body)}.c{font:700 30px/1.1 serif}"

    assert style_profile(sheet, {**TOKENS, "--vl-size-body": "18px"}).type_ratio == 2.5
    assert style_profile(sheet, {}).type_ratio == round(45 / 16, 2)
    assert style_profile(sheet, {}).body_size == 16
    assert style_profile(".a{font:inherit}.b{color:red}", TOKENS).type_ratio == 1.0
    assert style_profile(".a{font:800 72px/1 serif}", TOKENS).type_ratio == 4.5


def test_upper_case_is_counted_after_resolution() -> None:
    sheet = ".a{text-transform:var(--vl-heading-transform)}.b{text-transform:uppercase}"

    assert style_profile(sheet, TOKENS).uppercase == 2
    assert style_profile(sheet, {"--vl-heading-transform": "none"}).uppercase == 1


def test_colour_fields_and_tints_are_counted_by_rule() -> None:
    profile = style_profile(
        ".a{background:var(--vl-color-primary)}"
        ".b{background-color:var(--vl-color-accent)}"
        ".c{background:var(--vl-color-primary-soft)}"
        ".d{background:color-mix(in srgb, var(--vl-color-primary) 70%, var(--vl-color-surface))}"
        ".e{background:color-mix(in srgb, var(--vl-color-primary) 20%, var(--vl-color-surface))}"
        ".f{background:linear-gradient(var(--vl-color-primary), var(--vl-color-accent))}"
        ".g{background:var(--vl-color-primary);background-color:var(--vl-color-accent)}"
        ".h{color:var(--vl-color-primary)}"
        ".i{--m-brand:var(--vl-color-primary)}.j{background:var(--m-brand)}"
        ".k{background:color-mix(in srgb, var(--vl-color-surface) 30%, var(--vl-color-accent))}"
        ".l{background:color-mix(in srgb, var(--vl-color-primary), transparent)}"
        ".m{background:color-mix(in srgb, var(--vl-color-primary) 0%, transparent)}"
        ".n{background:var(--vl-color-surface-alt)}",
        TOKENS,
    )

    assert profile.colour_fields == 6
    assert profile.tints == 4
    assert profile.gradients == 1


def test_gradients_are_counted_by_declaration_after_resolution() -> None:
    profile = style_profile(
        ".a{--m-glow:radial-gradient(var(--vl-color-primary), transparent)}"
        ".b{background:var(--m-glow)}.c{background-image:linear-gradient(#fff, #000)}"
        ".d{border-image:repeating-linear-gradient(45deg, #000, #fff 4px) 1}",
        TOKENS,
    )

    assert profile.gradients == 3


def test_the_container_is_the_largest_width_in_its_range() -> None:
    sheet = (
        ".a{max-width:400px}.b{max-width:1200px}.c{max-width:min(100%, 1120px)}"
        ".d{max-width:2400px}.e{max-width:72ch}.f{max-width:var(--vl-content-width)}"
    )

    assert style_profile(sheet, TOKENS).container == 1200
    assert style_profile(sheet, {**TOKENS, "--vl-content-width": "1600px"}).container == 1600
    assert style_profile(".a{max-width:100%}.b{max-width:480px}", TOKENS).container == 480
    assert style_profile(".a{max-width:100%}", TOKENS).container is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1fr", ColumnsClass.ONE),
        ("minmax(0, 1fr)", ColumnsClass.ONE),
        ("1fr 1fr", ColumnsClass.TWO_EVEN),
        ("repeat(2, minmax(0, 1fr))", ColumnsClass.TWO_EVEN),
        ("minmax(0,1fr) minmax(0, 1fr)", ColumnsClass.TWO_EVEN),
        ("2fr 1fr", ColumnsClass.TWO_UNEVEN),
        ("1fr 320px", ColumnsClass.TWO_UNEVEN),
        ("[main] 1fr [side line] 280px [end]", ColumnsClass.TWO_UNEVEN),
        ("repeat(3, 1fr)", ColumnsClass.MANY),
        ("1fr 1fr 1fr", ColumnsClass.MANY),
        ("repeat(auto-fit, minmax(220px, 1fr))", ColumnsClass.MANY),
        ("repeat(auto-fill, 200px)", ColumnsClass.MANY),
        ("none", ColumnsClass.NONE),
        ("subgrid", ColumnsClass.NONE),
        ("var(--m-unknown)", ColumnsClass.NONE),
    ],
)
def test_column_tracks_are_classified(value: str, expected) -> None:
    profile = style_profile(f".a{{display:grid;grid-template-columns:{value}}}", TOKENS)

    assert profile.columns is expected
    assert profile.uneven_grids == (1 if expected is ColumnsClass.TWO_UNEVEN else 0)


def test_columns_ignore_narrow_media_queries_and_resolve_ties_in_order() -> None:
    uneven = style_profile(
        ".a{grid-template-columns:1fr 1fr}.b{grid-template-columns:2fr 1fr}"
        "@media (max-width: 720px){.a{grid-template-columns:1fr}"
        ".c{grid-template-columns:1fr 2fr}}",
        TOKENS,
    )
    many = style_profile(
        ".a{grid-template-columns:repeat(3, 1fr)}.b{grid-template-columns:1fr}"
        "@media (width < 600px){.c{grid-template-columns:3fr 1fr}}",
        TOKENS,
    )
    narrow = style_profile("@media (max-width: 720px){.a{grid-template-columns:1fr}}", TOKENS)
    wide = style_profile("@media (min-width: 900px){.a{grid-template-columns:1fr 1fr}}", TOKENS)

    assert (uneven.columns, uneven.uneven_grids) == (ColumnsClass.TWO_UNEVEN, 2)
    assert (many.columns, many.uneven_grids) == (ColumnsClass.MANY, 1)
    assert narrow.columns is ColumnsClass.NONE
    assert wide.columns is ColumnsClass.TWO_EVEN


def test_spans_spacing_and_monospace_are_read_from_their_declarations() -> None:
    profile = style_profile(
        ".a{grid-column:span 2}.b{grid-row:1 / 3}.c{grid-column:2}"
        ".d{grid-area:1 / 1 / 3 / 2}.e{grid-row:span var(--m-rows)}"
        ".f{padding:8px 16px}.g{gap:24px}.h{row-gap:0}.i{column-gap:var(--vl-space)}"
        ".j{padding:calc(var(--vl-space) * 2) 4px}.k{margin:99px}.l{padding-top:77px}",
        TOKENS,
    )

    assert profile.spans == 3
    assert profile.spacing == 18
    assert profile.monospace is False
    assert style_profile(".a{font-family:ui-monospace, monospace}", TOKENS).monospace
    assert style_profile(".a{font-family:var(--vl-font-mono)}", TOKENS).monospace
    assert style_profile(".a{font:600 14px/1.2 monospace}", TOKENS).monospace
    assert not style_profile(".a{font-family:var(--vl-font-body)}", TOKENS).monospace


@pytest.mark.parametrize(
    ("sheet", "expected"),
    [
        (".a{border:1px solid #000}", (1, 0)),
        (".a{border-width:2px;border-style:solid}", (1, 0)),
        (".a{border-style:dashed}", (1, 0)),
        (".a{border:none}.b{border:0}.c{border:1px #000}.d{border-width:2px}", (0, 0)),
        (
            ".a{border-top:1px solid;border-right:1px solid;border-bottom:1px solid;"
            "border-left:1px solid}",
            (1, 0),
        ),
        (".a{border-block:1px solid;border-inline:2px dotted}", (1, 0)),
        (".a{border:1px solid;border-top:none}", (0, 1)),
        (
            ".a{border-bottom:1px solid #000}.b{border-block-end:2px solid}"
            ".c{border-inline-start:3px solid}",
            (0, 3),
        ),
        (".a{border-width:0 0 1px;border-style:solid}", (0, 1)),
        (".a{border-block-width:1px 0;border-block-style:solid}", (0, 1)),
        (".a{border-top-width:2px;border-top-style:solid}", (0, 1)),
        (".a{border:var(--m-unknown) solid}", (0, 0)),
        (".a{border:var(--vl-border-width) solid #000}", (1, 0)),
        ("@media (max-width: 720px){.a{border:1px solid}}.b{border-left:4px solid}", (1, 1)),
        (
            ".a{border:1px solid;border-color:red}.b{border-radius:4px;border-collapse:collapse}",
            (1, 0),
        ),
    ],
)
def test_boxes_and_side_rules_count_the_visible_sides_of_each_rule(sheet, expected) -> None:
    profile = style_profile(sheet, TOKENS)

    assert (profile.boxes, profile.side_rules) == expected


@pytest.mark.parametrize(
    ("boxes", "side_rules", "expected"),
    [
        (0, 0, BoxingClass.OPEN),
        (3, 3, BoxingClass.OPEN),
        (4, 0, BoxingClass.BOXED),
        (6, 0, BoxingClass.BOXED),
        (0, 4, BoxingClass.RULED),
        (4, 8, BoxingClass.RULED),
        (4, 7, BoxingClass.BOXED),
        (3, 4, BoxingClass.BOXED),
        (9, 29, BoxingClass.RULED),
        (14, 10, BoxingClass.BOXED),
    ],
)
def test_boxing_compares_the_boxes_with_the_side_rules(boxes, side_rules, expected) -> None:
    sheet = rules("x", "border:1px solid #000", boxes) + rules(
        "y", "border-bottom:1px solid #000", side_rules
    )

    profile = style_profile(sheet, TOKENS)

    assert (profile.boxes, profile.side_rules, profile.boxing) == (boxes, side_rules, expected)


def test_the_title_ratio_reads_the_rules_of_the_first_h1_of_the_first_screen() -> None:
    markups = [
        '<header><p class="brand">Casa</p></header>'
        '<main><h1 class="page-title big">Prenota</h1></main>',
        '<main><h1 class="other">Due</h1></main>',
    ]
    sheet = (
        "h1{font-size:32px}.page-title{font-size:var(--vl-size-display)}"
        ".big{font-size:clamp(24px, 6vw, 64px)}"
        "@media (max-width: 720px){.page-title{font-size:20px}}"
        ".page-title-sub{font-size:90px}.h1{font-size:80px}h2{font-size:70px}"
        ".brand{font-size:60px}.other{font-size:50px}"
    )
    tokens = {**TOKENS, "--vl-size-display": "48px"}

    profile = style_profile(sheet, tokens, markups=markups)

    assert profile.title_ratio == 4.0
    assert profile.type_ratio == round(90 / 16, 2)
    assert style_profile("main > h1, h2{font-size:30px}", TOKENS).title_ratio == round(30 / 16, 2)


def test_the_title_ratio_falls_back_to_the_display_token_then_to_the_body() -> None:
    tokens = {**TOKENS, "--vl-size-display": "40px"}
    titled = ["<main><h1>Prenota</h1></main>"]

    untitled = ["<main><p>No</p></main>"]
    unknown = "h1{font-size:var(--m-unknown)}"

    assert style_profile("h1{font-size:64px}", tokens, markups=untitled).title_ratio == 2.5
    assert style_profile(".x{font-size:64px}", tokens, markups=titled).title_ratio == 2.5
    assert style_profile(".x{font-size:64px}", TOKENS, markups=titled).title_ratio == 1.0
    assert style_profile(unknown, tokens, markups=titled).title_ratio == 2.5
    assert style_profile("h1{font-size:64px}", TOKENS).title_ratio == 4.0
    assert style_profile(".t{font-size:64px}", TOKENS).title_ratio == 1.0


@pytest.mark.parametrize(
    "styles",
    ["", ".app{--m-gap:12px;--m-brand:var(--vl-color-primary)}", "}}{{.a{font-size:"],
)
def test_a_sheet_without_style_declarations_gives_the_neutral_profile(styles: str) -> None:
    profile = style_profile(styles, {})

    assert profile == style_profile("", TOKENS)
    assert (profile.radius, profile.border, profile.shadow, profile.columns) == (
        RadiusClass.SQUARE,
        BorderClass.NONE,
        ShadowClass.NONE,
        ColumnsClass.NONE,
    )
    assert (profile.type_ratio, profile.container, profile.spacing, profile.monospace) == (
        1.0,
        None,
        0,
        False,
    )
    assert (profile.uppercase, profile.colour_fields, profile.tints, profile.gradients) == (
        0,
        0,
        0,
        0,
    )
    assert (profile.spans, profile.uneven_grids, profile.largest_font) == (0, 0, 0.0)
    assert (profile.boxes, profile.side_rules, profile.boxing, profile.title_ratio) == (
        0,
        0,
        BoxingClass.OPEN,
        1.0,
    )
    assert profile.body_size == 16
    assert profile.properties == Counter()


def test_the_structure_profile_reads_the_screens_in_order() -> None:
    first = (
        '<header class="bar"><a href="#SCR-002">Casa</a><nav><a href="#SCR-002">Camere</a></nav>'
        "</header><main><section><h1>Prenota</h1><article><h2>Camera</h2><p>Vista mare</p>"
        "</article></section><aside><p>Aiuto</p></aside><form><fieldset><legend>Ospite</legend>"
        '<input type="text"></fieldset></form><table><tbody><tr><td>1</td></tr></tbody></table>'
        "</main>"
    )
    second = "<main><article><p>Due</p></article><article><p>Tre</p></article><br></main>"

    profile = structure_profile_from_markup([first, second])

    assert profile.tags == Counter(
        {
            "p": 4,
            "article": 3,
            "a": 2,
            "main": 2,
            "header": 1,
            "nav": 1,
            "section": 1,
            "h1": 1,
            "h2": 1,
            "aside": 1,
            "form": 1,
            "fieldset": 1,
            "legend": 1,
            "input": 1,
            "table": 1,
            "tbody": 1,
            "tr": 1,
            "td": 1,
            "br": 1,
        }
    )
    assert profile.outline == frozenset(
        {
            "header",
            "header>nav",
            "main",
            "main>section",
            "main>section>h1",
            "main>section>article",
            "main>aside",
            "main>form",
            "main>form>fieldset",
            "main>table",
        }
    )
    assert (profile.tables, profile.cards, profile.asides, profile.forms) == (1, 3, 1, 2)
    assert profile.navigation is NavigationPlacement.HEADER
    assert profile.screens == 2


def test_the_outline_is_made_of_semantic_elements_and_wrappers_are_transparent() -> None:
    bare = "<header><nav><a>Uno</a></nav></header><main><section><h2>Due</h2></section></main>"
    wrapped = (
        '<div class="page"><div><header><div class="bar"><nav><ul><li><a>Uno</a></li></ul>'
        '</nav></div></header><div class="body"><main><div><section><p><span>Testo</span></p>'
        "<h2>Due</h2></section></div></main></div></div>"
    )
    deep = "<main><div><section><div><article><h2>Tre</h2></article></div></section></div></main>"

    assert structure_profile_from_markup([bare]).outline == frozenset(
        {"header", "header>nav", "main", "main>section", "main>section>h2"}
    )
    assert structure_profile_from_markup([wrapped]).outline == frozenset(
        {"header", "header>nav", "header>nav>ul", "main", "main>section", "main>section>h2"}
    )
    assert structure_profile_from_markup([deep]).outline == frozenset(
        {"main", "main>section", "main>section>article"}
    )
    assert structure_profile_from_markup(["<div><p><span>Solo</span></p></div>"]).outline == (
        frozenset()
    )
    assert frozenset({"div", "span", "p", "li", "a", "h4", "tbody"}).isdisjoint(SEMANTIC_ELEMENTS)
    assert {"header", "nav", "main", "table", "h1", "h2", "h3"} <= SEMANTIC_ELEMENTS
    assert len(SEMANTIC_ELEMENTS) == 18


@pytest.mark.parametrize(
    ("markup", "expected"),
    [
        ("<header><div><nav><a>Uno</a></nav></div></header>", NavigationPlacement.HEADER),
        ("<aside><header><nav></nav></header></aside>", NavigationPlacement.HEADER),
        ("<aside><nav></nav></aside>", NavigationPlacement.SIDE),
        ("<nav></nav><main></main>", NavigationPlacement.TOP),
        ("<div><main><nav></nav></main></div>", NavigationPlacement.TOP),
        ("<div><nav></nav></div>", NavigationPlacement.OTHER),
        ("<main><p>Nulla</p></main>", NavigationPlacement.NONE),
    ],
)
def test_the_navigation_is_placed_by_the_first_nav_of_the_first_screen(markup, expected) -> None:
    assert structure_profile_from_markup([markup]).navigation is expected


def test_only_the_first_screen_gives_the_outline_and_the_navigation() -> None:
    profile = structure_profile_from_markup(
        ["<main><h1>Uno</h1></main>", "<header><nav><a>Due</a></nav></header>"]
    )

    assert profile.outline == frozenset({"main", "main>h1"})
    assert profile.navigation is NavigationPlacement.NONE
    assert profile.screens == 2
    assert structure_profile_from_markup(["<main><h1>Uno</h1></main>"]).screens == 1
    assert structure_profile_from_markup([]).screens == 0


def test_the_structure_of_a_mockup_is_the_structure_of_its_screens() -> None:
    first, _second = pair()
    drawn = mockup(first)

    assert structure_profile(drawn) == structure_profile_from_markup(
        [screen.markup for screen in drawn.screens]
    )
    assert structure_profile(drawn).navigation is NavigationPlacement.HEADER


@pytest.mark.parametrize(
    ("changes", "part", "expected"),
    [
        ({"boxing": BoxingClass.RULED}, StyleDifference.BOXING, 18),
        ({"boxing": BoxingClass.BOXED}, StyleDifference.BOXING, 18),
        ({"title_ratio": 2.0}, StyleDifference.TITLE_SCALE, 7),
        ({"title_ratio": 4.0}, StyleDifference.TITLE_SCALE, 14),
        ({"container": 1200}, StyleDifference.CONTAINER, 12),
        ({"border": BorderClass.THICK}, StyleDifference.BORDER, 10),
        ({"radius": RadiusClass.PILL}, StyleDifference.RADIUS, 10),
        ({"radius": RadiusClass.ROUNDED}, StyleDifference.RADIUS, 10),
        ({"columns": ColumnsClass.MANY}, StyleDifference.COLUMNS, 8),
        ({"shadow": ShadowClass.HARD}, StyleDifference.SHADOW, 8),
        ({"shadow": ShadowClass.SOFT}, StyleDifference.SHADOW, 0),
        ({"uppercase": 3}, StyleDifference.UPPERCASE, 6),
        ({"uppercase": 2}, StyleDifference.UPPERCASE, 0),
        ({"monospace": True}, StyleDifference.MONOSPACE, 4),
        ({"gradients": 2}, StyleDifference.GRADIENT, 4),
        ({"colour_fields": 1}, StyleDifference.COLOUR_FIELDS, 4 / 5),
        ({"colour_fields": 11}, StyleDifference.COLOUR_FIELDS, 4),
        ({"tints": 2}, StyleDifference.TINTS, 4 / 5),
        ({"tints": 9}, StyleDifference.TINTS, 2),
    ],
)
def test_every_style_part_follows_its_weight(changes, part, expected) -> None:
    base = style_profile("", {})

    parts = style_parts(base, replace(base, **changes))

    assert list(parts) == list(StyleDifference)
    assert parts[part] == pytest.approx(expected)
    assert all(value == 0 for key, value in parts.items() if key is not part)


def test_the_largest_size_the_spacing_and_the_counts_alone_leave_the_distance() -> None:
    base = style_profile("", {})
    other = replace(base, type_ratio=9.0, largest_font=144.0, spacing=40, boxes=2, side_rules=1)

    assert set(style_parts(base, other).values()) == {0}
    assert "TYPE_SCALE" not in StyleDifference.__members__
    assert "SPACING" not in StyleDifference.__members__


def test_the_style_parts_follow_the_order_and_the_weights_of_the_revision() -> None:
    assert dict(STYLE_WEIGHTS) == {
        StyleDifference.BOXING: 18,
        StyleDifference.TITLE_SCALE: 14,
        StyleDifference.CONTAINER: 12,
        StyleDifference.BORDER: 10,
        StyleDifference.RADIUS: 10,
        StyleDifference.COLUMNS: 8,
        StyleDifference.SHADOW: 8,
        StyleDifference.UPPERCASE: 6,
        StyleDifference.MONOSPACE: 4,
        StyleDifference.GRADIENT: 4,
        StyleDifference.COLOUR_FIELDS: 4,
        StyleDifference.TINTS: 2,
    }
    assert list(STYLE_WEIGHTS) == list(StyleDifference)
    assert dict(STRUCTURE_WEIGHTS) == {
        StructureDifference.OUTLINE: 30,
        StructureDifference.TAGS: 25,
        StructureDifference.TABLE: 10,
        StructureDifference.CARDS: 10,
        StructureDifference.SIDE_COLUMN: 10,
        StructureDifference.NAVIGATION: 10,
        StructureDifference.FORMS: 5,
    }


def test_the_shadow_part_counts_only_a_hard_shadow_on_one_side() -> None:
    base = style_profile("", {})
    soft = replace(base, shadow=ShadowClass.SOFT)
    hard = replace(base, shadow=ShadowClass.HARD)

    assert style_parts(soft, base)[StyleDifference.SHADOW] == 0
    assert style_parts(hard, replace(hard, radius=RadiusClass.PILL))[StyleDifference.SHADOW] == 0
    assert style_parts(hard, soft)[StyleDifference.SHADOW] == 8


def test_the_container_part_compares_two_widths() -> None:
    base = style_profile("", {})

    assert style_parts(replace(base, container=1000), replace(base, container=1200))[
        StyleDifference.CONTAINER
    ] == pytest.approx(6)
    assert style_parts(replace(base, container=640), replace(base, container=1600))[
        StyleDifference.CONTAINER
    ] == pytest.approx(12)
    assert style_parts(base, base)[StyleDifference.CONTAINER] == 0


def test_the_style_score_sums_the_parts_and_lists_those_with_half_their_weight() -> None:
    base = style_profile("", {})
    other = replace(
        base,
        radius=RadiusClass.PILL,
        title_ratio=1.8,
        colour_fields=1,
        tints=1,
        gradients=1,
        spacing=6,
        type_ratio=5.0,
    )

    assert styles_distance(base, other) == {
        "available": True,
        "score": 21,
        "differences": ["RADIUS", "GRADIENT"],
    }
    assert styles_distance(base, base) == {"available": True, "score": 0, "differences": []}


def test_the_style_score_reaches_one_hundred_when_every_part_differs() -> None:
    first = style_profile(STRONG, TOKENS)
    second = style_profile(GENTLE, TOKENS)

    assert styles_distance(first, second) == {
        "available": True,
        "score": 100,
        "differences": [item.value for item in StyleDifference],
    }
    assert sum(STYLE_WEIGHTS.values()) == 100
    assert sum(STRUCTURE_WEIGHTS.values()) == 100


@pytest.mark.parametrize(
    ("changes", "part", "expected"),
    [
        ({"outline": frozenset({"main", "main>h2"})}, StructureDifference.OUTLINE, 30 * 2 / 3),
        ({"tags": Counter({"div": 1})}, StructureDifference.TAGS, 25),
        ({"tables": 1}, StructureDifference.TABLE, 10),
        ({"cards": 2}, StructureDifference.CARDS, 0),
        ({"cards": 3}, StructureDifference.CARDS, 10),
        ({"asides": 2}, StructureDifference.SIDE_COLUMN, 10),
        ({"navigation": NavigationPlacement.SIDE}, StructureDifference.NAVIGATION, 10),
        ({"forms": 1}, StructureDifference.FORMS, 5),
    ],
)
def test_every_structure_part_follows_its_weight(changes, part, expected) -> None:
    base = replace(
        structure_profile_from_markup(["<main><h1>Uno</h1></main>"]), tags=Counter({"p": 1})
    )

    parts = structure_parts(base, replace(base, **changes))

    assert list(parts) == list(StructureDifference)
    assert parts[part] == pytest.approx(expected)
    assert all(value == 0 for key, value in parts.items() if key is not part)


def test_the_tag_part_scales_the_cosine_distance_and_the_card_part_its_ratio() -> None:
    base = structure_profile_from_markup([""])
    first = replace(base, tags=Counter({"p": 3, "div": 1}), cards=2)
    second = replace(base, tags=Counter({"p": 3, "div": 2}), cards=6)
    cosine = 1 - 11 / (math.sqrt(10) * math.sqrt(13))

    parts = structure_parts(first, second)

    assert parts[StructureDifference.TAGS] == pytest.approx(25 * cosine / 0.4)
    assert parts[StructureDifference.CARDS] == pytest.approx(10 * 4 / 6)
    assert structure_parts(base, replace(base, tags=Counter({"p": 1})))[
        StructureDifference.TAGS
    ] == pytest.approx(25)
    assert structure_distance(base, base) == {"available": True, "score": 0, "differences": []}


def test_the_structure_score_sums_the_parts_and_lists_those_with_half_their_weight() -> None:
    base = structure_profile_from_markup(["<main><h1>Uno</h1><p>Due</p></main>"])
    other = replace(base, outline=frozenset({"main", "main>h1", "main>ul"}), tables=2)
    wider = replace(base, outline=frozenset({"main", "main>h1", "main>ul", "main>ol"}), forms=1)

    assert base.outline == frozenset({"main", "main>h1"})
    assert structure_distance(base, other) == {
        "available": True,
        "score": 20,
        "differences": ["TABLE"],
    }
    assert structure_distance(base, wider) == {
        "available": True,
        "score": 20,
        "differences": ["OUTLINE", "FORMS"],
    }


def test_the_declared_distance_needs_a_visual_language_on_both_sides() -> None:
    first, second = PACKAGE.alternatives

    assert first.visual_language is None
    assert declared_distance(first, second) == {
        "score": None,
        "axes_different": None,
        "axes": [],
        "choices_different": None,
        "choices_total": 22,
        "primary_colour_distance": None,
    }
    assert CHOICES_TOTAL == len(VISUAL_DIMENSION_NAMES) == 22


def test_the_declared_distance_counts_the_choices_when_a_direction_is_missing() -> None:
    first, second = pair()
    choices = len(visual_differences(first.visual_language.choices, second.visual_language.choices))
    colour = colour_distance(
        first.visual_language.palette_roles["primary"],
        second.visual_language.palette_roles["primary"],
    )
    expected = {
        "score": round(100 * choices / 22),
        "axes_different": None,
        "axes": [],
        "choices_different": choices,
        "choices_total": 22,
        "primary_colour_distance": round(colour, 2),
    }
    directed_first, _ = pair(directed(FIRST_AXES))

    assert choices > 0
    assert declared_distance(first, second) == expected
    assert declared_distance(directed_first, second) == expected


def test_the_declared_distance_counts_the_axes_when_both_have_a_direction() -> None:
    second_language = PACKAGE.alternatives[1].visual_language
    first, second = pair(directed(FIRST_AXES), directed(SECOND_AXES, "Tool bench", second_language))

    declared = declared_distance(first, second)

    assert declared["score"] == 80
    assert declared["axes_different"] == 4
    assert declared["axes"] == ["layout", "shape", "type", "colour"]
    assert declared["choices_different"] == len(
        visual_differences(first.visual_language.choices, second.visual_language.choices)
    )
    assert declared["choices_total"] == 22
    assert isinstance(declared["primary_colour_distance"], float)
    same = declared_distance(first, replace(second, visual_language=first.visual_language))
    assert (same["score"], same["axes_different"], same["axes"]) == (0, 0, [])
    assert same["primary_colour_distance"] == 0.0


def test_a_pair_without_both_mockups_has_an_unknown_verdict() -> None:
    first, second = pair()

    measured = design_distance(first, second, first_mockup=mockup(first, STRONG))

    assert list(measured) == ["first", "second", "declared", "styles", "structure", "verdict"]
    assert (measured["first"], measured["second"]) == ("DES-001", "DES-002")
    assert measured["declared"] == declared_distance(first, second)
    assert measured["styles"] == {"available": False, "score": None, "differences": []}
    assert measured["structure"] == {"available": False, "score": None, "differences": []}
    assert measured["verdict"] == "UNKNOWN"
    assert design_distance(first, second)["verdict"] == "UNKNOWN"


def test_two_mockups_alike_in_style_and_structure_are_close() -> None:
    first, second = pair()

    measured = design_distance(
        first, second, first_mockup=mockup(first, STRONG), second_mockup=mockup(second, STRONG)
    )

    assert measured["styles"] == {"available": True, "score": 0, "differences": []}
    assert measured["structure"] == {"available": True, "score": 0, "differences": []}
    assert measured["verdict"] == "CLOSE"


def test_the_verdict_follows_the_drawn_style_and_the_structure_only_informs() -> None:
    first, second = pair()
    by_style = design_distance(
        first, second, first_mockup=mockup(first, STRONG), second_mockup=mockup(second, GENTLE)
    )
    by_structure = design_distance(
        first,
        second,
        first_mockup=mockup(first, STRONG),
        second_mockup=mockup(second, STRONG, OTHER_SCREENS),
    )

    assert by_style["styles"]["score"] == 100
    assert by_style["verdict"] == "FAR"
    assert by_structure["styles"] == {
        "available": True,
        "score": 14,
        "differences": ["TITLE_SCALE"],
    }
    assert by_structure["structure"] == {
        "available": True,
        "score": 65,
        "differences": ["OUTLINE", "TAGS", "NAVIGATION"],
    }
    assert by_structure["verdict"] == "CLOSE"


def test_a_pair_is_close_only_below_the_style_threshold() -> None:
    first, second = pair()
    boxed = BOXES + "h1{font-size:64px}.c{max-width:640px}"
    other = mockup(second, THIN + "h1{font-size:24px}")

    at = design_distance(
        first, second, first_mockup=mockup(first, boxed + fields(1)), second_mockup=other
    )
    below = design_distance(first, second, first_mockup=mockup(first, boxed), second_mockup=other)

    assert at["styles"] == {
        "available": True,
        "score": STYLES_CLOSE,
        "differences": ["BOXING", "TITLE_SCALE", "CONTAINER"],
    }
    assert at["verdict"] == "FAR"
    assert below["styles"]["score"] == STYLES_CLOSE - 1
    assert below["verdict"] == "CLOSE"


def test_the_threshold_comes_from_the_calibration_rule_and_structure_has_none() -> None:
    assert STYLES_CLOSE % 5 == 0
    assert STYLES_CLOSE == 45
    assert not hasattr(distance_module, "STRUCTURE_CLOSE")
    assert "STRUCTURE_CLOSE" not in distance_module.__all__


def adherence_case(axis: str, value: str):
    first, _second = pair()
    return replace(first, visual_language=directed(replace(BASE_AXES, **{axis: value})))


ADHERENCE = (
    ("shape", "ROUNDED_OUTLINE", ".r{border-radius:12px}" + THIN, ".r{border-radius:12px}"),
    ("shape", "ROUNDED_OUTLINE", ".r{border-radius:20px}" + THIN, ".r{border-radius:0}" + THIN),
    ("shape", "ROUNDED_OUTLINE", ".r{border-radius:8px}" + THIN, ".r{border-radius:999px}" + THIN),
    ("shape", "SQUARE_RULES", ".r{border-radius:0}" + THIN, ".r{border-radius:12px}" + THIN),
    ("shape", "SQUARE_RULES", ".r{border-radius:0}" + RULES, ".r{border-radius:0}" + BOXES),
    ("shape", "HEAVY_FRAME", THICK, SOFT + THIN),
    ("shape", "HEAVY_FRAME", HARD, THIN),
    ("shape", "SOFT_FILL", TWO_TINTS, BOXES),
    ("shape", "SOFT_FILL", THIN, RULES),
    ("shape", "SOFT_FILL", TWO_TINTS + HARD, THICK),
    ("shape", "PILL", ".r{border-radius:999px}", ".r{border-radius:2px}"),
    ("shape", "PILL", ".r{border-radius:8px}", ".r{border-radius:0}"),
    ("type", "EVEN", "h1{font-size:32px}", "h1{font-size:64px}"),
    ("type", "DISPLAY", "h1{font-size:64px}", "h1{font-size:32px}"),
    ("type", "DISPLAY", "", ".t{font-size:96px}h1{font-size:32px}"),
    (
        "type",
        "CAPS_LABELS",
        rules("u", "text-transform:uppercase", 3),
        rules("u", "text-transform:uppercase", 2),
    ),
    ("type", "READING", ".t{font-size:40px}", ".t{font-size:80px}"),
    ("colour", "ACCENT_ONLY", fields(4), fields(5)),
    ("colour", "FIELDS", fields(2), fields(1)),
    ("colour", "INK", fields(3) + TWO_TINTS, GRADIENT),
    ("colour", "INK", "", THREE_TINTS),
    ("colour", "INK", "", fields(4)),
    ("colour", "TINTED", THREE_TINTS, TWO_TINTS),
    ("layout", "STAGE", ".c{max-width:640px}", ".c{max-width:1200px}"),
    ("layout", "STAGE", ".c{max-width:var(--vl-content-width)}", ""),
    ("layout", "WORKBENCH", "", ".c{max-width:1200px}"),
    ("layout", "WORKBENCH", ".c{max-width:var(--vl-content-width)}", ".c{max-width:800px}"),
    (
        "layout",
        "EDITORIAL",
        ".k{display:grid;grid-template-columns:2fr 1fr}",
        ".k{display:grid;grid-template-columns:1fr 1fr}",
    ),
    (
        "layout",
        "EDITORIAL",
        ".k{grid-template-columns:repeat(3, 1fr)}"
        "@media (max-width: 720px){.k{grid-template-columns:1fr 280px}}",
        ".k{grid-template-columns:repeat(3, 1fr)}",
    ),
    (
        "layout",
        "MOSAIC",
        rules("m", "grid-column:span 2", 2),
        rules("m", "grid-column:span 2", 1),
    ),
    ("layout", "PANELS", ".k{grid-template-columns:repeat(3, 1fr)}", ".k{display:flex}"),
)


@pytest.mark.parametrize(("axis", "value", "following", "failing"), ADHERENCE)
def test_adherence_checks_each_axis_value(axis, value, following, failing) -> None:
    alternative = adherence_case(axis, value)

    kept = direction_adherence(alternative, mockup(alternative, following))
    missed = direction_adherence(alternative, mockup(alternative, failing))

    assert kept["available"] is missed["available"] is True
    assert list(kept["axes"]) == list(DIRECTION_AXES)
    assert kept["axes"][axis] == "FOLLOWED"
    assert missed["axes"][axis] == "NOT_FOLLOWED"
    assert kept["axes"]["density"] == missed["axes"]["density"] == "NOT_CHECKED"


@pytest.mark.parametrize(
    ("axis", "value"),
    [
        ("layout", "BANDS"),
        ("density", "COMPACT"),
        ("density", "COMFORTABLE"),
        ("density", "SPACIOUS"),
    ],
)
def test_bands_and_density_are_not_checked(axis: str, value: str) -> None:
    alternative = adherence_case(axis, value)

    for styles in ("", STRONG, GENTLE):
        result = direction_adherence(alternative, mockup(alternative, styles))
        assert result["axes"][axis] == "NOT_CHECKED"


def test_every_axis_value_of_the_vocabulary_has_an_adherence_case() -> None:
    covered = {(axis, value) for axis, value, _following, _failing in ADHERENCE}
    covered |= {("layout", "BANDS"), ("density", "COMPACT"), ("density", "COMFORTABLE")}
    covered |= {("density", "SPACIOUS")}

    assert covered == {
        (axis, value.value) for axis, values in DIRECTION_AXIS_VALUES.items() for value in values
    }


def test_reading_needs_a_large_size_when_the_body_token_is_small() -> None:
    alternative = adherence_case("type", "READING")
    language = alternative.visual_language
    small = replace(
        alternative,
        visual_language=replace(
            language, tokens=tuple({**language.token_values, "--vl-size-body": "16px"}.items())
        ),
    )

    assert language.token_values["--vl-size-body"] == "18px"
    assert direction_adherence(small, mockup(small, ".t{font-size:14px}"))["axes"]["type"] == (
        "NOT_FOLLOWED"
    )
    assert direction_adherence(small, mockup(small, ".t{font-size:18px}"))["axes"]["type"] == (
        "FOLLOWED"
    )


def test_adherence_is_unavailable_without_a_direction_or_a_mockup() -> None:
    first, second = pair()
    directed_first, _ = pair(directed(FIRST_AXES))

    assert direction_adherence(first, mockup(first, STRONG)) == {"available": False, "axes": {}}
    assert direction_adherence(directed_first, None) == {"available": False, "axes": {}}
    assert direction_adherence(PACKAGE.alternatives[0], None) == {"available": False, "axes": {}}
    assert direction_adherence(second, None) == {"available": False, "axes": {}}


def test_the_report_has_the_shape_of_the_contract() -> None:
    second_language = PACKAGE.alternatives[1].visual_language
    first, second = pair(directed(FIRST_AXES), directed(SECOND_AXES, "Tool bench", second_language))
    version = version_of(first, second)
    mockups = {first.id: mockup(first, STRONG), second.id: mockup(second, GENTLE, OTHER_SCREENS)}

    report = design_distance_report(version, mockups)

    assert list(report) == [
        "distance_version",
        "design_version_id",
        "design_content_hash",
        "pairs",
        "alternatives",
    ]
    assert report["distance_version"] == DESIGN_DISTANCE_VERSION == 1
    assert report["design_version_id"] == str(version.id)
    assert report["design_content_hash"] == version.content_hash
    assert report["pairs"] == [
        design_distance(
            first, second, first_mockup=mockups[first.id], second_mockup=mockups[second.id]
        )
    ]
    assert report["pairs"][0]["verdict"] == "FAR"
    assert report["alternatives"] == [
        {
            "code": "DES-001",
            "direction": "Printed register",
            "adherence": direction_adherence(first, mockups[first.id]),
        },
        {
            "code": "DES-002",
            "direction": "Tool bench",
            "adherence": direction_adherence(second, mockups[second.id]),
        },
    ]
    assert report["alternatives"][0]["adherence"]["axes"] == {
        "layout": "FOLLOWED",
        "shape": "NOT_FOLLOWED",
        "type": "FOLLOWED",
        "colour": "NOT_FOLLOWED",
        "density": "NOT_CHECKED",
    }


def test_the_report_of_a_design_without_directions_nor_mockups_is_unknown() -> None:
    version = design_fixtures.design_version()

    report = design_distance_report(version, {})

    assert report["pairs"] == [
        {
            "first": "DES-001",
            "second": "DES-002",
            "declared": {
                "score": None,
                "axes_different": None,
                "axes": [],
                "choices_different": None,
                "choices_total": 22,
                "primary_colour_distance": None,
            },
            "styles": {"available": False, "score": None, "differences": []},
            "structure": {"available": False, "score": None, "differences": []},
            "verdict": "UNKNOWN",
        }
    ]
    assert report["alternatives"] == [
        {"code": "DES-001", "direction": None, "adherence": {"available": False, "axes": {}}},
        {"code": "DES-002", "direction": None, "adherence": {"available": False, "axes": {}}},
    ]


def test_the_report_measures_every_pair_of_alternatives_in_order() -> None:
    first, second = pair()
    third = replace(
        second,
        id=UUID("00000000-0000-4000-8000-000000000072"),
        code="DES-003",
        approach=DesignApproach.TASK_FOCUSED,
    )
    critique = PACKAGE.critiques[1]
    package = replace(
        PACKAGE,
        alternatives=(first, second, third),
        critiques=(
            *PACKAGE.critiques,
            replace(
                critique,
                id=UUID("00000000-0000-4000-8000-000000000203"),
                code="CRQ-003",
                design_alternative_id=third.id,
            ),
        ),
    )
    version = design_fixtures.design_version(package=package)

    report = design_distance_report(version, {third.id: mockup(third, GENTLE)})

    assert [(item["first"], item["second"]) for item in report["pairs"]] == [
        ("DES-001", "DES-002"),
        ("DES-001", "DES-003"),
        ("DES-002", "DES-003"),
    ]
    assert [item["code"] for item in report["alternatives"]] == ["DES-001", "DES-002", "DES-003"]
    assert {item["verdict"] for item in report["pairs"]} == {"UNKNOWN"}


def test_the_measure_is_deterministic() -> None:
    second_language = PACKAGE.alternatives[1].visual_language
    first, second = pair(directed(FIRST_AXES), directed(SECOND_AXES, "Tool bench", second_language))
    version = version_of(first, second)

    reports = [
        design_distance_report(
            version, {first.id: mockup(first, STRONG), second.id: mockup(second, GENTLE)}
        )
        for _ in range(2)
    ]

    assert reports[0] == reports[1]
    assert json.dumps(reports[0], sort_keys=True) == json.dumps(reports[1], sort_keys=True)
    assert style_profile(STRONG, TOKENS) == style_profile(STRONG, TOKENS)
