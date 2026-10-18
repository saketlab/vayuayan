"""Tests for the CPCB historical API code."""

import io
from datetime import date

import pandas as pd
import pytest
import requests

import vayuayan.cpcb_common as cpcb_common
from vayuayan import CPCBHistorical
from vayuayan.exceptions import NetworkError, StationNotFoundError

from .fakes import FakeResponse, raise_connection_error


def test_normalize_frequency_preserves_package_compatibility():
    client = CPCBHistorical()

    assert client._normalize_frequency("hourly") == "1H"
    assert client._normalize_frequency("daily") == "1D"
    assert client._normalize_frequency("monthly") == "1M"
    assert client._normalize_frequency("15_minute") == "15M"
    assert client._normalize_frequency("1H") == "1H"


def test_get_file_path_uses_new_city_level_payload(monkeypatch):
    client = CPCBHistorical()
    calls = []

    monkeypatch.setattr(
        client,
        "_resolve_city",
        lambda city, state="": (
            {"state_name": "Delhi", "state_code": "ST-10"},
            {"city_name": "Delhi", "city_code": "CTY-000170"},
        ),
    )

    def fake_new_api_json(method, url, params=None, json_data=None):
        calls.append((method, url, json_data))
        return {
            "status": "success",
            "data": [
                {
                    "filepath": "/AQI_daily/city_level/delhi/2025/delhi_2025.xlsx",
                    "year": "2025",
                }
            ],
        }

    monkeypatch.setattr(client, "_new_api_json", fake_new_api_json)

    result = client.get_file_path(
        "", "", "Delhi", "Delhi", "2025", "daily", "cityLevel"
    )

    assert result[0]["year"] == "2025"
    assert calls[0][0] == "post"
    assert calls[0][1].endswith("/caaqms-common/dataRepository/file-path")
    assert calls[0][2] == {
        "station_id": "",
        "station_name": "",
        "state": "Delhi",
        "city": "Delhi",
        "year": "2025",
        "frequency": "1D",
        "dataType": "cityLevel",
    }


def test_get_file_path_uses_new_station_level_payload(monkeypatch):
    client = CPCBHistorical()
    calls = []

    monkeypatch.setattr(
        client,
        "_resolve_station",
        lambda station_id, station_name="", state="", city="": (
            {"state_name": "Delhi", "state_code": "ST-10"},
            {"city_name": "Delhi", "city_code": "CTY-000170"},
            {"station_id": "site_301", "station_name": "Anand Vihar, Delhi - DPCC"},
        ),
    )

    def fake_new_api_json(method, url, params=None, json_data=None):
        calls.append((method, url, json_data))
        return {
            "status": "success",
            "data": [
                {
                    "filepath": "/AQI_hourly/2025/January/Anand_Vihar_Delhi_DPCC_January_2025.xlsx",
                    "month": "January",
                }
            ],
        }

    monkeypatch.setattr(client, "_new_api_json", fake_new_api_json)

    result = client.get_file_path(
        "site_301", "", "", "Delhi", "2025", "hourly", "stationLevel"
    )

    assert result[0]["month"] == "January"
    assert calls[0][2] == {
        "station_id": "site_301",
        "station_name": "Anand Vihar, Delhi - DPCC",
        "state": "Delhi",
        "city": "Delhi",
        "year": "2025",
        "frequency": "1H",
        "dataType": "stationLevel",
    }


def test_read_repository_excel_uses_authenticated_download_endpoint(monkeypatch):
    client = CPCBHistorical()
    workbook = io.BytesIO()
    pd.DataFrame({"Day": [1], "January": [42]}).to_excel(workbook, index=False)
    calls = []

    monkeypatch.setattr(
        client, "_new_api_headers", lambda auth=False: {"Authorization": "token"}
    )

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return FakeResponse(content=workbook.getvalue())

    monkeypatch.setattr(cpcb_common, "send", fake_request)

    df = client._read_repository_excel(
        "/AQI_daily/city_level/delhi/2025/delhi_2025.xlsx"
    )

    assert df.to_dict("records") == [{"Day": 1, "January": 42}]
    assert calls[0][0] == "get"
    assert calls[0][1].endswith("/caaqms-common/dataRepository/download-excel-file")
    assert calls[0][2]["params"] == {
        "file_name": "/AQI_daily/city_level/delhi/2025/delhi_2025.xlsx"
    }
    assert calls[0][2]["headers"] == {"Authorization": "token"}


def test_custom_query_treats_empty_204_body_as_no_rows(monkeypatch):
    client = CPCBHistorical()
    monkeypatch.setattr(client, "_new_api_headers", lambda auth=False: {})

    class _EmptyResponse(FakeResponse):
        def json(self):
            raise ValueError("Expecting value")

    monkeypatch.setattr(cpcb_common, "send", lambda *a, **k: _EmptyResponse())

    assert client._custom_query("get-city-master-list", "state_code IS 'ST-11'") == []


def test_get_access_token_requires_token(monkeypatch, cpcb_credentials):
    client = CPCBHistorical()
    monkeypatch.setattr(
        cpcb_common,
        "send",
        lambda *args, **kwargs: FakeResponse(json_data={}),
    )

    with pytest.raises(Exception, match="access_token"):
        client._get_access_token()


def test_download_hourly_station_level_combines_monthly_workbooks(
    monkeypatch, tmp_path
):
    client = CPCBHistorical()
    entries = [
        {"filepath": "/AQI_hourly/2025/January/station.xlsx", "month": "January"},
        {"filepath": "/AQI_hourly/2025/February/station.xlsx", "month": "February"},
    ]

    monkeypatch.setattr(
        client,
        "get_file_path",
        lambda *a, **k: entries,
    )

    def fake_read(filepath):
        return pd.DataFrame(
            {"Day": [1], "00:00:00": [101 if "January" in filepath else 202]}
        )

    monkeypatch.setattr(client, "_read_repository_excel", fake_read)

    output = tmp_path / "hourly_station.csv"
    df = client.download_hourly_aqi_data_station_level(
        "site_301", "2025", str(output), city="Delhi"
    )

    assert df[["Month", "Day", "00:00:00"]].to_dict("records") == [
        {"Month": "January", "Day": 1, "00:00:00": 101},
        {"Month": "February", "Day": 1, "00:00:00": 202},
    ]
    assert output.exists()


def test_download_hourly_city_level_can_select_single_month(monkeypatch):
    client = CPCBHistorical()
    entries = [
        {
            "filepath": "/AQI_hourly/city_level/delhi/2025/January/delhi.xlsx",
            "month": "January",
        },
        {
            "filepath": "/AQI_hourly/city_level/delhi/2025/February/delhi.xlsx",
            "month": "February",
        },
    ]

    monkeypatch.setattr(
        client,
        "get_file_path",
        lambda *a, **k: entries,
    )
    monkeypatch.setattr(
        client,
        "_read_repository_excel",
        lambda filepath: pd.DataFrame({"Day": [1], "00:00:00": [123]}),
    )

    df = client.download_hourly_aqi_data_city_level(
        "Delhi", "2025", "", month="February", state="Delhi"
    )

    assert df.to_dict("records") == [{"Month": "February", "Day": 1, "00:00:00": 123}]


def test_download_raw_station_level_uses_raw_file_path_and_csv_reader(
    monkeypatch, tmp_path
):
    client = CPCBHistorical()
    calls = []

    monkeypatch.setattr(
        client,
        "get_file_path",
        lambda *a, **k: [
            {
                "filepath": "/Raw_data/15Min/2025/site_301_Anand_Vihar_Delhi_DPCC_15Min.csv"
            }
        ],
    )

    def fake_read_csv(filepath):
        calls.append(filepath)
        return pd.DataFrame(
            {"Timestamp": ["2025-01-01 00:15:00"], "PM2.5 (µg/m³)": [251.0]}
        )

    monkeypatch.setattr(client, "_read_repository_csv", fake_read_csv)

    output = tmp_path / "raw_15min.csv"
    df = client.download_raw_aqi_data_station_level(
        "site_301", "2025", str(output), city="Delhi"
    )

    assert calls == ["/Raw_data/15Min/2025/site_301_Anand_Vihar_Delhi_DPCC_15Min.csv"]
    assert df.to_dict("records") == [
        {"Timestamp": "2025-01-01 00:15:00", "PM2.5 (µg/m³)": 251.0}
    ]
    assert output.exists()


def _fail_request(*args, **kwargs):
    raise AssertionError("unexpected network call")


def test_station_lookup_uses_bundled_directory_without_credentials(monkeypatch):
    monkeypatch.setattr(cpcb_common, "send", _fail_request)
    client = CPCBHistorical()

    state, city, station = client._resolve_station("site_301")

    assert station["station_name"] == "Anand Vihar, Delhi - DPCC"
    assert city["city_name"] == "Delhi"
    assert state["state_name"] == "Delhi"
    assert "Authorization" not in client._new_api_headers()


def test_station_lookup_by_name_or_part_of_a_name(monkeypatch, rss_feed):
    monkeypatch.setattr(cpcb_common, "send", _fail_request)
    rss_feed([])
    client = CPCBHistorical()

    for query in ("Anand Vihar, Delhi - DPCC", "anand vihar, delhi"):
        _, _, station = client._resolve_station(query)
        assert station["station_id"] == "site_301"
    assert client._resolve_station("no such station") == (None, None, None)
    with pytest.raises(StationNotFoundError, match="more than one station"):
        client._resolve_station("Delhi - DPCC")


def test_token_is_sent_only_to_directory_queries(monkeypatch, cpcb_credentials):
    client = CPCBHistorical()
    monkeypatch.setattr(client, "_get_access_token", lambda: "token")
    sent = []

    def fake_request(method, url, **kwargs):
        sent.append(kwargs["headers"].get("Authorization"))
        return FakeResponse(content=b"[]", json_data=[])

    monkeypatch.setattr(cpcb_common, "send", fake_request)

    client._custom_query("get-state-master-list-data")
    client._download_repository_file("/AQI_daily/2024/x.xlsx")

    assert sent == ["token", None]


def test_live_directory_failure_falls_back_to_snapshot(monkeypatch, cpcb_credentials):
    client = CPCBHistorical()

    def unauthorized(*args, **kwargs):
        raise requests.HTTPError("401")

    monkeypatch.setattr(client, "_custom_query", unauthorized)

    assert len(client._new_state_list()) == 36
    assert client._live_directory is False


def test_unknown_station_resolves_from_rss_feed(rss_feed):
    rss_feed(
        [
            {
                "stateID": "Delhi",
                "cityName": "Delhi",
                "stationsInCity": [{"id": "site_new", "name": "New Station"}],
            }
        ]
    )
    client = CPCBHistorical()

    state, city, station = client._resolve_station("site_new", city="Delhi")

    assert (state["state_name"], city["city_name"]) == ("Delhi", "Delhi")
    assert station["station_name"] == "New Station"


def test_get_file_path_raises_when_no_endpoint_answers(monkeypatch):
    client = CPCBHistorical()

    monkeypatch.setattr(cpcb_common, "send", raise_connection_error)

    with pytest.raises(NetworkError):
        client.get_file_path("", "", "Delhi", "Delhi", "2024", "daily", "cityLevel")


def test_get_file_path_is_empty_when_cpcb_answers_without_files(monkeypatch):
    client = CPCBHistorical()
    monkeypatch.setattr(
        client, "_new_api_json", lambda *a, **k: {"status": "success", "data": []}
    )

    assert client.get_file_path("", "", "", "Delhi", "2024", "daily", "cityLevel") == []


def test_repository_files_of_past_years_are_cached(monkeypatch, tmp_path):
    client = CPCBHistorical(cache_dir=str(tmp_path))
    calls = []

    def fake_send(method, url, **kwargs):
        calls.append(kwargs["params"]["file_name"])
        return FakeResponse(content=b"Day,January\n1,42\n")

    monkeypatch.setattr(cpcb_common, "send", fake_send)
    past = "/AQI_daily/city_level/delhi/2020/delhi_2020.csv"
    current = f"/AQI_daily/city_level/delhi/{date.today().year}/delhi.csv"

    for _ in range(2):
        assert client._read_repository_csv(past)["January"].tolist() == [42]
        client._read_repository_csv(current)

    assert calls == [past, current, current]
    assert (tmp_path / "AQI_daily/city_level/delhi/2020/delhi_2020.csv").exists()

    CPCBHistorical(use_cache=False)._read_repository_csv(past)
    assert len(calls) == 4
