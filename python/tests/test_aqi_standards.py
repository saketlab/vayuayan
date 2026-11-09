"""NAQI and US AQI against tables typed from the source documents.

Bands are typed here, not read from the package. Expected values come from the
documented equation, so a wrong table in the package fails.
"""

from __future__ import annotations

import math

import pytest

from vayuayan.aqi import compute_aqi, sub_index
from vayuayan.constants import AQI_CATEGORIES
from vayuayan.us_aqi import compute_us_aqi, us_aqi_category, us_sub_index
from vayuayan.utils import get_aqi_category

# (concentration low, concentration high, index low, index high), Good to Severe.
# CPCB AQI-Calculator.xls Sheet1 D8-D20 and CUPS/82/2014-15 Table 3.11 p.35 and
# p.37 (continuous). The last top of each pollutant is the Very Poor width added
# to the Very Poor top, which is the calculator's Severe slope.
INDIA_BANDS = {
    "PM10": [
        (0, 50, 0, 50), (50, 100, 50, 100), (100, 250, 100, 200),
        (250, 350, 200, 300), (350, 430, 300, 400), (430, 510, 400, 500),
    ],
    "PM2.5": [
        (0, 30, 0, 50), (30, 60, 50, 100), (60, 90, 100, 200),
        (90, 120, 200, 300), (120, 250, 300, 400), (250, 380, 400, 500),
    ],
    "NO2": [
        (0, 40, 0, 50), (40, 80, 50, 100), (80, 180, 100, 200),
        (180, 280, 200, 300), (280, 400, 300, 400), (400, 520, 400, 500),
    ],
    # Severe stays on the published 748 band: the calculator's formula is wrong
    "O3": [
        (0, 50, 0, 50), (50, 100, 50, 100), (100, 168, 100, 200),
        (168, 208, 200, 300), (208, 748, 300, 400), (748, 1288, 400, 500),
    ],
    "CO": [
        (0, 1, 0, 50), (1, 2, 50, 100), (2, 10, 100, 200),
        (10, 17, 200, 300), (17, 34, 300, 400), (34, 51, 400, 500),
    ],
    "SO2": [
        (0, 40, 0, 50), (40, 80, 50, 100), (80, 380, 100, 200),
        (380, 800, 200, 300), (800, 1600, 300, 400), (1600, 2400, 400, 500),
    ],
    "NH3": [
        (0, 200, 0, 50), (200, 400, 50, 100), (400, 800, 100, 200),
        (800, 1200, 200, 300), (1200, 1800, 300, 400), (1800, 2400, 400, 500),
    ],
    # CUPS/82 Table 3.11 p.35; the calculator has no Pb row
    "Pb": [
        (0, 0.5, 0, 50), (0.5, 1, 50, 100), (1, 2, 100, 200),
        (2, 3, 200, 300), (3, 3.5, 300, 400), (3.5, 4, 400, 500),
    ],
}  # fmt: skip

# 40 CFR 58 App G Table 2 (FR 16404-05); EPA TAD EPA-403/B-26-003 Table 6 p.14
US_BANDS = {
    "PM2.5": (1, [
        (0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
        (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500),
    ]),
    "PM10": (0, [
        (0, 54, 0, 50), (55, 154, 51, 100), (155, 254, 101, 150),
        (255, 354, 151, 200), (355, 424, 201, 300), (425, 604, 301, 500),
    ]),
    "O3": (3, [
        (0.000, 0.054, 0, 50), (0.055, 0.070, 51, 100), (0.071, 0.085, 101, 150),
        (0.086, 0.105, 151, 200), (0.106, 0.200, 201, 300),
    ]),
    "O3_1h": (3, [
        (0.125, 0.164, 101, 150), (0.165, 0.204, 151, 200),
        (0.205, 0.404, 201, 300), (0.405, 0.604, 301, 500),
    ]),
    "CO": (1, [
        (0.0, 4.4, 0, 50), (4.5, 9.4, 51, 100), (9.5, 12.4, 101, 150),
        (12.5, 15.4, 151, 200), (15.5, 30.4, 201, 300), (30.5, 50.4, 301, 500),
    ]),
    "SO2": (0, [
        (0, 35, 0, 50), (36, 75, 51, 100), (76, 185, 101, 150), (186, 304, 151, 200),
    ]),
    "SO2_24h": (0, [(305, 604, 201, 300), (605, 1004, 301, 500)]),
    "NO2": (0, [
        (0, 53, 0, 50), (54, 100, 51, 100), (101, 360, 101, 150),
        (361, 649, 151, 200), (650, 1249, 201, 300), (1250, 2049, 301, 500),
    ]),
}  # fmt: skip

INDIA_CATEGORIES = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
US_CATEGORIES = [
    "Good",
    "Moderate",
    "Unhealthy for Sensitive Groups",
    "Unhealthy",
    "Very Unhealthy",
    "Hazardous",
]


def equation(c, c_lo, c_hi, i_lo, i_hi):
    """I = (IHI - ILO) / (BHI - BLO) * (C - BLO) + ILO (CUPS/82 p.37; TAD p.13)."""
    return (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo


INDIA_CASES = [(name, band) for name, bands in INDIA_BANDS.items() for band in bands]
US_CASES = [
    (name, decimals, band)
    for name, (decimals, bands) in US_BANDS.items()
    for band in bands
]


@pytest.mark.parametrize("name, band", INDIA_CASES)
def test_india_bottom_top_and_middle_of_every_band(name, band):
    c_lo, c_hi, i_lo, i_hi = band
    assert sub_index(name, c_lo) == pytest.approx(i_lo)
    assert sub_index(name, c_hi) == pytest.approx(i_hi)
    middle = (c_lo + c_hi) / 2
    assert sub_index(name, middle) == pytest.approx(equation(middle, *band))


@pytest.mark.parametrize("name, decimals, band", US_CASES)
def test_us_bottom_top_and_middle_of_every_band(name, decimals, band):
    c_lo, c_hi, i_lo, i_hi = band
    assert us_sub_index(name, c_lo) == pytest.approx(i_lo)
    assert us_sub_index(name, c_hi) == pytest.approx(i_hi)
    # the middle truncated to the table's precision, as TAD p.13 does first
    scale = 10**decimals
    middle = math.floor((c_lo + c_hi) / 2 * scale + 1e-9) / scale
    assert us_sub_index(name, middle) == pytest.approx(equation(middle, *band))


@pytest.mark.parametrize(
    "name, c, expected",
    [
        # Values of CPCB AQI-Calculator.xls, computed from its cell formulas
        ("PM2.5", 31, 50 + 1 * 50 / 30),
        ("PM2.5", 34, 50 + 4 * 50 / 30),
        ("PM2.5", 45, 75.0),
        ("PM2.5", 60, 100.0),
        ("PM2.5", 60.4, 100 + 0.4 * 100 / 30),
        ("PM2.5", 61, 100 + 1 * 100 / 30),
        ("PM2.5", 300, 400 + 50 * 100 / 130),
        ("PM10", 121, 100 + 21 * 100 / 150),
        ("PM10", 700, 400 + 270 * 100 / 80),
        ("CO", 1.1, 50 + 0.1 * 50 / 1),
        ("O3", 169, 200 + 1 * 100 / 40),
    ],
)
def test_india_matches_the_cpcb_calculator(name, c, expected):
    assert sub_index(name, c) == pytest.approx(expected)


def test_o3_above_748_keeps_the_published_band_and_is_not_the_calculator():
    # the calculator would give 400 + (749 - 400) * 100 / 539 = 464.75
    assert sub_index("O3", 749) == pytest.approx(400 + 1 * 100 / 540)
    assert sub_index("O3", 748) == pytest.approx(400.0)


def test_o3_above_208_stays_on_the_8_hour_value():
    assert sub_index("O3", 300) == pytest.approx(300 + 92 * 100 / 540)


def test_india_is_not_capped_at_500():
    assert sub_index("PM2.5", 1000) == pytest.approx(400 + 750 * 100 / 130)
    r = compute_aqi({"PM2.5": 1000, "PM10": 50, "NO2": 40})
    assert r.aqi == math.floor(400 + 750 * 100 / 130 + 0.5)
    assert r.category == "Severe"


def test_india_has_no_gaps_between_bands():
    # 30.5 is in the former gap between 30 and 31
    assert sub_index("PM2.5", 30.5) == pytest.approx(50 + 0.5 * 50 / 30)
    assert sub_index("PM10", 100.5) == pytest.approx(100 + 0.5 * 100 / 150)


# PM2.5, PM10, NO2 in µg/m³; expected AQI and category hand-computed below
SAME_AIR = [
    pytest.param(
        25, 45, 30,
        # India: PM2.5 25*50/30=41.67, PM10 45, NO2 37.5 -> 45 from PM10
        45, "Good", "PM10",
        # US: 49/26.3*15.9+51 = 80.62 -> 81
        81, "Moderate", "PM2.5", id="low",
    ),
    pytest.param(
        75, 150, 90,
        # India: PM2.5 100+15*100/30 = 150; PM10 133.33; NO2 110
        150, "Moderate", "PM2.5",
        # US: 49/69.9*19.5+151 = 164.67 -> 165
        165, "Unhealthy", "PM2.5", id="moderate",
    ),
    pytest.param(
        400, 700, 500,
        # India: PM10 400+270*100/80 = 737.5, half up 738; PM2.5 515.38; NO2 483.33
        738, "Severe", "PM10",
        # US: PM2.5 199/99.9*174.5+301 = 648.6 -> 649; PM10 606.73
        649, "Hazardous", "PM2.5", id="extreme",
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    "pm25, pm10, no2, india, india_cat, india_main, us, us_cat, us_main", SAME_AIR
)
def test_same_air_in_both_standards(
    pm25, pm10, no2, india, india_cat, india_main, us, us_cat, us_main
):
    naqi = compute_aqi({"PM2.5": pm25, "PM10": pm10, "NO2": no2})
    assert (naqi.aqi, naqi.category, naqi.dominant_pollutant) == (
        india, india_cat, india_main,
    )  # fmt: skip
    usaqi = compute_us_aqi({"PM2.5": pm25, "PM10": pm10})
    assert (usaqi.aqi, usaqi.category, usaqi.dominant_pollutant) == (
        us, us_cat, us_main,
    )  # fmt: skip
    assert naqi.category != usaqi.category


def test_category_sets_are_exactly_the_published_ones():
    assert list(AQI_CATEGORIES) == INDIA_CATEGORIES
    india = {get_aqi_category(v) for v in range(0, 1000)}
    assert india == set(INDIA_CATEGORIES)
    us = {us_aqi_category(v) for v in range(0, 1000)}
    assert us == set(US_CATEGORIES)
