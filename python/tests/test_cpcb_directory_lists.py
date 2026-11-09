"""The station directory: token, live and snapshot lists, lookups, coordinates."""

import logging

import pytest
import requests

from vayuayan import CPCBHistorical, cpcb_common, cpcb_directory
from vayuayan.exceptions import AuthenticationError, CPCBError

from .fakes import http_response

NOMINATIM = "https://nominatim.openstreetmap.org/search"
FEED_CITY = {
    "stateID": "Delhi",
    "cityName": "Delhi",
    "stationsInCity": [
        {"id": "site_new", "name": "New Station", "latitude": "28.5", "longitude": "77"}
    ],
}


def test_access_token_is_requested_once(monkeypatch, cpcb_credentials):
    sent = []

    def fake_send(*args, **kwargs):
        sent.append(args)
        return http_response(json_data={"access_token": "tok"})

    monkeypatch.setattr(cpcb_common, "send", fake_send)
    client = CPCBHistorical()

    assert client._get_access_token() == "tok"
    assert client._get_access_token() == "tok"
    assert len(sent) == 1


def test_access_token_needs_credentials():
    with pytest.raises(AuthenticationError, match="not set"):
        CPCBHistorical()._get_access_token()


def test_empty_new_api_response_is_none(monkeypatch):
    monkeypatch.setattr(cpcb_common, "send", lambda *a, **k: http_response(status=204))

    assert CPCBHistorical()._new_api_json("get", "https://x.example") is None


def test_custom_query_keeps_only_object_rows(monkeypatch):
    client = CPCBHistorical()
    monkeypatch.setattr(
        client, "_new_api_json", lambda *a, **k: [{"a": 1}, "junk", None]
    )
    assert client._custom_query("q") == [{"a": 1}]

    monkeypatch.setattr(client, "_new_api_json", lambda *a, **k: {"rows": []})
    assert client._custom_query("q") == []


def test_live_directory_rows_are_cached_per_level_and_code(cpcb_credentials):
    client = CPCBHistorical()
    asked = []

    def custom_query(name, filter_query=""):
        asked.append((name, filter_query))
        return [{"state_name": "Live", "state_code": "L1"}]

    client._custom_query = custom_query

    assert client._new_state_list() == client._new_state_list()
    assert asked == [("get-state-master-list-data", "")]


def test_empty_live_answer_uses_the_snapshot_and_stays_live(cpcb_credentials):
    client = CPCBHistorical()
    client._custom_query = lambda name, filter_query="": []

    assert client._new_city_list("ST-10")[0]["city_name"] == "Delhi"
    assert client._live_directory is True


def test_snapshot_has_no_rows_for_an_unknown_code():
    assert CPCBHistorical()._new_city_list("ST-404") == []


def test_prefetch_does_nothing_without_credentials():
    client = CPCBHistorical()
    client._prefetch("cities", ["ST-01", "ST-02"])
    assert client._directory_cache == {}


def test_state_list_is_sorted_and_has_no_blank_names():
    client = CPCBHistorical()
    client._directory_cache[("states", "")] = [
        {"state_name": "Zeta"},
        {"state_name": ""},
        {"state_name": "Alpha"},
    ]

    assert client.get_state_list() == ["Alpha", "Zeta"]


def test_state_list_from_the_snapshot_has_every_state():
    states = CPCBHistorical().get_state_list()

    assert len(states) == 36
    assert "Delhi" in states
    assert states == sorted(states)


@pytest.mark.parametrize("state", ["Delhi", "delhi", "ST-10", "st-10"])
def test_city_list_accepts_a_state_name_or_code(state):
    assert CPCBHistorical().get_city_list(state) == ["Delhi"]


def test_city_list_of_an_unknown_state_is_empty():
    assert CPCBHistorical().get_city_list("Atlantis") == []


def test_resolve_state_needs_a_name():
    client = CPCBHistorical()
    assert client._resolve_state("") is None
    assert client._states("Atlantis") == []


def test_iter_stations_filters_by_city_and_state():
    client = CPCBHistorical()

    entries = list(client.iter_stations(state="Delhi", city="delhi"))

    assert len(entries) == 59
    assert {s["state_name"] for s, _, _ in entries} == {"Delhi"}
    assert {c["city_name"] for _, c, _ in entries} == {"Delhi"}


def test_iter_stations_of_a_state_walks_its_cities():
    entries = list(CPCBHistorical().iter_stations(state="ST-10"))

    assert {station["station_id"] for _, _, station in entries} >= {"site_301"}


def test_iter_stations_of_an_unknown_city_is_empty():
    assert list(CPCBHistorical().iter_stations(city="Atlantis")) == []


def test_resolve_city_of_an_unknown_city_is_none():
    assert CPCBHistorical()._resolve_city("Atlantis") == (None, None)


def test_resolve_station_by_name_when_the_id_is_unknown(rss_feed):
    rss_feed([])
    client = CPCBHistorical()

    _, _, station = client._resolve_station("no-such-id", "Anand Vihar, Delhi - DPCC")

    assert station["station_id"] == "site_301"


def test_station_list_of_an_unknown_city_is_empty():
    assert CPCBHistorical().get_station_list("Atlantis") == []


def test_station_list_ignores_rss_stations_of_other_cities(rss_feed):
    rss_feed([{**FEED_CITY, "cityName": "Mumbai"}])

    stations = CPCBHistorical().get_station_list("Delhi")

    assert "site_new" not in {s["value"] for s in stations}
    assert stations == sorted(stations, key=lambda s: s["label"])


def test_add_coords_skips_the_feed_when_the_snapshot_has_every_station(monkeypatch):
    client = CPCBHistorical()
    monkeypatch.setattr(client, "_rss_cities", lambda: pytest.fail("feed was read"))

    rows = client.add_coords([{"label": "Alipur", "value": "site_5024"}])

    assert rows == [
        {"label": "Alipur", "value": "site_5024", "lat": 28.815329, "lon": 77.15301}
    ]


def test_add_coords_tries_snapshot_feed_then_nominatim(network, rss_feed):
    rss_feed([FEED_CITY])
    network.on(
        "get",
        NOMINATIM,
        http_response(json_data=[{"lat": "19.05", "lon": "72.84"}]),
    )

    rows = CPCBHistorical().add_coords(
        [
            {"label": "Alipur", "value": "site_5024"},
            {"label": "New Station", "value": "site_new"},
            {"label": "Bandra, Mumbai - MPCB", "value": "site_osm"},
        ]
    )

    assert [(r["lat"], r["lon"]) for r in rows] == [
        (28.815329, 77.15301),
        (28.5, 77.0),
        (19.05, 72.84),
    ]
    assert len(network.calls) == 1  # only the station that nothing else knows


def test_nominatim_request_strips_the_agency_and_waits_a_second(network):
    network.on("get", NOMINATIM, http_response(json_data=[{"lat": "1", "lon": "2"}]))

    assert cpcb_directory._nominatim("Bandra, Mumbai - MPCB") == (1.0, 2.0)

    [call] = network.calls
    assert (call.method, call.url) == ("get", NOMINATIM)
    assert call.kwargs["params"] == {
        "q": "Bandra, Mumbai",
        "format": "json",
        "limit": 1,
    }
    assert call.kwargs["headers"] == {"User-Agent": "vayuayan-python-package"}
    assert network.sleeps == [1]  # Nominatim's rate limit


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(json_data=[]), id="no-result"),
        pytest.param(http_response(status=500), id="500"),
        pytest.param(http_response(b"<html>"), id="malformed"),
        pytest.param(requests.ConnectionError("down"), id="connection"),
    ],
)
def test_nominatim_without_an_answer_gives_no_coordinates(network, reply):
    network.on("get", NOMINATIM, reply)

    assert cpcb_directory._nominatim("Nowhere") == (None, None)


@pytest.mark.parametrize(
    "value,expected", [("12.5", 12.5), (3, 3.0), (None, None), ("NA", None)]
)
def test_float_conversion(value, expected):
    assert cpcb_directory._float(value) == expected


def test_attempt_returns_the_result_and_lets_bugs_propagate():
    assert cpcb_common.attempt(lambda: 42, "failed (%s)") == 42

    def bug():
        raise KeyError("a bug, not a source failure")

    with pytest.raises(KeyError):
        cpcb_common.attempt(bug, "failed (%s)")


def test_attempt_accepts_extra_errors(caplog):
    def boom():
        raise CPCBError("source error")

    with caplog.at_level(logging.WARNING):
        result = cpcb_common.attempt(boom, "failed (%s)", logging.WARNING, (CPCBError,))

    assert result is None
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


def test_rss_directory_has_the_directory_shape(rss_feed):
    rss_feed([FEED_CITY])

    assert list(CPCBHistorical()._rss_directory()) == [
        (
            {"state_name": "Delhi"},
            {"city_name": "Delhi"},
            {
                "station_id": "site_new",
                "station_name": "New Station",
                "latitude": "28.5",
                "longitude": "77",
            },
        )
    ]
