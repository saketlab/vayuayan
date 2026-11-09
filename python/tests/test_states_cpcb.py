"""The named states of the CPCB clients: batches, places, listings and TLS."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import pytest
import requests

from vayuayan import CPCBHistorical, CPCBLive, http_client
from vayuayan.cpcb_common import is_outage
from vayuayan.exceptions import (
    AmbiguousMatchError,
    AuthenticationError,
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)

from .cpcb_urls import (
    BASE,
    CUSTOM_QUERY,
    FILE_PATH,
    LEGACY_FILE_PATH,
    OAUTH,
    RSS,
    RSS_FEED,
)
from .fakes import http_response

HOST = BASE.split("//")[1]
STATES_QUERY = f"{CUSTOM_QUERY}/get-state-master-list-data/data"
_HTTP_503 = requests.HTTPError("503", response=http_response(status=503))


# ---- item 9: credentials never go over unverified TLS


def test_token_request_is_verified_even_after_the_host_fell_back(
    network, cpcb_credentials
):
    http_client._INSECURE_HOSTS.add(HOST)
    network.on("post", OAUTH, http_response(json_data={"access_token": "t"}))
    network.on("get", STATES_QUERY, http_response(json_data=[{"state_name": "A"}]))

    CPCBHistorical()._new_state_list()

    assert [call.kwargs["verify"] for call in network.calls] == [True, True]


def test_broken_certificate_on_the_token_uses_the_snapshot_and_warns(
    network, cpcb_credentials, caplog
):
    network.on("post", OAUTH, requests.exceptions.SSLError("bad certificate"))
    client = CPCBHistorical()

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        states = client._new_state_list()

    assert states and client.directory_source == "snapshot"
    assert all(call.kwargs["verify"] is True for call in network.calls)
    assert "token request failed (SSLError)" in caplog.text
    assert OAUTH not in caplog.text


def test_insecure_hosts_is_a_read_only_view(network):
    http_client._INSECURE_HOSTS.add("example.org")
    view = http_client.insecure_hosts()

    assert view == frozenset({"example.org"})
    assert not hasattr(view, "add")


def test_an_oaq_signed_request_has_no_ssl_fallback(monkeypatch):
    from vayuayan import oaq

    seen = []

    def fake_request(method, url, **kwargs):
        seen.append(kwargs)
        return http_response(json_data={"signature": "sig=1"})

    monkeypatch.setattr(oaq.http_client, "request", fake_request)
    oaq.OAQClient("key")._get("meta/providers.json")

    assert len(seen) == 2 and not any(k.get("ssl_fallback") for k in seen)


# ---- item 8: live directory and OAuth


def test_a_401_clears_the_token_and_retries_once(network, cpcb_credentials):
    network.on("post", OAUTH, http_response(json_data={"access_token": "t"}))
    network.on(
        "get",
        STATES_QUERY,
        http_response(status=401),
        http_response(json_data=[{"state_name": "A"}]),
    )
    client = CPCBHistorical()

    assert client._new_state_list() == [{"state_name": "A"}]
    assert client.directory_source == "live"
    assert [c.url for c in network.calls].count(OAUTH) == 2


def test_a_second_401_uses_the_snapshot(network, cpcb_credentials):
    network.on("post", OAUTH, http_response(json_data={"access_token": "t"}))
    network.on("get", STATES_QUERY, http_response(status=401))
    client = CPCBHistorical()

    assert client._new_state_list()
    assert client.directory_source == "snapshot"
    assert len([c for c in network.calls if c.url == STATES_QUERY]) == 2


def test_directory_source_is_mixed_when_a_live_answer_is_empty(
    network, cpcb_credentials
):
    network.on("post", OAUTH, http_response(json_data={"access_token": "t"}))
    network.on("get", STATES_QUERY, http_response(json_data=[{"state_name": "A"}]))
    network.on(
        "get",
        f"{CUSTOM_QUERY}/get-city-master-list/data",
        http_response(json_data=[]),
    )
    client = CPCBHistorical()

    assert client.directory_source == "live"
    client._new_state_list()
    client._new_city_list("ST-01")

    assert client.directory_source == "mixed"


def test_the_auth_error_text_is_logged(monkeypatch, cpcb_credentials, caplog):
    client = CPCBHistorical()

    def refuse(*args, **kwargs):
        raise AuthenticationError("CPCB token response did not include access_token")

    monkeypatch.setattr(client, "_custom_query", refuse)
    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        client._new_state_list()

    assert "did not include access_token" in caplog.text


# ---- item 1: batch outcomes


def _with_station_lookup(client):
    client._resolved_station = lambda q, n="", s="", c="": {
        "station_id": q,
        "station_name": f"Name {q}",
        "city": "C",
        "state": "S",
    }


def test_outage_is_defined_by_the_failure():
    assert is_outage(requests.Timeout())
    assert is_outage(requests.ConnectionError())
    assert is_outage(_HTTP_503)
    assert is_outage(_cause(NetworkError("x"), _HTTP_503))
    not_found = requests.HTTPError("404", response=http_response(status=404))
    assert not is_outage(not_found)
    assert not is_outage(NetworkError("x"))
    assert not is_outage(
        _cause(
            DataNotFoundError("no report"),
            requests.HTTPError("500", response=http_response(status=500)),
        )
    )


def _cause(error, cause):
    error.__cause__ = cause
    return error


def _raw(frames):
    def fake(station, year, save, tidy=True, city="", state=""):
        outcome = frames[station]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return fake


LONG = pd.DataFrame(
    {"timestamp": ["2024-01-01"], "pollutant": ["PM2.5"], "value": [1.0]}
)


def test_raw_readings_names_each_station_and_warns_once(caplog):
    client = CPCBHistorical()
    client.download_raw_aqi_data_station_level = _raw(
        {
            "a": LONG,
            "b": DataNotFoundError("no file"),
            "c": StationNotFoundError("Station c not found"),
            "d": AmbiguousMatchError("'d' matches more than one: X; Y", ["X", "Y"]),
            "e": ValueError("cannot parse"),
        }
    )

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        out = client.raw_readings(["a", "b", "c", "d", "e"], 2024)

    assert out.attrs["station_status"] == {
        "a": "ok",
        "b": "no_data",
        "c": "not_found",
        "d": "ambiguous",
        "e": "error",
    }
    summaries = [r for r in caplog.records if "Partial result" in r.getMessage()]
    assert len(summaries) == 1
    assert "1 ok, 1 no_data, 1 not_found, 1 ambiguous, 1 error" in caplog.text
    assert "X; Y" in caplog.text  # the candidates are not lost


def test_a_503_stops_the_batch_and_keeps_what_it_has(caplog):
    client = CPCBHistorical()
    client.download_raw_aqi_data_station_level = _raw(
        {"a": LONG, "b": _cause(NetworkError("listing"), _HTTP_503), "c": LONG}
    )

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        out = client.raw_readings(["a", "b", "c"], 2024)

    assert len(out) == 1
    assert out.attrs["station_status"] == {
        "a": "ok",
        "b": "outage",
        "c": "not_attempted",
    }
    assert "1 ok, 1 outage, 1 not_attempted" in caplog.text


def test_nothing_fetched_in_an_outage_is_a_network_error():
    client = CPCBHistorical()
    client.download_raw_aqi_data_station_level = _raw({"a": requests.ConnectTimeout()})

    with pytest.raises(NetworkError, match="unavailable") as err:
        client.raw_readings(["a", "b"], 2024)

    assert err.value.station_status == {"a": "outage", "b": "not_attempted"}


def test_all_failed_with_no_outage_is_an_empty_frame_with_status():
    client = CPCBHistorical()
    client.download_raw_aqi_data_station_level = _raw({"a": DataNotFoundError("x")})

    out = client.raw_readings(["a"], 2024)

    assert out.empty and "pollutant" in out.columns
    assert out.attrs["station_status"] == {"a": "no_data"}


def test_station_daily_uses_the_same_loop(tmp_path):
    client = CPCBHistorical()
    _with_station_lookup(client)

    def fail(*args, **kwargs):
        raise requests.Timeout()

    client.download_past_year_aqi_data_station_level = fail

    with pytest.raises(NetworkError, match="unavailable"):
        client.station_daily(["a", "b"], 2020, cache_dir=str(tmp_path))


def test_station_daily_all_missing_keeps_its_columns(tmp_path):
    client = CPCBHistorical()
    _with_station_lookup(client)

    def nothing(*args, **kwargs):
        raise DataNotFoundError("none")

    client.download_past_year_aqi_data_station_level = nothing

    out = client.station_daily(["a"], 2020, cache_dir=str(tmp_path))

    assert list(out.columns) == [
        "station_id",
        "station_name",
        "day",
        "month",
        "value",
    ]
    assert out.attrs["station_status"] == {"a": "no_data"}
    assert not list(tmp_path.iterdir())  # no partial copy is left behind


def test_city_report_status_is_by_station_id_and_500_is_not_an_outage(monkeypatch):
    from vayuayan import cpcb_historical

    monkeypatch.setattr(cpcb_historical, "DOWNLOAD_WORKERS", 1)
    client = CPCBHistorical()
    client.station_table = lambda state="", city="": pd.DataFrame(
        {
            "station_id": ["s1", "s2"],
            "station_name": ["One", "Two"],
            "city": ["C", "C"],
            "state": ["S", "S"],
        }
    )

    def report(station_id, *args, **kwargs):
        if station_id == "s1":
            raise DataNotFoundError("CPCB could not build this report")
        return pd.DataFrame({"Timestamp": ["t"], "PM2.5 (µg/m³)": [1.0]})

    client.download_station_report = report

    out = client.download_city_report("C", "2026-01-01", "2026-01-02", state="S")

    assert out.attrs["station_status"] == {"s1": "no_data", "s2": "ok"}


# ---- item 4: station and place resolution


def test_ambiguous_match_is_a_station_not_found_with_candidates():
    error = AmbiguousMatchError("two", ["A", "B"])

    assert isinstance(error, StationNotFoundError)
    assert error.candidates == ["A", "B"]


def test_raw_download_raises_for_a_station_that_does_not_resolve():
    client = CPCBHistorical()

    with pytest.raises(StationNotFoundError, match="site_99999"):
        client.download_raw_aqi_data_station_level("site_99999", "2024", "")


@pytest.mark.parametrize("city", ["Aurangabad", "aurangabad", "Byrnihat"])
def test_a_city_in_two_states_needs_a_state(city):
    client = CPCBHistorical()

    with pytest.raises(AmbiguousMatchError) as err:
        client.get_file_path("", "", "", city, "2023", "daily", "cityLevel")

    assert len(err.value.candidates) == 2
    assert all(state in str(err.value) for state in err.value.candidates)


def test_every_city_argument_is_checked():
    client = CPCBHistorical()
    calls = [
        lambda: client.get_station_list("Aurangabad"),
        lambda: list(client.iter_stations(city="Aurangabad")),
        lambda: client.download_past_year_aqi_data_city_level("Aurangabad", "2023", ""),
        lambda: client.download_hourly_aqi_data_city_level("Aurangabad", "2023", ""),
        lambda: client.city_daily("Aurangabad", 2023),
        lambda: client.raw_readings(city="Aurangabad", year=2023),
        lambda: client.station_daily(city="Aurangabad", year=2023),
        lambda: client.download_city_report("Aurangabad", "2023-01-01", "2023-01-02"),
    ]
    for call in calls:
        with pytest.raises(AmbiguousMatchError):
            call()


def test_a_named_station_in_an_ambiguous_city_is_ambiguous():
    with pytest.raises(AmbiguousMatchError):
        CPCBHistorical()._resolve_station("anything", city="Aurangabad")


def test_a_state_settles_the_city():
    client = CPCBHistorical()

    assert client.get_station_list("Aurangabad", state="Maharashtra")
    bihar = client._city_stations("Aurangabad", "Bihar")
    assert set(bihar["state"]) == {"Bihar"}


def test_station_table_still_lists_both():
    table = CPCBHistorical().station_table(city="Aurangabad")

    assert {"Bihar", "Maharashtra"} <= set(table["state"])


def test_a_feed_spelling_of_a_directory_state_is_not_a_second_state():
    client = CPCBHistorical()
    client.station_table = lambda state="", city="": pd.DataFrame(
        {"station_id": ["a", "b"], "state": ["Jammu & Kashmir", "Jammu and Kashmir"]}
    )

    assert len(client._city_stations("Srinagar")) == 2


def test_a_part_of_a_name_in_the_directory_and_the_feed_is_ambiguous(rss_feed):
    client = CPCBHistorical()
    state, city, directory_station = next(client.iter_stations())
    word = directory_station["station_name"].split()[0]
    rss_feed(
        [
            {
                "cityName": city["city_name"],
                "cityID": city["city_name"],
                "stateID": state["state_name"],
                "stationsInCity": [
                    {"id": "site_new", "name": f"{word} Feed Only"},
                ],
            }
        ]
    )

    with pytest.raises(AmbiguousMatchError) as err:
        client._resolve_station(word)

    assert f"{word} Feed Only" in err.value.candidates


# ---- item 5: file listing and token download


def test_a_listing_204_on_both_routes_is_no_files(network):
    network.on("post", FILE_PATH, http_response(b"", status=204))
    network.on("post", LEGACY_FILE_PATH, http_response(b"", status=204))
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    args = ("site_1", "ITO", "Delhi", "Delhi", "2024", "daily", "stationLevel")
    assert CPCBHistorical().get_file_path(*args) == []


def test_a_failed_listing_is_an_outage_only_when_the_cause_is(network):
    network.on("post", FILE_PATH, http_response(status=503))
    network.on("post", LEGACY_FILE_PATH, http_response(status=503))
    network.on("get", RSS, http_response(json_data=RSS_FEED))
    args = ("site_1", "ITO", "Delhi", "Delhi", "2024", "daily", "stationLevel")

    with pytest.raises(NetworkError) as err:
        CPCBHistorical().get_file_path(*args)

    assert is_outage(err.value)


# ---- item 7 and 11: live reading and liveness


def _feed_station(sid, lat, value="70", last="09-11-2026 10:00:00", live=True):
    return {
        "id": sid,
        "name": f"Name {sid}",
        "latitude": lat,
        "longitude": 77.0,
        "live": live,
        "avg": value,
        "lastUpdate": last,
        "airQualityIndex": {"value": value},
        "pollutants": [],
    }


def _cities(*stations):
    return [{"cityName": "C", "stateID": "S", "stationsInCity": list(stations)}]


def test_dashboard_reading_carries_its_source():
    client = CPCBLive()
    client._make_request = lambda url, payload: {
        "metrics": [{"name": "PM2.5"}],
        "airQualityIndex": {"value": "90"},
        "lastUpdate": "09-11-2026 10:00:00",
    }

    data = client.get_live_aqi_data_for_station("site_1", "d")

    assert data["source"] == "dashboard"
    assert data["reading_state"] == "reading"
    assert data["as_of"] == "09-11-2026 10:00:00"


def test_a_dashboard_reply_without_metrics_falls_back_to_the_feed(network, rss_feed):
    client = CPCBLive()
    client._make_request = lambda url, payload: {"metrics": []}
    client._rss_cities = lambda: _cities(_feed_station("site_1", 28.0, value="NA"))

    data = client.get_live_aqi_data_for_station("site_1", "2020-01-01T00:00:00Z")

    assert data["source"] == "rss"
    assert data["reading_state"] == "no_reading"
    assert data["as_of"] == "09-11-2026 10:00:00"


def test_an_unknown_site_id_is_not_found(monkeypatch):
    client = CPCBLive()
    client._make_request = lambda url, payload: {"metrics": []}
    client._rss_cities = lambda: _cities(_feed_station("site_1", 28.0))

    with pytest.raises(StationNotFoundError):
        client.get_live_aqi_data_for_station("site_404", "d")


def test_get_all_india_says_where_it_came_from():
    client = CPCBLive()
    client._make_request = lambda url, payload: {"stations": [{"cityName": "A"}]}
    assert client.station_list_source is None

    client.get_all_india()

    assert client.station_list_source == "dashboard"


def _nearest_client():
    client = CPCBLive()
    client.get_all_india = lambda: _cities(
        _feed_station("near", 28.0, value="NA"),
        _feed_station("far", 29.0),
    )
    client.get_system_location = lambda: (28.0, 77.0)
    return client


def test_coordinates_keep_distance_order():
    assert _nearest_client().get_nearest_station((28.0, 77.0))[0] == "near"


def test_coordinates_can_ask_for_a_reading():
    client = _nearest_client()
    found = client.get_nearest_station((28.0, 77.0), prefer_reading=True)

    assert found[0] == "far"


def test_the_ip_location_prefers_a_reading():
    assert _nearest_client().get_nearest_station()[0] == "far"


def test_no_reading_anywhere_is_still_the_nearest():
    client = CPCBLive()
    client.get_all_india = lambda: _cities(
        _feed_station("near", 28.0, value="NA"), _feed_station("far", 29.0, value="NA")
    )

    assert client.get_nearest_station((28.0, 77.0), prefer_reading=True)[0] == "near"


def test_get_live_aqi_data_prefers_a_reading_even_with_coordinates():
    client = _nearest_client()
    asked = []
    client.get_live_aqi_data_for_station = lambda sid, dt: asked.append(sid) or {}

    client.get_live_aqi_data(coords=(28.0, 77.0))

    assert asked == ["far"]


# ---- item 12: CSV copies


SHEET = pd.DataFrame({"Day": [1], "Jan": [10]})


def _counting_client(tmp_path):
    client = CPCBHistorical()
    client.get_file_path = lambda *a: [
        {"year": str(date.today().year), "filepath": "/a"},
        {"year": "2020", "filepath": "/b"},
    ]
    calls = []

    def read(entries, year):
        calls.append(year)
        return SHEET

    client._read_year_excel = read
    return client, calls


def test_a_past_year_copy_is_reused_and_the_current_year_is_not(tmp_path):
    client, calls = _counting_client(tmp_path)
    this_year = date.today().year

    client.city_daily("Delhi", [2020, this_year], cache_dir=str(tmp_path))
    client.city_daily("Delhi", [2020, this_year], cache_dir=str(tmp_path))

    assert calls.count("2020") == 1
    assert calls.count(str(this_year)) == 2
    assert not list(tmp_path.glob("*.part"))


def test_city_copies_with_a_state_have_their_own_name(tmp_path):
    client, _ = _counting_client(tmp_path)

    client.city_daily("Aurangabad", 2020, cache_dir=str(tmp_path), state="Bihar")

    assert (tmp_path / "bihar_aurangabad_aqi_2020.csv").exists()


def test_a_failed_copy_leaves_no_file(tmp_path):
    client, _ = _counting_client(tmp_path)

    def broken(*a):
        raise DataNotFoundError("none")

    client._read_year_excel = broken

    with pytest.raises(DataNotFoundError):
        client.city_daily("Delhi", 2020, cache_dir=str(tmp_path))
    assert not list(tmp_path.iterdir())
