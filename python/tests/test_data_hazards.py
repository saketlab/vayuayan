"""Hazards of real CPCB and OAQ data: time zones, duplicates, gaps, failures."""

from __future__ import annotations

import math
from datetime import date

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from vayuayan.aqi import daily_aqi
from vayuayan.cpcb_historical import CPCBHistorical
from vayuayan.exceptions import DataNotFoundError
from vayuayan.oaq_records import compare_daily_records
from vayuayan.pm25 import PM25Client
from vayuayan.sensor_qa import (
    peer_ratio,
    ratio_by_humidity,
    readings_mean,
    sensor_accuracy,
    sensor_completeness,
    sensor_plausibility,
)
from vayuayan.tidy import (
    cpcb_raw_to_long,
    cpcb_tidy_daily,
    daily_aqi_workbook_to_long,
    parse_timestamps,
)
from vayuayan.utils import analyze_station_data, clean_station_name

from .fakes import write_pm25_netcdf

# --- Timestamps ---


def test_hour_24_is_midnight_of_the_next_day():
    parsed = parse_timestamps(pd.Series(["2024-01-01 24:00:00", "2024-01-01 24:00"]))
    assert list(parsed) == [pd.Timestamp("2024-01-02")] * 2


def test_raw_rows_at_hour_24_are_kept():
    raw = pd.DataFrame({"Timestamp": ["2024-01-01 24:00:00"], "PM2.5 (µg/m³)": [100.0]})
    assert cpcb_raw_to_long(raw)["timestamp"].iloc[0] == pd.Timestamp("2024-01-02")


def test_utc_offsets_keep_the_local_wall_clock_time():
    parsed = parse_timestamps(
        pd.Series(["2024-01-01T00:15:00+05:30", "2024-01-01T00:15:00Z", "2024-01-01"])
    )
    assert list(parsed) == [
        pd.Timestamp("2024-01-01 00:15:00"),
        pd.Timestamp("2024-01-01 00:15:00"),
        pd.Timestamp("2024-01-01"),
    ]


def test_tz_aware_timestamps_use_their_own_calendar_day():
    raw = pd.DataFrame(
        {
            "Timestamp": pd.date_range(
                "2024-01-01", periods=4, freq="15min", tz="Asia/Kolkata"
            ),
            "PM2.5 (µg/m³)": [40.0, 42.0, 44.0, 46.0],
        }
    )
    long = cpcb_raw_to_long(raw, start_date=date(2024, 1, 1), end_date=date(2024, 1, 1))
    assert len(long) == 4
    assert long["timestamp"].iloc[0] == pd.Timestamp("2024-01-01 00:00:00")


def test_daily_aqi_of_tz_aware_data_uses_the_local_day():
    stamps = pd.date_range("2024-01-01", periods=20, freq="h", tz="Asia/Kolkata")
    long = pd.DataFrame(
        {
            "timestamp": list(stamps) * 3,
            "pollutant": ["PM2.5"] * 20 + ["PM10"] * 20 + ["NO2"] * 20,
            "value": [30.0] * 20 + [50.0] * 20 + [40.0] * 20,
        }
    )
    out = daily_aqi(long)
    assert list(out["date"]) == [date(2024, 1, 1)]
    assert out.loc[0, "aqi"] == 50


# --- Duplicate readings ---


def _readings(stamps, value=25.0):
    return pd.DataFrame({"sensor_id": "s1", "timestamp": stamps, "pm25": value})


def test_duplicates_do_not_exceed_full_completeness():
    stamps = list(pd.date_range("2026-01-01", periods=96, freq="15min")) * 2
    out = sensor_completeness(_readings(stamps), "2026-01-01", "2026-01-01")
    assert out.loc[0, "readings_pct"] == pytest.approx(100.0)


def test_a_repeated_timestamp_is_not_a_valid_day():
    stamps = [pd.Timestamp("2026-01-01")] * 72
    assert readings_mean(_readings(stamps), by="day").empty
    out = sensor_completeness(_readings(stamps), "2026-01-01", "2026-01-01")
    assert out.loc[0, "valid_days"] == 0


def test_duplicates_are_averaged_once_in_the_hourly_mean():
    stamps = ["2024-01-01 00:00:00"] * 3 + ["2024-01-01 00:15:00"]
    long = pd.DataFrame(
        {"timestamp": stamps, "pollutant": "PM2.5", "value": [100.0] * 3 + [20.0]}
    )
    out = daily_aqi(long, min_hours=1)
    # hourly mean 60, not 80
    assert out.loc[0, "PM2.5_sub_index"] == pytest.approx(100.0)


def test_duplicates_are_one_reading_for_plausibility_and_record_checks():
    stamps = list(pd.date_range("2026-01-01", periods=4, freq="h")) * 2
    readings = _readings(stamps)
    assert sensor_plausibility(readings).loc[0, "readings"] == 4
    records = pd.DataFrame(
        {"sensor_id": ["s1"], "date": [date(2026, 1, 1)], "pm25": [25.0]}
    )
    assert compare_daily_records(readings, records).loc[0, "n"] == 4


# --- Infinite values and sensor checks ---


def test_infinite_text_in_raw_data_is_dropped():
    raw = pd.DataFrame(
        {
            "Timestamp": ["2024-01-01 00:00:00"],
            "PM2.5 (µg/m³)": ["Inf"],
            "PM10 (µg/m³)": ["-Inf"],
        }
    )
    assert cpcb_raw_to_long(raw).empty


def test_infinite_readings_count_as_missing():
    stamps = list(pd.date_range("2026-01-01", periods=96, freq="15min"))
    readings = _readings(stamps)
    readings.loc[:23, "pm25"] = math.inf
    out = sensor_completeness(readings, "2026-01-01", "2026-01-01")
    assert out.loc[0, "readings_pct"] == pytest.approx(75.0)
    assert readings_mean(readings, by="day").loc[0, "pm25"] == pytest.approx(25.0)


def test_peer_ratio_leaves_out_an_infinite_ratio():
    daily = pd.DataFrame(
        {
            "sensor_id": ["a", "b", "c"],
            "date": [date(2026, 1, 1)] * 3,
            "pm25": [10.0, 0.0, 0.0],
        }
    )
    a = peer_ratio(daily).set_index("sensor_id").loc["a"]
    assert a["days"] == 0
    assert not math.isinf(a["median_ratio"])


def test_stuck_sensor_has_false_flags_and_an_integer_score():
    paired = pd.DataFrame(
        {"sensor_id": "s", "pm25": 25.0, "reference": np.arange(1.0, 31.0)}
    )
    row = sensor_accuracy(paired).iloc[0]
    assert not row["r2_ok"]
    assert row["targets_met"] in range(5)
    assert not pd.isna(row["targets_met"])


def test_zero_humidity_is_in_the_first_band():
    hourly = pd.DataFrame(
        {"sensor": [15.0, 20.0], "reference": [10.0, 10.0], "rh": [0.0, 30.0]}
    )
    out = ratio_by_humidity(hourly)
    assert out.loc[out["band"] == "0-40", "hours"].iloc[0] == 2


# --- Workbooks and station tables ---


def test_workbook_ignores_footer_rows_and_empty_sheets():
    workbook = pd.DataFrame(
        {
            "Day": [1, 2, "Minimum", "Maximum", None],
            "January": [150, 160, 150, 160, 155],
        }
    )
    out = daily_aqi_workbook_to_long(workbook, year=2024)
    assert list(out["date"]) == [date(2024, 1, 1), date(2024, 1, 2)]
    assert daily_aqi_workbook_to_long(pd.DataFrame(), year=2024).empty

    empty = cpcb_tidy_daily(pd.DataFrame())
    assert list(empty.columns) == ["day", "month", "value"]
    assert empty.empty


def test_leap_years_keep_february_29_only_when_it_exists():
    sheet = pd.DataFrame({"Day": [28, 29, 30, 31], "February": [100, 120, 140, 160]})
    assert list(cpcb_tidy_daily(sheet, year=2024)["date"]) == [
        date(2024, 2, 28),
        date(2024, 2, 29),
    ]
    assert list(cpcb_tidy_daily(sheet, year=2023)["date"]) == [date(2023, 2, 28)]


def test_station_analysis_of_no_stations_has_no_infinities():
    out = analyze_station_data([])
    assert out["total_stations"] == 0
    assert pd.isna(out["min_aqi"]) and pd.isna(out["max_aqi"])


def test_station_analysis_keeps_stations_without_coordinates_and_drops_inf():
    data = [
        {
            "cityName": "Delhi",
            "stationsInCity": [
                {"id": "site_1", "latitude": 28.6, "longitude": 77.2, "avg": 100, "live": True},
                {"id": "site_2", "latitude": None, "longitude": None, "avg": "Inf", "live": True},
            ],
        }
    ]  # fmt: skip
    out = analyze_station_data(data)
    assert out["total_stations"] == 2
    assert out["max_aqi"] == 100.0


def test_clean_station_name_keeps_accents_and_micro_sign():
    assert clean_station_name("Sector µ-2, Café - CPCB") == "Sector_µ_2_Café_CPCB"


# --- CPCB repository and cache ---


def test_another_years_entries_are_never_combined():
    client = CPCBHistorical(use_cache=False)
    client._read_repository_excel = lambda fp: pd.DataFrame({"Value": [1]})
    entries = [{"year": "2023", "month": "January", "filepath": "2023_jan.xlsx"}]
    with pytest.raises(DataNotFoundError):
        client._combine_repository_excels(entries, year="2025")
    with pytest.raises(DataNotFoundError):
        client._combine_repository_excels(entries, year="2025", month="January")


def test_month_selection_stays_inside_the_year():
    client = CPCBHistorical(use_cache=False)
    entries = [
        {"year": "2022", "month": "January", "filepath": "/2022_jan.xlsx"},
        {"year": "2024", "month": "January", "filepath": "/2024_jan.xlsx"},
    ]
    selected = client._select_repository_entry(entries, "2024", "January")
    assert selected == [entries[1]]


def test_raw_download_does_not_use_another_years_file():
    client = CPCBHistorical(use_cache=False)
    client._station_info = lambda *a: {
        "station_id": "site_1", "station_name": "x", "city": "c", "state": "s"
    }  # fmt: skip
    client.get_file_path = lambda *a: [{"year": "2023", "filepath": "/Raw/x.csv"}]
    with pytest.raises(DataNotFoundError):
        client.download_raw_aqi_data_station_level("site_1", "2025", "")


@pytest.mark.parametrize(
    "path,cached",
    [
        ("raw/2022/site_2099_raw.csv", True),
        ("live/site_2020_latest.csv", False),
        ("/AQI/site_1998.csv", False),
        ("/AQI/site_301_2020.csv", True),
        ("/AQI/Delhi_DPCC_January_2020.xlsx", True),
        ("/AQI/2020/x.csv", True),
    ],
)
def test_cache_year_ignores_station_ids(tmp_path, path, cached):
    client = CPCBHistorical(cache_dir=str(tmp_path), use_cache=True)
    assert (client._cache_path(path) is not None) is cached


def _daily_raw(hours_by_year):
    def fake_raw(station_id, year, save_location="", **kwargs):
        hours = hours_by_year.get(str(year))
        if hours is None:
            raise DataNotFoundError(f"no {year}")
        return pd.DataFrame(
            {
                "station_id": "site_301",
                "timestamp": list(hours) * 3,
                "pollutant": ["PM2.5"] * len(hours)
                + ["PM10"] * len(hours)
                + ["NO2"] * len(hours),
                "unit": "µg/m³",
                "value": [30.0] * len(hours)
                + [50.0] * len(hours)
                + [40.0] * len(hours),
            }
        )

    return fake_raw


def test_window_across_the_new_year_uses_december_31():
    client = CPCBHistorical(use_cache=False)
    client.download_raw_aqi_data_station_level = _daily_raw(
        {
            "2023": pd.date_range("2023-12-31 16:00", periods=8, freq="h"),
            "2024": pd.date_range("2024-01-01 00:00", periods=10, freq="h"),
        }
    )
    out = client.daily_aqi("site_301", "2024", day_ends_at=16)
    jan1 = out.loc[out["date"] == date(2024, 1, 1)]
    assert jan1["aqi"].iloc[0] == 50
    assert all(d.year == 2024 for d in out["date"])


def test_missing_previous_year_is_not_fatal():
    client = CPCBHistorical(use_cache=False)
    client.download_raw_aqi_data_station_level = _daily_raw(
        {"2024": pd.date_range("2024-01-01 00:00", periods=20, freq="h")}
    )
    out = client.daily_aqi("site_301", "2024", day_ends_at=16)
    assert not out.empty


def test_calendar_days_do_not_ask_for_the_previous_year():
    client = CPCBHistorical(use_cache=False)
    asked = []
    fake = _daily_raw({"2024": pd.date_range("2024-01-01", periods=20, freq="h")})

    def spy(station_id, year, save_location="", **kwargs):
        asked.append(year)
        return fake(station_id, year, save_location, **kwargs)

    client.download_raw_aqi_data_station_level = spy
    client.daily_aqi("site_301", "2024")
    assert asked == ["2024"]


# --- PM2.5 grid edge ---


def _edge_client(tmp_path):
    client = PM25Client("V6", cache_dir=str(tmp_path / "cache"))
    write_pm25_netcdf(client, value=42.0)
    return client


def _polygon_file(tmp_path, polygon):
    path = str(tmp_path / "polygon.geojson")
    gpd.GeoDataFrame({"name": ["edge"]}, geometry=[polygon], crs="EPSG:4326").to_file(
        path, driver="GeoJSON"
    )
    return path


@pytest.mark.parametrize(
    "polygon",
    [
        box(84.6, 25.0, 85.0, 26.0),
        box(69.5, 25.0, 69.9, 26.0),
        box(75.0, 20.0, 76.0, 20.4),
    ],
)
def test_polygon_selecting_one_grid_line_at_the_edge(tmp_path, polygon):
    client = _edge_client(tmp_path)
    stats = client.get_pm25_stats(_polygon_file(tmp_path, polygon), 2020, 1)
    assert stats["mean"] == pytest.approx(42.0)
