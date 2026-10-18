"""Tests for the station directory: live prefetch, lists and failure logging."""

import logging
import threading
import time

import requests

from vayuayan import CPCBHistorical, cpcb_common


def _live_directory(client):
    """A fake live directory: 3 states x 4 cities x 2 stations."""
    threads = set()

    def custom_query(query_name, filter_query=""):
        if query_name.startswith("get-state"):
            return [
                {"state_code": f"S{i}", "state_name": f"State {i}"} for i in range(3)
            ]
        code = filter_query.split("'")[1]
        threads.add(threading.get_ident())
        time.sleep(0.02)
        if query_name == "get-city-master-list":
            return [
                {"city_code": f"{code}C{j}", "city_name": f"City {code}{j}"}
                for j in range(4)
            ]
        return [
            {"station_id": f"site_{code}_{k}", "station_name": f"Station {code} {k}"}
            for k in range(2)
        ]

    client._custom_query = custom_query
    return threads


def test_live_walk_is_parallel_and_finds_the_same_station(cpcb_credentials):
    client = CPCBHistorical()
    threads = _live_directory(client)

    state, city, station = client._resolve_station("site_S2C3_1")

    assert (state["state_code"], city["city_code"]) == ("S2", "S2C3")
    assert station["station_name"] == "Station S2C3 1"
    assert len(threads) > 1
    order = [s["station_id"] for _, _, s in client.iter_stations()]
    assert order[:3] == ["site_S0C0_0", "site_S0C0_1", "site_S0C1_0"]
    assert len(order) == 24


def test_station_list_adds_rss_stations_newer_than_the_directory(rss_feed):
    rss_feed(
        [
            {
                "stateID": "Delhi",
                "cityName": "Delhi",
                "stationsInCity": [{"id": "site_new", "name": "AAA New Station"}],
            }
        ]
    )
    stations = CPCBHistorical().get_station_list("delhi")

    assert stations[0] == {"label": "AAA New Station", "value": "site_new"}
    assert len(stations) > 30


def test_attempt_logs_the_status_but_not_the_url(caplog):
    def token_request():
        response = requests.Response()
        response.status_code = 401
        raise requests.HTTPError(
            "401 for url: https://x/token?password=secret", response=response
        )

    with caplog.at_level(logging.INFO):
        assert cpcb_common.attempt(token_request, "token failed (%s)") is None
    assert "token failed (401)" in caplog.text
    assert "secret" not in caplog.text
