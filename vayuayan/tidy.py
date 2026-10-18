"""
Tidy, long-format tables: one row per station, time and pollutant.

Every vayuayan source can be turned into TIDY_COLUMNS, so data from different
stations, years and sources concatenate and filter the same way, and feed
vayuayan.aqi.daily_aqi.
"""

from __future__ import annotations

import re
from datetime import date
from typing import TYPE_CHECKING, Any, Mapping, Optional, Tuple

if TYPE_CHECKING:
    import pandas as pd

TIDY_COLUMNS = [
    "station_id",
    "station_name",
    "city",
    "state",
    "timestamp",
    "pollutant",
    "unit",
    "value",
]

_LABEL_RE = re.compile(r"^\s*(.*?)\s*(?:\((.*?)\))?\s*$")


def split_label(label: str) -> Tuple[str, str]:
    """Split a CPCB column label such as "PM2.5 (µg/m³)" into (name, unit)."""
    match = _LABEL_RE.match(label)
    if not match:
        return label.strip(), ""
    return (match.group(1) or label).strip(), (match.group(2) or "").strip()


def cpcb_raw_to_long(
    raw: pd.DataFrame,
    station: Optional[Mapping[str, str]] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> pd.DataFrame:
    """Turn a raw CPCB station file (one column per pollutant) into tidy rows.

    Args:
        raw: Raw data with a Timestamp column and "<name> (<unit>)" columns,
            as CPCBHistorical.download_raw_aqi_data_station_level returns it.
        station: Optional station_id, station_name, city and state values for
            every row.
        start_date: Optional first date to keep.
        end_date: Optional last date to keep (inclusive).

    Returns:
        DataFrame with TIDY_COLUMNS, sorted by timestamp and pollutant. Rows
        without a timestamp or a numeric value are dropped.

    Raises:
        ValueError: If raw has no Timestamp column.
    """
    import pandas as pd

    if "Timestamp" not in raw.columns:
        raise ValueError("Raw CPCB data did not contain a Timestamp column")

    wide = raw.assign(timestamp=pd.to_datetime(raw["Timestamp"], errors="coerce"))
    wide = wide.dropna(subset=["timestamp"])
    if start_date is not None:
        wide = wide[wide["timestamp"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        wide = wide[wide["timestamp"] < pd.Timestamp(end_date) + pd.Timedelta(days=1)]
    labels = [c for c in wide.columns if c not in {"Timestamp", "timestamp"}]
    long = wide.melt(
        id_vars=["timestamp"], value_vars=labels, var_name="label", value_name="value"
    )
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])

    parsed = {label: split_label(label) for label in labels}
    station = station or {}
    long = long.assign(
        pollutant=long["label"].map({k: v[0] for k, v in parsed.items()}),
        unit=long["label"].map({k: v[1] for k, v in parsed.items()}),
        station_id=station.get("station_id", ""),
        station_name=station.get("station_name", ""),
        city=station.get("city", ""),
        state=station.get("state", ""),
    )
    return (
        long.reindex(columns=TIDY_COLUMNS)
        .sort_values(["timestamp", "pollutant"], kind="stable")
        .reset_index(drop=True)
    )


def daily_aqi_workbook_to_long(workbook: pd.DataFrame, year: int) -> pd.DataFrame:
    """Turn a CPCB daily AQI workbook (Day x month columns) into date, aqi rows.

    Args:
        workbook: The table that download_past_year_aqi_data_* returns: a Day
            column and one column per month name.
        year: Year of the workbook.

    Returns:
        DataFrame with columns date and aqi, one row per day with a value.
    """
    import pandas as pd

    months = [c for c in workbook.columns if c != "Day"]
    long = workbook.melt(
        id_vars=["Day"], value_vars=months, var_name="month", value_name="aqi"
    )
    long["aqi"] = pd.to_numeric(long["aqi"], errors="coerce")
    long = long.dropna(subset=["aqi"])
    dates = pd.to_datetime(
        long["Day"].astype(int).astype(str)
        + " "
        + long["month"].astype(str)
        + f" {year}",
        format="%d %B %Y",
        errors="coerce",
    )
    out = pd.DataFrame({"date": dates.dt.date, "aqi": long["aqi"].to_numpy()})
    return out.dropna(subset=["date"]).sort_values("date", ignore_index=True)


def live_to_long(aqi_data: Mapping[str, Any], station_id: str = "") -> pd.DataFrame:
    """Turn the recent hours of CPCBLive.get_live_aqi_data into tidy rows.

    Args:
        aqi_data: The dictionary that get_live_aqi_data returns. Its
            "last_hours" entry has one series of {"date", "val"} per pollutant.
        station_id: Optional station ID for every row.

    Returns:
        DataFrame with columns station_id, timestamp, pollutant and value,
        sorted by pollutant and timestamp. It is empty if the data have no
        recent hours, for example when the data come from the RSS feed.
    """
    import pandas as pd

    rows = [
        {
            "timestamp": point.get("date"),
            "pollutant": series.get("name"),
            "value": point.get("val"),
        }
        for series in aqi_data.get("last_hours", [])
        for point in series.get("data", [])
    ]
    long = pd.DataFrame(rows, columns=["timestamp", "pollutant", "value"])
    long["timestamp"] = pd.to_datetime(long["timestamp"], errors="coerce")
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long.insert(0, "station_id", station_id or aqi_data.get("station_id", ""))
    return long.dropna(subset=["timestamp", "value"]).sort_values(
        ["pollutant", "timestamp"], ignore_index=True
    )


def live_metrics(aqi_data: Mapping[str, Any]) -> pd.DataFrame:
    """The latest pollutant averages of CPCBLive.get_live_aqi_data as a table.

    Returns:
        DataFrame with columns pollutant, avg, min, max (numbers, NaN where
        CPCB has none) and period, one row per pollutant.
    """
    import pandas as pd

    table = pd.DataFrame(
        [
            {
                "pollutant": m.get("name"),
                "avg": m.get("avg"),
                "min": m.get("min"),
                "max": m.get("max"),
                "period": m.get("avgDesc"),
            }
            for m in aqi_data.get("metrics", [])
        ],
        columns=["pollutant", "avg", "min", "max", "period"],
    )
    for column in ("avg", "min", "max"):
        table[column] = pd.to_numeric(table[column], errors="coerce")
    return table
