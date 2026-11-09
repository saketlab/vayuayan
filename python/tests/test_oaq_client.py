"""OAQClient: the object paths and the tables built from them."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import requests

from vayuayan import OAQClient, oaq
from vayuayan.exceptions import AuthenticationError, DataParsingError, NetworkError

from .fakes import http_response

BROKER = "https://us-central1-oaqdms.cloudfunctions.net/brokerData"
DATA = "https://data.example/v1"


@pytest.fixture
def client():
    instance = OAQClient.__new__(OAQClient)  # no handshake
    instance.base_url = DATA
    instance.sig_string = "sig=1"
    return instance


def test_handshake_uses_the_default_base_url(network):
    network.on("get", BROKER, http_response(json_data={"Signature": "s=2"}))

    session = OAQClient("key")

    assert session.base_url == "https://oaq.notf.in/v1"
    assert session.sig_string == "s=2"
    assert network.calls[0].kwargs["params"] == {
        "action": "api_session",
        "token": "key",
    }


def test_handshake_key_comes_from_the_environment(network, monkeypatch):
    monkeypatch.setenv("OAQ_API_KEY", "env-key")
    network.on(
        "get",
        BROKER,
        http_response(json_data={"signature": "s", "baseUrl": DATA + "/"}),
    )

    assert OAQClient().base_url == DATA
    assert network.calls[0].kwargs["params"]["token"] == "env-key"


def test_handshake_without_a_signature_is_rejected(network):
    network.on("get", BROKER, http_response(json_data={"status": "ok"}))

    with pytest.raises(AuthenticationError, match="missing signature"):
        OAQClient("key")


@pytest.mark.parametrize(
    "call,path",
    [
        (lambda c: c.list_providers(), "meta/providers.json"),
        (lambda c: c.get_hierarchy("AirNet"), "provider=airnet/meta/hierarchy.json"),
        (
            lambda c: c.get_station_24h("CPCB", "s1"),
            "provider=cpcb/live/sensors/s1/last24h.json",
        ),
        (
            lambda c: c.get_daily("CPCB", "s1", 2026, 3, 7),
            "provider=cpcb/history/daily/s1/2026/03/07.json",
        ),
        (
            lambda c: c.get_monthly("CPCB", "s1", 2026, "03"),
            "provider=cpcb/history/aggregates/s1/monthly_2026_03.json",
        ),
    ],
)
def test_object_paths_are_signed(client, network, call, path):
    url = f"{DATA}/{path}"
    network.on("get", url, http_response(json_data={"ok": True}))

    assert call(client) == {"ok": True}
    assert network.urls() == [f"{url}?sig=1"]


def test_malformed_json_is_a_parsing_error(client, network):
    network.on("get", f"{DATA}/meta/providers.json", http_response(b"<html>"))

    with pytest.raises(DataParsingError, match="meta/providers.json"):
        client.list_providers()


def _stations(client, rows):
    client.get_stations_latest = lambda provider: {"stations": rows}


STATIONS = [
    {"id": "a", "name": "A", "city": "Delhi", "lat": "28", "lon": "77"},
    {"id": "b", "name": "B", "city": "Pune", "lat": "18", "lon": "73"},
]


def test_fetch_monthly_stations_joins_records_and_metadata(client):
    _stations(client, STATIONS)
    asked = []

    def monthly(provider, sid, year, month):
        asked.append((provider, sid, year, month))
        if month == "02":
            raise NetworkError("no file for this month")
        return {"data": [{"date": "2026-01-15", "pm25": "33.5"}]}

    client.get_monthly = monthly

    out = client.fetch_monthly_stations("cpcb", 2026, months=["01", "02"])

    assert asked == [
        ("cpcb", "a", 2026, "01"),
        ("cpcb", "a", 2026, "02"),
        ("cpcb", "b", 2026, "01"),
        ("cpcb", "b", 2026, "02"),
    ]
    assert out["station_id"].tolist() == ["a", "b"]
    assert out["pm25"].tolist() == [33.5, 33.5]
    assert out["name"].tolist() == ["A", "B"]
    assert out["provider"].tolist() == ["cpcb", "cpcb"]
    assert out["date"].tolist() == [date(2026, 1, 15), date(2026, 1, 15)]


def test_fetch_monthly_stations_defaults_to_twelve_months(client):
    _stations(client, STATIONS[:1])
    months = []
    client.get_monthly = lambda p, s, y, m: months.append(m) or {"data": []}

    assert client.fetch_monthly_stations("cpcb", 2026).empty
    assert months == [f"{m:02d}" for m in range(1, 13)]


def test_fetch_monthly_stations_filters_by_city(client):
    _stations(client, STATIONS)
    client.get_monthly = lambda p, s, y, m: {"data": [{"pm25": 1}]}

    out = client.fetch_monthly_stations("cpcb", 2026, ["01"], city=["Pune"])

    assert out["station_id"].tolist() == ["b"]
    assert "date" not in out


def test_stations_table_without_coordinates_is_empty(client):
    _stations(client, [{"id": "a"}])

    table = client.stations_table("cpcb")

    assert table.empty
    assert "id" in table.columns


def test_stations_table_drops_stations_without_coordinates(client):
    _stations(client, [{"id": "a", "lat": "1", "lon": "2"}, {"id": "b", "lat": None}])

    assert client.stations_table(["cpcb"])["id"].tolist() == ["a"]


def test_check_daily_records_without_records_is_empty(client):
    client.daily_records = lambda *a: pd.DataFrame(columns=["sensor_id", "date"])

    out = client.check_daily_records("cpcb", "s1", ["2026-01-01"])

    assert out.empty
    assert list(out.columns) == oaq.RECORD_COLUMNS


def test_check_daily_records_without_readings_is_empty(client):
    client.daily_records = lambda *a: pd.DataFrame(
        {"sensor_id": ["s1"], "date": [date(2026, 1, 1)], "pm25": [10.0]}
    )
    client.readings = lambda *a: pd.DataFrame(columns=["sensor_id", "timestamp"])

    out = client.check_daily_records("cpcb", "s1", ["2026-01-01"])

    assert out.empty
    assert list(out.columns) == oaq.RECORD_COLUMNS


def test_audit_without_records_is_empty(client):
    client.daily_records = lambda *a: pd.DataFrame(columns=["sensor_id", "date"])

    out = client.audit_daily_records([("cpcb", "s1")], [2026], until="2026-02-01")

    assert out.empty
    assert list(out.columns) == ["provider"] + oaq.RECORD_COLUMNS


def test_daily_records_skips_a_missing_year_and_bad_files(client):
    def annual(provider, sensor, year):
        if year == 2024:
            raise NetworkError("no file")
        if year == 2025:
            return {"data": [{"value": 1}]}  # no date column
        return {"data": [{"date": "2026-01-02", "pm25": "11"}]}

    client.get_annual = annual

    out = client.daily_records("cpcb", "s1", [2024, 2025, 2026])

    assert out.to_dict("records") == [
        {"sensor_id": "s1", "date": date(2026, 1, 2), "pm25": 11.0}
    ]


def test_daily_records_of_nothing_keeps_the_columns(client):
    client.get_annual = lambda *a: {"data": []}

    assert list(client.daily_records("cpcb", "s1", [2026]).columns) == [
        "sensor_id",
        "date",
    ]


def test_daily_records_of_several_sensors(client):
    client.get_annual = lambda p, s, y: {"data": [{"date": "2026-01-02", "pm25": 1}]}

    out = client.daily_records("cpcb", ["s1", "s2"], [2026])

    assert out["sensor_id"].tolist() == ["s1", "s2"]


def test_readings_skip_missing_files_and_files_without_dates(client):
    def daily(provider, sensor, year, month, day):
        if day == 1:
            raise DataParsingError("bad")
        return {"data": [{"value": 1}]}

    client.get_daily = daily

    out = client.readings("cpcb", "s1", ["2026-01-01", "2026-01-02"])

    assert out.empty
    assert list(out.columns) == ["sensor_id", "timestamp"]


def test_daily_means_skip_missing_files_and_empty_files(client):
    def daily(provider, sensor, year, month, day):
        if day == 1:
            raise NetworkError("no file")
        return {"data": []}

    client.get_daily = daily

    assert client.daily_means("cpcb", "s1", ["2026-01-01", "2026-01-02"]).empty


def test_daily_means_of_several_sensors_keep_their_order(client):
    client.get_daily = lambda p, s, y, m, d: {
        "data": [{"date": "2026-01-01T00:15:00", "pm25": 10}]
    }

    out = client.daily_means("cpcb", ["s2", "s1"], ["2026-01-01"], min_readings=1)

    assert out["sensor_id"].tolist() == ["s2", "s1"]
    assert out["pm25"].tolist() == [10.0, 10.0]
    assert out["n_pm25"].tolist() == [1, 1]


def test_each_with_no_sensors_is_an_empty_table():
    assert list(oaq._each(lambda s: pd.DataFrame(), []).columns) == ["sensor_id"]


def test_each_with_only_empty_tables_keeps_the_first():
    empty = pd.DataFrame(columns=["sensor_id", "timestamp"])

    assert oaq._each(lambda s: empty, ["a", "b"]) is empty


def test_today_is_in_india_time(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            # 20:00 UTC on 1 January is 01:30 on 2 January in India
            return (
                datetime(2026, 1, 1, 20, 0)
                .replace(tzinfo=oaq.timezone.utc)
                .astimezone(tz)
            )

    monkeypatch.setattr(oaq, "datetime", FixedClock)

    assert oaq._today_ist() == date(2026, 1, 2)


def test_city_tally_of_only_cpcb_sensors_is_empty():
    sensors = pd.DataFrame({"provider": ["CPCB"], "id": ["1"], "name": ["n"]})

    tally = oaq.oaq_city_tally(sensors)

    assert tally.empty
    assert "median_km_to_cpcb" in tally.columns


def test_handshake_failure_keeps_the_key_out_of_the_error(network):
    network.on("get", BROKER, requests.ConnectionError("https://x?token=secret"))

    with pytest.raises(AuthenticationError) as error:
        OAQClient("secret")
    assert "secret" not in str(error.value)
