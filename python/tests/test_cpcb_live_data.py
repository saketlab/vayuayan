"""CPCBLive: location, nearest station, live readings and their cleaning."""

from __future__ import annotations

from datetime import datetime

import pytest
import requests

from vayuayan import CPCBLive
from vayuayan import cpcb_live as live_module
from vayuayan.exceptions import NetworkError, StationNotFoundError

from .fakes import http_response

IP_API = "http://ip-api.com/json"
CITIES = [
    {
        "stationsInCity": [
            {"id": "site_far", "name": "Far Away", "latitude": 8.0, "longitude": 77.0},
            {
                "id": "site_near",
                "name": "Near By",
                "latitude": "28.6",
                "longitude": "77.2",
            },
            {"id": "site_none", "name": "No Coords", "latitude": None, "longitude": 77},
        ]
    }
]


def test_make_request_rejects_json_that_is_not_an_object(monkeypatch):
    client = CPCBLive()
    monkeypatch.setattr(live_module.cpcb_common, "legacy_post", lambda *a, **k: [1])

    with pytest.raises(ValueError, match="not a JSON object"):
        client._make_request("https://x.example", {})


def test_make_request_passes_the_form_headers_and_cookies(monkeypatch):
    client = CPCBLive()
    calls = []

    def fake_post(url, payload, headers, cookies, session):
        calls.append((url, payload, headers, cookies, session))
        return {"ok": True}

    monkeypatch.setattr(live_module.cpcb_common, "legacy_post", fake_post)

    assert client._make_request("https://x.example", {"a": 1}) == {"ok": True}
    assert calls == [
        ("https://x.example", {"a": 1}, client.headers, client.cookies, client.session)
    ]


def test_clean_pollution_data_without_a_chart_is_a_copy():
    data = {"metrics": []}
    cleaned = CPCBLive()._clean_pollution_data(data)

    assert cleaned == data
    assert cleaned is not data


def test_clean_pollution_data_turns_the_chart_into_named_series():
    data = {
        "metrics": [{"name": "PM2.5"}, {}],
        "chartData": [
            [["date", "PM2.5"], ["10:00", 41], [None, 5], ["11:00", None], ["12:00"]],
            [["date", "x"], ["10:00", 7]],
        ],
    }

    cleaned = CPCBLive()._clean_pollution_data(data)

    assert "chartData" not in cleaned
    assert cleaned["last_hours"] == [
        {"name": "PM2.5", "data": [{"date": "10:00", "val": 41}]},
        {"name": "Series 1", "data": [{"date": "10:00", "val": 7}]},
    ]
    assert "chartData" in data  # the reply is not changed


@pytest.mark.parametrize("series", [[], None, "text", [["header"]]])
def test_clean_pollution_data_skips_series_without_rows(series):
    data = {"metrics": [{"name": "PM2.5"}], "chartData": [series]}

    assert CPCBLive()._clean_pollution_data(data)["last_hours"] == []


def test_clean_pollution_data_drops_a_series_without_a_metric():
    data = {"metrics": [], "chartData": [[["h"], ["10:00", 1]]]}

    assert CPCBLive()._clean_pollution_data(data)["last_hours"] == []


def test_system_location_uses_the_ip_service(network):
    reply = {"status": "success", "lat": 19.07, "lon": 72.87}
    network.on("get", IP_API, http_response(json_data=reply))

    assert CPCBLive().get_system_location() == (19.07, 72.87)
    assert network.calls[0].method == "get"


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(status=500), id="500"),
        pytest.param(requests.ConnectionError("down"), id="connection"),
        pytest.param(http_response(b"<html>"), id="malformed"),
        pytest.param(
            http_response(json_data={"status": "fail", "message": "reserved"}),
            id="service-failure",
        ),
    ],
)
def test_system_location_failure_is_a_network_error(network, reply):
    network.on("get", IP_API, reply)

    with pytest.raises(NetworkError):
        CPCBLive().get_system_location()


def test_nearest_station_uses_the_given_coordinates():
    client = CPCBLive()
    client.get_all_india = lambda: CITIES
    client.get_system_location = lambda: pytest.fail("location was looked up")

    assert client.get_nearest_station((28.5, 77.1)) == ("site_near", "Near By")
    assert client.get_nearest_station((8.1, 77.0)) == ("site_far", "Far Away")


def test_nearest_station_falls_back_to_the_ip_location():
    client = CPCBLive()
    client.get_all_india = lambda: CITIES
    client.get_system_location = lambda: (8.1, 77.0)

    assert client.get_nearest_station()[0] == "site_far"


def test_nearest_station_needs_a_station_with_coordinates():
    client = CPCBLive()
    client.get_all_india = lambda: [{"stationsInCity": [{"id": "x"}]}]

    with pytest.raises(StationNotFoundError):
        client.get_nearest_station((1.0, 2.0))


def test_station_id_by_name():
    client = CPCBLive()
    client.get_all_india = lambda: CITIES

    assert client._station_id_by_name("near by") == "site_near"
    assert client._station_id_by_name("Far") == "site_far"
    with pytest.raises(StationNotFoundError):
        client._station_id_by_name("Atlantis")


def test_live_data_needs_a_station_and_a_time():
    client = CPCBLive()

    with pytest.raises(ValueError):
        client.get_live_aqi_data_for_station("", "2026-01-01T10:00:00Z")
    with pytest.raises(ValueError):
        client.get_live_aqi_data_for_station("site_1", "")


def test_live_data_looks_up_a_station_name_before_the_request():
    client = CPCBLive()
    client.get_all_india = lambda: CITIES
    payloads = []

    def fake_request(url, payload):
        payloads.append(payload)
        return {"airQualityIndex": {"value": 5}, "metrics": [{"name": "PM2.5"}]}

    client._make_request = fake_request

    client.get_live_aqi_data_for_station("Near By", "d")

    assert payloads == [{"station_id": "site_near", "date": "d"}]


@pytest.mark.parametrize("hour", [-1, 24])
def test_live_data_rejects_a_bad_hour(hour):
    with pytest.raises(ValueError, match="Hour"):
        CPCBLive().get_live_aqi_data(station_id="site_1", hour=hour)


def _capture_times(client):
    asked = []

    def fake_for_station(station_id, date_time):
        asked.append((station_id, date_time))
        return {
            "metrics": [{"name": "PM2.5"}],
            "chartData": [[["h"], ["10:00", 9]]],
        }

    client.get_live_aqi_data_for_station = fake_for_station
    return asked


def test_live_data_builds_the_time_from_date_and_hour():
    client = CPCBLive()
    asked = _capture_times(client)

    data = client.get_live_aqi_data(station_id="site_1", date="2026-02-25", hour=0)

    assert asked == [("site_1", "2026-02-25T00:00:00Z")]
    assert data["last_hours"][0]["data"] == [{"date": "10:00", "val": 9}]


def test_live_data_defaults_to_the_current_hour_and_nearest_station(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 3, 4, 9, 30)

    monkeypatch.setattr(live_module, "datetime", FixedClock)
    client = CPCBLive()
    asked = _capture_times(client)
    preferences = []

    def nearest(coords=None, prefer_reading=None):
        preferences.append(prefer_reading)
        return ("site_near", "Near")

    client.get_nearest_station = nearest

    client.get_live_aqi_data()

    assert asked == [("site_near", "2026-03-04T09:00:00Z")]
    assert preferences == [True]


def test_numeric_aqi_with_no_index_is_none():
    assert live_module._with_numeric_aqi({"a": 1}) == {
        "a": 1,
        "airQualityIndex": {"value": None},
    }
