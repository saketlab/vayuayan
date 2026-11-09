"""Upstream failures must be reported, and partial results stay partial."""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from vayuayan import oaq
from vayuayan.cpcb_live import CPCBLive
from vayuayan.exceptions import DataParsingError, NetworkError
from vayuayan.oaq import OAQClient


@pytest.fixture
def oaq_client():
    client = OAQClient.__new__(OAQClient)
    client.base_url = "https://oaq.example/v1"
    client.sig_string = "sig=1"
    return client


def _http_failure(status):
    error = requests.HTTPError(response=SimpleNamespace(status_code=status))

    def request(*args, **kwargs):
        raise error

    return request


def test_corrupt_oaq_json_is_warned_about(monkeypatch, oaq_client, caplog):
    def broken(*args):
        raise DataParsingError("Failed to parse OAQ response: corrupt JSON")

    monkeypatch.setattr(oaq_client, "get_daily", broken)
    with caplog.at_level(logging.WARNING):
        out = oaq_client.readings("airnet", "s1", ["2026-01-01"])
    assert out.empty
    assert any(
        "s1" in r.getMessage() and "corrupt" in r.getMessage() for r in caplog.records
    )


@pytest.mark.parametrize("call", ["readings", "daily_means"])
def test_oaq_outage_warns_but_a_404_stays_silent(monkeypatch, oaq_client, caplog, call):
    fetch = getattr(oaq_client, call)
    monkeypatch.setattr(oaq.http_client, "request", _http_failure(404))
    with caplog.at_level(logging.WARNING):
        assert fetch("airnet", "s1", ["2026-01-01"]).empty
    assert not caplog.records

    monkeypatch.setattr(oaq.http_client, "request", _http_failure(503))
    with caplog.at_level(logging.WARNING):
        assert fetch("airnet", "s1", ["2026-01-01"]).empty
    assert "s1" in caplog.records[0].getMessage()
    assert "503" in caplog.records[0].getMessage()


def test_oaq_daily_records_and_monthly_warn_on_outage(monkeypatch, oaq_client, caplog):
    monkeypatch.setattr(
        oaq_client,
        "get_annual",
        lambda *a: (_ for _ in ()).throw(NetworkError("OAQ request failed (503)")),
    )
    with caplog.at_level(logging.WARNING):
        oaq_client.daily_records("airnet", "s1", [2026])
    assert "s1 2026" in caplog.records[0].getMessage()
    caplog.clear()

    monkeypatch.setattr(
        oaq_client,
        "stations_table",
        lambda p: pd.DataFrame({"id": ["s1"], "lat": [1.0], "lon": [2.0]}),
    )
    monkeypatch.setattr(
        oaq_client,
        "get_monthly",
        lambda *a: (_ for _ in ()).throw(NetworkError("OAQ request failed (503)")),
    )
    with caplog.at_level(logging.WARNING):
        assert oaq_client.fetch_monthly_stations("airnet", 2026, ["03"]).empty
    assert "s1 03" in caplog.records[0].getMessage()


def _rss_station(last_update="09-11-2026 08:00:00"):
    return [
        {
            "cityName": "Delhi",
            "stationsInCity": [
                {
                    "id": "site_301",
                    "name": "Anand Vihar",
                    "lastUpdate": last_update,
                    "airQualityIndex": {"value": "180"},
                    "pollutants": [{"indexId": "PM2.5", "avg": "85"}],
                }
            ],
        }
    ]


def _live_with_rss_only(monkeypatch, cities):
    live = CPCBLive()
    monkeypatch.setattr(
        live,
        "_make_request",
        lambda url, payload: (_ for _ in ()).throw(ValueError("down")),
    )
    monkeypatch.setattr(live, "_rss_cities", lambda: cities)
    return live


def test_rss_fallback_warns_for_a_historical_request(monkeypatch, caplog):
    live = _live_with_rss_only(monkeypatch, _rss_station())
    with caplog.at_level(logging.WARNING):
        live.get_live_aqi_data_for_station("site_301", "2020-01-01T10:00:00Z")
    assert any("2020-01-01T10:00:00Z" in r.getMessage() for r in caplog.records)


def test_rss_fallback_is_quiet_for_the_current_hour(monkeypatch, caplog):
    live = _live_with_rss_only(monkeypatch, _rss_station())
    now = pd.Timestamp.now().strftime("%Y-%m-%dT%H:00:00Z")
    with caplog.at_level(logging.WARNING):
        live.get_live_aqi_data_for_station("site_301", now)
    assert not caplog.records


def test_rss_fallback_does_not_stamp_the_requested_time(monkeypatch):
    cities = _rss_station()
    del cities[0]["stationsInCity"][0]["lastUpdate"]
    live = _live_with_rss_only(monkeypatch, cities)
    out = live.get_live_aqi_data_for_station("site_301", "2020-01-01T10:00:00Z")
    assert out["metrics"][0]["avgDesc"] is None
