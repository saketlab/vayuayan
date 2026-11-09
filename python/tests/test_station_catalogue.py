"""The station catalogue, city input of the batch functions and city report outages."""

import logging

import pandas as pd
import pytest
import requests

from vayuayan import CPCBHistorical, cpcb_common, cpcb_historical, us_aqi
from vayuayan.exceptions import (
    CityNotFoundError,
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)

NEW_DELHI = {
    "stateID": "Delhi",
    "cityName": "Delhi",
    "stationsInCity": [
        {
            "id": "site_new",
            "name": "New Station",
            "latitude": "28.5",
            "longitude": "77",
        },
        {"id": "site_301", "name": "Feed spelling", "latitude": "1", "longitude": "2"},
    ],
}
NEW_GOA = {
    "stateID": "Goa",
    "cityName": "Panaji",
    "stationsInCity": [
        {"id": "site_goa", "name": "Goa Station", "latitude": "15", "longitude": "74"}
    ],
}


def test_station_table_adds_feed_only_stations_with_their_coordinates(rss_feed):
    rss_feed([NEW_DELHI, NEW_GOA])

    table = CPCBHistorical().station_table(city="Delhi")

    row = table[table["station_id"] == "site_new"].iloc[0]
    assert row.to_dict() == {
        "station_id": "site_new",
        "station_name": "New Station",
        "city": "Delhi",
        "state": "Delhi",
        "latitude": 28.5,
        "longitude": 77.0,
    }
    assert "site_goa" not in set(table["station_id"])
    assert list(table["station_name"]) == sorted(table["station_name"])


def test_a_station_in_both_comes_from_the_directory(rss_feed):
    rss_feed([NEW_DELHI])

    table = CPCBHistorical().station_table(city="Delhi")

    rows = table[table["station_id"] == "site_301"]
    assert list(rows["station_name"]) == ["Anand Vihar, Delhi - DPCC"]
    assert rows["latitude"].iloc[0] == pytest.approx(28.647, abs=0.01)


@pytest.mark.parametrize(
    "filters,found",
    [
        ({"state": "Goa"}, True),
        ({"city": "panaji"}, True),
        ({"state": "Delhi"}, False),
        ({"city": "Delhi"}, False),
        ({"city": "Panaji", "state": "Delhi"}, False),
    ],
)
def test_filters_apply_to_feed_only_stations(rss_feed, filters, found):
    rss_feed([NEW_GOA])

    table = CPCBHistorical().station_table(**filters)

    assert ("site_goa" in set(table["station_id"])) is found


def test_a_state_or_city_code_also_selects_feed_only_stations(rss_feed):
    rss_feed([NEW_DELHI])
    client = CPCBHistorical()
    _, city = client._resolve_city("Delhi")

    by_city = client.station_table(city=city["city_code"])
    by_state = client.station_table(state="ST-10")

    assert "site_new" in set(by_city["station_id"])
    assert "site_new" in set(by_state["station_id"])


def test_a_feed_failure_leaves_the_directory_and_logs_at_info(caplog):
    with caplog.at_level(logging.INFO, logger="vayuayan"):
        table = CPCBHistorical().station_table(city="Delhi")

    assert "site_301" in set(table["station_id"])
    feed_logs = [r for r in caplog.records if "RSS feed" in r.getMessage()]
    assert [r.levelno for r in feed_logs] == [logging.INFO]


def test_one_city_fetches_only_its_stations(cpcb_credentials, rss_feed):
    rss_feed([])
    client = CPCBHistorical()
    station_queries = []

    def custom_query(name, filter_query=""):
        if name.startswith("get-state"):
            return [{"state_code": f"S{i}", "state_name": f"State {i}"} for i in (0, 1)]
        code = filter_query.split("'")[1]
        if name == "get-city-master-list":
            return [{"city_code": f"{code}C", "city_name": f"City {code}"}]
        station_queries.append(code)
        return [{"station_id": f"site_{code}", "station_name": f"Station {code}"}]

    client._custom_query = custom_query

    table = client.station_table(city="City S1")

    assert list(table["station_id"]) == ["site_S1C"]
    assert station_queries == ["S1C"]


def test_station_list_keeps_directory_and_feed_stations_once(rss_feed):
    rss_feed([NEW_DELHI])

    stations = CPCBHistorical().get_station_list("Delhi")

    values = [s["value"] for s in stations]
    assert values.count("site_301") == 1 and "site_new" in values
    assert {"label": "Anand Vihar, Delhi - DPCC", "value": "site_301"} in stations


def test_city_narrows_an_ambiguous_name_also_in_the_feed(rss_feed):
    hapur = {
        "stateID": "Uttar Pradesh",
        "cityName": "Hapur",
        "stationsInCity": [{"id": "site_5023", "name": "Anand Vihar, Hapur - UPPCB"}],
    }
    rss_feed([hapur])
    client = CPCBHistorical()

    with pytest.raises(StationNotFoundError, match="more than one"):
        client._resolve_station("Anand Vihar")

    _, _, station = client._resolve_station("Anand Vihar", city="Delhi")
    assert station["station_id"] == "site_301"
    _, _, station = client._resolve_station("Anand Vihar", state="Delhi")
    assert station["station_id"] == "site_301"
    _, _, station = client._resolve_station("Anand Vihar", state="Uttar Pradesh")
    assert station["station_id"] == "site_5023"


def test_single_station_functions_pass_city_and_state_to_the_resolver(monkeypatch):
    client = CPCBHistorical()
    asked = []

    def resolved(station_id, station_name="", state="", city=""):
        asked.append((station_id, state, city))
        return None

    monkeypatch.setattr(client, "_resolved_station", resolved)

    with pytest.raises(StationNotFoundError):
        client.download_station_report(
            "Anand Vihar", "2025-01-01", "2025-01-02", city="Delhi", state="Delhi"
        )
    with pytest.raises(StationNotFoundError):
        client.download_past_year_aqi_data_station_level(
            "Anand Vihar", "2024", "", city="Delhi", state="Delhi"
        )

    assert asked == [("Anand Vihar", "Delhi", "Delhi")] * 2


def test_daily_aqi_narrows_both_years(monkeypatch):
    client = CPCBHistorical()
    asked = []

    def raw(station, year, path, tidy=False, city="", state=""):
        asked.append((station, year, city, state))
        return pd.DataFrame(
            {"timestamp": [pd.Timestamp(int(year), 12, 31, 10)], "pollutant": ["PM2.5"],
             "value": [50.0]}
        )  # fmt: skip

    monkeypatch.setattr(client, "download_raw_aqi_data_station_level", raw)

    client.daily_aqi("Anand Vihar", "2024", day_ends_at=16, city="Delhi", state="Delhi")

    assert asked == [
        ("Anand Vihar", "2024", "Delhi", "Delhi"),
        ("Anand Vihar", "2023", "Delhi", "Delhi"),
    ]


def _raw_frame(station):
    return pd.DataFrame(
        {"station_id": [station], "pollutant": ["PM2.5"], "value": [1.0]}
    )


def test_raw_readings_expands_a_city(monkeypatch, rss_feed):
    rss_feed([NEW_DELHI])
    client = CPCBHistorical()
    monkeypatch.setattr(
        client,
        "download_raw_aqi_data_station_level",
        lambda station, year, path, tidy=False, city="", state="": _raw_frame(station),
    )

    out = client.raw_readings(year=2024, city="Delhi", state="Delhi")

    expected = set(client.station_table("Delhi", "Delhi")["station_id"])
    assert set(out["station_id"]) == expected and "site_new" in expected


def test_raw_readings_keeps_positional_calls_and_narrows_names(monkeypatch):
    client = CPCBHistorical()
    asked = []

    def raw(station, year, path, tidy=False, city="", state=""):
        asked.append((station, year, city))
        return _raw_frame(station)

    monkeypatch.setattr(client, "download_raw_aqi_data_station_level", raw)

    out = client.raw_readings("Anand Vihar", 2024, ["PM2.5"], city="Delhi")

    assert asked == [("Anand Vihar", "2024", "Delhi")]
    assert list(out["pollutant"]) == ["PM2.5"]


@pytest.mark.parametrize("method", ["raw_readings", "station_daily"])
def test_batch_functions_need_a_station_or_a_city(method):
    with pytest.raises(ValueError, match="station_ids or a city"):
        getattr(CPCBHistorical(), method)(year=2024)
    with pytest.raises(ValueError, match="station_ids or a city"):
        getattr(CPCBHistorical(), method)([], 2024)


@pytest.mark.parametrize("method", ["raw_readings", "station_daily"])
def test_batch_functions_need_a_year(method):
    with pytest.raises(ValueError, match="year"):
        getattr(CPCBHistorical(), method)(["site_301"])


@pytest.mark.parametrize("method", ["raw_readings", "station_daily"])
def test_batch_functions_reject_an_unknown_city(method):
    with pytest.raises(CityNotFoundError, match="Atlantis"):
        getattr(CPCBHistorical(), method)(year=2024, city="Atlantis")


def test_station_daily_expands_a_city_and_narrows_names(tmp_path, monkeypatch):
    client = CPCBHistorical()
    asked = []

    def past_year(station_id, year, path, city="", state=""):
        asked.append((station_id, city))
        pd.DataFrame({"Day": [1], "January": [55]}).to_csv(path, index=False)

    monkeypatch.setattr(client, "download_past_year_aqi_data_station_level", past_year)

    out = client.station_daily("Anand Vihar", 2023, str(tmp_path), city="Delhi")

    assert asked == [("site_301", "Delhi")]
    assert list(out["station_id"]) == ["site_301"]

    everyone = client.station_daily(year=2023, cache_dir=str(tmp_path), city="Delhi")
    assert set(everyone["station_id"]) == set(
        client.station_table(city="Delhi")["station_id"]
    )


def _report_ok():
    return pd.DataFrame({"Timestamp": ["2026-11-08 00:00:00"], "PM2.5": [50]})


@pytest.fixture
def one_worker(monkeypatch):
    """Requests in table order, so the first failure is known."""
    monkeypatch.setattr(cpcb_historical, "DOWNLOAD_WORKERS", 1)


def _city_report(client):
    return client.download_city_report("Delhi", "2026-11-08", "2026-11-09")


def _outage_warnings(caplog):
    return [r for r in caplog.records if "outage" in r.getMessage()]


def _table(client):
    return list(client.station_table(city="Delhi")["station_id"])


def test_an_outage_stops_the_run_and_keeps_what_succeeded(one_worker, caplog):
    client = CPCBHistorical()
    first, second = _table(client)[:2]
    asked = []

    def report(station_id, *args, **kwargs):
        asked.append(station_id)
        if station_id == second:
            raise NetworkError("down") from requests.ConnectionError("down")
        return _report_ok()

    client.download_station_report = report

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        out = _city_report(client)

    assert asked == [first, second]
    assert list(out["station_id"]) == [first]
    assert len(_outage_warnings(caplog)) == 1
    assert not [r for r in caplog.records if "Skipped" in r.getMessage()]


def test_a_timeout_is_an_outage(one_worker, caplog):
    client = CPCBHistorical()
    asked = []

    def report(station_id, *args, **kwargs):
        asked.append(station_id)
        raise requests.Timeout("slow")

    client.download_station_report = report

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        with pytest.raises(NetworkError, match="unavailable"):
            _city_report(client)

    # nothing was fetched, so the error says it all and no warning repeats it
    assert len(asked) == 1 and len(_outage_warnings(caplog)) == 0


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(DataNotFoundError("no report"), id="no-report"),
        pytest.param(NetworkError("HTTP 503"), id="http-status"),
        pytest.param(requests.HTTPError("503"), id="http-error"),
    ],
)
def test_other_failures_do_not_stop_the_run(one_worker, caplog, error):
    client = CPCBHistorical()
    stations = _table(client)
    asked = []

    def report(station_id, *args, **kwargs):
        asked.append(station_id)
        if station_id == stations[0]:
            raise error
        return _report_ok()

    client.download_station_report = report

    with caplog.at_level(logging.WARNING, logger="vayuayan"):
        out = _city_report(client)

    assert asked == stations
    assert len(out) == len(stations) - 1
    assert not _outage_warnings(caplog)


def test_is_outage_reads_the_cause_of_a_network_error():
    wrapped = NetworkError("down")
    wrapped.__cause__ = requests.Timeout("slow")
    plain = NetworkError("HTTP 503")
    plain.__cause__ = requests.HTTPError("503")

    assert cpcb_common.is_outage(wrapped)
    assert cpcb_common.is_outage(requests.ConnectionError("down"))
    assert not cpcb_common.is_outage(plain)
    assert not cpcb_common.is_outage(DataNotFoundError("no report"))


@pytest.mark.parametrize("label", ["SO2 (24h) (ppb)", "SO2 24h", "SO2_24h"])
def test_24_hour_so2_labels(label):
    assert us_aqi.us_pollutant_name(label) == "SO2_24h"


@pytest.mark.parametrize("label", ["SO2", "SO2 (ppb)", "SO2 (µg/m³)", "SO2 1h"])
def test_other_so2_labels_stay_1_hour(label):
    assert us_aqi.us_pollutant_name(label) == "SO2"
