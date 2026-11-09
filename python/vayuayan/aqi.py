"""
The Indian National Air Quality Index (NAQI) of CPCB, from pollutant
concentrations.

Rules are from CPCB, "National Air Quality Index" (CUPS/82/2014-15), "About
National Air Quality Index", "How is AQI calculated?" and AQI-Calculator.xls.
CPCB's documents differ; docs/aqi_standards.rst lists where and why:

- A sub-index is continuous and piecewise linear: each band starts at the top
  of the band below, at the sub-index of that top, as in CPCB's calculator and
  CUPS/82 p.37. For example PM2.5 30-60 maps to 50-100. Concentrations are
  24-hour averages, and 8-hour averages for CO and O3, also for O3 above 208.
- A sub-index needs at least 16 hours of data.
- The overall AQI is the highest sub-index. It needs at least three pollutants,
  one of them PM2.5 or PM10; otherwise the data are insufficient.

CPCB gives no upper concentration for the Severe band (400-500). vayuayan
uses the width of the Very Poor band, which is the calculator's slope (for
example PM2.5 250-380). O3 stays on its published 208-748 and 748-1288 bands,
because the calculator's own O3 formula is wrong there. Above the last band
the sub-index continues on the same slope, so it can be more than 500. The
AQI is rounded half up, as the calculator shows it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Tuple

from .aqi_units import (
    DAILY_COLUMNS,
    _warn_volume_units,
    by_day,
    day_shift,
    hourly_means,
    in_short_days,
    rolling_8h,
    unit_factor,
)
from .constants import AQI_CATEGORIES
from .tidy import split_label
from .utils import get_aqi_category

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from numpy.typing import ArrayLike

# Sub-index at the top of each band, Good to Severe
_SUB_INDEX_TOPS = tuple(float(band["max"]) for band in AQI_CATEGORIES.values())


@dataclass(frozen=True)
class Pollutant:
    """One NAQI pollutant: its unit, averaging time and band tops."""

    name: str
    unit: str
    averaging_hours: int
    # Concentration at the top of each AQI band, Good to Severe
    tops: Tuple[float, ...]

    @property
    def breakpoints(self) -> Tuple[Tuple[float, float], ...]:
        """(low, high) of each band; the first starts at 0, the others at the last top."""
        return tuple(zip((0, *self.tops[:-1]), self.tops))


# CPCB band tops as continuous bands; CO in mg/m3, others in µg/m3; last is the Severe extension
POLLUTANTS: Dict[str, Pollutant] = {
    p.name: p
    for p in (
        Pollutant("PM10", "µg/m³", 24, (50, 100, 250, 350, 430, 510)),
        Pollutant("PM2.5", "µg/m³", 24, (30, 60, 90, 120, 250, 380)),
        Pollutant("NO2", "µg/m³", 24, (40, 80, 180, 280, 400, 520)),
        Pollutant("O3", "µg/m³", 8, (50, 100, 168, 208, 748, 1288)),
        Pollutant("CO", "mg/m³", 8, (1.0, 2.0, 10, 17, 34, 51)),
        Pollutant("SO2", "µg/m³", 24, (40, 80, 380, 800, 1600, 2400)),
        Pollutant("NH3", "µg/m³", 24, (200, 400, 800, 1200, 1800, 2400)),
        Pollutant("Pb", "µg/m³", 24, (0.5, 1.0, 2.0, 3.0, 3.5, 4.0)),
    )
}


def _key(label: str) -> str:
    """A label without its unit, case or punctuation: "PM2.5 (µg/m³)" -> "pm25"."""
    name = split_label(str(label))[0].lower().replace("2.5", "25")
    return re.sub(r"[^a-z0-9]", "", name)


def _qualifier_free_key(label: str) -> str:
    """_key without parenthesised qualifiers: "CO (8hr) (mg/m³)" -> "co"."""
    name = re.sub(r"\([^()]*\)", "", split_label(str(label))[0])
    return _key(name)


_NAMES = {_key(name): name for name in POLLUTANTS}
_NAMES.update({"ozone": "O3", "lead": "Pb"})

MIN_HOURS = 16
MIN_POLLUTANTS = 3

# health texts of CPCB's AQI-Calculator.xls
HEALTH_IMPACTS: Dict[str, str] = {
    "Good": "Minimal impact",
    "Satisfactory": "Minor breathing discomfort to sensitive people",
    "Moderate": (
        "Breathing discomfort to the people with lung, heart disease, "
        "children and older adults"
    ),
    "Poor": "Breathing discomfort to people on prolonged exposure",
    "Very Poor": "Respiratory illness to the people on prolonged exposure",
    "Severe": "Respiratory effects even on healthy people",
}

# WHO global air quality guidelines (2021) for PM2.5, in µg/m³
WHO_PM25_GUIDELINES: Dict[str, float] = {"annual": 5.0, "24-hour": 15.0}


def pollutant_name(name: str) -> Optional[str]:
    """The NAQI name of a pollutant label, or None if it is not a NAQI pollutant.

    Matches labels such as "PM2.5 (µg/m³)", "pm25", "Ozone", "CO (mg/m³)" and
    "CO (8hr) (mg/m³)".
    """
    return _NAMES.get(_key(name)) or _NAMES.get(_qualifier_free_key(name))


def sub_index(pollutant: str, concentration: float) -> float:
    """The NAQI sub-index of one concentration, or NaN for a missing value.

    Args:
        pollutant: A pollutant label (see pollutant_name). A mass unit in the
            label ("CO (µg/m³)") is converted to the unit of POLLUTANTS. A
            label in ppb or ppm gives NaN and a warning: converting a gas to
            mass needs its temperature and pressure.
        concentration: 24-hour average (8-hour for CO and O3), in the unit
            of the label, or without one in the unit of POLLUTANTS[pollutant]
            (mg/m3 for CO, µg/m3 for the others). Negative values and
            infinities give NaN.

    Raises:
        ValueError: If the pollutant is not a NAQI pollutant.
    """
    in_volume_units: List[str] = []
    sub = _label_sub_index(
        _require(pollutant).name, pollutant, concentration, in_volume_units
    )
    _warn_volume_units(in_volume_units)
    return sub


def health_impact(aqi_value: float) -> str:
    """CPCB's possible health impact of an AQI value, or "No Data" if missing.

    Example:
        >>> health_impact(250)
        'Breathing discomfort to people on prolonged exposure'
    """
    return HEALTH_IMPACTS.get(get_aqi_category(aqi_value), "No Data")


def pollutant_category(pollutant: str, concentration: float) -> str:
    """The AQI category of one pollutant concentration, from its sub-index.

    For example the category of a PM2.5 mean from satellite data. The
    breakpoints are for 24-hour averages (8-hour for CO and O3), so for an
    annual or monthly mean the category is an indication only.

    Example:
        >>> pollutant_category("PM2.5", 75)
        'Moderate'
    """
    return get_aqi_category(_round_half_up(sub_index(pollutant, concentration)))


@dataclass(frozen=True)
class AQIResult:
    """The overall AQI of one set of concentrations."""

    aqi: Optional[int]
    category: Optional[str]
    dominant_pollutant: Optional[str]
    sub_indices: Dict[str, float] = field(default_factory=dict)
    # ok, or why there is no AQI: no_pm, too_few_pollutants, no_sub_index, o3_beyond_table
    status: str = "ok"

    @property
    def sufficient(self) -> bool:
        """True if the data meet the minimum for an overall AQI."""
        return self.status == "ok"


def compute_aqi(concentrations: Mapping[str, float]) -> AQIResult:
    """The overall NAQI of a set of averaged concentrations.

    Args:
        concentrations: Pollutant label -> averaged concentration, in the
            unit of the label as for sub_index. Labels that are not NAQI
            pollutants, missing, negative or infinite values, and labels in
            ppb or ppm (with a warning) are ignored.

    Returns:
        The AQI, its category and dominant pollutant, and all sub-indices. The
        AQI is None if fewer than three pollutants, or neither PM2.5 nor PM10,
        have a value.

    Example:
        >>> compute_aqi({"PM2.5": 45, "PM10": 80, "NO2": 30}).aqi
        80
    """
    subs: Dict[str, float] = {}
    in_volume_units: List[str] = []
    for label, value in concentrations.items():
        name = pollutant_name(label)
        if name is None or _missing(value):
            continue
        sub = _label_sub_index(name, label, float(value), in_volume_units)
        if not math.isnan(sub):
            # A pollutant given twice (for example "PM10" and "pm10") counts once
            subs[name] = max(sub, subs.get(name, -math.inf))
    _warn_volume_units(in_volume_units)
    status = _subs_status(subs)
    if status != "ok":
        return AQIResult(None, None, None, subs, status)
    # Ties go to the first pollutant in POLLUTANTS order
    dominant = max(
        (name for name in POLLUTANTS if name in subs), key=lambda name: subs[name]
    )
    value = int(_round_half_up(subs[dominant]))
    return AQIResult(value, get_aqi_category(value), dominant, subs)


def daily_aqi(
    long: pd.DataFrame, min_hours: int = MIN_HOURS, day_ends_at: int = 24
) -> pd.DataFrame:
    """Daily NAQI of each station from tidy long data, such as 15-minute data.

    The data are first averaged by hour. Then, for each station and day:
    PM10, PM2.5, NO2, SO2, NH3 and Pb use the mean of the hourly values;
    CO and O3 use the highest 8-hour running mean (of at least 6 hourly
    values). A sub-index needs data in at least min_hours hours of the day.

    CPCB's daily bulletin reports the AQI at 4 PM, from the 24 hours before
    it; use day_ends_at=16 to compute the same window. CPCB also validates
    its data before it publishes, which vayuayan cannot repeat: for station
    site_301 (Anand Vihar) in 2024, daily_aqi(day_ends_at=16) differed from
    the published daily AQI by a median of 10, and was 5 higher on average.

    Args:
        long: Tidy data with columns timestamp, pollutant, value, and
            optionally station_id and unit (see vayuayan.tidy). Values in
            µg/m3 or mg/m3, by the unit column or the unit in the pollutant
            label, are converted to the unit of POLLUTANTS. Rows in ppb or ppm
            are left out, with one warning. Negative and infinite values are
            left out; readings repeated for one time are averaged first.
        min_hours: Minimum hours with data for a sub-index (CPCB: 16).
        day_ends_at: Hour (1-24) at which each day's 24 hours end. 24 means
            calendar days; 16 matches CPCB's 4 PM bulletin. The date of a row
            is the date on which its window ends.

    Returns:
        One row per station and date: station_id, date, aqi (nullable integer),
        category, dominant_pollutant, n_pollutants, aqi_status, and one
        <pollutant>_sub_index column per pollutant with data. aqi, category and
        dominant_pollutant are missing when the data are insufficient.
        aqi_status says why: "too_few_hours" if a pollutant had readings but
        too few hours, else "no_pm", else "too_few_pollutants"; "ok" with an AQI.
    """
    shift = day_shift(day_ends_at)
    import numpy as np
    import pandas as pd

    hourly = hourly_means(long, pollutant_name, _naqi_factor)
    if hourly.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)

    daily_parts = []
    for name, group in hourly.groupby("pollutant", sort=False):
        eight_hour = POLLUTANTS[name].averaging_hours == 8
        if eight_hour:
            group = rolling_8h(group, min(6, min_hours))
        # Hours are unique per station already, so every row is an hour with data
        value = by_day(group, "max" if eight_hour else "mean", min_hours, shift, "size")
        daily_parts.append(
            pd.Series(
                _interpolate(POLLUTANTS[name], value.to_numpy()),
                index=value.index,
                name=f"{name}_sub_index",
            )
        )

    daily = pd.concat(daily_parts, axis=1)
    # fixed order so ties match R
    order = [f"{name}_sub_index" for name in POLLUTANTS]
    daily = daily[[c for c in order if c in daily.columns]].reset_index()
    short_days = in_short_days(daily, daily_parts)
    daily["date"] = daily.pop("day").dt.date
    subs = daily.filter(like="_sub_index")
    present = subs.notna()
    has_pm = present.loc[
        :, subs.columns.isin(["PM2.5_sub_index", "PM10_sub_index"])
    ].any(axis=1)
    daily["n_pollutants"] = present.sum(axis=1)
    ok = (daily["n_pollutants"] >= MIN_POLLUTANTS) & has_pm
    status = np.where(
        ~has_pm,
        "no_pm",
        np.where(daily["n_pollutants"] < MIN_POLLUTANTS, "too_few_pollutants", "ok"),
    )
    daily["aqi_status"] = np.where(~ok & np.array(short_days), "too_few_hours", status)
    # Half up, as compute_aqi; Series.round() rounds half to even
    daily["aqi"] = np.floor(subs.max(axis=1).where(ok) + 0.5).astype("Int64")
    dominant = subs[ok].idxmax(axis=1).str.removesuffix("_sub_index")
    daily["dominant_pollutant"] = dominant.reindex(daily.index)
    daily["category"] = daily["aqi"].map(get_aqi_category, na_action="ignore")
    return daily[DAILY_COLUMNS + list(subs.columns)].sort_values(
        ["station_id", "date"], ignore_index=True
    )


def _require(pollutant: str) -> Pollutant:
    name = pollutant_name(pollutant)
    if name is None:
        raise ValueError(
            f"{pollutant!r} is not a NAQI pollutant: {', '.join(POLLUTANTS)}"
        )
    return POLLUTANTS[name]


def _interpolate(
    pollutant: Pollutant, concentrations: ArrayLike, factor: float = 1.0
) -> np.ndarray:
    """Sub-indices of concentrations (array); NaN, infinite and negative values
    give NaN. Above the last breakpoint the slope of the last band continues."""
    import numpy as np

    xs, ys = (0.0, *pollutant.tops), (0.0, *_SUB_INDEX_TOPS)
    c = np.asarray(concentrations, dtype=float) * factor
    invalid = ~np.isfinite(c) | (c < 0)
    slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    above = ys[-1] + (c - xs[-1]) * slope
    sub = np.where(c > xs[-1], above, np.interp(c, xs, ys))
    return np.where(invalid, np.nan, sub)


def _round_half_up(x: float) -> float:
    """Round half up, as Excel shows CPCB's calculator; round() rounds half to even."""
    return x if not math.isfinite(x) else float(math.floor(x + 0.5))


def _missing(value: Optional[float]) -> bool:
    """True for None, NaN and infinities."""
    return value is None or not math.isfinite(float(value))


def _subs_status(subs: Mapping[str, float]) -> str:
    """ok, or which CPCB minimum the sub-indices miss; PM is checked first."""
    if "PM2.5" not in subs and "PM10" not in subs:
        return "no_pm"
    return "ok" if len(subs) >= MIN_POLLUTANTS else "too_few_pollutants"


def _naqi_factor(name: str, unit: str) -> float:
    """Factor from unit to the NAQI unit of the pollutant; NaN for ppb and ppm."""
    return unit_factor(unit, POLLUTANTS[name].unit)


def _label_sub_index(
    name: str, label: str, value: float, in_volume_units: List[str]
) -> float:
    """Sub-index of a value in the unit of its label; a ppb or ppm label gives NaN
    and goes in in_volume_units, so that callers can warn once."""
    factor = _naqi_factor(name, split_label(str(label))[1])
    if math.isnan(factor):
        in_volume_units.append(str(label))
    return float(_interpolate(POLLUTANTS[name], value, factor))
