"""Tests for the tidy (long) tables."""

from datetime import date

import pandas as pd

from vayuayan.tidy import TIDY_COLUMNS, cpcb_raw_to_long, daily_aqi_workbook_to_long


def test_cpcb_raw_to_long_splits_labels_and_fills_the_station():
    raw = pd.DataFrame(
        {
            "Timestamp": ["2024-01-01 00:15:00", "2024-01-01 00:00:00", "bad"],
            "PM2.5 (µg/m³)": [20.5, "x", 1],
            "CO (mg/m³)": [1.2, 1.1, 1],
        }
    )
    long = cpcb_raw_to_long(raw, {"station_id": "site_301", "city": "Delhi"})

    assert list(long.columns) == TIDY_COLUMNS
    assert long[["pollutant", "unit", "value"]].values.tolist() == [
        ["CO", "mg/m³", 1.1],
        ["CO", "mg/m³", 1.2],
        ["PM2.5", "µg/m³", 20.5],
    ]
    assert set(long["station_id"]) == {"site_301"}
    assert set(long["station_name"]) == {""}


def test_daily_aqi_workbook_to_long_skips_days_that_do_not_exist():
    workbook = pd.DataFrame(
        {"Day": [1, 30], "January": [100, 120], "February": [80, None]}
    )
    long = daily_aqi_workbook_to_long(workbook, 2024)

    assert long["date"].tolist() == [
        date(2024, 1, 1),
        date(2024, 1, 30),
        date(2024, 2, 1),
    ]
    assert long["aqi"].tolist() == [100, 120, 80]


def test_live_data_to_tables():
    from vayuayan.tidy import live_metrics, live_to_long

    live = {
        "station_id": "site_301",
        "metrics": [
            {"name": "PM2.5", "avg": "167", "min": "35", "max": "313", "avgDesc": "x"},
            {"name": "OZONE", "avg": "NA", "min": "NA", "max": "NA", "avgDesc": "x"},
        ],
        "last_hours": [
            {"name": "PM2.5", "data": [{"date": "2024-01-01 01:00", "val": 50}]},
            {"name": "PM10", "data": [{"date": "2024-01-01 01:00", "val": "NA"}]},
        ],
    }
    metrics = live_metrics(live)
    assert metrics["avg"].tolist()[0] == 167
    assert metrics["avg"].isna().tolist() == [False, True]

    long = live_to_long(live)
    assert long[["station_id", "pollutant", "value"]].values.tolist() == [
        ["site_301", "PM2.5", 50]
    ]
    assert live_to_long({}).empty
