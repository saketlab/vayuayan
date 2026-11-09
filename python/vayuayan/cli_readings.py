"""A station's live reading as an explicit state, built from the CPCB feed.

Each feed value (avg, min, max, Hourly_sub_index) is an AQI sub-index, not a
concentration; see docs/cli_reference.rst for how that was checked.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Mapping, Optional, Tuple

from .cli_places import Station, coordinate
from .cli_scale import INDIA
from .utils import iter_city_stations

ReadingStatus = Literal["live", "stale", "offline", "no_reading", "fetch_failed"]

IST = timezone(timedelta(hours=5, minutes=30), "IST")
# CPCB publishes hourly, so a reading more than a few hours old is out of date
STALE_AFTER = timedelta(hours=3)

_FEED_TIME = "%d-%m-%Y %H:%M:%S"
_NAMES = {"OZONE": "Ozone"}


@dataclass(frozen=True)
class PollutantReading:
    """The sub-indices of one pollutant, on the AQI scale."""

    name: str
    average_24h: Optional[int]
    latest_hour: Optional[int]
    lowest_hour: Optional[int]
    highest_hour: Optional[int]


@dataclass(frozen=True)
class LiveReading:
    """A station's reading and what state it is in."""

    status: ReadingStatus
    station: Station
    aqi: Optional[int] = None
    category: Optional[str] = None
    dominant: Optional[str] = None
    pollutants: Tuple[PollutantReading, ...] = ()
    collected_at: Optional[datetime] = None
    age_minutes: Optional[int] = None
    source: Optional[str] = None
    reading_state: str = "no_reading"
    as_of: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """The reading as plain data."""
        data = asdict(self)
        data["station"] = self.station.to_dict()
        data["pollutants"] = [asdict(p) for p in self.pollutants]
        data["collected_at"] = (
            self.collected_at.isoformat() if self.collected_at else None
        )
        return data


def _number(value: Any) -> Optional[int]:
    """A feed value as a whole number; "NA" and blanks are None."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number + 0.5) if math.isfinite(number) else None


def parse_feed_time(text: Any) -> Optional[datetime]:
    """The feed's lastUpdate as an IST datetime, or None if it has no time."""
    try:
        return datetime.strptime(str(text).strip(), _FEED_TIME).replace(tzinfo=IST)
    except ValueError:
        return None


def _pollutant(raw: Mapping[str, Any]) -> PollutantReading:
    """One entry of the feed's pollutants list."""
    name = str(raw.get("indexId", ""))
    return PollutantReading(
        name=_NAMES.get(name, name),
        average_24h=_number(raw.get("avg")),
        latest_hour=_number(raw.get("Hourly_sub_index")),
        lowest_hour=_number(raw.get("min")),
        highest_hour=_number(raw.get("max")),
    )


def _dominant(pollutants: Tuple[PollutantReading, ...]) -> Optional[str]:
    """The pollutant with the highest 24-hour sub-index, which sets the AQI."""
    known = [p for p in pollutants if p.average_24h is not None]
    return max(known, key=lambda p: p.average_24h or 0).name if known else None


def _status(
    entry: Optional[Mapping[str, Any]],
    aqi: Optional[int],
    collected_at: Optional[datetime],
    now: datetime,
) -> ReadingStatus:
    """The state of a station's entry in the feed."""
    if entry is None or not entry.get("live", True):
        return "offline"
    if aqi is None:
        return "no_reading" if collected_at else "offline"
    if collected_at is None or now - collected_at > STALE_AFTER:
        return "stale"
    return "live"


def reading_from_feed(
    station: Station,
    entry: Optional[Mapping[str, Any]],
    now: datetime,
    source: Optional[str] = None,
) -> LiveReading:
    """The reading of a station from its feed entry.

    Args:
        station: The station.
        entry: Its entry in the feed, or None if the feed does not have it.
        now: The current time, timezone-aware.
        source: Where the feed came from, "dashboard" or "rss", if known.

    Returns:
        The LiveReading.
    """
    entry = entry or None
    aqi = _number((entry.get("airQualityIndex") or {}).get("value")) if entry else None
    collected_at = parse_feed_time(entry.get("lastUpdate")) if entry else None
    status = _status(entry, aqi, collected_at, now)
    pollutants = (
        tuple(_pollutant(p) for p in entry.get("pollutants") or []) if entry else ()
    )
    age = None
    if collected_at is not None:
        age = max(0, int((now - collected_at).total_seconds() // 60))
    return LiveReading(
        status=status,
        station=station,
        aqi=aqi,
        category=INDIA.category(aqi) if aqi is not None else None,
        dominant=_dominant(pollutants) if aqi is not None else None,
        pollutants=pollutants,
        collected_at=collected_at,
        age_minutes=age,
        source=source,
        reading_state="reading" if aqi is not None else "no_reading",
        as_of=(entry.get("lastUpdate") or None) if entry else None,
    )


def index_feed(cities: Any) -> Dict[str, Tuple[Station, Mapping[str, Any]]]:
    """Every feed station by ID, with its place in the catalogue's shape."""
    index: Dict[str, Tuple[Station, Mapping[str, Any]]] = {}
    for city, entry in iter_city_stations(cities):
        station = Station(
            id=str(entry.get("id", "")),
            name=str(entry.get("name", "")),
            city=str(city.get("cityName", "")),
            state=str(city.get("stateID", "")),
            latitude=coordinate(entry.get("latitude")),
            longitude=coordinate(entry.get("longitude")),
        )
        index[station.id] = (station, entry)
    return index
