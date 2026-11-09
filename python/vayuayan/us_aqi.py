"""
The US EPA Air Quality Index (AQI), from pollutant concentrations.

Breakpoints, categories and colors are from the EPA "Technical Assistance
Document for the Reporting of Daily Air Quality" (EPA-403/B-26-003, May 2026,
which that URL now serves; the calculation is that of EPA-454/B-24-002, May
2024), and 40 CFR Part 58 Appendix G:
https://document.airnow.gov/technical-assistance-document-for-the-reporting-of-daily-air-quailty.pdf

- Concentrations are truncated to the precision of the table (PM2.5 0.1
  µg/m³, PM10 1 µg/m³, O3 0.001 ppm, CO 0.1 ppm, SO2 and NO2 1 ppb). Then
  the sub-index is a linear function of the concentration within its band.
- O3 uses 8-hour averages up to 0.200 ppm, and 1-hour averages from 0.125
  ppm. SO2 uses 1-hour averages up to 304 ppb, and 24-hour averages from 305
  ppb. If you give both, the higher sub-index counts. If the 1-hour SO2 is
  305 ppb or more and the 24-hour SO2 is below 305 ppb or missing, the SO2
  sub-index is 200. Without a 1-hour value, 8-hour O3 above 0.200 ppm gives no
  AQI, because the 8-hour table stops at 300.
- Above the highest breakpoint, the sub-index continues on the slope of the
  301-500 band, so it can be more than 500. All values above 300 are
  Hazardous.
- The AQI is the highest sub-index, rounded to an integer. The EPA has no
  minimum number of pollutants.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Tuple

from .aqi import AQIResult, _key, _missing, _qualifier_free_key, _round_half_up
from .aqi_units import unit_factor
from .tidy import split_label

logger = logging.getLogger(__name__)

# AQI value range of each category; Hazardous has no upper limit
US_AQI_CATEGORIES: Dict[str, Tuple[float, float]] = {
    "Good": (0, 50),
    "Moderate": (51, 100),
    "Unhealthy for Sensitive Groups": (101, 150),
    "Unhealthy": (151, 200),
    "Very Unhealthy": (201, 300),
    "Hazardous": (301, math.inf),
}


# EPA Table 2 (standard) and Table 3 (ColorVision Assist)
US_AQI_COLORS: Dict[str, str] = dict(
    zip(
        US_AQI_CATEGORIES,
        ("#00E400", "#FFFF00", "#FF7E00", "#FF0000", "#8F3F97", "#7E0023"),
    )
)
US_AQI_COLORS_ASSIST: Dict[str, str] = dict(
    zip(
        US_AQI_CATEGORIES,
        ("#9EFF91", "#FFC905", "#FF8205", "#F02200", "#890997", "#640015"),
    )
)


@dataclass(frozen=True)
class USPollutant:
    """One US AQI pollutant: unit, averaging time, precision and bands."""

    name: str
    unit: str
    averaging_hours: int
    decimals: int
    molar_mass: Optional[float]  # g/mol, to convert µg/m³ or mg/m³; None for PM
    # (concentration low, concentration high, index low, index high)
    bands: Tuple[Tuple[float, float, int, int], ...]


US_POLLUTANTS: Dict[str, USPollutant] = {
    p.name: p
    for p in (
        USPollutant("PM2.5", "µg/m³", 24, 1, None, (
            (0.0, 9.0, 0, 50), (9.1, 35.4, 51, 100), (35.5, 55.4, 101, 150),
            (55.5, 125.4, 151, 200), (125.5, 225.4, 201, 300), (225.5, 325.4, 301, 500))),
        USPollutant("PM10", "µg/m³", 24, 0, None, (
            (0, 54, 0, 50), (55, 154, 51, 100), (155, 254, 101, 150),
            (255, 354, 151, 200), (355, 424, 201, 300), (425, 604, 301, 500))),
        USPollutant("O3", "ppm", 8, 3, 48.00, (
            (0.000, 0.054, 0, 50), (0.055, 0.070, 51, 100), (0.071, 0.085, 101, 150),
            (0.086, 0.105, 151, 200), (0.106, 0.200, 201, 300))),
        USPollutant("O3_1h", "ppm", 1, 3, 48.00, (
            (0.125, 0.164, 101, 150), (0.165, 0.204, 151, 200),
            (0.205, 0.404, 201, 300), (0.405, 0.604, 301, 500))),
        USPollutant("CO", "ppm", 8, 1, 28.01, (
            (0.0, 4.4, 0, 50), (4.5, 9.4, 51, 100), (9.5, 12.4, 101, 150),
            (12.5, 15.4, 151, 200), (15.5, 30.4, 201, 300), (30.5, 50.4, 301, 500))),
        USPollutant("SO2", "ppb", 1, 0, 64.07, (
            (0, 35, 0, 50), (36, 75, 51, 100), (76, 185, 101, 150), (186, 304, 151, 200))),
        USPollutant("SO2_24h", "ppb", 24, 0, 64.07, (
            (305, 604, 201, 300), (605, 1004, 301, 500))),
        USPollutant("NO2", "ppb", 1, 0, 46.01, (
            (0, 53, 0, 50), (54, 100, 51, 100), (101, 360, 101, 150),
            (361, 649, 151, 200), (650, 1249, 201, 300), (1250, 2049, 301, 500))),
    )
}  # fmt: skip

# the EPA switches to 1-hour O3 and 24-hour SO2 above these tables
_NO_EXTRAPOLATION = {"O3", "SO2"}


_NAMES = {
    **{_key(name): name for name in US_POLLUTANTS},
    "ozone": "O3", "ozone1h": "O3_1h", "o38h": "O3", "co8h": "CO",
    "so21h": "SO2", "no21h": "NO2", "pm2524h": "PM2.5", "pm1024h": "PM10",
}  # fmt: skip


def us_pollutant_name(label: str) -> Optional[str]:
    """The US AQI name of a pollutant label, or None if it is not one.

    Matches labels such as "PM2.5 (µg/m³)", "Ozone", "O3_1h", "SO2 24h" and
    "SO2 (24h) (ppb)".
    """
    return _NAMES.get(_key(label)) or _NAMES.get(_qualifier_free_key(label))


def us_sub_index(pollutant: str, concentration: Optional[float]) -> float:
    """The US AQI sub-index of one concentration, or NaN.

    Args:
        pollutant: A pollutant label (see us_pollutant_name). A label with a
            mass unit, such as "O3 (µg/m³)" or "CO (mg/m³)", is converted to
            ppm or ppb at 25 °C and 760 mm Hg, and ppb and ppm to the one the
            table uses. "PM2.5 (mg/m³)" is converted to µg/m³, and PM in ppb
            or ppm gives NaN, because a mass pollutant cannot be in them.
            Without a unit, the value must be in the unit of
            US_POLLUTANTS[name].
        concentration: The average for the averaging time of the pollutant.

    Returns:
        The sub-index. Above the highest breakpoint it continues on the slope
        of the 301-500 band. NaN for a missing, negative or infinite value,
        and for a value outside the table of a pollutant with two averaging
        times (for example 8-hour O3 above 0.200 ppm).

    Raises:
        ValueError: If the pollutant is not a US AQI pollutant.
    """
    name = us_pollutant_name(pollutant)
    if name is None:
        raise ValueError(
            f"{pollutant!r} is not a US AQI pollutant: {', '.join(US_POLLUTANTS)}"
        )
    return _band_sub_index(name, _table_value(name, pollutant, concentration))


def us_aqi_category(aqi_value: Optional[float]) -> str:
    """The US AQI category of an AQI value, or "No Data" if missing.

    Example:
        >>> us_aqi_category(120)
        'Unhealthy for Sensitive Groups'
    """
    if aqi_value is None or _missing(aqi_value):
        return "No Data"
    return next(
        (name for name, (_, hi) in US_AQI_CATEGORIES.items() if aqi_value <= hi),
        "Hazardous",
    )


def us_aqi_color(
    aqi_value: Optional[float], color_vision_assist: bool = False
) -> Optional[str]:
    """The EPA color of an AQI value as a hex code, or None if missing.

    Args:
        aqi_value: An AQI value.
        color_vision_assist: Use the ColorVision Assist colors (EPA Table 3),
            which have more contrast for people with color vision deficiency.

    Example:
        >>> us_aqi_color(120)
        '#FF7E00'
    """
    category = us_aqi_category(aqi_value)
    colors = US_AQI_COLORS_ASSIST if color_vision_assist else US_AQI_COLORS
    return colors.get(category)


def compute_us_aqi(concentrations: Mapping[str, Optional[float]]) -> AQIResult:
    """The overall US AQI of a set of averaged concentrations.

    Args:
        concentrations: Pollutant label -> concentration (see us_sub_index).
            Labels that are not US AQI pollutants, and missing values, are
            ignored.

    Returns:
        The AQI, its category and main pollutant, and all sub-indices that
        have a value. The AQI is None if no pollutant has a sub-index
        (status "no_sub_index"), and, with a warning, if 8-hour O3 is above
        0.200 ppm without a 1-hour value (status "o3_beyond_table").

    Example:
        >>> compute_us_aqi({"PM2.5": 35.4, "O3": 0.060}).aqi
        100
    """
    result, o3_beyond_table = _evaluate(concentrations)
    if o3_beyond_table:
        _warn_o3_beyond_table("8-hour O3 above 0.200 ppm")
    return result


def _warn_o3_beyond_table(what: str) -> None:
    logger.warning(
        "%s has no 8-hour sub-index and no 1-hour value was given, so no AQI "
        "is reported",
        what,
    )


def _evaluate(
    concentrations: Mapping[str, Optional[float]],
) -> Tuple[AQIResult, bool]:
    """The AQI of the concentrations, and whether 8-hour O3 prevented one."""
    subs: Dict[str, float] = {}
    o3_beyond_table = False
    so2: Dict[str, List[float]] = {"SO2": [], "SO2_24h": []}
    for label, value in concentrations.items():
        name = us_pollutant_name(label)
        if name is None:
            continue
        c = _table_value(name, label, value)
        if math.isnan(c):
            continue
        sub = _band_sub_index(name, c)
        if not math.isnan(sub):
            subs[name] = max(sub, subs.get(name, -math.inf))
        if name == "O3" and c > US_POLLUTANTS["O3"].bands[-1][1]:
            o3_beyond_table = True
        if name in so2:
            so2[name].append(c)
    # EPA TAD: 200 if the 24-hour is below 305; AQS aqi_breakpoints.csv: also if none
    highest_1h = max(so2["SO2"], default=-math.inf)
    if highest_1h >= 305 and max(so2["SO2_24h"], default=-math.inf) < 305:
        subs["SO2"] = max(200.0, subs.get("SO2", -math.inf))
    # 40 CFR 58 App G note 2: the 8-hour table does not define the index above 300
    if o3_beyond_table and "O3_1h" not in subs:
        return AQIResult(None, None, None, subs, "o3_beyond_table"), True
    if not subs:
        return AQIResult(None, None, None, subs, "no_sub_index"), False
    # Ties go to the first pollutant in US_POLLUTANTS order
    dominant = max(
        (name for name in US_POLLUTANTS if name in subs), key=lambda name: subs[name]
    )
    value = int(_round_half_up(subs[dominant]))  # the EPA rounds half up
    return AQIResult(value, us_aqi_category(value), dominant, subs), False


def _table_value(name: str, label: str, value: Optional[float]) -> float:
    """A concentration in the unit and precision of the table, or NaN if invalid."""
    if value is None or _missing(value) or value < 0:
        return math.nan
    p = US_POLLUTANTS[name]
    factor = unit_factor(split_label(str(label))[1], p.unit, p.molar_mass)
    scaled = float(value) * factor
    return scaled if math.isnan(scaled) else _truncate(scaled, p.decimals)


def _band_sub_index(name: str, c: float) -> float:
    """Sub-index of a table value; NaN if it is NaN or outside the table of name."""
    p = US_POLLUTANTS[name]
    last = len(p.bands) - 1
    for i, (c_lo, c_hi, i_lo, i_hi) in enumerate(p.bands):
        above = i == last and c > c_hi and name not in _NO_EXTRAPOLATION
        if c_lo <= c <= c_hi or above:
            return (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo
    # Below the table of 1-hour O3 or 24-hour SO2, the other average applies
    return math.nan


def _truncate(value: float, decimals: int) -> float:
    """Truncate to decimals; 1e-9 keeps 0.0549999... from a conversion at 0.055."""
    scale = 10.0**decimals
    return math.floor(value * scale + 1e-9) / scale
