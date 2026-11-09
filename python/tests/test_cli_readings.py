"""A live reading has one explicit state, and offline is never a failed fetch."""

from __future__ import annotations

from datetime import datetime

import pytest

from vayuayan.cli_places import Station
from vayuayan.cli_readings import (
    IST,
    LiveReading,
    index_feed,
    parse_feed_time,
    reading_from_feed,
)

from .cli_fakes import FRESH, NOW, OLD, feed, feed_station, pollutant

STATION = Station("site_1", "Powai", "Mumbai", "Maharashtra", 19.1, 72.9)


def _reading(**fields):
    return reading_from_feed(
        STATION, feed_station("site_1", "Powai", 19.1, 72.9, **fields), NOW
    )


def test_a_recent_reading_is_live():
    reading = _reading()

    assert reading.status == "live"
    assert reading.aqi == 82
    assert reading.category == "Satisfactory"
    assert reading.dominant == "PM10"
    assert reading.age_minutes == 60
    assert reading.collected_at == datetime(2026, 11, 9, 10, 0, tzinfo=IST)


def test_an_old_reading_is_stale():
    reading = _reading(updated=OLD)

    assert reading.status == "stale"
    assert reading.aqi == 82
    assert reading.age_minutes == 660


def test_an_aqi_without_a_time_is_stale():
    assert _reading(updated="NA").status == "stale"


def test_no_aqi_at_a_known_time_is_no_reading():
    reading = _reading(aqi="NA")

    assert reading.status == "no_reading"
    assert reading.aqi is None and reading.category is None and reading.dominant is None


def test_no_aqi_and_no_time_is_offline():
    assert _reading(aqi="NA", updated="NA").status == "offline"


def test_a_station_the_feed_lacks_is_offline():
    reading = reading_from_feed(STATION, None, NOW)

    assert reading.status == "offline"
    assert reading.pollutants == () and reading.age_minutes is None


def test_a_station_marked_not_live_is_offline():
    entry = {**feed_station("site_1", "Powai", 19.1, 72.9), "live": False}

    assert reading_from_feed(STATION, entry, NOW).status == "offline"


def test_a_future_time_counts_as_zero_age():
    entry = feed_station("site_1", "Powai", 19.1, 72.9, updated="09-11-2026 12:00:00")

    assert reading_from_feed(STATION, entry, NOW).age_minutes == 0


def test_values_are_named_by_what_they_are():
    reading = _reading(pollutants=[pollutant("OZONE", 20, 8, 29, 8)])

    only = reading.pollutants[0]
    assert only.name == "Ozone"
    assert (
        only.average_24h,
        only.lowest_hour,
        only.highest_hour,
        only.latest_hour,
    ) == (
        20,
        8,
        29,
        8,
    )


def test_na_pollutant_values_are_none_and_not_dominant():
    reading = _reading(pollutants=[pollutant("NO2", "NA"), pollutant("SO2", 18)])

    assert reading.pollutants[0].average_24h is None
    assert reading.dominant == "SO2"


@pytest.mark.parametrize(
    "text,expected",
    [
        (OLD, datetime(2026, 11, 9, 0, 0, tzinfo=IST)),
        (FRESH, datetime(2026, 11, 9, 10, 0, tzinfo=IST)),
        ("NA", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_feed_time(text, expected):
    assert parse_feed_time(text) == expected


def test_to_dict_is_plain_data():
    data = _reading().to_dict()

    assert data["station"]["kind"] == "station"
    assert data["collected_at"] == "2026-11-09T10:00:00+05:30"
    assert data["pollutants"][0]["name"] == "PM10"
    assert LiveReading("fetch_failed", STATION).to_dict()["collected_at"] is None


def test_index_feed_keeps_city_and_state():
    index = index_feed(feed())

    station, entry = index["site_1"]
    assert station.city == "Mumbai" and station.state == "Maharashtra"
    assert entry["name"] == "Powai, Mumbai - MPCB"
    assert len(index) == 4
