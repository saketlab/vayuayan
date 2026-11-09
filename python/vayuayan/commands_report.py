"""The concentration report of the history command, as plain data."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .cli_places import PlaceResult
from .tidy import split_label

# Names of the --every option and the frequencies of the report export
FREQUENCIES: Dict[str, str] = {
    "15min": "15_minute",
    "30min": "30_minute",
    "hourly": "hourly",
    "4hour": "4_hour",
    "8hour": "8_hour",
    "daily": "daily",
}
_ID_COLUMNS = ("Timestamp", "station_id", "station_name")


@dataclass(frozen=True)
class ReportRequest:
    """A period of readings to download."""

    start: datetime
    end: datetime
    frequency: str = "hourly"
    pollutants: Optional[Tuple[str, ...]] = None
    save: str = ""


def _summary(table: Any) -> List[Dict[str, Any]]:
    """Lowest, mean and highest of each pollutant column that has values."""
    rows = []
    for column in table.columns:
        if column in _ID_COLUMNS:
            continue
        values = table[column].dropna()
        if values.empty:
            continue
        name, unit = split_label(str(column))
        rows.append(
            {
                "pollutant": name,
                "unit": unit,
                "lowest": round(float(values.min()), 2),
                "mean": round(float(values.mean()), 2),
                "highest": round(float(values.max()), 2),
                "readings": int(values.size),
            }
        )
    return rows


def report_payload(
    table: Any, place: PlaceResult, request: ReportRequest
) -> Dict[str, Any]:
    """The JSON-ready data of a report table."""
    station = place.station
    payload: Dict[str, Any] = {
        "place": "station" if station is not None else "city",
        "kind": "report",
        "from": request.start.isoformat(),
        "to": request.end.isoformat(),
        "every": request.frequency,
        "summary": _summary(table),
        # to_json turns timestamps into text and NaN into null in one step
        "rows": json.loads(table.to_json(orient="records", date_format="iso")),
        "saved": request.save or None,
    }
    if station is not None:
        payload["station"] = station.to_dict()
    elif place.city is not None:
        payload["city"] = place.city.city
        payload["state"] = place.city.state
        payload["station_count"] = len(place.city.stations)
    return payload
