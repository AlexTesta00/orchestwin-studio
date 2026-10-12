from __future__ import annotations

import pytest

from orchestwin.artifacts.colour_names import (
    COLOUR_NAME_KEYS,
    NAMED_COLOURS,
    colour_name_key,
    named_colours_in,
)
from orchestwin.artifacts.visual_color import contrast_ratio


def test_the_keys_are_the_neutral_keys_of_the_contract() -> None:
    assert COLOUR_NAME_KEYS == (
        "red",
        "orange",
        "yellow",
        "green",
        "teal",
        "blue",
        "purple",
        "pink",
        "brown",
        "grey",
        "black",
        "white",
    )
    assert NAMED_COLOURS["blue"].hex == "#0000FF"
    assert NAMED_COLOURS["red"].hex == "#FF0000"


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("#FF3B30", "red"),
        ("#0A84FF", "blue"),
        ("#FFFFFF", "white"),
        ("#000000", "black"),
        ("#8E8E93", "grey"),
        ("#34C759", "green"),
        ("#FF9500", "orange"),
        ("#AF52DE", "purple"),
        ("#FF2D55", "pink"),
        ("#5AC8FA", "blue"),
        ("#A2845E", "brown"),
        ("#FFCC00", "yellow"),
        ("#00C3D0", "teal"),
        ("#0088FF", "blue"),
        ("#CB30E0", "purple"),
    ],
)
def test_well_known_colours_take_their_name(value: str, key: str) -> None:
    assert colour_name_key(value) == key


@pytest.mark.parametrize(
    ("value", "key"),
    [
        ("#D5F5DA", "green"),
        ("#FFFFE0", "yellow"),
        ("#FFE4E0", "pink"),
        ("#FFEDD5", "orange"),
        ("#DBEAFE", "blue"),
        ("#476E4F", "green"),
        ("#8B0000", "red"),
        ("#795548", "brown"),
        ("#D2B48C", "brown"),
        ("#1C1C1E", "black"),
        ("#F2F2F7", "grey"),
        ("#FAFAFA", "white"),
        ("#E2EDF8", "grey"),
    ],
)
def test_pale_dark_and_neutral_colours_keep_the_name_of_their_hue(value: str, key: str) -> None:
    assert colour_name_key(value) == key


def test_every_word_colour_is_named_by_its_own_key() -> None:
    assert {key: colour_name_key(entry.hex) for key, entry in NAMED_COLOURS.items()} == {
        key: key for key in COLOUR_NAME_KEYS
    }


def test_short_and_long_spellings_give_the_same_name() -> None:
    assert colour_name_key("#f00") == colour_name_key("#FF0000") == "red"
    assert colour_name_key("#0a84ff") == colour_name_key("#0A84FF")


@pytest.mark.parametrize("value", ["blue", "#12345", "#GGGGGG", "", "#0000FF00", "0000FF"])
def test_a_value_that_is_not_a_hex_colour_is_refused(value: str) -> None:
    with pytest.raises(ValueError, match="hex colour"):
        colour_name_key(value)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("barra rossa con il testo blu", (("rossa", "#FF0000"), ("blu", "#0000FF"))),
        (
            "make the background red and the text #0000ff",
            (("red", "#FF0000"), ("#0000ff", "#0000FF")),
        ),
        (
            "Pulsanti VERDI su sfondo #fff e testo Light  Blue",
            (("VERDI", "#008000"), ("#fff", "#FFFFFF"), ("Light  Blue", "#0000FF")),
        ),
        ("testo azzurro, poi blu e ancora #00f", (("azzurro", "#0000FF"),)),
        ("grigio, gray e grey", (("grigio", "#808080"),)),
        (
            "la rosa e il viola, il marrone e l'arancio",
            (
                ("rosa", "#FFC0CB"),
                ("viola", "#800080"),
                ("marrone", "#8B4513"),
                ("arancio", "#FFA500"),
            ),
        ),
    ],
)
def test_colours_named_in_a_request_are_found_in_order_once(
    text: str, expected: tuple[tuple[str, str], ...]
) -> None:
    assert named_colours_in(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "rendi il pulsante più grande e sposta il titolo in alto",
        "bluastro, rossiccio, verdeggiante e #abcd non sono colori del contratto",
        "",
    ],
)
def test_a_request_without_colours_names_none(text: str) -> None:
    assert named_colours_in(text) == ()


def test_the_colours_of_a_request_can_be_measured_against_each_other() -> None:
    [(_red, red), (_blue, blue)] = named_colours_in("barra rossa con il testo blu")
    assert round(contrast_ratio(blue, red), 1) == 2.1
