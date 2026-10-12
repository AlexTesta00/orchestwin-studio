from __future__ import annotations

import pytest

from orchestwin.artifacts.generated_mockup_contrast import (
    CONTROL_BORDER_REPLACED,
    TEXT_COLOUR_REPLACED,
    ContrastCorrection,
    repair_contrast,
    repair_contrast_with_corrections,
)
from orchestwin.artifacts.generated_mockup_repair import RepairNote
from orchestwin.artifacts.visual_color import contrast_ratio
from src.test.python.models.test_generated_mockup_binding import FAINT, bind, chosen
from src.test.python.models.test_generated_mockup_support import GUIDED_ID, draft_payload

from .test_generated_mockup_support import LIGHT_TOKENS

BLUE_ON_RED = {
    **LIGHT_TOKENS,
    "--vl-color-primary": "#0000ff",
    "--vl-color-danger": "#ff0000",
    "--vl-color-text": "#000000",
}
BAR = ".bar{color:var(--vl-color-primary);background:var(--vl-color-danger)}"
WEAK_BORDER = "input{border:1px solid var(--vl-color-border)}"


def repaired(
    styles: str,
    tokens: dict[str, str] = LIGHT_TOKENS,
    *,
    text: float = 4.5,
    large: float = 3.0,
    ui: float = 3.0,
) -> tuple[str, tuple[RepairNote, ...], tuple[ContrastCorrection, ...]]:
    return repair_contrast_with_corrections(
        styles, tokens, text_threshold=text, large_text_threshold=large, ui_threshold=ui
    )


def test_blue_text_on_a_red_bar_is_replaced_and_declared() -> None:
    styles, notes, corrections = repaired(BAR, BLUE_ON_RED)
    assert styles == ".bar{color:var(--vl-color-text);background:var(--vl-color-danger)}"
    before = contrast_ratio("#0000ff", "#ff0000")
    after = contrast_ratio("#000000", "#ff0000")
    assert round(before, 1) == 2.1
    assert corrections == (
        ContrastCorrection(
            code=TEXT_COLOUR_REPLACED,
            selector=".bar",
            property="color",
            before_value="var(--vl-color-primary)",
            before_hex="#0000FF",
            before_ratio=before,
            after_token="text",
            after_hex="#000000",
            after_ratio=after,
            background_hex="#FF0000",
            inherited_background=False,
            threshold=4.5,
            large_text=False,
            count=1,
        ),
    )
    assert after >= 4.5
    assert [note.detail for note in notes] == [
        f".bar var(--vl-color-primary)→var(--vl-color-text) {after:.2f}"
    ]


def test_the_snapshot_of_a_correction_names_the_colours_in_neutral_keys() -> None:
    [correction] = repaired(BAR, BLUE_ON_RED)[2]
    assert correction.to_snapshot() == {
        "code": TEXT_COLOUR_REPLACED,
        "selector": ".bar",
        "property": "color",
        "before": {
            "value": "var(--vl-color-primary)",
            "hex": "#0000FF",
            "ratio": 2.15,
            "name": "blue",
        },
        "after": {"token": "text", "hex": "#000000", "ratio": 5.25, "name": "black"},
        "background": {"hex": "#FF0000", "name": "red", "inherited": False},
        "threshold": 4.5,
        "large_text": False,
        "count": 1,
    }


def test_large_text_is_held_to_the_large_text_threshold() -> None:
    styles = BAR.replace("}", ";font-size:24px}")
    [correction] = repaired(styles, BLUE_ON_RED)[2]
    assert (correction.threshold, correction.large_text) == (3.0, True)
    assert correction.before_ratio < 3.0 <= correction.after_ratio


def test_a_text_without_its_own_background_is_measured_against_the_inherited_ones() -> None:
    [correction] = repaired(".ghost{color:var(--vl-color-accent)}")[2]
    muted = LIGHT_TOKENS["--vl-color-text-muted"]
    surface = LIGHT_TOKENS["--vl-color-surface"]
    assert correction.inherited_background is True
    assert correction.background_hex == surface.upper()
    assert correction.after_token == "text-muted"
    assert correction.after_ratio == contrast_ratio(muted, surface)
    assert correction.before_ratio == contrast_ratio(LIGHT_TOKENS["--vl-color-accent"], surface)
    assert correction.before_ratio < correction.threshold <= correction.after_ratio


def test_a_weak_border_of_a_control_is_replaced_and_declared() -> None:
    styles, notes, corrections = repaired(WEAK_BORDER)
    assert styles == "input{border:1px solid var(--vl-color-text-muted)}"
    border = LIGHT_TOKENS["--vl-color-border"]
    muted = LIGHT_TOKENS["--vl-color-text-muted"]
    surface = LIGHT_TOKENS["--vl-color-surface"]
    [correction] = corrections
    assert (correction.code, correction.property) == (CONTROL_BORDER_REPLACED, "border-color")
    assert (correction.before_value, correction.before_hex) == (
        "var(--vl-color-border)",
        border.upper(),
    )
    assert correction.background_hex == surface.upper()
    assert correction.before_ratio == contrast_ratio(border, surface) < 3.0
    assert correction.after_ratio == contrast_ratio(muted, surface) >= 3.0
    assert (correction.threshold, correction.large_text) == (3.0, False)
    assert correction.inherited_background is False
    assert [note.code for note in notes] == [CONTROL_BORDER_REPLACED]


def test_identical_corrections_are_counted_once_in_the_order_of_the_notes() -> None:
    rule = ".x{color:var(--vl-color-border);background:var(--vl-color-surface)}"
    styles = WEAK_BORDER + rule + "@media (max-width:600px){" + rule + "}"
    _styles, notes, corrections = repaired(styles)
    assert [(item.code, item.count) for item in corrections] == [
        (CONTROL_BORDER_REPLACED, 1),
        (TEXT_COLOUR_REPLACED, 2),
    ]
    assert [(note.code, note.count) for note in notes] == [
        (item.code, item.count) for item in corrections
    ]
    assert corrections[1].to_snapshot()["count"] == 2


@pytest.mark.parametrize(
    "styles",
    [
        "main{color:var(--vl-color-text)}.a{color:var(--vl-color-text-muted)}",
        "@keyframes fade{from{color:var(--vl-color-primary-soft)}}",
        "main{color:red}",
    ],
)
def test_a_sheet_without_corrections_is_returned_as_it_is(styles: str) -> None:
    result = repaired(styles)
    assert result == (styles, (), ())
    assert result[0] is styles


@pytest.mark.parametrize(
    "styles",
    [
        BAR,
        WEAK_BORDER,
        ".ghost{color:var(--vl-color-accent)}",
        ".x{color:var(--vl-color-border);background:var(--vl-color-surface)}"
        "@media (max-width:600px){.x{color:var(--vl-color-border);"
        "background:var(--vl-color-surface)}}",
        "main{color:var(--vl-color-text)}",
        "main{color:var(--vl-color-border)",
    ],
)
def test_the_repair_of_today_matches_the_one_with_corrections(styles: str) -> None:
    for tokens in (LIGHT_TOKENS, BLUE_ON_RED):
        repaired_styles, notes, _corrections = repaired(styles, tokens)
        assert repair_contrast(
            styles, tokens, text_threshold=4.5, large_text_threshold=3.0, ui_threshold=3.0
        ) == (repaired_styles, notes)


def test_the_binding_exposes_the_corrections_beside_the_warnings() -> None:
    payload = draft_payload()
    binding = bind({**payload, "css": payload["css"] + FAINT + WEAK_BORDER})
    tokens = chosen(GUIDED_ID).visual_language.token_values
    border = tokens["--vl-color-border"]
    muted = tokens["--vl-color-text-muted"]
    surface = tokens["--vl-color-surface"]
    snapshots = binding.correction_snapshots()
    assert snapshots == tuple(correction.to_snapshot() for correction in binding.corrections)
    summary = [(item["code"], item["selector"], item["property"]) for item in snapshots]
    assert summary == [
        (CONTROL_BORDER_REPLACED, "input", "border-color"),
        (TEXT_COLOUR_REPLACED, ".m-faint", "color"),
    ]
    assert [item["count"] for item in snapshots] == [1, 1]
    assert snapshots[1]["before"]["hex"] == border.upper()
    assert snapshots[1]["after"]["hex"] == muted.upper()
    assert snapshots[1]["background"]["hex"] == surface.upper()
    assert [item["code"] for item in binding.warning_snapshots()] == [
        CONTROL_BORDER_REPLACED,
        TEXT_COLOUR_REPLACED,
    ]
