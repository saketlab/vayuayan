"""
The daily US EPA AQI of each station from raw readings.

The EPA sets no completeness rule for a daily AQI. The rules here are
assumptions taken from its NAAQS data handling and listed in docs/aqi_standards.rst.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .aqi import AQIResult
from .aqi_units import (
    DAILY_COLUMNS,
    by_day,
    day_shift,
    hourly_means,
    in_short_days,
    rolling_8h,
    unit_factor,
)
from .us_aqi import (
    US_POLLUTANTS,
    _evaluate,
    _warn_o3_beyond_table,
    us_aqi_category,
    us_pollutant_name,
)

if TYPE_CHECKING:
    import pandas as pd

# Pollutants of the daily AQI; ties go to the first
_POLLUTANTS = ("PM2.5", "PM10", "O3", "CO", "SO2", "NO2")

# 40 CFR 50 App U 3(b) and 50.8(c): an 8-hour mean needs 6 of its 8 hours
_WINDOW_MIN_HOURS = 6


def _resolve(label: str) -> Optional[str]:
    """The pollutant of a reading; averaged labels such as O3_1h are not readings."""
    name = us_pollutant_name(label)
    return name if name in _POLLUTANTS else None


def _epa_factor(name: str, unit: str) -> float:
    p = US_POLLUTANTS[name]
    return unit_factor(unit, p.unit, p.molar_mass)


def _with_one_so2(result: AQIResult) -> AQIResult:
    """result with the 1-hour and 24-hour SO2 as one pollutant, SO2."""
    subs = dict(result.sub_indices)
    if "SO2_24h" in subs:
        subs["SO2"] = max(subs.pop("SO2_24h"), subs.get("SO2", 0.0))
    dominant = (result.dominant_pollutant or "").removesuffix("_24h") or None
    return replace(result, sub_indices=subs, dominant_pollutant=dominant)


def daily_us_aqi(
    long: pd.DataFrame, day_ends_at: int = 24, min_hours: int = 18
) -> pd.DataFrame:
    """Daily US AQI of each station from tidy long data, such as 15-minute data.

    Readings are first averaged by hour, as in vayuayan.aqi.daily_aqi. Then,
    for each station and day:

    - PM2.5 and PM10 use the 24-hour mean (EPA TAD p.2).
    - O3 and CO use the highest 8-hour running mean (TAD p.2, p.24). A window
      is placed at its last hour, needs 6 of its 8 hours (40 CFR 50 App U
      3(b), 50.8(c)), and a day needs min_hours of its 24 windows.
    - SO2 and NO2 use the highest 1-hour value (TAD p.2), and the 24-hour SO2
      mean decides the bands above 304 ppb as in compute_us_aqi.
    - PM, the 1-hour pollutants and the 24-hour SO2 need min_hours hours.

    The 18 of 24 (75%) is an assumption: the EPA sets no completeness rule for
    the AQI, so this applies the NAAQS rules (40 CFR 50 App K, N, S, T, U) to
    every hour of the day. The bulletin window (day_ends_at) is a vayuayan
    option, not an EPA rule. There is no minimum number of pollutants (TAD p.22).

    Args:
        long: Tidy data with columns timestamp, pollutant, value, and
            optionally station_id and unit (see vayuayan.tidy). Mass units
            are converted to ppb or ppm at 25 °C and 760 mm Hg (40 CFR 50.3),
            which is an assumption for CPCB data: CPCB states no reference
            conditions. A blank unit means the unit of the US table.
        day_ends_at: Hour (1-24) at which each day's 24 hours end, as in
            daily_aqi.
        min_hours: Hours, or 8-hour windows, a pollutant needs in a day.

    Returns:
        One row per station and date: station_id, date, aqi (nullable integer),
        category, dominant_pollutant, n_pollutants, aqi_status, and one
        <pollutant>_sub_index column per pollutant with data. aqi, category and
        dominant_pollutant are missing if no pollutant has a sub-index, and,
        with one warning, on days when 8-hour O3 is above 0.200 ppm, which the
        8-hour table does not cover (40 CFR 58 App G note 2). aqi_status says
        why: "o3_beyond_table" first, as more hours would not fix it; then
        "too_few_hours" if a pollutant had readings but too few hours; else
        "no_sub_index"; "ok" with an AQI.

    Raises:
        ValueError: If day_ends_at is not from 1 to 24.
    """
    shift = day_shift(day_ends_at)
    import pandas as pd

    hourly = hourly_means(long, _resolve, _epa_factor)
    if hourly.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    values: Dict[str, pd.Series] = {}
    for name, group in hourly.groupby("pollutant", sort=False):
        hours = US_POLLUTANTS[name].averaging_hours
        if hours == 8:
            group = rolling_8h(group, _WINDOW_MIN_HOURS, full_grid=True)
        how = "mean" if hours == 24 else "max"
        values[name] = by_day(group, how, min_hours, shift, "count")
        if name == "SO2":
            values["SO2_24h"] = by_day(group, "mean", min_hours, shift, "count")

    # Only days with a reading; the 8-hour grid also holds the hours of a gap
    days = hourly.assign(day=(hourly["hour"] + shift).dt.normalize())
    index = pd.MultiIndex.from_frame(
        days[["station_id", "day"]].drop_duplicates(), names=["station_id", "day"]
    )
    daily = pd.DataFrame(values).reindex(index)

    present = [name for name in _POLLUTANTS if name in values]
    rows: List[Dict[str, Any]] = []
    o3_days = 0
    for record in daily.to_dict("records"):
        result, o3_beyond_table = _evaluate(record)
        o3_days += o3_beyond_table
        one_so2 = _with_one_so2(result)
        subs = one_so2.sub_indices
        row: Dict[str, Any] = {
            "aqi": result.aqi,
            "dominant_pollutant": one_so2.dominant_pollutant,
            "aqi_status": result.status,
        }
        row.update({f"{n}_sub_index": subs.get(n, float("nan")) for n in present})
        rows.append(row)
    if o3_days:
        _warn_o3_beyond_table(f"8-hour O3 above 0.200 ppm on {o3_days} day(s)")

    table = pd.DataFrame(rows, index=daily.index).reset_index()
    short = in_short_days(table, values.values())
    table["aqi_status"] = [
        "too_few_hours" if is_short and status == "no_sub_index" else status
        for status, is_short in zip(table["aqi_status"], short)
    ]
    table["date"] = table.pop("day").dt.date
    sub_columns = [f"{n}_sub_index" for n in present]
    table["n_pollutants"] = table[sub_columns].notna().sum(axis=1)
    table["aqi"] = table["aqi"].astype("Float64").astype("Int64")
    table["category"] = table["aqi"].map(us_aqi_category, na_action="ignore")
    return table[DAILY_COLUMNS + sub_columns].sort_values(
        ["station_id", "date"], ignore_index=True
    )
