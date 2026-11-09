"""The history command: daily AQI of a year or month, and concentration reports."""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cli_places import PlaceResult, Station, coordinate, require_station
from .cli_results import CommandResult, write_rows, write_table
from .cli_scale import SCALES, Scale
from .commands_report import ReportRequest, report_payload
from .commands_shared import unresolved_place
from .tidy import daily_aqi_workbook_to_long

Progress = Callable[[str], None]

_NEEDS_A_STATION = "This is computed from one station's raw readings. Pick a station:"


@dataclass(frozen=True)
class HistoryRequest:
    """What the history command was asked for."""

    year: int
    month: Optional[int] = None
    standard: str = "india"
    computed: bool = False
    bulletin: bool = False
    save: str = ""

    @property
    def from_raw(self) -> bool:
        """True if the AQI must be computed from raw readings."""
        return self.standard == "us" or self.computed


def place_for_request(place: PlaceResult, request: HistoryRequest) -> PlaceResult:
    """Turn a city into a choice of stations when the request needs one."""
    return require_station(place, _NEEDS_A_STATION) if request.from_raw else place


def _no_progress(_: str) -> None:
    """Progress is optional."""


def _day_rows(table: Any, scale: Scale) -> List[Dict[str, Any]]:
    """Plain rows of a daily table; days without an AQI are left out."""
    rows = []
    for record in table.to_dict("records"):
        # coordinate takes NaN, None and the pd.NA of a nullable column
        value = coordinate(record.get("aqi"))
        if value is None:
            continue
        aqi = int(math.floor(value + 0.5))
        rows.append(
            {
                "date": record["date"].isoformat(),
                "aqi": aqi,
                "category": scale.category(aqi),
                "dominant_pollutant": record.get("dominant_pollutant"),
            }
        )
    return rows


def _days_without_aqi(table: Any, month: Optional[int]) -> Dict[str, int]:
    """The days of a computed table with no AQI, by the reason there is none."""
    if "aqi_status" not in getattr(table, "columns", ()):
        return {}
    counts: Dict[str, int] = {}
    for day, status in zip(table["date"], table["aqi_status"]):
        if status != "ok" and (month is None or day.month == month):
            counts[status] = counts.get(status, 0) + 1
    return counts


def _batch_outcome(table: Any) -> Tuple[Dict[str, Any], str]:
    """The status fields of a city report, and a note if it is partial."""
    status = getattr(table, "attrs", {}).get("station_status")
    if not status:
        return {}, ""
    values = list(status.values())
    fields = {"station_status": status, "partial": values.count("ok") < len(values)}
    if not fields["partial"]:
        return fields, ""
    note = f"Partial result: {values.count('ok')} of {len(values)} stations have data."
    if "outage" in values:
        note += " CPCB stopped answering, so the rest were not fetched."
    return fields, note


def _days_in_period(year: int, month: Optional[int], today: date) -> int:
    """The days of the period that have happened; future days are not missing."""
    first = date(year, month or 1, 1)
    end_month = month or 12
    last = date(year, end_month, calendar.monthrange(year, end_month)[1])
    return max(0, (min(last, today) - first).days + 1)


def _mean(values: List[int]) -> float:
    """The arithmetic mean."""
    return sum(values) / len(values)


def _summary(rows: List[Dict[str, Any]], scale: Scale, total: int) -> Dict[str, Any]:
    """Mean, worst and best day, days with data and a count per category."""
    counts = {name: 0 for name in scale.colors}
    for row in rows:
        counts[row["category"]] += 1
    mean = _mean([row["aqi"] for row in rows])
    return {
        "mean": round(mean, 1),
        "mean_category": scale.category(math.floor(mean + 0.5)),
        "worst": max(rows, key=lambda row: row["aqi"]),
        "best": min(rows, key=lambda row: row["aqi"]),
        "days_with_data": len(rows),
        "days_in_period": total,
        "category_counts": counts,
    }


def _month_rows(rows: List[Dict[str, Any]], scale: Scale) -> List[Dict[str, Any]]:
    """One summary per month that has data."""
    by_month: Dict[int, List[Dict[str, Any]]] = {}
    for row in rows:
        by_month.setdefault(int(row["date"][5:7]), []).append(row)
    months = []
    for number, group in sorted(by_month.items()):
        mean = _mean([r["aqi"] for r in group])
        months.append(
            {
                "month": number,
                "name": calendar.month_name[number],
                "mean": round(mean, 1),
                "category": scale.category(math.floor(mean + 0.5)),
                "worst": max(group, key=lambda r: r["aqi"]),
                "days_with_data": len(group),
            }
        )
    return months


def _published_days(client: Any, place: PlaceResult, year: int) -> Any:
    """The date, aqi rows of CPCB's published daily workbook."""
    if place.station is not None:
        station = place.station
        workbook = client.download_past_year_aqi_data_station_level(
            station.id, str(year), "", city=station.city, state=station.state
        )
    else:
        assert place.city is not None
        workbook = client.download_past_year_aqi_data_city_level(
            place.city.city, str(year), "", state=place.city.state
        )
    return daily_aqi_workbook_to_long(workbook, year)


def _computed_days(client: Any, station: Station, request: HistoryRequest) -> Any:
    """Daily rows computed from a station's raw readings."""
    return client.daily_aqi(
        station.id,
        str(request.year),
        day_ends_at=16 if request.bulletin else 24,
        standard=request.standard,
        city=station.city,
        state=station.state,
    )


def _place_data(place: PlaceResult) -> Dict[str, Any]:
    """The place fields of a history result."""
    if place.station is not None:
        return {"place": "station", "station": place.station.to_dict()}
    assert place.city is not None
    return {"place": "city", "city": place.city.city, "state": place.city.state}


def history(
    client: Any,
    place: PlaceResult,
    request: HistoryRequest,
    progress: Progress = _no_progress,
    today: Optional[date] = None,
) -> CommandResult:
    """The daily AQI of a station or city for a year or a month.

    Args:
        client: A CPCBHistorical.
        place: The result of lookup_place.
        request: What to fetch.
        progress: Receives a sentence before each slow step.
        today: The current date, so that future days do not count as missing.

    Returns:
        The result; data has days, summary and months when status is ok.
    """
    place = place_for_request(place, request)
    unresolved = unresolved_place("history", place)
    if unresolved is not None:
        return unresolved

    scale = SCALES[request.standard]
    if request.from_raw:
        assert place.station is not None
        progress(
            f"Downloading a year of raw readings to compute the {scale.label}; "
            "this takes longer than the published data."
        )
        table = _computed_days(client, place.station, request)
    else:
        progress("Downloading CPCB's published daily AQI...")
        table = _published_days(client, place, request.year)

    rows = _day_rows(table, scale)
    without_aqi = _days_without_aqi(table, request.month)
    if request.month:
        rows = [r for r in rows if int(r["date"][5:7]) == request.month]
    if not rows:
        period = str(request.year)
        if request.month:
            period = f"{calendar.month_name[request.month]} {period}"
        message = f"CPCB has no AQI for this place in {period}."
        if without_aqi:
            message = f"No day in {period} had enough data for an AQI."
        empty = {"year": request.year, "days_without_aqi": without_aqi}
        return CommandResult("history", "no_data", empty, message)

    if request.save:
        write_rows(rows, request.save)
    total = _days_in_period(request.year, request.month, today or date.today())
    data: Dict[str, Any] = {
        **_place_data(place),
        "year": request.year,
        "month": request.month,
        "standard": scale.key,
        "standard_label": scale.label,
        "source": "computed" if request.from_raw else "published",
        "days": rows,
        "summary": _summary(rows, scale, total),
        "days_without_aqi": without_aqi,
        "months": _month_rows(rows, scale),
        "saved": request.save or None,
    }
    return CommandResult("history", "ok", data)


def history_report(
    client: Any,
    place: PlaceResult,
    request: ReportRequest,
    progress: Progress = _no_progress,
) -> CommandResult:
    """Concentrations of a station or city for any period, from CPCB's report.

    Args:
        client: A CPCBHistorical.
        place: The result of lookup_place.
        request: The period, interval, pollutants and CSV file.
        progress: Receives a sentence before the download.

    Returns:
        The result; data has rows and a per-pollutant summary.
    """
    unresolved = unresolved_place("history", place)
    if unresolved is not None:
        return unresolved
    progress("Downloading CPCB's report...")
    if place.station is not None:
        station = place.station
        table = client.download_station_report(
            station.id,
            request.start,
            request.end,
            request.frequency,
            request.pollutants,
            city=station.city,
            state=station.state,
        )
    else:
        assert place.city is not None
        table = client.download_city_report(
            place.city.city,
            request.start,
            request.end,
            request.frequency,
            request.pollutants,
            place.city.state,
        )
    if request.save:
        write_table(table, request.save)
    fields, note = _batch_outcome(table)
    payload = {**report_payload(table, place, request), **fields}
    return CommandResult("history", "ok", payload, note)
