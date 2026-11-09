"""The CLI commands return plain data; nothing here needs a terminal."""

from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from vayuayan import commands
from vayuayan.cli_places import catalogue_from_table, resolve_place
from vayuayan.cli_results import EXIT_CODES, CommandResult, error_result, write_rows
from vayuayan.commands_history import HistoryRequest, _days_in_period
from vayuayan.commands_report import ReportRequest
from vayuayan.exceptions import (
    CityNotFoundError,
    DataNotFoundError,
    DataParsingError,
    NetworkError,
    StationNotFoundError,
)
from vayuayan.exceptions import FileNotFoundError as CPCBFileNotFoundError

from .cli_fakes import (
    NOW,
    OLD,
    FakeHistorical,
    FakeLive,
    catalogue,
    feed_station,
    workbook,
)

STATIONS = catalogue_from_table(catalogue())


def _place(query):
    return resolve_place(query, STATIONS)


def _old_feed():
    """Every station has an old reading."""
    return [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [
                feed_station("site_2", "Kurla", 19.08, 72.88, updated=OLD),
                feed_station("site_1", "Powai", 19.13, 72.91, updated=OLD),
            ],
        }
    ]


@pytest.mark.parametrize(
    "status,code",
    [
        ("ok", 0),
        ("error", 1),
        ("usage_error", 2),
        ("not_found", 3),
        ("ambiguous", 4),
        ("no_data", 5),
        ("network_error", 6),
        ("location_unknown", 6),
    ],
)
def test_exit_codes_are_pinned(status, code):
    assert EXIT_CODES[status] == code
    assert CommandResult("x", status).exit_code == code


def test_document_is_flat_strict_json():
    result = CommandResult(
        "x",
        "ok",
        {"value": float("nan"), "when": date(2025, 1, 2), "items": ({"n": 1},)},
        "hello",
    )

    document = result.to_document()

    assert document == {
        "status": "ok",
        "command": "x",
        "message": "hello",
        "value": None,
        "when": "2025-01-02",
        "items": [{"n": 1}],
    }
    json.dumps(document, allow_nan=False)


def test_document_turns_numpy_numbers_into_plain_ones():
    import numpy as np

    document = CommandResult("x", "ok", {"n": np.float64(1.5)}).to_document()

    assert type(document["n"]) is float


@pytest.mark.parametrize(
    "error,status",
    [
        (StationNotFoundError("x"), "not_found"),
        (CityNotFoundError("x"), "not_found"),
        (DataNotFoundError("x"), "no_data"),
        (FileNotFoundError("x"), "not_found"),
        (CPCBFileNotFoundError("x"), "not_found"),
        (NetworkError("x"), "network_error"),
        (DataParsingError("x"), "network_error"),
        (requests.ConnectionError("x"), "network_error"),
        (PermissionError("no"), "error"),
        (RuntimeError("boom"), "error"),
    ],
)
def test_errors_become_results(error, status):
    assert error_result("x", error).status == status


def test_network_errors_do_not_show_technical_details():
    result = error_result("x", requests.ConnectionError("HTTPSConnectionPool(...)"))

    assert "HTTPSConnectionPool" not in result.message
    assert "CPCB" in result.message


def test_write_rows_creates_the_folder(tmp_path):
    target = tmp_path / "new" / "out.csv"

    write_rows([{"a": 1}], str(target))

    assert target.read_text().splitlines() == ["a", "1"]


def test_lookup_place_passes_the_filters():
    client = FakeHistorical()

    place = commands.lookup_place(client, "powai", "Mumbai", "Maharashtra")

    assert place.station.id == "site_1"
    assert client.calls == [("station_table", "Maharashtra", "Mumbai")]


def test_live_station_panel_data():
    result = commands.live_place(FakeLive(), _place("powai"), NOW)

    assert (result.status, result.exit_code) == ("ok", 0)
    assert result.data["place"] == "station"
    assert result.data["reading"]["status"] == "live"
    assert result.message == ""


def test_live_old_reading_says_so_and_still_succeeds():
    result = commands.live_place(FakeLive(_old_feed()), _place("powai"), NOW)

    assert (result.status, result.data["reading"]["status"]) == ("ok", "stale")
    assert "old" in result.message


def test_live_offline_station_is_no_data_not_a_failure():
    result = commands.live_place(FakeLive(), _place("colaba"), NOW)

    assert result.status == "no_data" and result.exit_code == 5
    assert result.data["reading"]["status"] == "offline"
    assert "offline" in result.message


def test_live_station_the_feed_lacks_is_offline():
    result = commands.live_place(FakeLive(), _place("panaji"), NOW)

    assert result.data["reading"]["status"] == "offline"


def test_live_no_reading_is_its_own_state():
    cities = [
        {
            "cityName": "Mumbai",
            "stateID": "Maharashtra",
            "stationsInCity": [
                feed_station("site_1", "Powai", 19.1, 72.9, aqi="NA"),
            ],
        }
    ]

    result = commands.live_place(FakeLive(cities), _place("powai"), NOW)

    assert (result.status, result.data["reading"]["status"]) == (
        "no_data",
        "no_reading",
    )


def test_live_fetch_failure_is_network_error_not_offline():
    result = commands.live_place(FakeLive(down=True), _place("powai"), NOW)

    assert result.status == "network_error" and result.exit_code == 6
    assert result.data["reading"]["status"] == "fetch_failed"


def test_live_city_is_ranked_worst_first_with_offline_last():
    result = commands.live_place(FakeLive(), _place("mumbai"), NOW)

    assert result.status == "ok"
    assert [r["station"]["id"] for r in result.data["readings"]] == [
        "site_2",
        "site_1",
        "site_3",
    ]
    assert result.data["city"] == "Mumbai"


def test_live_city_during_a_feed_failure():
    result = commands.live_place(FakeLive(down=True), _place("mumbai"), NOW)

    assert result.status == "network_error"
    assert "readings" not in result.data


def test_live_city_with_no_readings_is_no_data():
    result = commands.live_place(
        FakeLive(cities=[{"stationsInCity": []}]), _place("mumbai"), NOW
    )

    assert result.status == "no_data"
    assert result.message.startswith("No station in Mumbai")


def test_live_not_found_and_ambiguous():
    missing = commands.live_place(FakeLive(), _place("atlantis"), NOW)
    several = commands.live_place(FakeLive(), _place("vihar"), NOW)

    assert (missing.status, missing.exit_code) == ("not_found", 3)
    assert (several.status, several.exit_code) == ("ambiguous", 4)
    assert [m["id"] for m in several.data["matches"]] == ["site_8", "site_7"]


def test_near_picks_the_nearest_live_station_and_skips_offline():
    # Colaba would be nearest of the three to this point, but it is offline
    result = commands.live_near(FakeLive(location=(18.9, 72.8)), now=NOW)

    assert result.status == "ok"
    assert result.data["place"] == "nearest"
    assert result.data["source"] == "ip"
    assert result.data["reading"]["station"]["id"] == "site_2"
    assert result.data["distance_km"] > 0


def test_near_uses_given_coordinates_without_the_ip_lookup():
    result = commands.live_near(FakeLive(ip_down=True), (28.6, 77.2), NOW)

    assert result.data["source"] == "coordinates"
    assert result.data["reading"]["station"]["id"] == "site_9"


def test_near_falls_back_to_the_nearest_old_reading_and_says_so():
    result = commands.live_near(FakeLive(_old_feed()), now=NOW)

    assert result.data["reading"]["status"] == "stale"
    assert "older" in result.message


def test_near_when_the_ip_lookup_fails():
    result = commands.live_near(FakeLive(ip_down=True), now=NOW)

    assert result.status == "location_unknown" and result.exit_code == 6
    assert "location" in result.message


def test_near_when_the_feed_fails():
    assert commands.live_near(FakeLive(down=True), now=NOW).status == "network_error"


def test_near_with_no_readable_stations_is_no_data():
    cities = [
        {
            "cityName": "X",
            "stateID": "Y",
            "stationsInCity": [
                feed_station("s", "S", 1.0, 2.0, aqi="NA", updated="NA"),
            ],
        }
    ]

    assert commands.live_near(FakeLive(cities), now=NOW).status == "no_data"


def test_history_of_a_station_uses_the_published_workbook():
    client = FakeHistorical()

    result = commands.history(
        client, _place("powai"), HistoryRequest(2025), today=date(2026, 11, 9)
    )

    assert result.status == "ok"
    assert client.calls[0][0] == "station_year"
    assert client.calls[0][1] == ("site_1", "2025", "")
    assert client.calls[0][2] == {"city": "Mumbai", "state": "Maharashtra"}
    data = result.data
    assert (data["standard"], data["source"]) == ("india", "published")
    assert [d["aqi"] for d in data["days"]] == [40, 150, 420]
    assert [d["category"] for d in data["days"]] == ["Good", "Moderate", "Severe"]


def test_history_summary():
    data = commands.history(
        FakeHistorical(), _place("powai"), HistoryRequest(2025), today=date(2026, 11, 9)
    ).data

    summary = data["summary"]
    assert summary["mean"] == pytest.approx(203.3, abs=0.05)
    assert summary["mean_category"] == "Poor"
    assert summary["worst"]["aqi"] == 420 and summary["best"]["aqi"] == 40
    assert summary["days_with_data"] == 3 and summary["days_in_period"] == 365
    assert summary["category_counts"] == {
        "Good": 1,
        "Satisfactory": 0,
        "Moderate": 1,
        "Poor": 0,
        "Very Poor": 0,
        "Severe": 1,
    }


def test_history_of_a_city_uses_the_city_workbook_with_its_state():
    client = FakeHistorical()

    result = commands.history(client, _place("mumbai"), HistoryRequest(2025))

    assert client.calls[0][0] == "city_year"
    assert client.calls[0][1] == ("Mumbai", "2025", "")
    assert client.calls[0][2] == {"state": "Maharashtra"}
    assert result.data["place"] == "city"
    assert result.data["months"][0]["name"] == "January"


def test_history_month_narrows_the_days():
    sheet = workbook({"January": {1: 40}, "February": {2: 150}})

    result = commands.history(
        FakeHistorical(sheet=sheet),
        _place("powai"),
        HistoryRequest(2025, month=2),
        today=date(2026, 11, 9),
    )

    assert [d["date"] for d in result.data["days"]] == ["2025-02-02"]
    assert result.data["summary"]["days_in_period"] == 28


def test_history_year_without_data_says_so():
    result = commands.history(
        FakeHistorical(sheet=workbook({"January": {}})),
        _place("powai"),
        HistoryRequest(2025),
    )

    assert (result.status, result.exit_code) == ("no_data", 5)
    assert "2025" in result.message


def test_history_month_without_data_names_the_month():
    result = commands.history(
        FakeHistorical(), _place("powai"), HistoryRequest(2025, month=7)
    )

    assert "July 2025" in result.message


def test_history_us_is_computed_and_says_so():
    client = FakeHistorical()
    told = []

    result = commands.history(
        client, _place("powai"), HistoryRequest(2025, standard="us"), told.append
    )

    assert client.calls[0][0] == "daily_aqi"
    assert client.calls[0][2]["standard"] == "us"
    assert client.calls[0][2]["day_ends_at"] == 24
    assert "raw readings" in told[0] and "US AQI" in told[0]
    assert result.data["source"] == "computed"
    assert result.data["standard"] == "us"
    assert [d["category"] for d in result.data["days"]] == [
        "Unhealthy for Sensitive Groups",
        "Hazardous",
    ]


def test_history_computed_bulletin_uses_the_4_pm_day():
    client = FakeHistorical()

    commands.history(
        client,
        _place("powai"),
        HistoryRequest(2025, computed=True, bulletin=True),
    )

    assert client.calls[0][2]["day_ends_at"] == 16


def test_history_us_for_a_city_asks_for_a_station():
    client = FakeHistorical()

    result = commands.history(
        client, _place("mumbai"), HistoryRequest(2025, standard="us")
    )

    assert result.status == "ambiguous"
    assert len(result.data["matches"]) == 3
    assert "station" in result.message
    assert client.calls == []


def test_history_not_found():
    assert (
        commands.history(
            FakeHistorical(), _place("atlantis"), HistoryRequest(2025)
        ).status
        == "not_found"
    )


def test_history_save_writes_the_days(tmp_path):
    target = tmp_path / "sub" / "days.csv"

    result = commands.history(
        FakeHistorical(), _place("powai"), HistoryRequest(2025, save=str(target))
    )

    assert result.data["saved"] == str(target)
    saved = pd.read_csv(target)
    assert list(saved["aqi"]) == [40, 150, 420]


@pytest.mark.parametrize(
    "year,month,today,expected",
    [
        (2025, None, date(2026, 1, 1), 365),
        (2026, None, date(2026, 3, 1), 60),
        (2024, 2, date(2026, 1, 1), 29),
        (2027, None, date(2026, 1, 1), 0),
    ],
)
def test_days_in_period_ignores_the_future(year, month, today, expected):
    assert _days_in_period(year, month, today) == expected


def _report(**kwargs):
    return ReportRequest(
        datetime(2026, 11, 8), datetime(2026, 11, 9), "hourly", None, **kwargs
    )


def test_report_of_a_station():
    client = FakeHistorical()
    told = []

    result = commands.history_report(client, _place("powai"), _report(), told.append)

    assert client.calls[0][0] == "station_report"
    assert client.calls[0][1][0] == "site_1"
    assert client.calls[0][2] == {"city": "Mumbai", "state": "Maharashtra"}
    assert told
    data = result.data
    assert data["kind"] == "report" and data["place"] == "station"
    assert data["summary"] == [
        {
            "pollutant": "PM2.5",
            "unit": "µg/m³",
            "lowest": 10.0,
            "mean": 15.0,
            "highest": 20.0,
            "readings": 2,
        }
    ]
    assert data["rows"][0]["CO (mg/m³)"] is None
    assert data["from"] == "2026-11-08T00:00:00"


def test_report_of_a_city_passes_its_state_and_saves(tmp_path):
    client = FakeHistorical()
    target = tmp_path / "r.csv"

    result = commands.history_report(
        client, _place("mumbai"), _report(save=str(target))
    )

    assert client.calls[0][0] == "city_report"
    assert client.calls[0][1][-1] == "Maharashtra"
    assert result.data["station_count"] == 3
    assert target.exists()


def test_report_unresolved_place():
    client = FakeHistorical()

    assert (
        commands.history_report(client, _place("atlantis"), _report()).status
        == "not_found"
    )
    assert client.calls == []


def test_find_lists_every_match():
    result = commands.find_stations(_place("anand vihar"))

    assert (result.status, result.data["count"]) == ("ok", 2)
    assert result.data["matches"][0]["name"].startswith("Anand Vihar")


def test_find_of_a_city_lists_its_stations(tmp_path):
    target = tmp_path / "f.csv"

    result = commands.find_stations(_place("mumbai"), str(target))

    assert result.data["count"] == 3
    assert result.data["saved"] == str(target)
    assert len(pd.read_csv(target)) == 3


def test_find_with_nothing_found():
    result = commands.find_stations(_place("atlantis"))

    assert (result.status, result.exit_code) == ("not_found", 3)


def test_stations_lists_and_filters():
    client = FakeHistorical()

    result = commands.list_stations(client, "", "Goa")

    assert result.data["count"] == 1
    assert client.calls == [("station_table", "Goa", "")]


def test_stations_nothing_matches():
    assert commands.list_stations(FakeHistorical(), "Atlantis").status == "not_found"


def test_stations_saves_the_table(tmp_path):
    target = tmp_path / "s.csv"

    result = commands.list_stations(FakeHistorical(), save=str(target))

    assert result.data["saved"] == str(target)
    assert len(pd.read_csv(target)) == len(catalogue())


def test_pm25_of_a_whole_file():
    client = SimpleNamespace(get_pm25_stats=lambda *a: {"mean": 40.0})

    result = commands.pm25_stats(client, "a.geojson", 2020, 3)

    assert result.data["rows"] == [{"mean": 40.0}]
    assert result.data["month"] == 3


def test_pm25_by_group():
    table = pd.DataFrame({"state": ["A"], "mean": [40.0]})
    client = SimpleNamespace(get_pm25_stats=lambda *a: table)

    result = commands.pm25_stats(client, "a.geojson", 2020, None, "state")

    assert result.data["rows"] == [{"state": "A", "mean": 40.0}]
    assert result.data["group_by"] == "state"


def test_place_for_request_only_narrows_computed_requests():
    city = _place("mumbai")

    assert commands.place_for_request(city, HistoryRequest(2025)) is city
    narrowed = commands.place_for_request(city, HistoryRequest(2025, computed=True))
    assert narrowed.status == "ambiguous"
