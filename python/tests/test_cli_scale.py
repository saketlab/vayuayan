"""The official colours and category names of both AQI standards, pinned."""

from __future__ import annotations

import pytest

from vayuayan.cli_scale import INDIA, SCALES, US, contrast, luminance, readable_text

INDIA_COLOURS = {
    "Good": "#00B050",
    "Satisfactory": "#92D050",
    "Moderate": "#FFFF00",
    "Poor": "#FF9900",
    "Very Poor": "#FF0000",
    "Severe": "#C00000",
}
US_COLOURS = {
    "Good": "#00E400",
    "Moderate": "#FFFF00",
    "Unhealthy for Sensitive Groups": "#FF7E00",
    "Unhealthy": "#FF0000",
    "Very Unhealthy": "#8F3F97",
    "Hazardous": "#7E0023",
}


def test_india_colours_and_names_are_pinned():
    assert INDIA.colors == INDIA_COLOURS
    assert list(INDIA.colors) == list(INDIA_COLOURS)


def test_us_colours_and_names_are_pinned():
    assert US.colors == US_COLOURS
    assert list(US.colors) == list(US_COLOURS)


def test_scales_are_found_by_their_key():
    assert SCALES == {"india": INDIA, "us": US}
    assert INDIA.label != US.label


@pytest.mark.parametrize(
    "value,india,us",
    [
        (50, "Good", "Good"),
        (100, "Satisfactory", "Moderate"),
        (150, "Moderate", "Unhealthy for Sensitive Groups"),
        (200, "Moderate", "Unhealthy"),
        (300, "Poor", "Very Unhealthy"),
        (400, "Very Poor", "Hazardous"),
        (450, "Severe", "Hazardous"),
    ],
)
def test_each_standard_has_its_own_categories(value, india, us):
    assert INDIA.category(value) == india
    assert US.category(value) == us


def test_ranges_and_bands():
    assert INDIA.ranges["Severe"] == "401-500"
    assert US.ranges["Hazardous"] == "301+"
    assert US.ranges["Unhealthy for Sensitive Groups"] == "101-150"
    assert [INDIA.band(name) for name in INDIA.colors] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize(
    "background,text",
    [
        ("#00B050", "#000000"),
        ("#92D050", "#000000"),
        ("#FFFF00", "#000000"),
        ("#FF9900", "#000000"),
        ("#FF0000", "#000000"),
        ("#C00000", "#FFFFFF"),
        ("#00E400", "#000000"),
        ("#FF7E00", "#000000"),
        ("#8F3F97", "#FFFFFF"),
        ("#7E0023", "#FFFFFF"),
    ],
)
def test_text_is_black_or_white_by_contrast(background, text):
    assert readable_text(background) == text
    other = "#FFFFFF" if text == "#000000" else "#000000"
    assert contrast(background, text) >= contrast(background, other)


@pytest.mark.parametrize("scale", [INDIA, US])
def test_every_cell_is_readable(scale):
    for name in scale.colors:
        assert contrast(scale.color(name), readable_text(scale.color(name))) >= 4.5


def test_luminance_ends():
    assert luminance("#000000") == 0
    assert luminance("#FFFFFF") == pytest.approx(1)


def test_style_and_legend_use_the_exact_colour():
    assert INDIA.style("Poor") == "#000000 on #FF9900"
    assert US.legend()[-1] == (6, "Hazardous", "301+", "#FFFFFF on #7E0023")
