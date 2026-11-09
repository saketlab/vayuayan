"""What each CLI command does. Every function returns plain data and prints nothing."""

from __future__ import annotations

from typing import Any, Optional

from .cli_places import PlaceResult, catalogue_from_table, resolve_place
from .cli_results import CommandResult, error_result, write_rows, write_table
from .commands_history import (
    HistoryRequest,
    ReportRequest,
    history,
    history_report,
    place_for_request,
)
from .commands_live import live_near, live_place
from .commands_shared import unresolved_place

__all__ = [
    "CommandResult",
    "HistoryRequest",
    "ReportRequest",
    "error_result",
    "find_stations",
    "history",
    "history_report",
    "list_stations",
    "live_near",
    "live_place",
    "lookup_place",
    "place_for_request",
    "pm25_stats",
]


def lookup_place(
    client: Any, query: str, city: str = "", state: str = ""
) -> PlaceResult:
    """Resolve a place name against the station catalogue.

    Args:
        client: A CPCBHistorical.
        query: Station ID, station name, part of a name, or city.
        city: Optional city that narrows the catalogue.
        state: Optional state that narrows the catalogue.

    Returns:
        The PlaceResult.
    """
    return resolve_place(query, catalogue_from_table(client.station_table(state, city)))


def find_stations(place: PlaceResult, save: str = "") -> CommandResult:
    """Every station a query matches; several matches are the normal case here.

    Args:
        place: The result of lookup_place.
        save: Optional CSV file.

    Returns:
        The result; data has count and matches, one row per station.
    """
    if place.status == "not_found":
        unresolved = unresolved_place("find", place)
        assert unresolved is not None
        return unresolved
    rows = [s.to_dict() for s in place.stations()]
    if save:
        write_rows(rows, save)
    data = {
        "query": place.query,
        "count": len(rows),
        "matches": rows,
        "saved": save or None,
    }
    return CommandResult("find", "ok", data)


def list_stations(
    client: Any, city: str = "", state: str = "", save: str = ""
) -> CommandResult:
    """The stations of the catalogue, optionally of one city or state.

    Args:
        client: A CPCBHistorical.
        city: Optional city name or code.
        state: Optional state name or code.
        save: Optional CSV file.

    Returns:
        The result; status not_found if the filters match nothing.
    """
    table = client.station_table(state, city)
    if table.empty:
        message = "No stations match those filters."
        return CommandResult("stations", "not_found", message=message)
    if save:
        write_table(table, save)
    stations = catalogue_from_table(table)
    data = {
        "count": len(stations),
        "stations": [s.to_dict() for s in stations],
        "saved": save or None,
    }
    return CommandResult("stations", "ok", data)


def pm25_stats(
    client: Any,
    geojson: str,
    year: int,
    month: Optional[int] = None,
    group_by: Optional[str] = None,
) -> CommandResult:
    """Satellite PM2.5 statistics for the polygons of a GeoJSON file.

    Args:
        client: A PM25Client.
        geojson: Path to the GeoJSON file.
        year: The year.
        month: Optional month; annual data if None.
        group_by: Optional column names, comma-separated.

    Returns:
        The result; data has rows, one per group or one for the whole file.
    """
    stats = client.get_pm25_stats(geojson, year, month, group_by)
    rows = stats.to_dict("records") if hasattr(stats, "to_dict") else [dict(stats)]
    data = {"year": year, "month": month, "group_by": group_by, "rows": rows}
    return CommandResult("pm25", "ok", data)
