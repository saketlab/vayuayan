"""Concentration units of AQI labels (µg/m³, mg/m³, ppb and ppm) and the
daily scaffold that both the NAQI and the US AQI use."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Callable, Iterable, List, Optional

from .tidy import _finite_numeric, _mean_duplicates, parse_timestamps, split_label

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# Unit factors between mass concentrations (µg and mg, with either mu character)
_MASS_FACTORS = {("µg", "mg"): 1e-3, ("mg", "µg"): 1e3}
_VOLUME_FACTORS = {("ppb", "ppm"): 1e-3, ("ppm", "ppb"): 1e3}

# litres per mole at 25 °C and 760 mm Hg, the conditions of 40 CFR 50.3
_MOLAR_VOLUME = 24.45

# The columns of a daily table before its <pollutant>_sub_index columns
DAILY_COLUMNS = [
    "station_id",
    "date",
    "aqi",
    "category",
    "dominant_pollutant",
    "n_pollutants",
    "aqi_status",
]


def _mass_unit(unit: str) -> str:
    """ "µg" or "mg" for a concentration unit such as "µg/m³", else ""."""
    prefix = str(unit).strip().lower().replace("μ", "µ").replace("ug", "µg")[:2]
    return prefix if prefix in ("µg", "mg") else ""


def _volume_unit(unit: str) -> str:
    """ "ppb" or "ppm" for a mixing-ratio unit, else ""."""
    prefix = str(unit).strip().lower()[:3]
    return prefix if prefix in ("ppb", "ppm") else ""


def unit_factor(
    unit: str, table_unit: str, molar_mass: Optional[float] = None
) -> float:
    """Factor from unit to the unit of a table; 1.0 for a blank or unknown unit.

    Args:
        unit: The unit of the value.
        table_unit: The unit of the table.
        molar_mass: g/mol of a gas, to convert a mass to a table in ppb or ppm.

    Returns:
        The factor. NaN from ppb or ppm to a mass unit, which needs temperature
        and pressure, and from a mass to ppb or ppm without a molar mass.
    """
    mass, volume = _mass_unit(unit), _volume_unit(unit)
    table_mass, table_volume = _mass_unit(table_unit), _volume_unit(table_unit)
    if volume and table_mass:
        return math.nan
    if volume and table_volume:
        return _VOLUME_FACTORS.get((volume, table_volume), 1.0)
    if mass and table_volume:
        if molar_mass is None:
            return math.nan
        mg_per_m3 = 1.0 / 1000 if mass == "µg" else 1.0
        ppm = mg_per_m3 * _MOLAR_VOLUME / molar_mass
        return ppm * 1000 if table_volume == "ppb" else ppm
    return _MASS_FACTORS.get((mass, table_mass), 1.0)


def _warn_volume_units(labels: List[str]) -> None:
    if labels:
        logger.warning(
            "Ignoring values in ppb or ppm, which need temperature and pressure "
            "to convert to a mass concentration: %s",
            ", ".join(sorted(set(labels))),
        )


def day_shift(day_ends_at: int) -> pd.Timedelta:
    """The shift that puts a day ending at hour day_ends_at on its calendar date.

    Raises:
        ValueError: If day_ends_at is not an hour from 1 to 24.
    """
    if not 1 <= day_ends_at <= 24:
        raise ValueError("day_ends_at must be an hour from 1 to 24")
    import pandas as pd

    return pd.Timedelta(hours=24 - day_ends_at)


def rolling_8h(
    hourly: pd.DataFrame, min_periods: int, full_grid: bool = False
) -> pd.DataFrame:
    """8-hour running means of each station, placed at the last hour of a window.

    Args:
        hourly: Columns station_id, hour and value of one pollutant.
        min_periods: Fewest hours of data in a window.
        full_grid: Also return the hours of a gap, so that a missing hour still
            ends a window.

    Returns:
        DataFrame with columns station_id, hour and value.
    """
    import pandas as pd

    frames = []
    for station, rows in hourly.groupby("station_id", sort=False):
        series = rows.set_index("hour")["value"].sort_index()
        if full_grid:
            series = series.asfreq("h")
        rolled = series.rolling("8h", min_periods=min_periods).mean()
        frames.append(
            pd.DataFrame(
                {"station_id": station, "hour": rolled.index, "value": rolled.values}
            )
        )
    return pd.concat(frames, ignore_index=True)


def by_day(
    frame: pd.DataFrame, how: str, min_hours: int, shift: pd.Timedelta, count: str
) -> pd.Series:
    """Daily aggregate of hourly values per station, missing below min_hours.

    Args:
        frame: Columns station_id, hour and value.
        how: "mean" or "max".
        min_hours: Fewest counted hours for a value.
        shift: From day_shift.
        count: "size" counts rows and "count" counts non-missing values. They
            differ for 8-hour pollutants, whose windows can be missing.

    Returns:
        The values, indexed by station_id and day.
    """
    # An hour is labelled by its start, so the hour at day_ends_at is in the next day
    day = (frame["hour"] + shift).dt.normalize()
    grouped = frame.assign(day=day).groupby(["station_id", "day"])["value"]
    return grouped.agg(how).where(grouped.agg(count) >= min_hours)


def in_short_days(table: pd.DataFrame, parts: Iterable[pd.Series]) -> List[bool]:
    """For each row of table (station_id, day), whether a pollutant fell short.

    parts are by_day values, which are missing on a day that had readings but
    too few hours for that pollutant.
    """
    short = set()
    for part in parts:
        short.update(part.index[part.isna()].tolist())
    return [key in short for key in zip(table["station_id"], table["day"])]


def hourly_means(
    long: pd.DataFrame,
    resolve: Callable[[str], Optional[str]],
    factor: Callable[[str, str], float],
) -> pd.DataFrame:
    """Hourly means of tidy data, in the unit each standard's tables use.

    Args:
        long: Tidy data with columns timestamp, pollutant, value, and
            optionally station_id and unit. A blank unit cell falls back to
            the unit in the pollutant label.
        resolve: Label -> pollutant name, or None to leave the label out.
        factor: (name, unit) -> factor to the unit of the tables. NaN leaves
            the rows out, with one warning.

    Returns:
        DataFrame with columns station_id, pollutant, hour and value. Negative
        and infinite values are left out; readings repeated for one time are
        averaged first.
    """
    import pandas as pd

    # Labels repeat on every row; resolve each distinct label once
    labels = long["pollutant"].unique()
    names = {label: resolve(label) for label in labels}
    label_units = {label: split_label(str(label))[1] for label in labels}
    units = long["pollutant"].map(label_units).astype(object)
    if "unit" in long:
        given = long["unit"].notna() & (long["unit"].astype(str).str.strip() != "")
        units = long["unit"].where(given, units)
    data = long.assign(
        pollutant=long["pollutant"].map(names),
        value=_finite_numeric(long["value"]),
        _unit=units,
    )
    data = data.dropna(subset=["pollutant", "value"])
    # Negative values are sensor faults; left in, they would pull the mean down
    data = data[data["value"] >= 0]
    if "station_id" not in data:
        data = data.assign(station_id="")
    pairs = pd.MultiIndex.from_frame(data[["pollutant", "_unit"]])
    factors = {pair: factor(*pair) for pair in pairs.unique()}
    _warn_volume_units(
        [f"{name} ({unit})" for (name, unit), f in factors.items() if math.isnan(f)]
    )
    data = data.assign(
        value=data["value"] * pairs.map(factors).to_numpy(dtype=float),
        timestamp=lambda d: parse_timestamps(d["timestamp"]),
    ).dropna(subset=["value"])
    data = _mean_duplicates(data, ["station_id", "pollutant", "timestamp"], "value")
    data = data.assign(hour=data["timestamp"].dt.floor("h"))
    return data.groupby(["station_id", "pollutant", "hour"], as_index=False)[
        "value"
    ].mean()
