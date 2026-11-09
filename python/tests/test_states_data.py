"""The named states of AQI sufficiency, PM2.5, GEE, OAQ, the dump script and the CLI."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import warnings
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests

from vayuayan import PM25Client, commands, gee, pm25
from vayuayan.aqi import compute_aqi, daily_aqi
from vayuayan.cli_render import render
from vayuayan.cli_results import error_result
from vayuayan.exceptions import (
    AmbiguousMatchError,
    AuthenticationError,
    CPCBError,
    DataNotFoundError,
    NetworkError,
    PM25DownloadError,
)
from vayuayan.oaq import OAQClient
from vayuayan.us_aqi import compute_us_aqi
from vayuayan.us_aqi_daily import daily_us_aqi
from vayuayan.utils import stations_to_coordinates_dataframe, stations_to_dataframe

from .cli_fakes import FakeHistorical, FakeLive, feed, recording, text_of
from .fakes import http_response

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "dump_raw_15min_pollutants.py"
)
SPEC = importlib.util.spec_from_file_location("dump_for_states", SCRIPT)
dump = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(dump)


# ---- item 10: daily AQI sufficiency


def _hours(pollutant, hours, value, day="2024-01-01", unit="µg/m³"):
    return pd.DataFrame(
        {
            "station_id": "s",
            "timestamp": pd.date_range(f"{day} 00:00", periods=hours, freq="h"),
            "pollutant": pollutant,
            "unit": unit,
            "value": value,
        }
    )


def _status_of(table):
    return table.loc[0, "aqi_status"]


@pytest.mark.parametrize(
    "values,status",
    [
        ({"PM2.5": 40, "PM10": 80, "NO2": 30}, "ok"),
        ({"NO2": 30, "SO2": 20, "CO": 1}, "no_pm"),
        ({"PM2.5": 40, "NO2": 30}, "too_few_pollutants"),
        ({}, "no_pm"),
    ],
)
def test_compute_aqi_status(values, status):
    result = compute_aqi(values)

    assert result.status == status
    assert result.sufficient is (status == "ok")


def test_compute_us_aqi_status():
    assert compute_us_aqi({"PM2.5": 35.4}).status == "ok"
    assert compute_us_aqi({"NO2": None}).status == "no_sub_index"
    assert compute_us_aqi({"O3": 0.3}).status == "o3_beyond_table"


def test_daily_aqi_hours_come_before_pm_and_count():
    long = pd.concat(
        [
            _hours("PM2.5", 10, 40.0),  # too few hours
            _hours("NO2", 24, 30.0),
            _hours("SO2", 24, 20.0),
            _hours("NH3", 24, 20.0),
        ]
    )

    table = daily_aqi(long)

    assert pd.isna(table.loc[0, "PM2.5_sub_index"])
    assert _status_of(table) == "too_few_hours"
    assert pd.isna(table.loc[0, "aqi"])


def test_daily_aqi_no_pm_and_too_few_pollutants():
    no_pm = pd.concat([_hours("NO2", 24, 30.0), _hours("SO2", 24, 20.0)])
    assert _status_of(daily_aqi(no_pm)) == "no_pm"

    few = pd.concat([_hours("PM2.5", 24, 40.0), _hours("NO2", 24, 30.0)])
    assert _status_of(daily_aqi(few)) == "too_few_pollutants"


def test_daily_aqi_ok_day():
    long = pd.concat(
        [
            _hours("PM2.5", 24, 40.0),
            _hours("NO2", 24, 30.0),
            _hours("SO2", 24, 20.0),
        ]
    )

    assert _status_of(daily_aqi(long)) == "ok"


def test_daily_aqi_short_extra_pollutant_stays_ok():
    long = pd.concat(
        [
            _hours("PM2.5", 24, 40.0),
            _hours("NO2", 24, 30.0),
            _hours("SO2", 24, 20.0),
            _hours("NH3", 5, 20.0),
        ]
    )

    assert _status_of(daily_aqi(long)) == "ok"


def test_daily_us_aqi_statuses():
    ok = daily_us_aqi(_hours("PM2.5", 24, 40.0))
    assert _status_of(ok) == "ok"

    short = daily_us_aqi(_hours("PM2.5", 10, 40.0))
    assert _status_of(short) == "too_few_hours"


def test_daily_us_aqi_o3_beyond_table_comes_first(caplog):
    long = pd.concat(
        [
            _hours("O3", 24, 0.3, unit="ppm"),
            _hours("PM2.5", 5, 40.0),  # short, but more hours would not fix the O3
        ]
    )

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        table = daily_us_aqi(long)

    assert _status_of(table) == "o3_beyond_table"
    assert pd.isna(table.loc[0, "aqi"])


@pytest.mark.parametrize("compute", [daily_aqi, daily_us_aqi])
def test_empty_input_without_a_station_column_has_the_columns(compute):
    empty = pd.DataFrame(columns=["timestamp", "pollutant", "value"])

    with warnings.catch_warnings():
        warnings.simplefilter("error", FutureWarning)
        out = compute(empty)

    assert out.empty and "aqi_status" in out.columns


# ---- item 11: station status


def test_status_says_no_reading_for_live_without_aqi():
    cities = [
        {
            "cityName": "C",
            "stationsInCity": [
                {"id": "a", "live": True, "avg": "90", "latitude": 1, "longitude": 2},
                {"id": "b", "live": True, "avg": "", "latitude": 1, "longitude": 2},
                {"id": "c", "live": False, "avg": "", "latitude": 1, "longitude": 2},
            ],
        }
    ]

    expected = ["Live", "No Reading", "Offline"]
    assert stations_to_dataframe(cities)["status"].tolist() == expected
    assert stations_to_coordinates_dataframe(cities)["status"].tolist() == expected


# ---- item 6: PM2.5 source chain


@pytest.fixture
def client(tmp_path):
    pm25_client = PM25Client(version="V6", cache_dir=str(tmp_path))
    pm25_client._gee_initialized = False  # never start real Earth Engine
    return pm25_client


def _s3_fails(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("no S3")

    monkeypatch.setattr(pm25.http_client, "request", fail)


def test_a_cached_tif_warns_that_it_is_coarse(client, caplog):
    tif = Path(client.get_netcdf_path(2020, 1)).with_suffix(".tif")
    tif.write_bytes(b"tif")

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        assert client.download_netcdf_if_needed(2020, 1) == str(tif)

    assert "coarse Google Earth Engine fallback" in caplog.text


def test_a_small_netcdf_is_not_usable(client, real_size_rule, monkeypatch):
    path = Path(client.get_netcdf_path(2020, 1))
    path.write_bytes(b"x" * pm25.MIN_CACHED_BYTES)
    monkeypatch.setattr(client, "_download_from_gee", lambda *a: None)
    _s3_fails(monkeypatch)

    with pytest.raises(PM25DownloadError):
        client.download_netcdf_if_needed(2020, 1)


def test_a_netcdf_above_one_mib_is_used(client, real_size_rule):
    path = Path(client.get_netcdf_path(2020, 1))
    path.write_bytes(b"x" * (pm25.MIN_CACHED_BYTES + 1))

    assert client.download_netcdf_if_needed(2020, 1) == str(path)


def test_a_tif_is_kept_under_the_size_rule(client, real_size_rule):
    tif = Path(client.get_netcdf_path(2020, 1)).with_suffix(".tif")
    tif.write_bytes(b"tif")

    assert client.download_netcdf_if_needed(2020, 1) == str(tif)


def test_download_error_is_both_kinds_of_error(client, monkeypatch):
    monkeypatch.setattr(client, "_download_from_gee", lambda *a: None)
    _s3_fails(monkeypatch)

    with pytest.raises(PM25DownloadError) as err:
        client.download_netcdf_if_needed(2020, 1)

    assert isinstance(err.value, requests.RequestException)
    assert isinstance(err.value, CPCBError)
    assert "manually" in str(err.value)


def test_gee_is_skipped_outside_india_regions(tmp_path):
    europe = PM25Client(version="V6", cache_dir=str(tmp_path), region="EU")
    europe._gee_initialized = True

    assert "EU" in europe._gee_skip_reason(2020)


def test_gee_is_still_used_for_a_region_with_india(tmp_path):
    asia = PM25Client(version="V6", cache_dir=str(tmp_path), region="AS")
    asia._gee_initialized = True

    assert asia._gee_skip_reason(2020) is None


def test_monthly_stats_report_the_failed_months(client, monkeypatch):
    def stats(geojson, year, month, group_by):
        if month == 2:
            raise requests.ConnectionError("down")
        return {"mean": 1.0, "std": 0.0, "min": 1.0, "max": 1.0}

    monkeypatch.setattr(client, "get_pm25_stats", stats)

    table = client.get_pm25_monthly_stats("x.geojson", 2020, months=[1, 2])

    assert table["month"].tolist() == [1]
    assert table.attrs["failed_months"] == [2]


def test_all_months_failing_still_reports_them(client, monkeypatch):
    def stats(*args):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(client, "get_pm25_stats", stats)

    table = client.get_pm25_monthly_stats("x.geojson", 2020, months=[3])

    assert table.empty and table.attrs["failed_months"] == [3]


# ---- item 13: GEE setup


@pytest.fixture
def ee(monkeypatch, tmp_path):
    stub = MagicMock(name="ee")
    monkeypatch.setitem(sys.modules, "ee", stub)
    monkeypatch.setattr(gee, "is_available", lambda: True)
    monkeypatch.setattr(gee, "get_gee_project_file", lambda: tmp_path / "project")
    return stub


def _stdin(monkeypatch, is_terminal):
    monkeypatch.setattr(sys, "stdin", MagicMock(isatty=lambda: is_terminal))


def test_setup_authenticates_only_after_initialize_fails(ee, monkeypatch):
    _stdin(monkeypatch, True)
    ee.Initialize.side_effect = [RuntimeError("no credentials"), None]

    assert gee.setup_earth_engine("p") is True
    ee.Authenticate.assert_called_once_with(force=True)


def test_setup_without_a_terminal_never_prompts(ee, monkeypatch):
    _stdin(monkeypatch, False)
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=AssertionError))

    assert gee.setup_earth_engine() is False
    ee.Authenticate.assert_not_called()


def test_setup_without_a_terminal_does_not_open_a_browser(ee, monkeypatch):
    _stdin(monkeypatch, False)
    ee.Initialize.side_effect = RuntimeError("no credentials")

    assert gee.setup_earth_engine("p") is False
    ee.Authenticate.assert_not_called()


def test_a_failing_project_warns_before_the_default(ee, monkeypatch, caplog):
    monkeypatch.setattr(gee, "project_id", lambda: "mine")
    ee.Initialize.side_effect = [RuntimeError("a"), RuntimeError("denied"), None]

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        assert gee.initialize() is True

    assert "GEE project mine failed (denied)" in caplog.text


# ---- item 14: OAQ session expiry


@pytest.mark.parametrize("status", [401, 403])
def test_an_expired_oaq_session_stops_the_run(monkeypatch, status):
    client = OAQClient.__new__(OAQClient)
    client.base_url, client.sig_string = "https://oaq.example", "sig=SECRET"

    def refuse(*args, **kwargs):
        raise requests.HTTPError("x", response=http_response(status=status))

    monkeypatch.setattr("vayuayan.oaq.http_client.request", refuse)

    with pytest.raises(AuthenticationError) as err:
        client.daily_records("cpcb", "s1", [2023, 2024])

    assert "SECRET" not in str(err.value)


@pytest.mark.parametrize("status", [404, 500])
def test_other_oaq_failures_still_keep_going(monkeypatch, status):
    client = OAQClient.__new__(OAQClient)
    client.base_url, client.sig_string = "https://oaq.example", "sig=1"

    def fail(*args, **kwargs):
        raise requests.HTTPError("x", response=http_response(status=status))

    monkeypatch.setattr("vayuayan.oaq.http_client.request", fail)

    assert client.daily_records("cpcb", "s1", [2024]).empty


# ---- item 3: dump script


STATION = {"station_id": "s", "station_name": "N", "city": "C", "state": "S"}
RAW = pd.DataFrame({"Timestamp": ["2020-06-01 00:00:00"], "PM2.5 (µg/m³)": [20.0]})


class _Dump:
    def __init__(self, outcome=RAW):
        self.outcome = outcome
        self.calls = 0

    def download_raw_aqi_data_station_level(self, *args, **kwargs):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def test_past_year_shard_and_marker_are_honoured(tmp_path):
    client = _Dump()

    assert dump.dump_station_year(client, STATION, 2020, tmp_path) == "written:1"
    assert dump.dump_station_year(client, STATION, 2020, tmp_path) == "cached"
    assert client.calls == 1

    empty = _Dump(DataNotFoundError("none"))
    assert dump.dump_station_year(empty, STATION, 2019, tmp_path) == "empty"
    assert dump.dump_station_year(empty, STATION, 2019, tmp_path) == "empty-cached"


def test_current_year_is_always_fetched(tmp_path):
    year = date.today().year
    rows = pd.DataFrame(
        {"Timestamp": [f"{year}-01-01 00:00:00"], "PM2.5 (µg/m³)": [20.0]}
    )
    client = _Dump(rows)

    assert dump.dump_station_year(client, STATION, year, tmp_path) == "written:1"
    assert dump.dump_station_year(client, STATION, year, tmp_path) == "written:1"
    assert client.calls == 2


def test_an_outage_writes_no_marker(tmp_path):
    client = _Dump(NetworkError("down"))

    with pytest.raises(NetworkError):
        dump.dump_station_year(client, STATION, 2020, tmp_path)

    assert not list(tmp_path.rglob("*.empty"))
    assert not list(tmp_path.rglob("*.part"))


def test_a_date_range_shard_stays_out_of_the_year_shards(tmp_path):
    client = _Dump()

    dump.dump_station_year(
        client, STATION, 2020, tmp_path, False, date(2020, 1, 1), date(2020, 12, 31)
    )

    assert dump.collect_parquet_files(tmp_path) == []
    label = dump.range_label(date(2020, 1, 1), date(2020, 12, 31))
    assert len(dump.collect_parquet_files(tmp_path, label)) == 1


def test_station_parquet_is_rebuilt_when_a_shard_is_newer(tmp_path):
    cache, out = tmp_path / "cache", tmp_path / "out"
    dump.dump_station_year(_Dump(), STATION, 2020, cache)

    assert dump.build_station_parquet(cache, out, "s").startswith("written")
    assert dump.build_station_parquet(cache, out, "s") == "cached"

    built = dump.station_parquet_path(out, "s")
    old = built.stat().st_mtime - 100
    os.utime(built, (old, old))

    assert dump.build_station_parquet(cache, out, "s").startswith("written")


def _run_main(monkeypatch, tmp_path, client):
    monkeypatch.setattr(dump, "CPCBHistorical", lambda use_cache=False: client)
    monkeypatch.setattr(
        dump,
        "iter_master_stations",
        lambda *a, **k: iter([{**STATION, "city_code": "x", "state_code": "y"}]),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "dump",
            "--cache",
            str(tmp_path / "cache"),
            "--station-out-dir",
            str(tmp_path / "stations"),
            "--out",
            str(tmp_path / "all.parquet"),
            "--duckdb-temp-dir",
            str(tmp_path / "tmp"),
            "--start-year",
            "2020",
            "--end-year",
            "2020",
            "--sleep",
            "0",
        ],
    )
    return dump.main()


def test_main_succeeds_and_prints_a_summary(monkeypatch, tmp_path, capsys):
    assert _run_main(monkeypatch, tmp_path, _Dump()) == 0
    assert "summary: 1 written" in capsys.readouterr().out
    assert (tmp_path / "all.parquet").exists()


def test_main_exits_nonzero_when_something_failed(monkeypatch, tmp_path, capsys):
    assert _run_main(monkeypatch, tmp_path, _Dump(NetworkError("down"))) == 1
    assert "1 failed" in capsys.readouterr().out


def test_main_exits_nonzero_when_nothing_was_found(monkeypatch, tmp_path):
    assert _run_main(monkeypatch, tmp_path, _Dump(DataNotFoundError("x"))) == 1


# ---- the CLI uses the richer library information


def _city_place():
    table = FakeHistorical().station_table()
    place = commands.lookup_place(FakeHistorical(table), "Mumbai")
    assert place.status == "city"
    return place


def _report_request():
    from datetime import datetime

    return commands.ReportRequest(datetime(2026, 1, 1), datetime(2026, 1, 2))


class _Partial(FakeHistorical):
    def __init__(self, status):
        super().__init__()
        self.status = status

    def download_city_report(self, *args, **kwargs):
        table = pd.DataFrame(
            {"Timestamp": ["2026-01-01"], "PM2.5 (µg/m³)": [1.0], "station_id": ["a"]}
        )
        table.attrs["station_status"] = self.status
        return table


def test_a_partial_report_in_an_outage_is_visible():
    status = {"a": "ok", "b": "outage", "c": "not_attempted"}

    result = commands.history_report(_Partial(status), _city_place(), _report_request())

    assert result.exit_code == 0
    document = json.loads(json.dumps(result.to_document()))
    assert document["partial"] is True
    assert document["station_status"] == status
    assert "stopped answering" in document["message"]

    out = recording()
    render(result, out, recording())
    assert "stopped answering" in text_of(out)


def test_a_complete_report_is_not_partial():
    result = commands.history_report(
        _Partial({"a": "ok"}), _city_place(), _report_request()
    )

    assert result.status == "ok" and result.message == ""
    assert result.data["partial"] is False


def test_an_ambiguous_library_error_exits_4_with_its_candidates():
    error = AmbiguousMatchError("City is in two states: A; B", ["A", "B"])

    result = error_result("history", error)

    assert result.status == "ambiguous" and result.exit_code == 4
    assert result.to_document()["candidates"] == ["A", "B"]

    err = recording()
    render(result, recording(), err)
    assert "A; B" in text_of(err)


def test_an_outage_error_carries_the_station_status():
    error = NetworkError("CPCB is unavailable")
    error.station_status = {"a": "outage"}

    result = error_result("history", error)

    assert result.exit_code == 6
    assert result.to_document()["station_status"] == {"a": "outage"}


def test_a_pm25_failure_keeps_the_manual_instructions():
    result = error_result("pm25", PM25DownloadError("Download it manually from X"))

    assert result.exit_code == 6 and "manually" in result.message


def test_live_json_has_source_state_and_as_of():
    client = FakeLive()
    client.station_list_source = "rss"
    station = commands.lookup_place(FakeHistorical(), "Powai")

    result = commands.live_place(client, station)
    reading = result.to_document()["reading"]

    assert reading["source"] == "rss"
    assert reading["reading_state"] == "reading"
    assert reading["as_of"] == feed()[0]["stationsInCity"][0]["lastUpdate"]

    out = recording(width=100)
    render(result, out, recording())
    assert "CPCB RSS feed" in text_of(out)


def test_a_failed_live_fetch_has_no_reading_state():
    client = FakeLive(down=True)
    station = commands.lookup_place(FakeHistorical(), "Powai")

    reading = commands.live_place(client, station).data["reading"]

    assert reading["reading_state"] == "no_reading" and reading["as_of"] is None


def test_days_without_an_aqi_reach_json_and_the_display():
    table = pd.DataFrame(
        {
            "date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)],
            "aqi": pd.array([80, pd.NA, pd.NA], dtype="Int64"),
            "dominant_pollutant": ["PM2.5", None, None],
            "aqi_status": ["ok", "too_few_hours", "no_pm"],
        }
    )

    class Computed(FakeHistorical):
        def daily_aqi(self, *args, **kwargs):
            return table

    request = commands.HistoryRequest(year=2024, computed=True)
    station = commands.place_for_request(
        commands.lookup_place(Computed(), "Powai"), request
    )

    result = commands.history(Computed(), station, request, today=date(2025, 1, 1))

    assert result.status == "ok"
    assert result.data["days_without_aqi"] == {"too_few_hours": 1, "no_pm": 1}
    out = recording()
    render(result, out, recording())
    assert "1 too few hours" in text_of(out)


def test_no_computed_day_says_why():
    table = pd.DataFrame(
        {
            "date": [date(2024, 1, 2)],
            "aqi": pd.array([pd.NA], dtype="Int64"),
            "dominant_pollutant": [None],
            "aqi_status": ["too_few_hours"],
        }
    )

    class Computed(FakeHistorical):
        def daily_aqi(self, *args, **kwargs):
            return table

    request = commands.HistoryRequest(year=2024, computed=True)
    station = commands.lookup_place(Computed(), "Powai")

    result = commands.history(Computed(), station, request)

    assert result.status == "no_data" and result.exit_code == 5
    assert "enough data" in result.message
