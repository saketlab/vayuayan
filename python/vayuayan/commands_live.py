"""The live command: readings of a place, or of the station nearest to the user."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type

from . import cpcb_common
from .cli_places import PlaceResult
from .cli_readings import (
    IST,
    LiveReading,
    ReadingStatus,
    index_feed,
    reading_from_feed,
)
from .cli_results import CPCB_DOWN, CommandResult
from .commands_shared import unresolved_place
from .exceptions import CPCBError
from .utils import station_distances

_RESULT_OF_READING: Dict[ReadingStatus, str] = {
    "live": "ok",
    "stale": "ok",
    "offline": "no_data",
    "no_reading": "no_data",
    "fetch_failed": "network_error",
}
_MESSAGE_OF_READING: Dict[ReadingStatus, str] = {
    "live": "",
    "stale": "This is the latest reading CPCB has published, and it is old.",
    "offline": "This station is offline: CPCB has no current reading for it.",
    "no_reading": "This station has no AQI for the latest hour.",
    "fetch_failed": CPCB_DOWN,
}
_FETCH_ERRORS: Tuple[Type[BaseException], ...] = (
    CPCBError,
    *cpcb_common.SOURCE_ERRORS,
)


def _now() -> datetime:
    """The current time in IST."""
    return datetime.now(IST)


def _source(client: Any) -> Optional[str]:
    """Which source the client's last station list came from."""
    return getattr(client, "station_list_source", None)


def live_place(
    client: Any, place: PlaceResult, now: Optional[datetime] = None
) -> CommandResult:
    """The live reading of a station, or of every station in a city.

    Args:
        client: A CPCBLive.
        place: The result of lookup_place.
        now: The current time, timezone-aware.

    Returns:
        The result; data has reading for a station, readings for a city.
    """
    unresolved = unresolved_place("live", place)
    if unresolved is not None:
        return unresolved
    now = now or _now()
    stations = place.stations()
    readings: List[LiveReading]
    try:
        feed = index_feed(client.get_all_india())
    except _FETCH_ERRORS:
        readings = [LiveReading(status="fetch_failed", station=s) for s in stations]
    else:
        readings = [
            reading_from_feed(
                s, feed[s.id][1] if s.id in feed else None, now, _source(client)
            )
            for s in stations
        ]

    if place.station is not None:
        reading = readings[0]
        return CommandResult(
            "live",
            _RESULT_OF_READING[reading.status],
            {"place": "station", "reading": reading.to_dict()},
            _MESSAGE_OF_READING[reading.status],
        )

    assert place.city is not None
    if all(r.status == "fetch_failed" for r in readings):
        return CommandResult("live", "network_error", message=CPCB_DOWN)
    readings.sort(key=lambda r: -r.aqi if r.aqi is not None else 1)
    has_data = any(r.aqi is not None for r in readings)
    data = {
        "place": "city",
        "city": place.city.city,
        "state": place.city.state,
        "readings": [r.to_dict() for r in readings],
    }
    if has_data:
        return CommandResult("live", "ok", data)
    message = f"No station in {place.city.city} has a reading now."
    return CommandResult("live", "no_data", data, message)


def live_near(
    client: Any,
    coords: Optional[Tuple[float, float]] = None,
    now: Optional[datetime] = None,
) -> CommandResult:
    """The live reading of the nearest station with one.

    Args:
        client: A CPCBLive.
        coords: (latitude, longitude). If None, the IP address decides.
        now: The current time, timezone-aware.

    Returns:
        The result: status location_unknown if the IP lookup failed, and
        otherwise data with reading, distance_km and source.
    """
    now = now or _now()
    try:
        cities = client.get_all_india()
    except _FETCH_ERRORS:
        return CommandResult("live", "network_error", message=CPCB_DOWN)
    source = "coordinates" if coords else "ip"
    try:
        lat, lon = coords or client.get_system_location()
    except _FETCH_ERRORS:
        message = "Could not work out your location from your IP address."
        return CommandResult("live", "location_unknown", {"source": source}, message)

    feed = index_feed(cities)
    candidates = []
    for entry, km in sorted(station_distances(cities, lat, lon), key=lambda c: c[1]):
        station = feed[str(entry.get("id", ""))][0]
        candidates.append((reading_from_feed(station, entry, now, _source(client)), km))

    # When the feed lags everywhere, the nearest old reading beats no answer
    for wanted in ("live", "stale"):
        for reading, km in candidates:
            if reading.status != wanted:
                continue
            note = (
                ""
                if wanted == "live"
                else "No station has a fresh reading; this is the nearest with an older one."
            )
            data = {
                "place": "nearest",
                "source": source,
                "distance_km": round(km, 1),
                "reading": reading.to_dict(),
            }
            return CommandResult("live", "ok", data, note)
    return CommandResult("live", "no_data", message="No station has a reading now.")
