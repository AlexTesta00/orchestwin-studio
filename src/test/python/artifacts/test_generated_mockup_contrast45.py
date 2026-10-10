from __future__ import annotations

import pytest

from orchestwin.artifacts.generated_mockup_contrast import (
    CONTRAST_NOTE_CODES,
    CONTROL_BORDER_REPLACED,
    REPLACEMENT_TOKENS,
    TEXT_COLOUR_REPLACED,
    repair_contrast,
)
from orchestwin.artifacts.generated_mockup_repair import RepairNote
from orchestwin.artifacts.generated_mockup_review import (
    MockupIssueSeverity,
    is_large_text,
    review_generated_mockup,
)
from orchestwin.artifacts.generated_mockup_styles import parse_style_sheet
from orchestwin.artifacts.visual_catalog import MODES, ColorMode
from orchestwin.artifacts.visual_color import contrast_ratio, format_hex, parse_hex

from .test_generated_mockup_support import (
    BASE_CODES,
    BASE_STYLES,
    CSS_COMMENT_CLOSE,
    CSS_COMMENT_OPEN,
    DARK_TOKENS,
    FIXTURES,
    HIGH_CONTRAST_TOKENS,
    LIGHT_TOKENS,
    build,
    fixture_data,
    fixture_tokens,
)

ERROR = MockupIssueSeverity.ERROR
BOTH_MODES = pytest.mark.parametrize("tokens", [LIGHT_TOKENS, DARK_TOKENS], ids=["light", "dark"])
CONTRAST_CODES = frozenset({"LOW_CONTRAST", "UNREADABLE_TEXT_COLOUR", "WEAK_CONTROL_BORDER"})
SURFACES = ("background", "surface", "surface-alt")
PAIR = "color:var(--vl-color-text);background:var(--vl-color-accent)"


def colour(tokens: dict[str, str], role: str) -> str:
    return tokens[f"--vl-color-{role}"]


def ratio(tokens: dict[str, str], first: str, second: str) -> float:
    return contrast_ratio(colour(tokens, first), colour(tokens, second))


def best(tokens: dict[str, str], role: str, backgrounds: tuple[str, ...]) -> float:
    return max(ratio(tokens, role, background) for background in backgrounds)


def repaired(
    styles: str,
    tokens: dict[str, str] = LIGHT_TOKENS,
    *,
    text: float = 4.5,
    large: float = 3.0,
    ui: float = 3.0,
) -> tuple[str, tuple[RepairNote, ...]]:
    return repair_contrast(
        styles, tokens, text_threshold=text, large_text_threshold=large, ui_threshold=ui
    )


def details(notes: tuple[RepairNote, ...]) -> list[tuple[str, str]]:
    return [(note.code, note.detail) for note in notes]


def contrast_issues(
    styles: str, tokens: dict[str, str] = LIGHT_TOKENS, *, text: float = 4.5, large: float = 3.0
) -> list[tuple[str, MockupIssueSeverity]]:
    report = review_generated_mockup(
        build(styles=BASE_STYLES + styles),
        tokens=tokens,
        requirement_codes=BASE_CODES,
        text_contrast_threshold=text,
        large_text_threshold=large,
    )
    return [(issue.code, issue.severity) for issue in report.issues if issue.code in CONTRAST_CODES]


@BOTH_MODES
def test_a_muted_text_unreadable_on_its_background_stays_muted(tokens: dict[str, str]) -> None:
    styles = ".chip{color:var(--vl-color-primary-soft);background:var(--vl-color-surface)}"
    result, notes = repaired(styles, tokens)
    assert result == ".chip{color:var(--vl-color-text-muted);background:var(--vl-color-surface)}"
    expected = ratio(tokens, "text-muted", "surface")
    assert details(notes) == [
        (
            TEXT_COLOUR_REPLACED,
            f".chip var(--vl-color-primary-soft)→var(--vl-color-text-muted) {expected:.2f}",
        )
    ]
    assert contrast_issues(styles, tokens) == [("LOW_CONTRAST", ERROR)]
    assert contrast_issues(result, tokens) == []


@BOTH_MODES
def test_a_text_on_a_band_takes_the_closest_colour_that_reads_on_the_band(
    tokens: dict[str, str],
) -> None:
    styles = ".band{background:var(--vl-color-text);color:var(--vl-color-text-muted)}"
    result, notes = repaired(styles, tokens)
    assert result == ".band{background:var(--vl-color-text);color:var(--vl-color-surface-alt)}"
    expected = ratio(tokens, "surface-alt", "text")
    assert details(notes) == [
        (
            TEXT_COLOUR_REPLACED,
            f".band var(--vl-color-text-muted)→var(--vl-color-surface-alt) {expected:.2f}",
        )
    ]
    assert ratio(tokens, "on-primary", "text") > expected
    assert contrast_issues(result, tokens) == []


def test_without_a_background_the_closest_token_readable_on_a_candidate_is_chosen() -> None:
    alone = ".ghost{color:var(--vl-color-accent)}"
    result, notes = repaired(alone)
    assert result == ".ghost{color:var(--vl-color-text-muted)}"
    expected = best(LIGHT_TOKENS, "text-muted", SURFACES)
    assert details(notes) == [
        (
            TEXT_COLOUR_REPLACED,
            f".ghost var(--vl-color-accent)→var(--vl-color-text-muted) {expected:.2f}",
        )
    ]
    band = ".band{background:var(--vl-color-text);color:var(--vl-color-surface)}"
    result, notes = repaired(band + alone)
    assert result == band + ".ghost{color:var(--vl-color-text-muted)}"
    assert contrast_issues(band + alone) == [("UNREADABLE_TEXT_COLOUR", ERROR)]
    assert contrast_issues(result) == []
    clear = ".ghost{color:var(--vl-color-primary-soft);background:transparent}"
    assert repaired(clear)[0] == ".ghost{color:var(--vl-color-text-muted);background:transparent}"


def test_a_text_colour_that_no_token_can_rescue_is_left_to_the_review() -> None:
    dark = parse_hex(colour(LIGHT_TOKENS, "text"))
    light = parse_hex(colour(LIGHT_TOKENS, "surface"))
    mixed = format_hex(
        tuple(0.6 * first + 0.4 * second for first, second in zip(dark, light, strict=True))
    )
    assert all(
        contrast_ratio(colour(LIGHT_TOKENS, role), mixed) < 4.5 for role in REPLACEMENT_TOKENS
    )
    styles = (
        ".mid{color:var(--vl-color-primary-soft);"
        "background:color-mix(in srgb, var(--vl-color-text) 60%, var(--vl-color-surface))}"
    )
    assert repaired(styles) == (styles, ())
    assert contrast_issues(styles) == [("LOW_CONTRAST", ERROR)]


@pytest.mark.parametrize(
    ("styles", "expected"),
    [
        (
            ".chip{color:var(--vl-color-primary-soft) !important;"
            "background:var(--vl-color-surface)}",
            ".chip{color:var(--vl-color-text-muted) !important;background:var(--vl-color-surface)}",
        ),
        (
            ".chip{color:var(--vl-color-primary-soft)!important;"
            "background:var(--vl-color-surface)}",
            ".chip{color:var(--vl-color-text-muted)!important;background:var(--vl-color-surface)}",
        ),
        (
            "button:hover{border-bottom:2px dashed var(--vl-color-border) !important}",
            "button:hover{border-bottom:2px dashed var(--vl-color-text-muted) !important}",
        ),
    ],
)
def test_important_is_kept(styles: str, expected: str) -> None:
    result, notes = repaired(styles)
    assert result == expected
    assert len(notes) == 1


def test_rules_inside_keyframes_are_never_touched() -> None:
    styles = (
        "@keyframes fade{from{color:var(--vl-color-primary-soft);"
        "background:var(--vl-color-surface)}to{color:var(--vl-color-border)}}"
    )
    assert repaired(styles) == (styles, ())
    assert contrast_issues(styles) == []


@pytest.mark.parametrize(
    ("rule", "expected", "olds"),
    [
        (
            "input{border:1px solid var(--vl-color-border)}",
            "input{border:1px solid var(--vl-color-text-muted)}",
            ("var(--vl-color-border)",),
        ),
        (
            ".form select{border-color:var(--vl-color-border) var(--vl-color-surface-alt)}",
            ".form select{border-color:var(--vl-color-text-muted) var(--vl-color-text-muted)}",
            ("var(--vl-color-border)", "var(--vl-color-surface-alt)"),
        ),
        (
            "p,textarea{padding:4px;border:var(--vl-border-width) solid var(--vl-color-border)}",
            "p,textarea{padding:4px;border:var(--vl-border-width) solid "
            "var(--vl-color-text-muted)}",
            ("var(--vl-color-border)",),
        ),
    ],
)
def test_a_weak_control_border_takes_the_muted_text_colour(
    rule: str, expected: str, olds: tuple[str, ...]
) -> None:
    result, notes = repaired(rule)
    assert result == expected
    muted = best(LIGHT_TOKENS, "text-muted", ("background", "surface"))
    selector = rule.split("{", 1)[0]
    assert details(notes) == [
        (CONTROL_BORDER_REPLACED, f"{selector} {old}→var(--vl-color-text-muted) {muted:.2f}")
        for old in olds
    ]
    assert contrast_issues(rule) == [("WEAK_CONTROL_BORDER", ERROR)]
    assert contrast_issues(result) == []


def test_a_weak_control_border_takes_the_text_colour_when_the_muted_one_is_weak_too() -> None:
    tokens = {**LIGHT_TOKENS, "--vl-color-text-muted": "#c8c8c8"}
    assert best(tokens, "text-muted", ("background", "surface")) < 3.0
    result, notes = repaired("input{border:1px solid var(--vl-color-border)}", tokens)
    assert result == "input{border:1px solid var(--vl-color-text)}"
    expected = best(tokens, "text", ("background", "surface"))
    assert details(notes) == [
        (
            CONTROL_BORDER_REPLACED,
            f"input var(--vl-color-border)→var(--vl-color-text) {expected:.2f}",
        )
    ]


def test_a_sheet_that_passes_is_returned_byte_for_byte() -> None:
    styles = (
        "main{color:var(--vl-color-text)}\r\n"
        f"{CSS_COMMENT_OPEN} quiet {CSS_COMMENT_CLOSE}"
        ".a{color:var(--vl-color-text-muted);background:var(--vl-color-surface)}\r\n"
        "input{border:1px solid var(--vl-color-text-muted)}"
        f".t{{{PAIR};font-size:24px}}"
    )
    result = repaired(styles)
    assert result == (styles, ())
    assert result[0] is styles


@pytest.mark.parametrize("name", FIXTURES)
def test_the_styles_of_the_fixtures_are_kept_in_every_mode(name: str) -> None:
    styles = fixture_data(name)["styles"]
    assert isinstance(styles, str)
    for tokens in (fixture_tokens(name), LIGHT_TOKENS, DARK_TOKENS):
        assert repaired(styles, tokens) == (styles, ())


@pytest.mark.parametrize("name", FIXTURES)
def test_a_fault_added_to_a_real_sheet_is_the_only_change(name: str) -> None:
    styles = fixture_data(name)["styles"]
    assert isinstance(styles, str)
    fault = ".m-faint{color:var(--vl-color-border);background:var(--vl-color-surface)}"
    fixed = fault.replace("var(--vl-color-border)", "var(--vl-color-text-muted)")
    result, notes = repaired(fault + styles + fault, fixture_tokens(name))
    assert result == fixed + styles + fixed
    assert [(note.code, note.count) for note in notes] == [(TEXT_COLOUR_REPLACED, 2)]


@pytest.mark.parametrize(
    "styles",
    ["main{color:red}", "main{color:var(--vl-color-border)", ".a{color:var(--vl-color-border)}p{"],
)
def test_styles_that_cannot_be_read_are_returned_unchanged(styles: str) -> None:
    assert repaired(styles) == (styles, ())


def test_large_text_keeps_a_colour_that_normal_text_would_lose() -> None:
    assert 3.0 <= ratio(LIGHT_TOKENS, "text", "accent") < 4.5
    large = f".big{{{PAIR};font-size:24px}}.bold{{{PAIR};font-size:20px;font-weight:700}}"
    assert repaired(large) == (large, ())
    result, notes = repaired(f".small{{{PAIR};font-size:20px}}")
    assert result == (
        ".small{color:var(--vl-color-on-primary);background:var(--vl-color-accent);font-size:20px}"
    )
    expected = ratio(LIGHT_TOKENS, "on-primary", "accent")
    assert details(notes) == [
        (
            TEXT_COLOUR_REPLACED,
            f".small var(--vl-color-text)→var(--vl-color-on-primary) {expected:.2f}",
        )
    ]


def test_the_thresholds_of_high_contrast_are_given_by_the_caller() -> None:
    mode = MODES[ColorMode.HIGH_CONTRAST_LIGHT]
    rule = ".m{color:var(--vl-color-border);background:var(--vl-color-surface-alt)}"
    assert mode.ui_threshold <= ratio(HIGH_CONTRAST_TOKENS, "border", "surface-alt") < 7.0
    options = {"text": mode.text_threshold, "large": mode.ui_threshold, "ui": mode.ui_threshold}
    result, notes = repaired(rule, HIGH_CONTRAST_TOKENS, **options)
    assert result == ".m{color:var(--vl-color-text-muted);background:var(--vl-color-surface-alt)}"
    assert ratio(HIGH_CONTRAST_TOKENS, "text-muted", "surface-alt") >= mode.text_threshold
    assert [note.code for note in notes] == [TEXT_COLOUR_REPLACED]
    large = rule.replace("}", ";font-size:2rem}")
    assert repaired(large, HIGH_CONTRAST_TOKENS, **options) == (large, ())
    assert repaired(rule, HIGH_CONTRAST_TOKENS) == (rule, ())


def test_rewrites_inside_media_queries_keep_the_rest_of_the_sheet() -> None:
    styles = (
        ".a{--m-ink:var(--vl-color-border);color:var(--m-ink);background:var(--vl-color-surface)}"
        "@media (max-width:600px){.b{padding:4px;color:color-mix(in srgb, "
        "var(--vl-color-surface) 90%, var(--vl-color-text));"
        "background-color:var(--vl-color-surface)}}"
    )
    result, notes = repaired(styles)
    assert result == (
        ".a{--m-ink:var(--vl-color-border);color:var(--vl-color-text-muted);"
        "background:var(--vl-color-surface)}"
        "@media (max-width:600px){.b{padding:4px;color:var(--vl-color-text-muted);"
        "background-color:var(--vl-color-surface)}}"
    )
    expected = f"{ratio(LIGHT_TOKENS, 'text-muted', 'surface'):.2f}"
    assert details(notes) == [
        (TEXT_COLOUR_REPLACED, f".a var(--m-ink)→var(--vl-color-text-muted) {expected}"),
        (
            TEXT_COLOUR_REPLACED,
            ".b color-mix(in srgb, var(--vl-color-surface) 90%, var(--vl-color-text))"
            f"→var(--vl-color-text-muted) {expected}",
        ),
    ]


def test_the_declaration_that_wins_is_the_one_replaced() -> None:
    background = "background:var(--vl-color-surface)"
    repeated = f".x{{color:var(--vl-color-border);color:var(--vl-color-border);{background}}}"
    assert repaired(repeated)[0] == (
        f".x{{color:var(--vl-color-border);color:var(--vl-color-text-muted);{background}}}"
    )
    important = (
        f".x{{color:var(--vl-color-border) !important;color:var(--vl-color-text);{background}}}"
    )
    assert repaired(important)[0] == (
        f".x{{color:var(--vl-color-text-muted) !important;color:var(--vl-color-text);{background}}}"
    )


def test_identical_replacements_are_counted_in_one_note() -> None:
    rule = ".x{color:var(--vl-color-border);background:var(--vl-color-surface)}"
    result, notes = repaired(rule + "@media (max-width:600px){" + rule + "}")
    assert result.count("color:var(--vl-color-text-muted);") == 2
    expected = ratio(LIGHT_TOKENS, "text-muted", "surface")
    name = f".x var(--vl-color-border)→var(--vl-color-text-muted) {expected:.2f}"
    assert notes == (RepairNote(TEXT_COLOUR_REPLACED, None, name, 2),)
    assert notes[0].detail == f"{name} (2)"
    assert {note.code for note in notes} <= set(CONTRAST_NOTE_CODES)


@pytest.mark.parametrize(
    ("tokens", "mode"),
    [
        (LIGHT_TOKENS, ColorMode.LIGHT),
        (DARK_TOKENS, ColorMode.DARK),
        (HIGH_CONTRAST_TOKENS, ColorMode.HIGH_CONTRAST_LIGHT),
    ],
    ids=["light", "dark", "high-contrast"],
)
def test_a_repaired_sheet_passes_the_contrast_checks_of_the_review(
    tokens: dict[str, str], mode: ColorMode
) -> None:
    spec = MODES[mode]
    styles = (
        ".chip{color:var(--vl-color-primary-soft);background:var(--vl-color-surface)}"
        ".ghost{color:var(--vl-color-primary-soft)}"
        ".note{color:var(--vl-color-border);background:var(--vl-color-surface-alt)}"
        "input,select{border:1px solid var(--vl-color-border)}"
        "@media (max-width:600px){.chip{color:var(--vl-color-surface-alt)}}"
    )
    thresholds = {"text": spec.text_threshold, "large": spec.ui_threshold}
    result, notes = repaired(styles, tokens, ui=spec.ui_threshold, **thresholds)
    assert contrast_issues(styles, tokens, **thresholds)
    assert contrast_issues(result, tokens, **thresholds) == []
    assert notes and {note.code for note in notes} <= set(CONTRAST_NOTE_CODES)


@pytest.mark.parametrize(
    ("declarations", "large"),
    [
        ("font-size:24px", True),
        ("font-size:1.5rem", True),
        ("font-size:1.5em", True),
        ("font-size:var(--vl-size-display)", True),
        ("font-size:var(--vl-size-display-narrow)", True),
        ("font-size:20px;font-weight:700", True),
        ("font-size:1.25rem;font-weight:bold", True),
        ("font-size:20px;font-weight:var(--vl-heading-weight)", True),
        ("font-size:23px", False),
        ("font-size:18px;font-weight:700", False),
        ("font-size:20px;font-weight:600", False),
        ("font-size:20px;font-weight:bolder", False),
        ("font-size:min(var(--vl-size-display), 8vw)", False),
        ("font-size:var(--vl-size-body)", False),
        ("font-size:24px;font-size:16px", False),
        ("font-weight:900", False),
    ],
)
def test_large_text_follows_the_size_and_the_weight_declared_in_the_rule(
    declarations: str, large: bool
) -> None:
    tokens = {**LIGHT_TOKENS, "--vl-size-display-narrow": "40px"}
    rule = parse_style_sheet(f".t{{{declarations}}}").rules[0]
    assert is_large_text(rule, tokens) is large


@pytest.mark.parametrize(
    ("size", "large"),
    [("2.5rem", True), ("1.25rem", False), ("clamp(1rem, 4vw, 3rem)", False)],
)
def test_a_display_size_is_resolved_from_the_value_of_its_token(size: str, large: bool) -> None:
    rule = parse_style_sheet(".t{font-size:var(--vl-size-display)}").rules[0]
    assert is_large_text(rule, {**LIGHT_TOKENS, "--vl-size-display": size}) is large
