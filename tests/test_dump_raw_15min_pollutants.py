from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "dump_raw_15min_pollutants.py"
)
SPEC = importlib.util.spec_from_file_location("dump_raw_15min_pollutants", SCRIPT_PATH)
dump_raw_15min_pollutants = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dump_raw_15min_pollutants)


def test_normalize_raw_csv_melts_pollutants_and_sorts_rows():
    raw = pd.DataFrame(
        {
            "Timestamp": [
                "2025-01-01 00:15:00",
                "2024-12-31 23:45:00",
                "2025-01-01 00:00:00",
            ],
            "PM2.5 (µg/m³)": ["20.5", "99", "bad"],
            "NO2 (µg/m³)": [10, None, 8],
        }
    )
    station = {
        "station_id": "site_301",
        "station_name": "Anand Vihar, Delhi - DPCC",
        "city": "Delhi",
        "state": "Delhi",
    }

    normalized = dump_raw_15min_pollutants.normalize_raw_csv(
        raw, station, 2025, start_date=date(2025, 1, 1), end_date=date(2025, 1, 1)
    )

    assert list(normalized["pollutant_name"]) == ["NO2", "NO2", "PM2.5"]
    assert list(normalized["time"]) == ["00:00:00", "00:15:00", "00:15:00"]
    assert normalized["pollutant_unit"].tolist() == ["µg/m³", "µg/m³", "µg/m³"]
    assert normalized["value"].tolist() == [8.0, 10.0, 20.5]
    assert set(normalized["year"]) == {2025}
    assert normalized["station_id"].unique().tolist() == ["site_301"]


def test_shard_paths_include_date_range_when_filtered(tmp_path):
    shard, empty = dump_raw_15min_pollutants.shard_paths(
        tmp_path, "site_301", 2026, date(2026, 1, 1), date(2026, 5, 31)
    )

    assert shard.name == "2026_2026-01-01_to_2026-05-31.parquet"
    assert empty.name == "2026_2026-01-01_to_2026-05-31.empty"


def test_dump_station_year_uses_date_range_in_cache_and_rows(tmp_path):
    raw = pd.DataFrame(
        {
            "Timestamp": ["2025-01-01 00:00:00", "2025-06-01 00:00:00"],
            "PM2.5 (µg/m³)": [20, 40],
        }
    )

    class FakeClient:
        def get_file_path(self, **kwargs):
            return [{"filepath": "/Raw_data/15Min/2025/fake.csv"}]

        def _read_repository_csv(self, filepath):
            return raw

    station = {
        "station_id": "site_301",
        "station_name": "Anand Vihar, Delhi - DPCC",
        "city": "Delhi",
        "state": "Delhi",
    }

    status = dump_raw_15min_pollutants.dump_station_year(
        FakeClient(),
        station,
        2025,
        tmp_path,
        overwrite=False,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 5, 31),
    )

    assert status == "written:1"
    shard = tmp_path / "site_301" / "2025_2025-01-01_to_2025-05-31.parquet"
    assert shard.exists()
    rows = pd.read_parquet(shard)
    assert rows["date"].tolist() == [date(2025, 1, 1)]


def test_build_station_parquet_writes_sorted_station_file(tmp_path):
    cache = tmp_path / "cache"
    station_out_dir = tmp_path / "stations"
    shard_dir = cache / "site_301"
    shard_dir.mkdir(parents=True)

    rows = pd.DataFrame(
        [
            {
                "year": 2025,
                "date": pd.Timestamp("2025-01-02").date(),
                "time": "00:00:00",
                "timestamp": pd.Timestamp("2025-01-02 00:00:00"),
                "station_name": "B Station",
                "station_id": "site_302",
                "city": "Delhi",
                "state": "Delhi",
                "pollutant_name": "PM10",
                "pollutant_unit": "µg/m³",
                "value": 40.0,
            },
            {
                "year": 2024,
                "date": pd.Timestamp("2024-12-31").date(),
                "time": "23:45:00",
                "timestamp": pd.Timestamp("2024-12-31 23:45:00"),
                "station_name": "A Station",
                "station_id": "site_301",
                "city": "Delhi",
                "state": "Delhi",
                "pollutant_name": "NO2",
                "pollutant_unit": "µg/m³",
                "value": 8.0,
            },
        ]
    )
    rows.to_parquet(shard_dir / "2025.parquet", index=False)

    status = dump_raw_15min_pollutants.build_station_parquet(
        cache, station_out_dir, "site_301"
    )

    assert status == "written:1 shards"
    station_file = station_out_dir / "site_301.parquet"
    assert station_file.exists()

    sorted_rows = pd.read_parquet(station_file)
    assert sorted_rows[
        ["year", "date", "time", "station_id", "pollutant_name"]
    ].to_dict("records") == [
        {
            "year": 2024,
            "date": pd.Timestamp("2024-12-31").date(),
            "time": "23:45:00",
            "station_id": "site_301",
            "pollutant_name": "NO2",
        },
        {
            "year": 2025,
            "date": pd.Timestamp("2025-01-02").date(),
            "time": "00:00:00",
            "station_id": "site_302",
            "pollutant_name": "PM10",
        },
    ]


def test_finalize_sorted_parquet_orders_flat_station_files(tmp_path):
    station_dir = tmp_path / "stations"
    station_dir.mkdir()
    out = tmp_path / "raw_15min.parquet"
    rows = pd.DataFrame(
        [
            {
                "year": 2025,
                "date": pd.Timestamp("2025-01-02").date(),
                "time": "00:00:00",
                "timestamp": pd.Timestamp("2025-01-02 00:00:00"),
                "station_name": "B Station",
                "station_id": "site_302",
                "city": "Delhi",
                "state": "Delhi",
                "pollutant_name": "PM10",
                "pollutant_unit": "µg/m³",
                "value": 40.0,
            },
            {
                "year": 2024,
                "date": pd.Timestamp("2024-12-31").date(),
                "time": "23:45:00",
                "timestamp": pd.Timestamp("2024-12-31 23:45:00"),
                "station_name": "A Station",
                "station_id": "site_301",
                "city": "Delhi",
                "state": "Delhi",
                "pollutant_name": "NO2",
                "pollutant_unit": "µg/m³",
                "value": 8.0,
            },
        ]
    )
    rows.iloc[[0]].to_parquet(station_dir / "site_302.parquet", index=False)
    rows.iloc[[1]].to_parquet(station_dir / "site_301.parquet", index=False)

    dump_raw_15min_pollutants.finalize_sorted_parquet(station_dir, out)

    sorted_rows = pd.read_parquet(out)
    assert sorted_rows[
        ["year", "date", "time", "station_id", "pollutant_name"]
    ].to_dict("records") == [
        {
            "year": 2024,
            "date": pd.Timestamp("2024-12-31").date(),
            "time": "23:45:00",
            "station_id": "site_301",
            "pollutant_name": "NO2",
        },
        {
            "year": 2025,
            "date": pd.Timestamp("2025-01-02").date(),
            "time": "00:00:00",
            "station_id": "site_302",
            "pollutant_name": "PM10",
        },
    ]
