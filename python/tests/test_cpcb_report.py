"""CPCB's report export: the exact request, the Excel parsing and the failures."""

from __future__ import annotations

import io
import json
from datetime import datetime

import pandas as pd
import pytest
import requests

from vayuayan import CPCBHistorical, cpcb_report
from vayuayan.exceptions import (
    CityNotFoundError,
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)
from vayuayan.tidy import cpcb_raw_to_long

from .fakes import http_response

URL = "https://airquality.cpcb.gov.in/cpcb-common-report/api/excel/export"
NOW = datetime(2026, 11, 9, 10, 3, 37)
INFO = {
    "station_id": "site_301",
    "station_name": "Anand Vihar, Delhi - DPCC",
    "state": "Delhi",
    "city": "Delhi",
}
HEADINGS = [
    "From Date", "To Date", "PM2.5", "PM10", "NO", "NO2", "NOX", "NH3", "SO2",
    "CO", "OZONE",
]  # fmt: skip
ALL_KEYS = "PM25,PM10,NO,NO2,NOx,NH3,SO2,CO,Ozone"
ALL_LABELS = [
    "PM2.5 (µg/m³)", "PM10 (µg/m³)", "NO (µg/m³)", "NO2 (µg/m³)", "NOx (ppb)",
    "NH3 (µg/m³)", "SO2 (µg/m³)", "CO (mg/m³)", "Ozone (µg/m³)",
]  # fmt: skip


def _xlsx(rows, sheet="Report"):
    buffer = io.BytesIO()
    pd.DataFrame(rows).to_excel(buffer, header=False, index=False, sheet_name=sheet)
    return buffer.getvalue()


def _report(data_rows=None, headings=HEADINGS, footer=True):
    blank = [None] * len(headings)
    rows = [
        ["CENTRAL POLLUTION CONTROL BOARD"] + blank[1:],
        ["State", None, "Delhi"] + blank[3:],
        ["Station", None, "Anand Vihar, Delhi - DPCC"] + blank[3:],
        headings,
    ]
    if data_rows is None:
        data_rows = [
            ["01-11-2025 00:00", "01-11-2025 00:15"] + [None] * 9,
            ["01-11-2025 00:15", "01-11-2025 00:30", 146, 309, 165.2, 103, 189.1,
             0.1, 61.8, None, 19],
            ["01-11-2025 00:30", "01-11-2025 00:45", 150, 312, 167.3, 119.5, 199.6,
             11.9, 66.7, 4.05, 18.5],
        ]  # fmt: skip
    rows += data_rows
    if footer:
        rows += [["Average"] + blank[1:], ["Min"] + blank[1:]]
    return _xlsx(rows)


@pytest.fixture
def client(tmp_path, monkeypatch):
    instance = CPCBHistorical(cache_dir=str(tmp_path / "cpcb"))
    monkeypatch.setattr(instance, "_resolved_station", lambda *a, **k: dict(INFO))
    monkeypatch.setattr(cpcb_report, "_now", lambda: NOW)
    return instance


def test_request_url_method_headers_and_full_body(client, network):
    network.on("post", URL, http_response(_report()))

    client.download_station_report(
        "site_301", "2026-11-01 00:00:00", "2026-11-01 06:00:00"
    )

    assert len(network.calls) == 1
    call = network.calls[0]
    assert (call.method, call.url) == ("post", URL)
    assert call.kwargs["headers"] == {
        "Content-Type": "application/json",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    assert "Authorization" not in call.kwargs["headers"]
    assert call.kwargs["json"] == {
        "reportDate": "09-11-2026",
        "reportTime": "10:03:37",
        "stationId": "site_301",
        "state": "Delhi",
        "city": "Delhi",
        "station": "Anand Vihar, Delhi - DPCC",
        "parameters": ALL_KEYS,
        "columns": f"from_time,to_time,{ALL_KEYS}",
        "avgPeriod": "15M",
        "fromDate": "2026-11-01 00:00:00",
        "toDate": "2026-11-01 06:00:00",
        "callid": "get-real-time-report-excel",
        "templateId": "get-real-time-report-excel",
        "callIdArguments": "stationId,fromDate,toDate,avgPeriod,parameters",
    }


def test_the_table_has_the_raw_file_columns_and_stops_at_the_footer(client, network):
    network.on("post", URL, http_response(_report()))

    df = client.download_station_report("site_301", "2025-11-01", "2025-11-02")

    assert list(df.columns) == ["Timestamp"] + ALL_LABELS
    assert df["Timestamp"].tolist() == [
        "2025-11-01 00:00:00",
        "2025-11-01 00:15:00",
        "2025-11-01 00:30:00",
    ]
    assert df.loc[0, "PM2.5 (µg/m³)"] != df.loc[0, "PM2.5 (µg/m³)"]  # blank is missing
    assert df.loc[1, "CO (mg/m³)"] != df.loc[1, "CO (mg/m³)"]
    assert df.loc[2, "CO (mg/m³)"] == pytest.approx(4.05)
    assert df.loc[1, "NOx (ppb)"] == pytest.approx(189.1)


def test_cpcb_raw_to_long_works_unchanged(client, network):
    network.on("post", URL, http_response(_report()))
    wide = client.download_station_report("site_301", "2025-11-01", "2025-11-02")
    long = cpcb_raw_to_long(wide, INFO)
    co = long[long["pollutant"] == "CO"]
    assert co["unit"].tolist() == ["mg/m³"]
    assert co["value"].tolist() == [4.05]


def test_tidy_and_save_location(client, network, tmp_path):
    network.on("post", URL, http_response(_report()))
    path = tmp_path / "report.csv"

    long = client.download_station_report(
        "site_301", "2025-11-01", "2025-11-02", tidy=True, save_location=str(path)
    )

    assert set(long["station_id"]) == {"site_301"}
    assert set(long["city"]) == {"Delhi"}
    assert list(pd.read_csv(path).columns) == list(long.columns)


def test_a_blank_from_date_ends_the_table(client, network):
    rows = [
        ["01-11-2025 00:00", "01-11-2025 00:15"] + [10] * 9,
        [None, None] + [99] * 9,
        ["01-11-2025 00:30", "01-11-2025 00:45"] + [20] * 9,
    ]
    network.on("post", URL, http_response(_report(rows, footer=False)))
    df = client.download_station_report("site_301", "2025-11-01", "2025-11-02")
    assert df["Timestamp"].tolist() == ["2025-11-01 00:00:00"]


def test_datetime_cells_are_accepted(client, network):
    rows = [
        [datetime(2025, 11, 1, 0, 0), datetime(2025, 11, 1, 0, 15)] + [10] * 9,
    ]
    network.on("post", URL, http_response(_report(rows, footer=False)))
    df = client.download_station_report("site_301", "2025-11-01", "2025-11-02")
    assert df["Timestamp"].tolist() == ["2025-11-01 00:00:00"]


@pytest.mark.parametrize(
    "frequency, period",
    [
        ("15_minute", "15M"), ("15M", "15M"), ("30_minute", "30M"), ("30M", "30M"),
        ("hourly", "1H"), ("1H", "1H"), ("1_hour", "1H"), ("4_hour", "4H"), ("4H", "4H"),
        ("8_hour", "8H"), ("8H", "8H"), ("daily", "24H"), ("24H", "24H"),
        ("24_hours", "24H"), ("1d", "24H"),
    ],
)  # fmt: skip
def test_frequencies(frequency, period):
    body = cpcb_report.report_payload(INFO, "2025-01-01", "2025-01-02", frequency, None)
    assert body["avgPeriod"] == period


def test_frequency_must_be_known():
    with pytest.raises(ValueError, match="frequency"):
        cpcb_report.report_payload(INFO, "2025-01-01", "2025-01-02", "weekly", None)


@pytest.mark.parametrize(
    "names, keys",
    [
        (["PM2.5", "pm25", "NOx"], "PM25,NOx"),
        (["O3", "Ozone", "NH3"], "Ozone,NH3"),
        (["NOX", "CO"], "NOx,CO"),
        ("PM10", "PM10"),
    ],
)
def test_pollutant_names_become_request_keys(names, keys):
    body = cpcb_report.report_payload(INFO, "2025-01-01", "2025-01-02", "1H", names)
    assert body["parameters"] == keys
    assert body["columns"] == f"from_time,to_time,{keys}"


@pytest.mark.parametrize("pollutants", [["Benzene"], []])
def test_pollutants_must_be_known(pollutants):
    with pytest.raises(ValueError):
        cpcb_report.report_payload(INFO, "2025-01-01", "2025-01-02", "1H", pollutants)


def test_date_objects_are_midnight():
    body = cpcb_report.report_payload(
        INFO, datetime(2025, 1, 1), datetime(2025, 1, 2, 6, 30), "1H", None
    )
    assert body["fromDate"] == "2025-01-01 00:00:00"
    assert body["toDate"] == "2025-01-02 06:30:00"


def test_unknown_station(tmp_path, monkeypatch, network):
    client = CPCBHistorical(cache_dir=str(tmp_path))
    monkeypatch.setattr(client, "_resolved_station", lambda *a, **k: None)
    with pytest.raises(StationNotFoundError):
        client.download_station_report("nowhere", "2025-11-01", "2025-11-02")
    assert network.calls == []


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<html>error</html>",
        json.dumps({"status": "failed"}).encode(),
        b"PK\x03\x04broken",
    ],
)
def test_unusable_bodies_are_no_data(client, network, body):
    network.on("post", URL, http_response(body))
    with pytest.raises(DataNotFoundError):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")


def test_a_workbook_without_the_table_is_no_data(client, network):
    network.on("post", URL, http_response(_xlsx([["CPCB", None], ["State", "Delhi"]])))
    with pytest.raises(DataNotFoundError, match="data table"):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")


def test_a_table_with_only_blank_readings_is_no_data(client, network):
    rows = [["01-11-2025 00:00", "01-11-2025 00:15"] + [None] * 9]
    network.on("post", URL, http_response(_report(rows)))
    with pytest.raises(DataNotFoundError, match="no readings"):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")


def test_http_500_is_no_data(client, network):
    network.on("post", URL, http_response(b"Excel generation failed", status=500))
    with pytest.raises(DataNotFoundError, match="could not build"):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")


def test_other_http_errors_and_outages_are_network_errors(client, network):
    network.on("post", URL, http_response(b"", status=503))
    with pytest.raises(NetworkError):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")

    network.on("post", URL, requests.ConnectionError("down"))
    with pytest.raises(NetworkError):
        client.download_station_report("site_301", "2025-11-01", "2025-11-02")


def test_reports_are_never_cached(client, network, tmp_path):
    network.on("post", URL, http_response(_report()))
    client.download_station_report("site_301", "2020-11-01", "2020-11-02")
    client.download_station_report("site_301", "2020-11-01", "2020-11-02")
    assert len(network.calls) == 2
    assert not (tmp_path / "cpcb").exists()


def test_station_table_lists_stations_with_coordinates():
    client = CPCBHistorical()

    delhi = client.station_table(city="delhi")

    assert list(delhi.columns) == [
        "station_id",
        "station_name",
        "city",
        "state",
        "latitude",
        "longitude",
    ]
    assert "site_301" in set(delhi["station_id"])
    assert set(delhi["city"]) == {"Delhi"}
    assert delhi["latitude"].notna().all()
    assert list(delhi["station_name"]) == sorted(delhi["station_name"])
    assert len(client.station_table()) > len(delhi)
    assert len(client.station_table(state="Delhi")) == len(delhi)
    assert client.station_table(city="Delhi", state="Kerala").empty
    assert client.station_table(city="nowhere").empty


def test_city_report_joins_stations_and_skips_those_without_a_report(tmp_path):
    client = CPCBHistorical()
    asked = []

    def report(station_id, *args, **kwargs):
        asked.append(station_id)
        if station_id == "site_301":
            raise DataNotFoundError("no report")
        return pd.DataFrame({"Timestamp": ["2026-11-08 00:00:00"], "PM2.5": [50]})

    client.download_station_report = report
    output = tmp_path / "delhi.csv"

    out = client.download_city_report(
        "Delhi", "2026-11-08", "2026-11-09", save_location=str(output)
    )

    assert list(out.columns[:3]) == ["station_id", "station_name", "Timestamp"]
    assert set(asked) == set(client.station_table(city="Delhi")["station_id"])
    assert "site_301" not in set(out["station_id"])
    assert len(out) == len(asked) - 1
    assert len(pd.read_csv(output)) == len(out)


def test_city_report_of_an_unknown_city_raises():
    with pytest.raises(CityNotFoundError, match="nowhere"):
        CPCBHistorical().download_city_report("nowhere", "2026-11-08", "2026-11-09")


def test_city_report_with_no_station_data_raises():
    client = CPCBHistorical()

    def report(*args, **kwargs):
        raise DataNotFoundError("no report")

    client.download_station_report = report

    with pytest.raises(DataNotFoundError, match="Delhi"):
        client.download_city_report("Delhi", "2026-11-08", "2026-11-09")


def test_tidy_city_report_adds_no_columns():
    client = CPCBHistorical()
    client.download_station_report = lambda *a, **k: pd.DataFrame({"value": [1]})

    out = client.download_city_report("Delhi", "2026-11-08", "2026-11-09", tidy=True)

    assert list(out.columns) == ["value"]
