"""Daily US AQI from raw readings, and the standard option of the station helper."""

from __future__ import annotations

import logging
import math

import pandas as pd
import pytest

from vayuayan import CPCBHistorical, daily_us_aqi
from vayuayan.us_aqi import compute_us_aqi


def equation(c, c_lo, c_hi, i_lo, i_hi):
    return (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo


def _long(values, start="2024-01-01", station="s1", unit=None):
    """{label: [hourly values]}, one row per value; None leaves the hour out."""
    rows = []
    for label, series in values.items():
        for hour, value in enumerate(series):
            if value is None:
                continue
            rows.append(
                {
                    "station_id": station,
                    "timestamp": pd.Timestamp(start) + pd.Timedelta(hours=hour),
                    "pollutant": label,
                    "value": value,
                }
            )
    frame = pd.DataFrame(rows)
    return frame if unit is None else frame.assign(unit=unit)


def test_pm_uses_the_24_hour_mean_and_18_hours():
    long = _long({"PM2.5": [20.0] * 18})
    out = daily_us_aqi(long)
    assert out.loc[0, "PM2.5_sub_index"] == pytest.approx(
        equation(20.0, 9.1, 35.4, 51, 100)
    )
    assert out.loc[0, "aqi"] == 71
    assert out.loc[0, "category"] == "Moderate"
    assert out.loc[0, "dominant_pollutant"] == "PM2.5"
    assert out.loc[0, "n_pollutants"] == 1

    short = daily_us_aqi(_long({"PM2.5": [20.0] * 17}))
    assert pd.isna(short.loc[0, "aqi"]) and pd.isna(short.loc[0, "category"])
    assert pd.isna(short.loc[0, "dominant_pollutant"])
    assert short.loc[0, "n_pollutants"] == 0


def test_min_hours_adjusts_the_18():
    long = _long({"PM2.5": [20.0] * 10})
    assert daily_us_aqi(long, min_hours=10).loc[0, "aqi"] == 71
    assert pd.isna(daily_us_aqi(long, min_hours=11).loc[0, "aqi"])


def test_fifteen_minute_readings_become_hourly_means_first():
    stamps = pd.date_range("2024-01-01", periods=24 * 4, freq="15min")
    long = pd.DataFrame(
        {
            "station_id": "s1",
            "timestamp": stamps,
            "pollutant": "PM2.5 (µg/m³)",
            # negatives are left out before the hourly mean, as in daily_aqi
            "value": [-999.0 if i % 4 == 0 else 20.0 for i in range(96)],
        }
    )
    assert daily_us_aqi(long).loc[0, "PM2.5_sub_index"] == pytest.approx(
        equation(20.0, 9.1, 35.4, 51, 100)
    )


def test_eight_hour_o3_converts_and_uses_the_highest_window():
    # 100 µg/m³ = 100 * 24.45 / 48 / 1000 = 0.0509 ppm, truncated to 0.050
    series = [20.0] * 8 + [100.0] * 8 + [20.0] * 8
    out = daily_us_aqi(_long({"O3": series}, unit="µg/m³"))
    assert out.loc[0, "O3_sub_index"] == pytest.approx(
        equation(0.050, 0.0, 0.054, 0, 50)
    )


@pytest.mark.parametrize("first_hour, has_value", [(1, True), (2, False)])
def test_eight_hour_day_needs_18_of_24_windows(first_hour, has_value):
    # the 18th window from the end needs hours 1-6 (6 hours); from hour 2, only 17
    series = [None] * first_hour + [1.0] * (24 - first_hour)
    out = daily_us_aqi(_long({"CO": series}))
    assert pd.notna(out.loc[0, "CO_sub_index"]) == has_value


def test_eight_hour_window_needs_six_hours():
    # hours 0-4 and 8-23: only the windows ending at hours 13-23 hold 6 hours
    series = [1.0] * 5 + [None] * 3 + [1.0] * 16
    long = _long({"CO": series})
    assert pd.isna(daily_us_aqi(long).loc[0, "CO_sub_index"])
    assert pd.notna(daily_us_aqi(long, min_hours=11).loc[0, "CO_sub_index"])
    assert pd.isna(daily_us_aqi(long, min_hours=12).loc[0, "CO_sub_index"])


def test_a_missing_hour_still_ends_a_window():
    # hours 5-11 are high, 12 is missing, the rest are low: only the window
    # ending at 12 has nothing but high values
    series = [0.1] * 5 + [8.0] * 7 + [None] + [0.1] * 11
    out = daily_us_aqi(_long({"CO": series}))
    assert out.loc[0, "CO_sub_index"] == pytest.approx(equation(8.0, 4.5, 9.4, 51, 100))


def test_no2_uses_the_highest_hour_and_needs_18_hours():
    long = _long({"NO2": [40.0] * 20 + [120.0] + [40.0] * 3}, unit="ppb")
    out = daily_us_aqi(long)
    assert out.loc[0, "NO2_sub_index"] == pytest.approx(
        equation(120.0, 101, 360, 101, 150)
    )
    assert pd.isna(daily_us_aqi(_long({"NO2": [120.0] * 17})).loc[0, "aqi"])


def test_so2_below_305_uses_the_1_hour_table():
    out = daily_us_aqi(_long({"SO2": [50.0] * 23 + [100.0]}, unit="ppb"))
    assert out.loc[0, "SO2_sub_index"] == pytest.approx(
        equation(100.0, 76, 185, 101, 150)
    )


def test_so2_above_304_with_a_low_24_hour_mean_is_200():
    out = daily_us_aqi(_long({"SO2": [10.0] * 23 + [400.0]}, unit="ppb"))
    assert out.loc[0, "SO2_sub_index"] == pytest.approx(200.0)
    assert out.loc[0, "dominant_pollutant"] == "SO2"


def test_so2_24_hour_mean_decides_the_upper_bands():
    out = daily_us_aqi(_long({"SO2": [400.0] * 24}, unit="ppb"))
    assert out.loc[0, "SO2_sub_index"] == pytest.approx(
        equation(400.0, 305, 604, 201, 300)
    )
    assert out.loc[0, "dominant_pollutant"] == "SO2"


def test_the_aqi_needs_no_minimum_number_of_pollutants():
    out = daily_us_aqi(_long({"PM10": [100.0] * 24}))
    # 49 / 99 * 45 + 51 = 73.27
    assert out.loc[0, "aqi"] == 73
    assert out.columns[-1] == "PM10_sub_index"


def test_pollutants_are_converted_and_reported_in_table_order():
    long = pd.concat(
        [
            _long({"NO2": [100.0] * 24}, unit="ppb"),
            _long({"PM2.5": [12.0] * 24}, unit="µg/m³"),
            _long({"CO": [1000.0] * 24}, unit="µg/m³"),
            _long({"NH3": [50.0] * 24}, unit="µg/m³"),
        ]
    )
    out = daily_us_aqi(long)
    assert [c for c in out.columns if c.endswith("_sub_index")] == [
        "PM2.5_sub_index",
        "CO_sub_index",
        "NO2_sub_index",
    ]
    # 1 mg/m³ CO = 1 * 24.45 / 28.01 = 0.873 ppm, truncated to 0.8
    assert out.loc[0, "CO_sub_index"] == pytest.approx(equation(0.8, 0.0, 4.4, 0, 50))


def test_a_blank_unit_means_the_unit_of_the_us_table():
    out = daily_us_aqi(_long({"O3": [0.060] * 24}, unit=""))
    assert out.loc[0, "O3_sub_index"] == pytest.approx(
        equation(0.060, 0.055, 0.070, 51, 100)
    )


def test_day_ends_at_moves_the_window():
    long = _long({"PM2.5": [20.0] * 24}, start="2024-01-01 16:00")
    # calendar days hold 8 and 16 hours, both below 18
    assert daily_us_aqi(long)["aqi"].isna().tolist() == [True, True]
    bulletin = daily_us_aqi(long, day_ends_at=16)
    assert bulletin["date"].astype(str).tolist() == ["2024-01-02"]
    assert bulletin["aqi"].tolist() == [71]


def test_day_ends_at_must_be_an_hour():
    with pytest.raises(ValueError, match="day_ends_at"):
        daily_us_aqi(_long({"PM2.5": [20.0] * 24}), day_ends_at=25)


def test_a_gap_of_whole_days_makes_no_rows():
    long = pd.concat(
        [
            _long({"CO": [1.0] * 24}),
            _long({"CO": [1.0] * 24}, start="2024-01-05"),
        ]
    )
    assert daily_us_aqi(long)["date"].astype(str).tolist() == [
        "2024-01-01",
        "2024-01-05",
    ]


def test_several_stations_are_kept_apart():
    long = pd.concat(
        [
            _long({"PM2.5": [20.0] * 24}, station="b"),
            _long({"PM2.5": [100.0] * 24}, station="a"),
        ]
    )
    out = daily_us_aqi(long)
    assert out["station_id"].tolist() == ["a", "b"]
    assert out["aqi"].tolist() == [compute_us_aqi({"PM2.5": 100.0}).aqi, 71]


def test_without_us_pollutants_the_result_is_empty():
    out = daily_us_aqi(_long({"NH3": [50.0] * 24}))
    assert out.empty
    assert list(out.columns)[:2] == ["station_id", "date"]


def test_eight_hour_o3_above_the_table_gives_no_aqi_with_one_warning(caplog):
    long = pd.concat(
        [
            _long({"O3": [0.25] * 48}, unit="ppm"),
            _long({"PM2.5": [20.0] * 48}, unit="µg/m³"),
        ]
    )
    with caplog.at_level(logging.WARNING):
        out = daily_us_aqi(long)
    assert out["aqi"].isna().all() and out["category"].isna().all()
    assert out.loc[0, "PM2.5_sub_index"] == pytest.approx(
        equation(20.0, 9.1, 35.4, 51, 100)
    )
    assert math.isnan(out.loc[0, "O3_sub_index"])
    assert len([r for r in caplog.records if "O3" in r.getMessage()]) == 1
    assert "2 day" in caplog.text


def test_station_helper_standard(tmp_path, monkeypatch):
    long = pd.DataFrame(
        [
            {
                "station_id": "s1",
                "timestamp": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=h),
                "pollutant": p,
                "unit": "µg/m³",
                "value": v,
            }
            for h in range(24)
            for p, v in (("PM2.5", 45.0), ("PM10", 80.0), ("NO2", 30.0))
        ]
    )
    client = CPCBHistorical(cache_dir=str(tmp_path))
    monkeypatch.setattr(
        client, "download_raw_aqi_data_station_level", lambda *a, **k: long.copy()
    )

    india = client.daily_aqi("s1", "2024")
    us = client.daily_aqi("s1", "2024", standard="us")
    assert india.loc[0, "category"] == "Satisfactory"
    assert india.loc[0, "aqi"] == 80
    assert us.loc[0, "aqi"] == 124
    assert us.loc[0, "category"] == "Unhealthy for Sensitive Groups"
    with pytest.raises(ValueError, match="standard"):
        client.daily_aqi("s1", "2024", standard="eu")
