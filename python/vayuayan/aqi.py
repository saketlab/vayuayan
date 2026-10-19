"""
The Indian National Air Quality Index (NAQI) of CPCB, from pollutant
concentrations.

Breakpoints and rules are from CPCB, "About National Air Quality Index" and
"How is AQI calculated?" (cpcb.gov.in). Where CPCB documents differ (Pb
0.5-1.0 here, 0.6-1.0 in the 2014 NAQI report), vayuayan follows the About
page:

- A sub-index is a linear function of the concentration within a breakpoint
  band. Concentrations are 24-hour averages, and 8-hour averages for CO and O3.
- A sub-index needs at least 16 hours of data.
- The overall AQI is the highest sub-index. It needs at least three pollutants,
  one of them PM2.5 or PM10; otherwise the data are insufficient.

CPCB gives no upper concentration for the Severe band (401-500). vayuayan
extends it by the width of the Very Poor band, as common open
implementations do (for example PM2.5 250-380). Above that, the sub-index
continues on the same slope, as in CPCB's AQI calculator (AQI-Calculator.xls),
so it can be more than 500. The AQI is rounded half up, as the calculator
shows it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Mapping, Optional, Tuple

from .constants import AQI_CATEGORIES
from .tidy import split_label
from .utils import get_aqi_category

if TYPE_CHECKING:
    import numpy as np
    import pandas as pd
    from numpy.typing import ArrayLike

# AQI value range of each category, Good to Severe
AQI_BANDS: List[Tuple[int, int]] = [
    (b["min"], b["max"]) for b in AQI_CATEGORIES.values()
]


@dataclass(frozen=True)
class Pollutant:
    """One NAQI pollutant: its unit, averaging time and breakpoints."""

    name: str
    unit: str
    averaging_hours: int
    # (low, high) concentration of each AQI band, Good to Severe
    breakpoints: Tuple[Tuple[float, float], ...]

    def points(self) -> Tuple[List[float], List[float]]:
        """(concentrations, sub-indices) to interpolate, increasing."""
        xs: List[float] = []
        ys: List[float] = []
        for (c_lo, c_hi), (i_lo, i_hi) in zip(self.breakpoints, AQI_BANDS):
            if xs and c_lo <= xs[-1]:
                # Bands that share a boundary (Pb 0.5, CO 10): the boundary
                # belongs to the lower band
                c_lo = xs[-1] + 1e-9
            xs += [c_lo, c_hi]
            ys += [float(i_lo), float(i_hi)]
        return xs, ys


# CPCB breakpoints; CO in mg/m3, the others in µg/m3. The last band is the
# Severe extension described in the module docstring.
POLLUTANTS: Dict[str, Pollutant] = {
    p.name: p
    for p in (
        Pollutant("PM10", "µg/m³", 24, ((0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (430, 510))),
        Pollutant("PM2.5", "µg/m³", 24, ((0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (250, 380))),
        Pollutant("NO2", "µg/m³", 24, ((0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (400, 520))),
        Pollutant("O3", "µg/m³", 8, ((0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (748, 1288))),
        Pollutant("CO", "mg/m³", 8, ((0, 1.0), (1.1, 2.0), (2.1, 10), (10, 17), (17, 34), (34, 51))),
        Pollutant("SO2", "µg/m³", 24, ((0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1600, 2400))),
        Pollutant("NH3", "µg/m³", 24, ((0, 200), (201, 400), (401, 800), (801, 1200), (1200, 1800), (1800, 2400))),
        Pollutant("Pb", "µg/m³", 24, ((0, 0.5), (0.5, 1.0), (1.1, 2.0), (2.1, 3.0), (3.1, 3.5), (3.5, 3.9))),
    )
}  # fmt: skip

# Interpolation points of each pollutant, computed once
_POINTS = {name: p.points() for name, p in POLLUTANTS.items()}


def _key(label: str) -> str:
    """A label without its unit, case or punctuation: "PM2.5 (µg/m³)" -> "pm25"."""
    name = split_label(str(label))[0].lower().replace("2.5", "25")
    return re.sub(r"[^a-z0-9]", "", name)


_NAMES = {_key(name): name for name in POLLUTANTS}
_NAMES.update({"ozone": "O3", "lead": "Pb"})

# Unit factors to the unit of POLLUTANTS (µg and mg, with either mu character)
_MASS_FACTORS = {("µg", "mg"): 1e-3, ("mg", "µg"): 1e3}

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

    Matches labels such as "PM2.5 (µg/m³)", "pm25", "Ozone" and "CO (mg/m³)".
    """
    return _NAMES.get(_key(name))


def sub_index(pollutant: str, concentration: float) -> float:
    """The NAQI sub-index of one concentration, or NaN for a missing value.

    Args:
        pollutant: A pollutant label (see pollutant_name).
        concentration: 24-hour average (8-hour for CO and O3), in the unit
            of POLLUTANTS[pollutant] (mg/m3 for CO, µg/m3 for the others).

    Raises:
        ValueError: If the pollutant is not a NAQI pollutant.
    """
    return float(_interpolate(_require(pollutant), concentration))


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

    @property
    def sufficient(self) -> bool:
        """True if the data meet the CPCB minimum for an overall AQI."""
        return self.aqi is not None


def compute_aqi(concentrations: Mapping[str, float]) -> AQIResult:
    """The overall NAQI of a set of averaged concentrations.

    Args:
        concentrations: Pollutant label -> averaged concentration. Labels that
            are not NAQI pollutants, and missing values, are ignored.

    Returns:
        The AQI, its category and dominant pollutant, and all sub-indices. The
        AQI is None if fewer than three pollutants, or neither PM2.5 nor PM10,
        have a value.

    Example:
        >>> compute_aqi({"PM2.5": 45, "PM10": 80, "NO2": 30}).aqi
        80
    """
    subs: Dict[str, float] = {}
    for label, value in concentrations.items():
        name = pollutant_name(label)
        if name is None or value is None or math.isnan(float(value)):
            continue
        sub = float(_interpolate(POLLUTANTS[name], float(value)))
        # A pollutant given twice (for example "PM10" and "pm10") counts once
        subs[name] = max(sub, subs.get(name, -math.inf))
    if not _sufficient(subs):
        return AQIResult(None, None, None, subs)
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
            µg/m3 or mg/m3 are converted to the unit of POLLUTANTS.
        min_hours: Minimum hours with data for a sub-index (CPCB: 16).
        day_ends_at: Hour (1-24) at which each day's 24 hours end. 24 means
            calendar days; 16 matches CPCB's 4 PM bulletin. The date of a row
            is the date on which its window ends.

    Returns:
        One row per station and date: station_id, date, aqi (nullable integer),
        category, dominant_pollutant, n_pollutants, and one <pollutant>_sub_index
        column per pollutant with data. aqi, category and dominant_pollutant
        are missing when the data are insufficient.
    """
    if not 1 <= day_ends_at <= 24:
        raise ValueError("day_ends_at must be an hour from 1 to 24")
    import numpy as np
    import pandas as pd

    shift = pd.Timedelta(hours=24 - day_ends_at)
    hourly = _hourly_means(long)
    columns = [
        "station_id",
        "date",
        "aqi",
        "category",
        "dominant_pollutant",
        "n_pollutants",
    ]
    if hourly.empty:
        return pd.DataFrame(columns=columns)

    daily_parts = []
    for name, group in hourly.groupby("pollutant", sort=False):
        group = group.sort_values(["station_id", "hour"])
        eight_hour = POLLUTANTS[name].averaging_hours == 8
        if eight_hour:
            # groupby keeps the (station, hour) order of the sorted group
            rolled = (
                group.set_index("hour")
                .groupby("station_id")["value"]
                .rolling("8h", min_periods=6)
                .mean()
            )
            group = group.assign(value=rolled.to_numpy())
        # An hour is labelled by its start, so the hour that starts at
        # day_ends_at belongs to the next day
        group = group.assign(day=(group["hour"] + shift).dt.normalize())
        stats = group.groupby(["station_id", "day"]).agg(
            value=("value", "max" if eight_hour else "mean"),
            hours=("hour", "size"),  # hours are unique per station already
        )
        value = stats["value"].where(stats["hours"] >= min_hours)
        daily_parts.append(
            pd.Series(
                _interpolate(POLLUTANTS[name], value.to_numpy()),
                index=stats.index,
                name=f"{name}_sub_index",
            )
        )

    daily = pd.concat(daily_parts, axis=1)
    # fixed order so ties match R
    order = [f"{name}_sub_index" for name in POLLUTANTS]
    daily = daily[[c for c in order if c in daily.columns]].reset_index()
    daily["date"] = daily.pop("day").dt.date
    subs = daily.filter(like="_sub_index")
    present = subs.notna()
    has_pm = present.loc[
        :, subs.columns.isin(["PM2.5_sub_index", "PM10_sub_index"])
    ].any(axis=1)
    daily["n_pollutants"] = present.sum(axis=1)
    ok = (daily["n_pollutants"] >= MIN_POLLUTANTS) & has_pm
    # Half up, as compute_aqi; Series.round() rounds half to even
    daily["aqi"] = np.floor(subs.max(axis=1).where(ok) + 0.5).astype("Int64")
    dominant = subs[ok].idxmax(axis=1).str.removesuffix("_sub_index")
    daily["dominant_pollutant"] = dominant.reindex(daily.index)
    daily["category"] = daily["aqi"].map(get_aqi_category, na_action="ignore")
    return daily[columns + list(subs.columns)].sort_values(
        ["station_id", "date"], ignore_index=True
    )


def _require(pollutant: str) -> Pollutant:
    name = pollutant_name(pollutant)
    if name is None:
        raise ValueError(
            f"{pollutant!r} is not a NAQI pollutant: {', '.join(POLLUTANTS)}"
        )
    return POLLUTANTS[name]


def _interpolate(pollutant: Pollutant, concentrations: ArrayLike) -> np.ndarray:
    """Sub-indices of concentrations (array); NaN stays NaN. Above the last
    breakpoint the slope of the last band continues."""
    import numpy as np

    xs, ys = _POINTS[pollutant.name]
    c = np.asarray(concentrations, dtype=float)
    slope = (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
    above = ys[-1] + (c - xs[-1]) * slope
    sub = np.where(c > xs[-1], above, np.interp(c, xs, ys))
    return np.where(np.isnan(c), np.nan, sub)


def _round_half_up(x: float) -> float:
    """Round half up, as Excel shows CPCB's calculator; round() rounds half to even."""
    return x if math.isnan(x) else float(math.floor(x + 0.5))


def _sufficient(subs: Mapping[str, float]) -> bool:
    return len(subs) >= MIN_POLLUTANTS and ("PM2.5" in subs or "PM10" in subs)


def _hourly_means(long: pd.DataFrame) -> pd.DataFrame:
    """Hourly means of the NAQI pollutants in tidy data, in the NAQI units."""
    import pandas as pd

    # Labels repeat on every row; resolve each distinct label once
    names = {label: pollutant_name(label) for label in long["pollutant"].unique()}
    data = long.assign(
        pollutant=long["pollutant"].map(names),
        value=pd.to_numeric(long["value"], errors="coerce").astype(float),
    )
    data = data.dropna(subset=["pollutant", "value"])
    if "station_id" not in data:
        data = data.assign(station_id="")
    if "unit" in data:
        for (name, unit), rows in data.groupby(["pollutant", "unit"]).groups.items():
            factor = _MASS_FACTORS.get(
                (_mass_unit(unit), _mass_unit(POLLUTANTS[name].unit))
            )
            if factor:
                data.loc[rows, "value"] *= factor
    timestamps = data["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps):
        timestamps = pd.to_datetime(timestamps)
    data = data.assign(hour=timestamps.dt.floor("h"))
    return data.groupby(["station_id", "pollutant", "hour"], as_index=False)[
        "value"
    ].mean()


def _mass_unit(unit: str) -> str:
    """ "µg" or "mg" for a concentration unit such as "µg/m³", else ""."""
    prefix = str(unit).strip().lower().replace("μ", "µ").replace("ug", "µg")[:2]
    return prefix if prefix in ("µg", "mg") else ""
