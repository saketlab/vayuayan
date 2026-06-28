"""Tests for CPCB historical API compatibility glue."""

import io

import pandas as pd
import pytest

from vayuayan.air_quality_client import CPCBHistorical


class _FakeResponse:
    def __init__(self, content=b"", json_data=None):
        self.content = content
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        return None


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

    monkeypatch.setattr(client, "_new_api_headers", lambda: {"Authorization": "token"})

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return _FakeResponse(content=workbook.getvalue())

    monkeypatch.setattr(client, "_request_with_ssl_fallback", fake_request)

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


def test_get_access_token_requires_token(monkeypatch):
    client = CPCBHistorical()
    monkeypatch.setattr(
        client,
        "_request_with_ssl_fallback",
        lambda *args, **kwargs: _FakeResponse(json_data={}),
    )

    with pytest.raises(Exception, match="access_token"):
        client._get_access_token()
