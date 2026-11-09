"""Saved files: the format comes from the extension and rows are sorted ascending."""

from __future__ import annotations

import argparse
import json

import pandas as pd
import pytest

from vayuayan import cli, cli_parser, commands
from vayuayan.cli_places import catalogue_from_table, resolve_place
from vayuayan.cli_results import write_table

from .cli_fakes import NOW, FakeLive, catalogue, recording

STATIONS = catalogue_from_table(catalogue())


def _place(query):
    return resolve_place(query, STATIONS)


UNSORTED = pd.DataFrame(
    {"date": ["2026-11-03", "2026-11-01", "2026-11-02"], "aqi": [3, 1, 2]}
)


def _read(path):
    if path.suffix.lower() == ".json":
        return pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


@pytest.mark.parametrize("name", ["x.csv", "x.json", "x.parquet", "X.JSON"])
def test_each_format_is_written_sorted_by_date(tmp_path, name):
    path = tmp_path / "new" / name

    write_table(UNSORTED, str(path))

    table = _read(path)
    assert table["date"].astype(str).tolist() == [
        "2026-11-01",
        "2026-11-02",
        "2026-11-03",
    ]
    assert table["aqi"].tolist() == [1, 2, 3]


def test_json_is_a_list_of_records(tmp_path):
    path = tmp_path / "x.json"

    write_table(UNSORTED, str(path))

    assert json.loads(path.read_text(encoding="utf-8"))[0] == {
        "date": "2026-11-01",
        "aqi": 1,
    }


def test_stations_sort_by_state_city_then_name(tmp_path):
    table = pd.DataFrame(
        {
            "state": ["Punjab", "Delhi", "Delhi"],
            "city": ["Patiala", "Delhi", "Delhi"],
            "station_name": ["A", "Z", "B"],
        }
    )
    path = tmp_path / "x.csv"

    write_table(table, str(path))

    assert pd.read_csv(path)["station_name"].tolist() == ["B", "Z", "A"]


def test_report_rows_sort_by_station_then_time(tmp_path):
    table = pd.DataFrame(
        {
            "station_id": ["b", "a", "a"],
            "station_name": ["B", "A", "A"],
            "Timestamp": pd.to_datetime(
                ["2026-11-08 00:00", "2026-11-08 01:00", "2026-11-08 00:00"]
            ),
        }
    )
    path = tmp_path / "x.parquet"

    write_table(table, str(path))

    saved = pd.read_parquet(path)
    assert saved["station_id"].tolist() == ["a", "a", "b"]
    assert saved["Timestamp"].is_monotonic_increasing is False
    assert saved["Timestamp"].iloc[0] < saved["Timestamp"].iloc[1]


def test_a_failed_write_leaves_no_file(tmp_path, monkeypatch):
    def fail(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail)
    path = tmp_path / "x.csv"

    with pytest.raises(OSError):
        write_table(UNSORTED, str(path))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["x.csv", "x.JSON", "a/b.parquet"])
def test_save_path_accepts_the_three_formats(name):
    assert cli_parser.save_path(name) == name


@pytest.mark.parametrize("name", ["x.xlsx", "x", "x.csv.gz"])
def test_save_path_rejects_anything_else(name):
    with pytest.raises(argparse.ArgumentTypeError, match="parquet"):
        cli_parser.save_path(name)


def test_parquet_without_pyarrow_says_how_to_install(monkeypatch):
    monkeypatch.setattr(cli_parser.importlib.util, "find_spec", lambda name: None)

    with pytest.raises(argparse.ArgumentTypeError, match=r"vayuayan\[parquet\]"):
        cli_parser.save_path("x.parquet")


@pytest.mark.parametrize(
    "command", [["live", "powai"], ["find", "powai"], ["stations"]]
)
def test_a_bad_extension_is_a_usage_error_before_any_fetch(command, tmp_path):
    with pytest.raises(SystemExit) as stopped:
        code = cli.run(
            [*command, "--save", str(tmp_path / "x.xlsx")], recording(), recording()
        )
        raise SystemExit(code)

    assert stopped.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_live_station_saves_one_flat_row(tmp_path):
    path = tmp_path / "powai.csv"

    result = commands.live_place(FakeLive(), _place("powai"), NOW, save=str(path))

    assert result.data["saved"] == str(path)
    row = pd.read_csv(path).iloc[0]
    assert row["station_id"] == "site_1"
    assert row["aqi"] == 82
    assert row["city"] == "Mumbai"
    assert pd.notna(row["latitude"])
    assert "collected_at" in row.index


def test_live_city_file_is_sorted_though_the_display_is_worst_first(tmp_path):
    path = tmp_path / "mumbai.json"

    result = commands.live_place(FakeLive(), _place("mumbai"), NOW, save=str(path))

    saved = [r["station_name"] for r in json.loads(path.read_text(encoding="utf-8"))]
    assert saved == sorted(saved)
    shown = [r["aqi"] for r in result.data["readings"] if r["aqi"] is not None]
    assert shown == sorted(shown, reverse=True)


def test_live_near_saves_the_reading(tmp_path):
    path = tmp_path / "near.parquet"

    result = commands.live_near(FakeLive(), (19.13, 72.91), NOW, save=str(path))

    assert result.data["saved"] == str(path)
    assert pd.read_parquet(path)["station_id"].tolist() == ["site_1"]


def test_live_writes_nothing_when_the_feed_is_down(tmp_path):
    path = tmp_path / "x.csv"

    commands.live_place(FakeLive(down=True), _place("powai"), NOW, save=str(path))

    assert not path.exists()
