"""Place lookup for the CLI: one result type and the one function that makes it."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, replace
from typing import Any, Callable, Dict, List, Literal, Optional, Sequence, Tuple, Union

PlaceStatus = Literal["station", "city", "ambiguous", "not_found"]


@dataclass(frozen=True)
class Station:
    """One monitoring station of the CPCB catalogue."""

    id: str
    name: str
    city: str
    state: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """The station as plain data."""
        return {"kind": "station", **asdict(self)}


@dataclass(frozen=True)
class CityPlace:
    """A city and its stations."""

    city: str
    state: str
    stations: Tuple[Station, ...]

    def to_dict(self) -> Dict[str, Any]:
        """The city as plain data."""
        return {
            "kind": "city",
            "city": self.city,
            "state": self.state,
            "station_count": len(self.stations),
        }


Match = Union[Station, CityPlace]


@dataclass(frozen=True)
class PlaceResult:
    """What a place name turned out to be.

    Attributes:
        status: station, city, ambiguous or not_found.
        query: The text the user gave.
        station: Set when status is station.
        city: Set when status is city.
        matches: The candidates when status is ambiguous.
        reason: Why the candidates need a choice, if not because of the name.
    """

    status: PlaceStatus
    query: str
    station: Optional[Station] = None
    city: Optional[CityPlace] = None
    matches: Tuple[Match, ...] = ()
    reason: str = ""

    def stations(self) -> Tuple[Station, ...]:
        """Every station this result covers."""
        if self.station is not None:
            return (self.station,)
        if self.city is not None:
            return self.city.stations
        found: List[Station] = []
        for match in self.matches:
            found.extend(match.stations if isinstance(match, CityPlace) else [match])
        return tuple(found)


def _normalise(text: str) -> str:
    """Lower case with punctuation as single spaces; underscores stay for IDs."""
    return " ".join(re.sub(r"[^\w]+", " ", text.lower()).split())


def _word_match(wanted: str, text: str) -> bool:
    """Every word of wanted starts some word of text, in any order."""
    words = _normalise(text).split()
    return all(any(w.startswith(token) for w in words) for token in wanted.split())


def _part_match(wanted: str, text: str) -> bool:
    """Wanted appears anywhere in text."""
    return wanted in _normalise(text)


def _cities(catalogue: Sequence[Station]) -> List[CityPlace]:
    """The catalogue grouped by city and state, in catalogue order."""
    groups: Dict[Tuple[str, str], List[Station]] = {}
    for station in catalogue:
        groups.setdefault((station.city, station.state), []).append(station)
    return [CityPlace(c, s, tuple(members)) for (c, s), members in groups.items()]


def _of_stations(query: str, stations: Sequence[Station]) -> PlaceResult:
    """The result for one or several matching stations."""
    if len(stations) == 1:
        return PlaceResult("station", query, station=stations[0])
    return PlaceResult("ambiguous", query, matches=tuple(stations))


def _of_cities(query: str, cities: Sequence[CityPlace]) -> PlaceResult:
    """The result for one or several matching cities."""
    if len(cities) > 1:
        return PlaceResult("ambiguous", query, matches=tuple(cities))
    if len(cities[0].stations) == 1:
        return PlaceResult("station", query, station=cities[0].stations[0])
    return PlaceResult("city", query, city=cities[0])


def resolve_place(query: str, catalogue: Sequence[Station]) -> PlaceResult:
    """Decide what a place name means.

    An exact station ID or name wins, then an exact city name. After that the
    words of the query must start words of a station's name and city, and
    last of all the query may appear anywhere in them.

    Args:
        query: Station ID, station name, part of a name, or city.
        catalogue: The stations to search.

    Returns:
        The PlaceResult; never raises for a name that does not match.
    """
    wanted = _normalise(query)
    if not wanted:
        return PlaceResult("not_found", query)

    exact = [s for s in catalogue if wanted in (_normalise(s.id), _normalise(s.name))]
    if exact:
        return _of_stations(query, exact)

    cities = _cities(catalogue)
    exact_cities = [c for c in cities if _normalise(c.city) == wanted]
    if exact_cities:
        return _of_cities(query, exact_cities)

    matchers: Tuple[Callable[[str, str], bool], ...] = (_word_match, _part_match)
    for matches in matchers:
        stations = [s for s in catalogue if matches(wanted, f"{s.name} {s.city}")]
        if not stations:
            continue
        named = [c for c in cities if matches(wanted, c.city)]
        # "navi" names a city, and its stations match only through that name
        if len(named) == 1 and set(stations) <= set(named[0].stations):
            return _of_cities(query, named)
        return _of_stations(query, stations)
    return PlaceResult("not_found", query)


def choose(place: PlaceResult, index: int) -> PlaceResult:
    """The result of picking one candidate of an ambiguous result.

    Raises:
        IndexError: If index is not a position in place.matches.
    """
    match = place.matches[index]
    if isinstance(match, Station):
        return _of_stations(place.query, [match])
    return _of_cities(place.query, [match])


def require_station(place: PlaceResult, reason: str) -> PlaceResult:
    """Turn a city into a choice among its stations, for per-station commands."""
    if place.city is None:
        return place
    return replace(
        place,
        status="ambiguous",
        city=None,
        matches=tuple(place.city.stations),
        reason=reason,
    )


def coordinate(value: Any) -> Optional[float]:
    """A finite float, or None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def catalogue_from_table(table: Any) -> List[Station]:
    """The rows of CPCBHistorical.station_table as stations."""
    return [
        Station(
            id=str(row["station_id"]),
            name=str(row["station_name"]),
            city=str(row["city"]),
            state=str(row["state"]),
            latitude=coordinate(row["latitude"]),
            longitude=coordinate(row["longitude"]),
        )
        for row in table.to_dict("records")
    ]
