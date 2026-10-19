"""US EPA AQI against values computed by hand from the May 2024 EPA tables."""

import math

import pytest

from vayuayan import (
    compute_us_aqi,
    us_aqi_category,
    us_aqi_color,
    us_pollutant_name,
    us_sub_index,
)


@pytest.mark.parametrize(
    "pollutant, concentration, expected",
    [
        ("PM2.5", 9.0, 50.0),
        ("PM2.5", 9.05, 50.0),  # truncated to 9.0
        ("PM2.5", 9.1, 51.0),
        ("PM2.5", 12.0, 49 / 26.3 * 2.9 + 51),
        ("PM2.5", 35.4, 100.0),
        ("PM2.5", 400, 199 / 99.9 * 174.5 + 301),  # above the table: same slope
        ("PM10", 155, 101.0),
        ("O3", 0.078, 125.5),
        ("O3_1h", 0.21, 99 / 0.199 * 0.005 + 201),
        ("SO2_24h", 400, 99 / 299 * 95 + 201),
        ("CO", 600, 199 / 19.9 * 569.5 + 301),
        ("NO2", 3000, 199 / 799 * 1750 + 301),
        ("O3_1h", 0.7, 199 / 0.199 * 0.295 + 301),
        # mass units are converted at 25 °C: 100 µg/m³ O3 = 0.0509 ppm -> 0.050
        ("O3 (µg/m³)", 100, 50 / 0.054 * 0.050),
        ("NO2 (µg/m³)", 100, 50.0),  # 53.1 ppb -> 53
        ("CO (mg/m³)", 5, 50 / 4.4 * 4.3),  # 4.37 ppm -> 4.3
    ],
)
def test_us_sub_index(pollutant, concentration, expected):
    assert us_sub_index(pollutant, concentration) == pytest.approx(expected)


@pytest.mark.parametrize(
    "pollutant, concentration",
    [
        ("O3", 0.21),  # 8-hour O3 above 0.200 ppm: the EPA uses 1-hour O3
        ("O3_1h", 0.1),  # 1-hour O3 below 0.125 ppm: the EPA uses 8-hour O3
        ("SO2", 400),  # 1-hour SO2 above 304 ppb: the EPA uses 24-hour SO2
        ("SO2_24h", 300),
        ("PM2.5", math.nan),
    ],
)
def test_us_sub_index_outside_table_is_nan(pollutant, concentration):
    assert math.isnan(us_sub_index(pollutant, concentration))


def test_us_sub_index_rejects_unknown_pollutant():
    with pytest.raises(ValueError, match="not a US AQI pollutant"):
        us_sub_index("NH3", 10)


def test_compute_us_aqi():
    r = compute_us_aqi({"PM2.5": 35.4, "O3": 0.060, "Benzene": 3, "NO2": None})
    assert (r.aqi, r.category, r.dominant_pollutant) == (100, "Moderate", "PM2.5")
    assert set(r.sub_indices) == {"PM2.5", "O3"}


def test_compute_us_aqi_rounds_half_up():
    assert compute_us_aqi({"O3": 0.078}).aqi == 126


def test_compute_us_aqi_takes_higher_of_two_averaging_times():
    r = compute_us_aqi({"O3": 0.21, "O3_1h": 0.21})
    assert (r.aqi, r.dominant_pollutant) == (203, "O3_1h")


def test_compute_us_aqi_so2_crossover_is_200():
    # EPA-454/B-24-002: 1-hour SO2 >= 305 ppb but 24-hour SO2 < 305 ppb
    r = compute_us_aqi({"SO2": 305, "SO2_24h": 304})
    assert (r.aqi, r.dominant_pollutant) == (200, "SO2")


def test_compute_us_aqi_above_500_is_hazardous():
    r = compute_us_aqi({"PM2.5": 400})
    assert (r.aqi, r.category) == (649, "Hazardous")


def test_compute_us_aqi_without_values():
    assert compute_us_aqi({"Benzene": 3}).aqi is None


@pytest.mark.parametrize(
    "value, category",
    [
        (50, "Good"),
        (51, "Moderate"),
        (150, "Unhealthy for Sensitive Groups"),
        (200, "Unhealthy"),
        (300, "Very Unhealthy"),
        (301, "Hazardous"),
        (650, "Hazardous"),
        (math.nan, "No Data"),
    ],
)
def test_us_aqi_category(value, category):
    assert us_aqi_category(value) == category


def test_us_pollutant_name():
    assert us_pollutant_name("PM2.5 (µg/m³)") == "PM2.5"
    assert us_pollutant_name("Ozone") == "O3"
    assert us_pollutant_name("SO2 24h") == "SO2_24h"
    assert us_pollutant_name("NH3") is None


def test_us_aqi_color():
    # EPA Tables 2 and 3: Orange is RGB 255 126 0, assist Orange 255 130 5
    assert us_aqi_color(120) == "#FF7E00"
    assert us_aqi_color(120, color_vision_assist=True) == "#FF8205"
    assert us_aqi_color(650) == "#7E0023"
    assert us_aqi_color(None) is None
