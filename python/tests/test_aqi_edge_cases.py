"""Units, invalid values and breakpoint boundaries of the NAQI and US AQI."""

from __future__ import annotations

import logging
import math

import pandas as pd
import pytest

from vayuayan.aqi import (
    POLLUTANTS,
    compute_aqi,
    daily_aqi,
    pollutant_category,
    pollutant_name,
    sub_index,
)
from vayuayan.aqi_units import unit_factor
from vayuayan.tidy import split_label
from vayuayan.us_aqi import (
    US_POLLUTANTS,
    compute_us_aqi,
    us_aqi_category,
    us_aqi_color,
    us_pollutant_name,
    us_sub_index,
)
from vayuayan.utils import get_aqi_categories, get_aqi_category


def _long(hours, values):
    """24-style hourly rows: {label: value} for each of the given hours."""
    stamps = pd.date_range("2024-01-01", periods=hours, freq="h")
    return pd.DataFrame(
        {
            "timestamp": list(stamps) * len(values),
            "pollutant": [label for label in values for _ in range(hours)],
            "value": [v for v in values.values() for _ in range(hours)],
        }
    )


# --- Units in the label ---


@pytest.mark.parametrize(
    "label,value",
    [("CO (µg/m³)", 1000.0), ("CO (ug/m3)", 1000.0), ("PM2.5 (mg/m³)", 0.030)],
)
def test_naqi_sub_index_converts_a_mass_unit_in_the_label(label, value):
    assert sub_index(label, value) == pytest.approx(50.0)


def test_naqi_compute_aqi_converts_a_mass_unit_in_the_label():
    res = compute_aqi(
        {"PM2.5 (µg/m³)": 30.0, "PM10 (µg/m³)": 50.0, "CO (µg/m³)": 1000.0}
    )
    assert res.aqi == 50
    assert res.category == "Good"
    assert res.sub_indices["CO"] == pytest.approx(50.0)


def test_daily_aqi_converts_the_label_unit_without_a_unit_column():
    long = _long(
        24, {"PM2.5 (µg/m³)": 30.0, "PM10 (µg/m³)": 50.0, "CO (µg/m³)": 1000.0}
    )
    out = daily_aqi(long)
    assert out.loc[0, "CO_sub_index"] == pytest.approx(50.0)
    assert out.loc[0, "aqi"] == 50


def test_daily_aqi_prefers_a_non_empty_unit_column_over_the_label():
    long = _long(24, {"PM2.5": 30.0, "PM10": 50.0, "CO": 1.0}).assign(unit="mg/m³")
    long.loc[long["pollutant"] != "CO", "unit"] = ""
    out = daily_aqi(long)
    assert out.loc[0, "CO_sub_index"] == pytest.approx(50.0)
    assert out.loc[0, "PM2.5_sub_index"] == pytest.approx(50.0)


def test_naqi_gas_in_ppb_or_ppm_is_missing_with_one_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert math.isnan(sub_index("NO2 (ppb)", 20.0))
        assert math.isnan(sub_index("CO (ppm)", 1.0))
    assert len(caplog.records) == 2
    caplog.clear()

    with caplog.at_level(logging.WARNING):
        res = compute_aqi(
            {"PM2.5": 30.0, "PM10": 50.0, "NO2 (ppb)": 20.0, "CO (ppm)": 1.0}
        )
    assert res.aqi is None
    assert set(res.sub_indices) == {"PM2.5", "PM10"}
    assert len(caplog.records) == 1
    assert "NO2 (ppb)" in caplog.records[0].getMessage()
    assert "CO (ppm)" in caplog.records[0].getMessage()


def test_daily_aqi_drops_gas_in_ppb_with_one_warning(caplog):
    long = _long(24, {"PM2.5": 30.0, "PM10": 50.0, "NO2": 20.0, "SO2": 20.0, "CO": 1.0})
    long["unit"] = long["pollutant"].map(
        {"PM2.5": "µg/m³", "PM10": "µg/m³", "NO2": "ppb", "SO2": "ppb", "CO": "ppm"}
    )
    with caplog.at_level(logging.WARNING):
        out = daily_aqi(long)
    assert len(caplog.records) == 1
    assert "NO2_sub_index" not in out.columns
    assert pd.isna(out.loc[0, "aqi"])


def test_unit_factor_is_nan_when_it_cannot_convert():
    assert math.isnan(unit_factor("ppb", "µg/m³"))
    assert math.isnan(unit_factor("µg/m³", "ppb"))
    assert unit_factor("µg/m³", "ppb", 46.01) == pytest.approx(24.45 / 46.01)


def test_us_aqi_of_a_mass_pollutant_in_ppb_is_missing():
    assert math.isnan(us_sub_index("PM2.5 (ppb)", 20.0))
    assert math.isnan(us_sub_index("PM10 (ppm)", 20.0))
    result = compute_us_aqi({"PM2.5 (ppb)": 20.0, "NO2": 40.0})
    assert list(result.sub_indices) == ["NO2"]


def test_us_aqi_converts_ppb_and_ppm_to_the_unit_of_the_table():
    assert us_sub_index("O3 (ppb)", 54.0) == pytest.approx(50.0)
    assert us_sub_index("O3_1h (ppb)", 164.0) == pytest.approx(150.0)
    assert us_sub_index("SO2 (ppm)", 0.035) == pytest.approx(50.0)
    assert us_sub_index("NO2 (ppm)", 0.053) == pytest.approx(50.0)
    assert us_sub_index("CO (ppm)", 4.4) == pytest.approx(50.0)


def test_split_label_takes_the_last_group_as_the_unit():
    assert split_label("CO (8hr) (µg/m³)") == ("CO (8hr)", "µg/m³")
    assert pollutant_name("CO (8hr) (µg/m³)") == "CO"
    assert us_pollutant_name("PM2.5 (Fine) (µg/m³)") == "PM2.5"
    assert sub_index("CO (8hr) (µg/m³)", 1000.0) == pytest.approx(50.0)
    assert split_label("SO2") == ("SO2", "")
    assert split_label("PM2.5 (µg/m³)") == ("PM2.5", "µg/m³")


# --- Negative and infinite values ---


def test_negative_concentration_has_no_sub_index():
    assert math.isnan(sub_index("PM2.5", -10.0))
    assert math.isnan(sub_index("CO", -0.5))
    assert pollutant_category("PM2.5", -999.0) == "No Data"


def test_negative_pm_does_not_satisfy_the_pm_rule():
    res = compute_aqi({"PM2.5": -999.0, "NO2": 20.0, "SO2": 20.0})
    assert res.aqi is None
    assert not res.sufficient
    assert "PM2.5" not in res.sub_indices


def test_daily_aqi_leaves_out_negative_readings_before_the_hourly_mean():
    stamps = pd.date_range("2024-01-01", periods=24 * 4, freq="15min")
    pm = [-999.0 if i % 4 == 0 else 60.0 for i in range(96)]
    long = pd.DataFrame(
        {
            "timestamp": list(stamps) * 3,
            "pollutant": ["PM2.5"] * 96 + ["NO2"] * 96 + ["SO2"] * 96,
            "value": pm + [40.0] * 96 + [40.0] * 96,
        }
    )
    assert daily_aqi(long).loc[0, "PM2.5_sub_index"] == pytest.approx(100.0)

    all_faulty = _long(24, {"PM2.5": -999.0, "NO2": 40.0, "SO2": 40.0})
    out = daily_aqi(all_faulty)
    assert "PM2.5_sub_index" not in out.columns
    assert pd.isna(out.loc[0, "aqi"])


def test_negative_us_concentration_is_invalid_even_within_the_float_tolerance():
    assert math.isnan(us_sub_index("PM10", -5e-10))
    assert math.isnan(us_sub_index("PM2.5", -5e-11))


def test_infinite_values_are_missing():
    for infinity in (math.inf, -math.inf):
        assert math.isnan(sub_index("PM2.5", infinity))
        assert math.isnan(us_sub_index("PM2.5", infinity))
        assert compute_aqi({"PM2.5": infinity, "PM10": 50.0, "NO2": 40.0}).aqi is None
        assert compute_us_aqi({"PM2.5": infinity}).aqi is None
        assert get_aqi_category(infinity) == "No Data"
        assert us_aqi_category(infinity) == "No Data"
        assert us_aqi_color(infinity) is None
    assert get_aqi_categories([math.inf, 50, "Inf"]) == ["No Data", "Good", "No Data"]


def test_daily_aqi_treats_infinite_text_as_missing():
    long = _long(24, {"PM2.5": 30.0, "PM10": 50.0, "NO2": 40.0, "SO2": 40.0})
    long["value"] = long["value"].astype(object)
    long.loc[long["pollutant"] == "SO2", "value"] = "Inf"
    out = daily_aqi(long)
    assert "SO2_sub_index" not in out.columns
    assert out.loc[0, "aqi"] == 50


# --- SO2 crossover and ties ---


def test_so2_crossover_uses_200_unless_the_24h_value_is_at_or_above_305():
    assert compute_us_aqi({"SO2": -1.0, "SO2_24h": 10.0}).aqi is None
    assert compute_us_aqi({"SO2": 20.0, "so2_1h": -1.0, "SO2_24h": 10.0}).aqi == 29
    # AQS aqi_breakpoints.csv: 1-hour SO2 at or above 305 ppb is 200 with no 24-hour value
    assert compute_us_aqi({"SO2": 305.0, "SO2_24h": -1.0}).aqi == 200
    assert compute_us_aqi({"SO2": 305.0}).aqi == 200
    assert compute_us_aqi({"SO2": 305.0, "SO2_24h": 10.0}).aqi == 200
    assert compute_us_aqi({"SO2": 304.9, "SO2_24h": 10.0}).aqi == 200
    assert compute_us_aqi({"SO2": 350.0, "SO2_24h": 305.0}).aqi == 201


def test_us_aqi_ties_do_not_depend_on_the_order_of_the_input():
    first = compute_us_aqi({"O3": 0.054, "PM2.5": 9.0})
    second = compute_us_aqi({"PM2.5": 9.0, "O3": 0.054})
    assert first.dominant_pollutant == second.dominant_pollutant == "PM2.5"
    tie = compute_us_aqi({"SO2": 305.0, "SO2_24h": 20.0, "NO2": 649.0})
    assert tie.dominant_pollutant == "SO2"


# --- daily_aqi sufficiency ---


def test_daily_aqi_of_one_insufficient_day_has_no_aqi():
    out = daily_aqi(_long(10, {"PM2.5": 45.0, "PM10": 80.0, "NO2": 30.0}))
    assert len(out) == 1
    assert pd.isna(out.loc[0, "aqi"])
    assert pd.isna(out.loc[0, "dominant_pollutant"])
    assert pd.isna(out.loc[0, "category"])


def test_eight_hour_window_follows_a_small_min_hours():
    out = daily_aqi(_long(4, {"PM2.5": 30.0, "PM10": 50.0, "O3": 50.0}), min_hours=4)
    assert out.loc[0, "O3_sub_index"] == pytest.approx(50.0)
    assert out.loc[0, "aqi"] == 50


def test_eight_hour_window_keeps_six_hours_by_default():
    out = daily_aqi(_long(20, {"PM2.5": 30.0, "PM10": 50.0, "O3": 50.0}), min_hours=7)
    assert out.loc[0, "O3_sub_index"] == pytest.approx(50.0)


# --- Breakpoints ---

_NAQI_INDEX_BANDS = ((0, 50), (50, 100), (100, 200), (200, 300), (300, 400), (400, 500))


@pytest.mark.parametrize(
    "pollutant,c_lo,c_hi,i_lo,i_hi",
    [
        (name, c_lo, c_hi, i_lo, i_hi)
        for name, p in POLLUTANTS.items()
        for (c_lo, c_hi), (i_lo, i_hi) in zip(p.breakpoints, _NAQI_INDEX_BANDS)
    ],
)
def test_every_naqi_band_boundary_and_midpoint(pollutant, c_lo, c_hi, i_lo, i_hi):
    assert sub_index(pollutant, c_hi) == pytest.approx(float(i_hi), abs=1e-6)
    mid_c = (c_lo + c_hi) / 2.0
    assert sub_index(pollutant, mid_c) == pytest.approx((i_lo + i_hi) / 2.0, abs=1e-5)
    # the bands are continuous, so the bottom of a band is the top of the last
    assert sub_index(pollutant, c_lo) == pytest.approx(float(i_lo), abs=1e-6)


@pytest.mark.parametrize(
    "pollutant,c_lo,c_hi,i_lo,i_hi,decimals",
    [
        (name, c_lo, c_hi, i_lo, i_hi, p.decimals)
        for name, p in US_POLLUTANTS.items()
        for (c_lo, c_hi, i_lo, i_hi) in p.bands
    ],
)
def test_every_us_band_boundary_and_truncation(
    pollutant, c_lo, c_hi, i_lo, i_hi, decimals
):
    assert us_sub_index(pollutant, c_lo) == pytest.approx(float(i_lo), abs=1e-6)
    assert us_sub_index(pollutant, c_hi) == pytest.approx(float(i_hi), abs=1e-6)
    step = 10.0 ** (-decimals)
    assert us_sub_index(pollutant, c_hi + 0.4 * step) == pytest.approx(
        float(i_hi), abs=1e-6
    )


def test_aqi_rounds_half_up_at_the_boundary():
    res = compute_aqi({"PM2.5": 15.3, "PM10": 10.0, "NO2": 10.0})
    assert res.sub_indices["PM2.5"] == pytest.approx(25.5)
    assert res.aqi == 26


def test_categories_at_every_band_edge():
    assert get_aqi_categories(
        [0, 50, 51, 100, 101, 200, 201, 300, 301, 400, 401, 500, 650]
    ) == [
        "Good", "Good", "Satisfactory", "Satisfactory", "Moderate", "Moderate",
        "Poor", "Poor", "Very Poor", "Very Poor", "Severe", "Severe", "Severe",
    ]  # fmt: skip
