"""Write the Python outputs that the R parity tests compare against.

Run from python/ after changing AQI, tidy, cache, PM2.5 or station-name code:

    python scripts/make_parity_fixtures.py

It writes ../R/tests/testthat/fixtures/parity_python.json and
daily_aqi_python.csv. tests/test_parity_fixtures.py fails when they are stale.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from vayuayan import aqi, oaq, oaq_records, sensor_qa, tidy, utils
from vayuayan.constants import AQI_CATEGORIES
from vayuayan.cpcb_historical import CPCBHistorical
from vayuayan.pm25_versions import PM25_VERSIONS

FIXTURES = Path(__file__).resolve().parents[2] / "R" / "tests" / "testthat" / "fixtures"
JSON_PATH = FIXTURES / "parity_python.json"
DAILY_INPUT = FIXTURES / "daily_aqi_input.csv"
DAILY_OUTPUT = FIXTURES / "daily_aqi_python.csv"

# Public Python function or method -> the R export that does the same.
# tests/test_parity_fixtures.py and R's test_parity.R check that every public
# name of each package is here or in PYTHON_ONLY / R_ONLY.
API = {
    "compute_aqi": "compute_aqi",
    "sub_index": "aqi_sub_index",
    "pollutant_name": "aqi_pollutant_name",
    "daily_aqi": "daily_aqi",
    "health_impact": "aqi_health_impact",
    "pollutant_category": "aqi_pollutant_category",
    "cpcb_raw_to_long": "cpcb_raw_to_long",
    "cpcb_tidy_daily": "cpcb_tidy_daily",
    "live_to_long": "cpcb_live_to_long",
    "live_metrics": "cpcb_live_metrics",
    "clean_station_name": "clean_station_name",
    "stations_to_dataframe": "stations_to_dataframe",
    "stations_to_city_summary": "stations_to_city_summary",
    "analyze_station_data": "analyze_station_data",
    "get_aqi_category": "get_aqi_category",
    "get_aqi_categories": "get_aqi_categories",
    "haversine_distance": "haversine_distance",
    "nearest_stations": "nearest_stations",
    "india_boundary": "india_boundary",
    "get_cache_dir": "vayuayan_cache_dir",
    "CPCBHistorical.get_complete_list": "cpcb_get_complete_list",
    "CPCBHistorical.get_state_list": "cpcb_get_state_list",
    "CPCBHistorical.get_city_list": "cpcb_get_city_list",
    "CPCBHistorical.get_station_list": "cpcb_get_station_list",
    "CPCBHistorical.add_coords": "cpcb_add_coords",
    "CPCBHistorical.get_file_path": "cpcb_get_file_path",
    "CPCBHistorical.download_raw_aqi_data_station_level": "cpcb_download_raw_station_data",
    "CPCBHistorical.daily_aqi": "cpcb_station_daily_aqi",
    "CPCBHistorical.download_hourly_aqi_data_city_level": "cpcb_download_hourly_city_data",
    "CPCBHistorical.download_hourly_aqi_data_station_level": "cpcb_download_hourly_station_data",
    "CPCBHistorical.download_past_year_aqi_data_city_level": "cpcb_download_city_data",
    "CPCBHistorical.download_past_year_aqi_data_station_level": "cpcb_download_station_data",
    "CPCBHistorical.city_daily": "cpcb_city_daily",
    "CPCBHistorical.station_daily": "cpcb_station_daily",
    "CPCBHistorical.raw_readings": "cpcb_raw_readings",
    "CPCBLive.get_system_location": "cpcb_get_system_location",
    "CPCBLive.get_nearest_station": "cpcb_get_nearest_station",
    "CPCBLive.get_all_india": "cpcb_get_all_india",
    "CPCBLive.get_live_aqi_data_for_station": "cpcb_get_live_aqi_data_for_station",
    "CPCBLive.get_live_aqi_data": "cpcb_get_live_aqi_data",
    "CPCBClient.get_nearest_station": "cpcb_get_nearest_station",
    "CPCBClient.get_k_nearest_stations": "cpcb_get_nearest_stations",
    "CPCBClient.get_nearest_station_within_radius": "cpcb_get_nearest_stations",
    "PM25Client.download_netcdf_if_needed": "pm25_download_netcdf",
    "PM25Client.get_pm25_at_point": "pm25_get_point",
    "PM25Client.get_pm25_stats": "pm25_get_stats",
    "PM25Client.get_pm25_monthly_stats": "pm25_monthly",
    "PM25Client.get_pm25_stats_by_polygon": "pm25_get_stats_by_polygon",
    "PM25Client.clear_cache": "pm25_clear_cache",
    "PM25Client.list_cached_files": "pm25_list_cached_files",
    "OAQClient.__init__": "oaq_session",
    "OAQClient.list_providers": "oaq_list_providers",
    "OAQClient.get_hierarchy": "oaq_get_hierarchy",
    "OAQClient.get_city_latest": "oaq_get_city_latest",
    "OAQClient.get_stations_latest": "oaq_get_stations_latest",
    "OAQClient.get_station_24h": "oaq_get_station_24h",
    "OAQClient.get_daily": "oaq_get_daily",
    "OAQClient.get_monthly": "oaq_get_monthly",
    "OAQClient.get_annual": "oaq_get_annual",
    "OAQClient.stations_table": "oaq_stations_table",
    "OAQClient.fetch_monthly_stations": "oaq_fetch_monthly_stations",
    "OAQClient.sensors": "oaq_sensors",
    "OAQClient.daily_means": "oaq_daily_means",
    "OAQClient.readings": "oaq_readings",
    "OAQClient.daily_records": "oaq_daily_records",
    "OAQClient.check_daily_records": "oaq_check_daily_records",
    "OAQClient.audit_daily_records": "oaq_audit_daily_records",
    "compare_daily_records": "compare_daily_records",
    "daily_record_summary": "daily_record_summary",
    "plot_daily_record_day": "plot_daily_record_day",
    "plot_daily_record_timeline": "plot_daily_record_timeline",
    "plot_daily_record_scatter": "plot_daily_record_scatter",
    "plot_daily_record_share": "plot_daily_record_share",
    "plot_daily_record_series": "plot_daily_record_series",
    "plot_daily_record_difference": "plot_daily_record_difference",
    "readings_mean": "readings_mean",
    "sensor_completeness": "sensor_completeness",
    "sensor_plausibility": "sensor_plausibility",
    "collocated_precision": "collocated_precision",
    "peer_ratio": "peer_ratio",
    "sensor_accuracy": "sensor_accuracy",
    "ratio_by_humidity": "ratio_by_humidity",
    "oaq_nearest_cpcb": "oaq_nearest_cpcb",
    "oaq_city_tally": "oaq_city_tally",
}

# Public names with no counterpart in the other package, and why
PYTHON_ONLY = {
    "setup_earth_engine": "Earth Engine fallback; R reads the S3 files only",
    "get_gee_project_file": "Earth Engine",
    "get_config_dir": "Earth Engine project file location",
    "daily_aqi_workbook_to_long": "older shape (date, aqi) of cpcb_tidy_daily",
    "convert_station_data_to_dataframe": "older wrapper of stations_to_dataframe",
    "CPCBHistorical.iter_stations": "generator over the directory",
    "PM25Client.get_netcdf_path": "cache path; R returns it from the download",
    "CPCBClient.list_stations": "legacy client",
    "CPCBClient.download_raw_data": "legacy client",
}
R_ONLY = {
    "pm25_map": "ggplot2 map",
    "pm25_read_netcdf_bbox": "NetCDF reader for the vignettes",
    "pm25_load_netcdf_bbox": "NetCDF reader for the vignettes",
    "pm25_v5gl04_path": "file name helper for the vignettes",
    "vayuayan_welcome": "startup banner",
}

LABELS = [
    "PM2.5", "PM2.5 (µg/m³)", "pm25", "PM10 (ug/m3)", "Ozone", "O3",
    "CO (mg/m3)", "NO2", "SO2", "NH3", "lead", "Pb", "Benzene", "Toluene (ug/m3)",
]  # fmt: skip

AQI_CASES: List[Dict[str, Optional[float]]] = [
    {"PM2.5": 45, "PM10": 80, "NO2": 30},
    {"PM2.5": 45, "NO2": 30},
    {"NO2": 30, "SO2": 10, "CO": 2},
    {"PM10 (ug/m3)": 300, "Ozone": 250, "CO (mg/m3)": 12, "Benzene": 5},
    {"PM2.5": 500, "PM10": 600, "NH3": 3000, "Pb": 4},
    {"PM2.5": 30.5, "PM10": 50.5, "SO2": 40.5},
    {"PM2.5": None, "PM10": 120, "NO2": 90, "O3": 70},
]

CATEGORY_VALUES = [
    0,
    1,
    50,
    50.4,
    50.6,
    51,
    100,
    101,
    200,
    250,
    300,
    301,
    400,
    401,
    500,
    999,
    None,
]

HAVERSINE_PAIRS = [
    [28.61, 77.21, 19.08, 72.88],
    [0, 0, 0, 180],
    [90, 0, -90, 0],
    [12.97, 77.59, 12.97, 77.59],
    [-33.87, 151.21, 51.51, -0.13],
]

STATION_NAMES = [
    "Dr. Karni Singh Shooting Range, Delhi - DPCC",
    "ITO, Delhi - DPCC",
    "Bandra Kurla Complex, Mumbai - IITM",
    "  Sector-62, Noida - IMD  ",
    "Anand Vihar (East), Delhi -- DPCC!!",
    "Lal Bahadur Shastri Nagar_Kalaburagi - KSPCB",
    "",
]

FREQUENCIES = ["hourly", "1_hour", "1h", "daily", "24_hours", "24h", "1d",
               "monthly", "1m", "15_minute", "15m", "Daily", "HOURLY", "weekly"]  # fmt: skip

CACHE_PATHS = [
    "Raw_data/15Min/2023/site_301_2023.csv",
    "/Raw_data/1Day/Delhi/2019/site 1 (A&B)_2019.xlsx",
    "../AQI_Bulletin/2020-2021/city.xlsx",
    "Raw_data/1Hr/2099/site_1.csv",
    "no_year/here.csv",
]

RAW = pd.DataFrame(
    {
        "Timestamp": ["2024-01-01 00:00:00", "2024-01-01 00:15:00", "bad", "2024-01-02 23:45:00"],
        "PM2.5 (ug/m3)": [158, 160, 1, None],
        "CO (mg/m3)": [1.6, None, 1, 2.2],
        "Benzene": ["0.5", "x", 1, 0.7],
    }
)  # fmt: skip

WORKBOOK = pd.DataFrame(
    {
        "Day": [1, 28, 29, 30, 31],
        "January": [180, None, 150, 140, 130],
        "February": [120, 110, 100, None, 90],
        "April": [None, 60, 70, 80, 75],
    }
)

CATEGORY_CASES = [("PM2.5", 20), ("PM2.5", 75), ("PM10", 300), ("O3", 900), ("CO", 12)]

LIVE = {
    "station_id": "site_301",
    "last_hours": [
        {"name": "PM2.5", "data": [
            {"date": "2024-01-01 10:00:00", "val": 80},
            {"date": "2024-01-01 09:00:00", "val": "85"},
            {"date": "bad", "val": 1},
            {"date": "2024-01-01 08:00:00", "val": "NA"},
        ]},
        {"name": "CO", "data": [{"date": "2024-01-01 10:00", "val": 1.2}]},
        {"name": "NO2", "data": []},
    ],
    "metrics": [
        {"name": "PM2.5", "avg": "80", "min": 60, "max": "NA", "avgDesc": "Over the last 24 hours"},
        {"name": "CO", "avg": 1.2, "min": None, "max": "2", "avgDesc": "Over the last 8 hours"},
    ],
}  # fmt: skip

FROM_POINTS = pd.DataFrame(
    {"id": ["a", "b"], "lat": [28.61, 19.08], "lon": [77.21, 72.88]}
)
TO_POINTS = pd.DataFrame(
    {
        "id": ["s1", "s2", "s3", "s4"],
        "lat": [28.65, 19.0, 12.97, 28.5],
        "lon": [77.2, 72.8, 77.59, 77.3],
    }
)

# OAQ sensors: low-cost ones in cities with and without CPCB stations, and an
# OAQ copy of a CPCB station, which the tally leaves out
OAQ_SENSORS = pd.DataFrame(
    {
        "id": ["12031", "12032", "14410", "15452", "103"],
        "name": ["Rajanukunte", "Kumarapark west", "Burla", "Korapalli", "CRRI"],
        "city": ["Bengaluru", "Bengaluru", "Burla", "Korapalli", "Delhi"],
        "lat": [13.1568, 12.9928, 21.4942, 19.4167, 28.5512],
        "lon": [77.5521, 77.5799, 83.8722, 84.8333, 77.2736],
        "provider": ["airnet", "airnet", "aurassure", "aurassure", "cpcb"],
    }
)


def _qa_readings() -> pd.DataFrame:
    """15-minute readings of 4 sensors over 4 days, with known problems."""
    times = pd.date_range("2026-01-01", periods=4 * 96, freq="15min")
    base = [round(30 + 10 * math.sin(i / 12), 2) for i in range(len(times))]
    frames = []
    for sensor, factor in [("a", 1.0), ("b", 1.2), ("c", 0.9), ("d", 1.5)]:
        frames.append(
            pd.DataFrame({"sensor_id": sensor, "timestamp": times,
                          "pm25": [round(v * factor, 2) for v in base]})
        )  # fmt: skip
    df = pd.concat(frames, ignore_index=True)
    c, d = df["sensor_id"] == "c", df["sensor_id"] == "d"
    day = df["timestamp"].dt.day
    df.loc[c & (day == 2) & (df.index % 2 == 0), "pm25"] = math.nan  # half a day
    df.loc[c & (day == 3), "pm25"] = df.loc[c & (day == 3), "pm25"].where(
        df.loc[c & (day == 3)].index % 96 >= 10, 25.0
    )  # stuck for 10 readings
    first_c = df.index[c][0]
    df.loc[first_c + 20, "pm25"] = -1.0
    df.loc[first_c + 30, "pm25"] = 0.0
    df.loc[first_c + 40, "pm25"] = 1500.0  # above 1000, and a spike
    df.loc[first_c + 50, "pm25"] = 400.0  # a spike
    df = df[~(d & (day >= 3))]  # d stops after two days
    return df.reset_index(drop=True)


def _qa_cases() -> Dict[str, Any]:
    """Inputs and Python outputs of the sensor_qa functions."""
    readings = _qa_readings()
    daily = sensor_qa.readings_mean(readings, min_readings=40)
    ref = daily[daily.sensor_id == "a"][["date", "pm25"]].rename(
        columns={"pm25": "reference"}
    )
    paired = daily[daily.sensor_id != "a"].merge(ref, on="date")
    hourly = pd.DataFrame(
        {
            "sensor": [20.0, 30.0, 45.0, 50.0, 12.0, 3.0, 66.0, 40.0],
            "reference": [20.0, 20.0, 30.0, 25.0, 10.0, 2.0, 30.0, 41.0],
            "rh": [35.0, 45.0, 65.0, 95.0, 100.0, 50.0, 85.0, 40.0],
        }
    )

    def text_dates(df: pd.DataFrame) -> pd.DataFrame:
        return df.assign(**{c: df[c].astype(str) for c in ("date",) if c in df})

    return {
        "readings": _columns(readings),
        "daily": _columns(text_dates(sensor_qa.readings_mean(readings))),
        "daily_40": _columns(text_dates(daily)),
        "hourly_mean": _columns(sensor_qa.readings_mean(readings, by="hour")),
        "completeness": _columns(
            sensor_qa.sensor_completeness(
                readings, "2026-01-01", "2026-01-05", ids=["a", "b", "c", "d", "e"]
            )
        ),
        "plausibility": _columns(sensor_qa.sensor_plausibility(readings)),
        "precision": _columns(text_dates(sensor_qa.collocated_precision(daily))),
        "peer_ratio": _columns(sensor_qa.peer_ratio(daily)),
        "accuracy": _columns(sensor_qa.sensor_accuracy(paired, min_days=2)),
        "humidity_input": hourly.to_dict(orient="list"),
        "humidity": _columns(sensor_qa.ratio_by_humidity(hourly)),
    }


def _record_cases() -> Dict[str, Any]:
    """Readings and records of two sensors: records are the mean until
    February and the last reading from March, with one record that is
    neither and one missing reading."""
    rows = []
    for sensor, offset in [("a", 0.0), ("b", 5.0)]:
        for day in pd.date_range("2026-02-25", "2026-03-04"):
            for k in range(8):  # 8 readings a day, the last one high
                value = 10.0 + offset + k if k < 7 else 90.0 + offset
                if (sensor, day.day, k) == ("b", 2, 3):
                    value = math.nan
                rows.append((sensor, day + pd.Timedelta(minutes=15 * k), value))
    readings = pd.DataFrame(rows, columns=["sensor_id", "timestamp", "pm25"])
    days = readings.assign(date=readings["timestamp"].dt.date).dropna(subset=["pm25"])
    stats = (
        days.groupby(["sensor_id", "date"])["pm25"].agg(["mean", "last"]).reset_index()
    )
    march = stats["date"] >= pd.Timestamp("2026-03-01").date()
    record = stats["mean"].round(2).where(~march, stats["last"])
    odd = (stats["sensor_id"] == "b") & (
        stats["date"] == pd.Timestamp("2026-03-03").date()
    )
    record[odd] = 50.0
    records = stats[["sensor_id", "date"]].assign(pm25=record)
    compared = oaq_records.compare_daily_records(readings, records)
    summary = oaq_records.daily_record_summary(compared)
    dates = ["date", "last_mean_day", "first_last_day"]
    return {
        "readings": _columns(readings),
        "records": _columns(records.assign(date=records["date"].astype(str))),
        "compared": _columns(compared.assign(date=compared["date"].astype(str))),
        "summary": _columns(
            summary.assign(**{c: summary[c].astype(str) for c in dates[1:]})
        ),
    }


def _columns(df: pd.DataFrame) -> Dict[str, List[Any]]:
    """Columns of df as JSON lists, with NaN as null and dates as text."""
    return {
        c: [_num(v) if isinstance(v, float) else v for v in df[c].astype(object)]
        if df[c].dtype.kind != "M"
        else df[c].dt.strftime("%Y-%m-%d %H:%M:%S").tolist()
        for c in df.columns
    }


def _num(x: Optional[float]) -> Optional[float]:
    """JSON number, with NaN as null."""
    return None if x is None or math.isnan(x) else x


def _sub_index_cases() -> List[Dict[str, Any]]:
    """Every breakpoint, its neighbours and band midpoints of each pollutant."""
    cases = []
    for name, p in aqi.POLLUTANTS.items():
        edges = sorted({c for band in p.breakpoints for c in band})
        concs = set(edges)
        concs |= {e + d for e in edges for d in (-0.05, 0.05) if e + d >= 0}
        concs |= {(lo + hi) / 2 for lo, hi in p.breakpoints}
        concs |= {edges[-1] * 1.5}
        cases += [
            {"pollutant": name, "concentration": c, "sub_index": aqi.sub_index(name, c)}
            for c in sorted(concs)
        ]
    return cases


def _compute_aqi_case(case: Dict[str, Optional[float]]) -> Dict[str, Any]:
    """compute_aqi of one case, with None as a missing value."""
    r = aqi.compute_aqi({k: math.nan if v is None else v for k, v in case.items()})
    return {
        "input": case,
        "aqi": r.aqi,
        "category": r.category,
        "dominant_pollutant": r.dominant_pollutant,
        "sub_indices": r.sub_indices,
    }


def build() -> Dict[str, Any]:
    """All parity cases with the Python outputs."""
    historical = CPCBHistorical(cache_dir="cpcb")
    long = tidy.cpcb_raw_to_long(
        RAW, station={"station_id": "site_301", "city": "Delhi"}
    )
    workbook = tidy.daily_aqi_workbook_to_long(WORKBOOK, 2023)
    return {
        "api": API,
        "r_only": R_ONLY,
        "pollutants": {
            name: {
                "unit": p.unit,
                "hours": p.averaging_hours,
                "breakpoints": [list(b) for b in p.breakpoints],
            }
            for name, p in aqi.POLLUTANTS.items()
        },
        "aqi_categories": {k: [v["min"], v["max"]] for k, v in AQI_CATEGORIES.items()},
        "pollutant_name": [{"label": x, "name": aqi.pollutant_name(x)} for x in LABELS],
        "sub_index": _sub_index_cases(),
        "compute_aqi": [_compute_aqi_case(c) for c in AQI_CASES],
        "aqi_category": [
            {"aqi": v, "category": utils.get_aqi_category(math.nan if v is None else v)}
            for v in CATEGORY_VALUES
        ],
        "haversine": [
            {"args": a, "km": utils.haversine_distance(*a)} for a in HAVERSINE_PAIRS
        ],
        "clean_station_name": [
            {"name": n, "clean": utils.clean_station_name(n)} for n in STATION_NAMES
        ],
        "frequency": [
            {"frequency": f, "code": historical._normalize_frequency(f)}
            for f in FREQUENCIES
        ],
        "cache_path": [
            {
                "filepath": f,
                "cache": None
                if (p := historical._cache_path(f)) is None
                else p.as_posix(),
            }
            for f in CACHE_PATHS
        ],
        "pm25": [
            {
                "version": key,
                "year": year,
                "month": month,
                "region": region,
                "key": v.key(year, month, region),
                "variable": v.variable_name,
                "years": list(v.year_range),
                "regions": list(v.regions),
            }
            for key, v in PM25_VERSIONS.items()
            for region in v.regions
            for year in v.year_range
            for month in (None, 1, 12)
        ],
        "health_impact": [
            {"aqi": v, "impact": aqi.health_impact(math.nan if v is None else v)}
            for v in CATEGORY_VALUES
        ],
        "pollutant_category": [
            {
                "pollutant": p,
                "concentration": c,
                "category": aqi.pollutant_category(p, c),
            }
            for p, c in CATEGORY_CASES
        ],
        "live": {
            "data": LIVE,
            "long": _columns(tidy.live_to_long(LIVE)),
            "metrics": _columns(tidy.live_metrics(LIVE)),
        },
        "nearest_stations": {
            "from": FROM_POINTS.to_dict(orient="list"),
            "to": TO_POINTS.to_dict(orient="list"),
            "out": {
                k: _columns(utils.nearest_stations(FROM_POINTS, TO_POINTS, k=k))
                for k in (1, 3, 9)
            },
        },
        "oaq": {
            "sensors": OAQ_SENSORS.to_dict(orient="list"),
            "nearest": _columns(oaq.oaq_nearest_cpcb(OAQ_SENSORS, k=2)),
            "tally": _columns(oaq.oaq_city_tally(OAQ_SENSORS)),
        },
        "sensor_qa": _qa_cases(),
        "daily_records": _record_cases(),
        "tidy_daily": {
            "no_year": _columns(tidy.cpcb_tidy_daily(WORKBOOK)),
            "year": _columns(
                tidy.cpcb_tidy_daily(WORKBOOK, 2024).assign(
                    date=lambda d: d["date"].astype(str)
                )
            ),
        },
        "raw_to_long": {
            "raw": RAW.astype(object).where(RAW.notna(), None).to_dict(orient="list"),
            "station": {"station_id": "site_301", "city": "Delhi"},
            "out": {
                "station_id": long["station_id"].tolist(),
                "city": long["city"].tolist(),
                "timestamp": long["timestamp"]
                .dt.strftime("%Y-%m-%d %H:%M:%S")
                .tolist(),
                "pollutant": long["pollutant"].tolist(),
                "unit": long["unit"].tolist(),
                "value": [_num(v) for v in long["value"]],
            },
        },
        "workbook_to_long": {
            "workbook": WORKBOOK.astype(object)
            .where(WORKBOOK.notna(), None)
            .to_dict(orient="list"),
            "year": 2023,
            "out": {
                "date": [d.isoformat() for d in workbook["date"]],
                "aqi": [_num(v) for v in workbook["aqi"]],
            },
        },
    }


def build_daily_csv() -> str:
    """daily_aqi_python.csv: daily_aqi of daily_aqi_input.csv for both day ends."""
    long = pd.read_csv(DAILY_INPUT, encoding="utf-8")
    frames = [
        aqi.daily_aqi(long, day_ends_at=end).assign(day_ends_at=end) for end in (24, 16)
    ]
    out = pd.concat(frames, ignore_index=True)
    out = out[["day_ends_at"] + [c for c in out.columns if c != "day_ends_at"]]
    buf = io.StringIO()
    out.to_csv(buf, index=False)
    return buf.getvalue()


def dumps(data: Dict[str, Any]) -> str:
    """Stable JSON text of the cases."""
    return json.dumps(data, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


if __name__ == "__main__":
    JSON_PATH.write_text(dumps(build()), encoding="utf-8")
    DAILY_OUTPUT.write_text(build_daily_csv(), encoding="utf-8")
