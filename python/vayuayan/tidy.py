"""
Tidy, long-format tables: one row per station, time and pollutant.

Every vayuayan source can be turned into TIDY_COLUMNS, so data from different
stations, years and sources concatenate and filter the same way, and feed
vayuayan.aqi.daily_aqi.
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence, Tuple

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

# The unit is the last parenthesised group; earlier groups stay in the name
_LABEL_RE = re.compile(r"^\s*(.*?)\s*(?:\(([^()]*)\))?\s*$")


def split_label(label: str) -> Tuple[str, str]:
    """Split a CPCB column label such as "PM2.5 (µg/m³)" into (name, unit)."""
    match = _LABEL_RE.match(label)
    if not match:
        return label.strip(), ""
    return (match.group(1) or label).strip(), (match.group(2) or "").strip()


# Timestamp formats of CPCB data, tried in order
_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
)


# A UTC offset after a time of day, not the "-01" of a date
_UTC_OFFSET = r"(\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)\s*(?:Z|[+-]\d{2}(?::?\d{2})?)$"
_HOUR_24 = r"\d{4}-\d{2}-\d{2}[ T]24:00(?::00(?:\.0+)?)?"


def _finite_numeric(values: pd.Series) -> pd.Series:
    """Numbers of a column; text, infinities and missing values are NaN."""
    import numpy as np
    import pandas as pd

    numeric = pd.to_numeric(values, errors="coerce").astype(float)
    return numeric.replace([np.inf, -np.inf], np.nan)


def _finite_rows(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    """Rows with a finite value in every column."""
    import numpy as np

    infinite = df[list(columns)].isin([np.inf, -np.inf]).any(axis=1)
    return df[~infinite].dropna(subset=list(columns))


def _mean_duplicates(df: pd.DataFrame, keys: Sequence[str], value: str) -> pd.DataFrame:
    """One row per key with the mean value; rows with a missing key are left out."""
    return df.groupby(list(keys), as_index=False, sort=False)[value].mean()


def parse_timestamps(values: pd.Series) -> pd.Series:
    """Timestamps of CPCB data, NaT where no format matches.

    Each value is parsed on its own, so one value in another format does not
    turn the others into NaT, as pandas' format inference can. A time zone or
    UTC offset is dropped and the local wall-clock time is kept, as CPCB data
    are in local time; "24:00" is 00:00 of the next day.
    """
    import pandas as pd

    if pd.api.types.is_datetime64_any_dtype(values):
        return values.dt.tz_localize(None) if values.dt.tz is not None else values
    text = values.astype("string").str.strip()
    text = text.str.replace(_UTC_OFFSET, r"\1", regex=True)
    out = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    midnight = text.str.fullmatch(_HOUR_24).fillna(False).astype(bool)
    out[midnight] = pd.to_datetime(
        text[midnight].str.slice(0, 10), format="%Y-%m-%d", errors="coerce"
    ) + pd.Timedelta(days=1)
    for fmt in _TIMESTAMP_FORMATS:
        missing = out.isna() & text.notna() & ~midnight
        if not missing.any():
            break
        out[missing] = pd.to_datetime(text[missing], format=fmt, errors="coerce")
    return out


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

    wide = raw.assign(timestamp=parse_timestamps(raw["Timestamp"]))
    wide = wide.dropna(subset=["timestamp"])
    if start_date is not None:
        wide = wide[wide["timestamp"] >= pd.Timestamp(start_date)]
    if end_date is not None:
        wide = wide[wide["timestamp"] < pd.Timestamp(end_date) + pd.Timedelta(days=1)]
    labels = [c for c in wide.columns if c not in {"Timestamp", "timestamp"}]
    long = wide.melt(
        id_vars=["timestamp"], value_vars=labels, var_name="label", value_name="value"
    )
    long["value"] = _finite_numeric(long["value"])
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

    if "Day" not in workbook.columns:
        return pd.DataFrame(columns=["date", "aqi"])
    months = [c for c in workbook.columns if c != "Day"]
    long = workbook.melt(
        id_vars=["Day"], value_vars=months, var_name="month", value_name="aqi"
    )
    long["aqi"] = _finite_numeric(long["aqi"])
    # Footer rows ("Minimum", "Maximum", blanks) have no day number
    long["Day"] = _finite_numeric(long["Day"])
    long = long.dropna(subset=["Day", "aqi"])
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


def cpcb_tidy_daily(sheet: pd.DataFrame, year: Optional[int] = None) -> pd.DataFrame:
    """Turn a CPCB daily sheet (Day x month columns) into one row per day.

    Args:
        sheet: A Day column and one column per month name.
        year: Optional year. With it, a date column is added and impossible
            dates (31 February) are dropped.

    Returns:
        DataFrame with integer day and month, numeric value, and date
        (datetime.date) when year is given, sorted by date. Days without a
        reading are dropped.
    """
    import pandas as pd

    months = {name: i for i, name in enumerate(calendar.month_name) if name}
    if sheet.shape[1] == 0:
        return pd.DataFrame(columns=["day", "month", "value"])
    day = pd.to_numeric(sheet.iloc[:, 0], errors="coerce")
    frames = [
        pd.DataFrame(
            {
                "day": day,
                "month": months[column],
                "value": _finite_numeric(sheet[column]),
            }
        )
        for column in sheet.columns[1:]
        if column in months
    ]
    columns = ["day", "month", "value"]
    out = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=columns)
    )
    out = out.dropna(subset=["day", "value"]).astype({"day": int, "month": int})
    if year is not None:
        dates = pd.to_datetime(
            pd.DataFrame({"year": int(year), "month": out["month"], "day": out["day"]}),
            errors="coerce",
        )
        out = out.assign(date=dates.dt.date)[dates.notna()]
        out = out.sort_values("date", kind="stable")
    return out.reset_index(drop=True)


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
    long["timestamp"] = parse_timestamps(long["timestamp"])
    long["value"] = _finite_numeric(long["value"])
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
        table[column] = _finite_numeric(table[column])
    return table
