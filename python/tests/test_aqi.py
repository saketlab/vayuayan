"""Tests for the CPCB National AQI."""

import math

import pandas as pd
import pytest

from vayuayan.aqi import (
    compute_aqi,
    daily_aqi,
    pollutant_category,
    pollutant_name,
    sub_index,
)


@pytest.mark.parametrize(
    "pollutant, concentration, expected",
    [
        # The worked examples of CPCB, "About National Air Quality Index"
        ("PM2.5", 31, 51),
        ("PM2.5", 60, 100),
        ("PM2.5", 45, 75),
        # Band edges, the shared boundaries, and the Severe slope above 500
        ("PM10", 50, 50),
        ("PM10", 51, 51),
        ("PM10", 430, 400),
        ("PM10", 600, 611),  # 500 + 90 * 99 / 80
        ("CO", 10, 200),
        ("Pb", 0.5, 50),
        ("O3", 748, 400),
    ],
)
def test_sub_index_follows_the_cpcb_breakpoints(pollutant, concentration, expected):
    assert round(sub_index(pollutant, concentration)) == expected


def test_sub_index_of_a_missing_value_is_nan():
    assert math.isnan(sub_index("PM2.5", float("nan")))


@pytest.mark.parametrize(
    "label, name",
    [
        ("PM2.5 (µg/m³)", "PM2.5"),
        ("pm25", "PM2.5"),
        ("Ozone (µg/m³)", "O3"),
        ("CO (mg/m³)", "CO"),
        ("NO (µg/m³)", None),
        ("NOx (ppb)", None),
        ("AT (°C)", None),
    ],
)
def test_pollutant_name_matches_cpcb_labels(label, name):
    assert pollutant_name(label) == name


def test_aqi_needs_three_pollutants_with_pm():
    assert compute_aqi({"PM2.5": 45, "NO2": 30}).aqi is None
    assert compute_aqi({"NO2": 30, "SO2": 10, "CO": 1}).aqi is None

    result = compute_aqi({"PM2.5": 45, "PM10": 80, "NO2": 30, "AT": 20})
    assert (result.aqi, result.category, result.dominant_pollutant) == (
        80,
        "Satisfactory",
        "PM10",
    )
    assert set(result.sub_indices) == {"PM2.5", "PM10", "NO2"}


def _hourly(start, hours, values, unit="µg/m³"):
    times = pd.date_range(start, periods=hours, freq="h")
    return pd.DataFrame(
        [
            {
                "station_id": "s1",
                "timestamp": t,
                "pollutant": p,
                "unit": unit,
                "value": v,
            }
            for t in times
            for p, v in values.items()
        ]
    )


def test_daily_aqi_uses_daily_means_and_the_16_hour_rule():
    long = pd.concat(
        [
            _hourly("2024-01-01", 24, {"PM2.5 (µg/m³)": 45, "PM10": 80, "NO2": 30}),
            _hourly("2024-01-02", 10, {"PM2.5": 45, "PM10": 80, "NO2": 30}),
        ]
    )
    daily = daily_aqi(long)

    assert daily["aqi"].tolist()[0] == 80
    assert daily["dominant_pollutant"].tolist()[0] == "PM10"
    assert daily["aqi"].isna().tolist() == [False, True]
    assert daily["dominant_pollutant"].isna().tolist() == [False, True]


def test_daily_aqi_converts_co_and_uses_the_highest_8_hour_mean():
    base = _hourly("2024-01-01", 24, {"PM2.5": 20, "PM10": 40, "NO2": 20})
    co = _hourly("2024-01-01", 24, {"CO": 500}, unit="µg/m³")  # 0.5 mg/m3
    co.loc[co["timestamp"].dt.hour >= 16, "value"] = 15000  # 15 mg/m3 at night
    daily = daily_aqi(pd.concat([base, co]))

    assert daily.loc[0, "CO_sub_index"] == pytest.approx(sub_index("CO", 15))
    assert daily.loc[0, "dominant_pollutant"] == "CO"


def test_day_ends_at_moves_the_daily_window():
    long = _hourly("2024-01-01 16:00", 24, {"PM2.5": 45, "PM10": 80, "NO2": 30})

    # Calendar days: 8 hours (too few) on Jan 1, 16 hours on Jan 2
    assert daily_aqi(long)["aqi"].isna().tolist() == [True, False]
    bulletin = daily_aqi(long, day_ends_at=16)
    assert bulletin["date"].astype(str).tolist() == ["2024-01-02"]
    assert bulletin["aqi"].tolist() == [80]


def test_health_impact_and_pollutant_category():
    from vayuayan.aqi import health_impact, pollutant_category

    assert health_impact(250) == "Breathing discomfort to people on prolonged exposure"
    assert health_impact(float("nan")) == "No Data"
    assert pollutant_category("PM2.5", 75) == "Moderate"
    assert pollutant_category("PM2.5", 400) == "Severe"


def test_aqi_rounds_half_up_and_category_uses_the_rounded_value():
    # PM2.5 30.5 -> sub-index 50.5: half up gives 51, Satisfactory
    r = compute_aqi({"PM2.5": 30.5, "PM10": 10, "NO2": 10})
    assert (r.aqi, r.category) == (51, "Satisfactory")
    assert pollutant_category("PM2.5", 30.5) == "Satisfactory"
    assert pollutant_category("PM2.5", 30.2) == "Good"  # 50.33 -> 50


def test_compute_aqi_counts_a_repeated_pollutant_once():
    r = compute_aqi({"PM10": 80, "pm10": 120, "NO2": 30})
    assert r.aqi is None  # two pollutants, not three
    assert r.sub_indices["PM10"] == sub_index("PM10", 120)


def test_compute_aqi_tie_goes_to_the_first_pollutant_in_order():
    # PM10 100 and NO2 80 both give 100
    r = compute_aqi({"NO2": 80, "PM10": 100, "SO2": 10})
    assert r.dominant_pollutant == "PM10"


def test_compute_aqi_matches_the_cpcb_calculator_sample():
    # sample inputs of CPCB's AQI-Calculator.xls, which shows 114 from PM10
    sample = {
        "PM10": 121,
        "PM2.5": 34,
        "SO2": 0,
        "NO2": 8,
        "CO": 0,
        "O3": 57,
        "NH3": 34,
    }
    r = compute_aqi(sample)
    assert (r.aqi, r.dominant_pollutant) == (114, "PM10")
