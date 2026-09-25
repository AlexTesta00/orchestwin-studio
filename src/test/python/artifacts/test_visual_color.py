from __future__ import annotations

import pytest

from orchestwin.artifacts.visual_color import (
    colour_distance,
    contrast_ratio,
    format_hex,
    hex_to_oklab,
    hue_difference,
    is_hex_colour,
    oklch_to_hex,
    parse_hex,
    relative_luminance,
)


def test_contrast_ratio_matches_the_wcag_reference_values():
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#777777", "#ffffff") == pytest.approx(4.48, abs=0.01)
    assert relative_luminance("#ffffff") == pytest.approx(1.0)
    assert relative_luminance("#000000") == pytest.approx(0.0)


def test_hex_parsing_round_trips_and_rejects_malformed_values():
    assert format_hex(parse_hex("#1C2B3A")) == "#1c2b3a"
    assert is_hex_colour("#1c2b3a")
    assert not is_hex_colour("#1C2B3A")
    assert not is_hex_colour("1c2b3a")
    assert not is_hex_colour(12)
    for value in ("#12345", "#12345g", "123456", "", "#1234567"):
        with pytest.raises(ValueError, match="invalid hex colour"):
            parse_hex(value)


def test_oklch_grey_axis_maps_to_neutral_colours_and_is_monotone_in_lightness():
    colours = [oklch_to_hex(level / 10, 0.0, 120.0) for level in range(11)]
    assert colours[0] == "#000000"
    assert colours[-1] == "#ffffff"
    luminances = [relative_luminance(colour) for colour in colours]
    assert luminances == sorted(luminances)
    for colour in colours:
        red, green, blue = parse_hex(colour)
        assert abs(red - green) < 0.01 and abs(green - blue) < 0.01


def test_out_of_gamut_chroma_is_reduced_to_a_valid_colour():
    colour = oklch_to_hex(0.6, 0.9, 30.0)
    assert is_hex_colour(colour)
    lightness, _, _ = hex_to_oklab(colour)
    assert lightness == pytest.approx(0.6, abs=0.03)


def test_oklab_round_trip_and_distances():
    lightness, a, b = hex_to_oklab("#ffffff")
    assert lightness == pytest.approx(1.0, abs=1e-3)
    assert abs(a) < 1e-3 and abs(b) < 1e-3
    assert colour_distance("#ffffff", "#ffffff") == 0.0
    assert colour_distance("#000000", "#ffffff") == pytest.approx(1.0, abs=1e-3)
    assert colour_distance("#ff0000", "#00ff00") > colour_distance("#ff0000", "#ff2200")


def test_hue_difference_wraps_around_the_circle():
    assert hue_difference(10, 350) == 20
    assert hue_difference(350, 10) == 20
    assert hue_difference(0, 180) == 180
    assert hue_difference(725, 5) == 0
