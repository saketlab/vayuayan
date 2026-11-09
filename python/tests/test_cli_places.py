"""Place resolution: every outcome comes from one function and one result type."""

from __future__ import annotations

import pandas as pd
import pytest

from vayuayan.cli_places import (
    CityPlace,
    PlaceResult,
    Station,
    catalogue_from_table,
    choose,
    coordinate,
    require_station,
    resolve_place,
)

from .cli_fakes import catalogue


@pytest.fixture
def stations():
    return catalogue_from_table(catalogue())


def _twin_cities():
    return [
        Station("a1", "Rail Yard", "Aurangabad", "Bihar"),
        Station("m1", "Station Road", "Aurangabad", "Maharashtra"),
        Station("m2", "CIDCO", "Aurangabad", "Maharashtra"),
    ]


def test_exact_id_is_a_station(stations):
    place = resolve_place("SITE_1", stations)

    assert place.status == "station"
    assert place.station.name == "Powai, Mumbai - MPCB"
    assert place.stations() == (place.station,)


def test_exact_name_beats_other_partial_names(stations):
    assert resolve_place("Powai, Mumbai - MPCB", stations).station.id == "site_1"


def test_one_word_of_a_name_is_a_station(stations):
    assert resolve_place("powai", stations).station.id == "site_1"


def test_words_in_any_order_and_with_punctuation(stations):
    assert resolve_place("mumbai, powai", stations).station.id == "site_1"


def test_city_name_is_a_city_even_when_station_names_contain_it(stations):
    place = resolve_place("mumbai", stations)

    assert place.status == "city"
    assert place.city.city == "Mumbai" and place.city.state == "Maharashtra"
    assert len(place.stations()) == 3


def test_city_prefix_is_that_city(stations):
    assert resolve_place("mumb", stations).status == "city"


def test_city_with_one_station_is_that_station(stations):
    assert resolve_place("panaji", stations).station.id == "site_6"


def test_several_stations_are_ambiguous(stations):
    place = resolve_place("anand vihar", stations)

    assert place.status == "ambiguous"
    assert [m.id for m in place.matches] == ["site_8", "site_7"]
    assert len(place.stations()) == 2


def test_city_name_in_two_states_is_ambiguous():
    place = resolve_place("aurangabad", _twin_cities())

    assert place.status == "ambiguous"
    assert all(isinstance(m, CityPlace) for m in place.matches)
    assert len(place.stations()) == 3


def test_part_of_a_word_matches_when_no_word_starts_with_it(stations):
    assert resolve_place("owai", stations).station.id == "site_1"


@pytest.mark.parametrize("query", ["atlantis", "", "   ", "!!!"])
def test_no_match_is_not_found(stations, query):
    place = resolve_place(query, stations)

    assert place.status == "not_found"
    assert place.stations() == ()


def test_choose_a_station_or_a_city():
    stations = _twin_cities()
    among_cities = resolve_place("aurangabad", stations)

    assert choose(among_cities, 0).status == "station"
    assert choose(among_cities, 1).status == "city"

    among_stations = PlaceResult("ambiguous", "q", matches=tuple(stations))
    assert choose(among_stations, 2).station.id == "m2"


def test_require_station_turns_a_city_into_a_choice(stations):
    place = require_station(resolve_place("mumbai", stations), "Pick one")

    assert place.status == "ambiguous"
    assert place.reason == "Pick one"
    assert len(place.matches) == 3
    assert place.city is None


def test_require_station_leaves_a_station_alone(stations):
    place = resolve_place("powai", stations)

    assert require_station(place, "Pick one") is place


def test_to_dict_of_a_station_and_a_city():
    station = Station("s", "N", "C", "S", 1.0, 2.0)

    assert station.to_dict() == {
        "kind": "station",
        "id": "s",
        "name": "N",
        "city": "C",
        "state": "S",
        "latitude": 1.0,
        "longitude": 2.0,
    }
    assert CityPlace("C", "S", (station,)).to_dict() == {
        "kind": "city",
        "city": "C",
        "state": "S",
        "station_count": 1,
    }


@pytest.mark.parametrize(
    "value,expected",
    [("19.5", 19.5), (None, None), ("x", None), (float("nan"), None)],
)
def test_coordinate(value, expected):
    assert coordinate(value) == expected


def test_catalogue_of_an_empty_table_is_empty():
    assert catalogue_from_table(pd.DataFrame(columns=catalogue().columns)) == []


def test_catalogue_turns_missing_coordinates_into_none(stations):
    assert [s for s in stations if s.id == "site_6"][0].latitude is None
