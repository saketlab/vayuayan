"""
Quality checks of air sensor readings: completeness, plausibility, precision
of collocated sensors, accuracy against a reference, and humidity effects.

The targets are those of the US EPA for PM2.5 sensors: Duvall et al. (2021),
"Performance Testing Protocols, Metrics, and Target Values for Fine
Particulate Matter Air Sensors", EPA/600/R-20/280.
"""

from __future__ import annotations

import math
from datetime import date
from typing import TYPE_CHECKING, Any, Dict, Iterable, Optional, Sequence, Union

if TYPE_CHECKING:
    import pandas as pd

# US EPA target values for PM2.5 sensors (Duvall et al., 2021)
EPA_PM25_TARGETS: Dict[str, Any] = {
    "completeness": 0.75,  # share of readings for a valid 24-hour average
    "sd": 5.0,  # precision: SD across collocated sensors, µg/m³
    "cv_pct": 30.0,  # precision: CV across collocated sensors, %
    "slope": (0.65, 1.35),
    "intercept": (-5.0, 5.0),  # µg/m³
    "r2": 0.70,
    "rmse": 7.0,  # µg/m³
    "nrmse_pct": 30.0,
}

READINGS_PER_DAY = 96  # 15-minute readings
HUMIDITY_BREAKS = (0, 40, 50, 60, 70, 80, 90, 100)


def readings_mean(
    readings: pd.DataFrame,
    value: str = "pm25",
    by: str = "day",
    min_readings: Optional[int] = None,
    id_col: str = "sensor_id",
    time_col: str = "timestamp",
) -> pd.DataFrame:
    """Daily or hourly means of 15-minute readings.

    Args:
        readings: One row per reading, such as OAQClient.readings or
            cpcb_raw_to_long (with id_col="station_id", value="value").
        value: Column to average.
        by: "day" or "hour".
        min_readings: Fewest readings for a mean. The default is 75 % of the
            15-minute readings of the period (72 a day, 3 an hour), the EPA
            completeness rule.

    Returns:
        DataFrame with id_col, "date" (datetime.date) or "hour" (Timestamp),
        value and n (number of readings), for the periods with enough readings.
    """
    if by not in ("day", "hour"):
        raise ValueError('by must be "day" or "hour"')
    per = READINGS_PER_DAY if by == "day" else READINGS_PER_DAY // 24
    if min_readings is None:
        need = math.ceil(EPA_PM25_TARGETS["completeness"] * per)
    else:
        need = min_readings
    df = readings[[id_col, time_col, value]].dropna(subset=[time_col, value])
    period = df[time_col].dt.date if by == "day" else df[time_col].dt.floor("h")
    key = "date" if by == "day" else "hour"
    out = (
        df.assign(**{key: period})
        .groupby([id_col, key])[value]
        .agg(["mean", "size"])
        .reset_index()
        .rename(columns={"mean": value, "size": "n"})
    )
    return out[out["n"] >= need].reset_index(drop=True)


def sensor_completeness(
    readings: pd.DataFrame,
    start: Union[str, date],
    end: Union[str, date],
    value: str = "pm25",
    ids: Optional[Iterable[str]] = None,
    id_col: str = "sensor_id",
    time_col: str = "timestamp",
) -> pd.DataFrame:
    """Share of the expected 15-minute readings, and of valid days, per sensor.

    Args:
        readings: One row per reading.
        start, end: First and last day of the period (inclusive).
        value: Column that must have a value.
        ids: Sensors to report, also those without readings. Default: the
            sensors in readings.

    Returns:
        DataFrame with id_col, readings_pct, valid_days (days with 75 % of the
        readings) and valid_days_pct, sorted by id_col.
    """
    import pandas as pd

    days = pd.date_range(start, end).date
    df = readings.dropna(subset=[time_col, value])
    df = df[(df[time_col].dt.date >= days[0]) & (df[time_col].dt.date <= days[-1])]
    per_day = df.groupby([id_col, df[time_col].dt.date]).size()
    need = math.ceil(EPA_PM25_TARGETS["completeness"] * READINGS_PER_DAY)
    ids = sorted(set(df[id_col]) if ids is None else set(ids))
    total = per_day.groupby(level=0).sum().reindex(ids, fill_value=0)
    valid = (per_day >= need).groupby(level=0).sum().reindex(ids, fill_value=0)
    out = pd.DataFrame(
        {
            id_col: ids,
            "readings_pct": 100 * total.to_numpy() / (READINGS_PER_DAY * len(days)),
            "valid_days": valid.to_numpy().astype(int),
        }
    )
    out["valid_days_pct"] = 100 * out["valid_days"] / len(days)
    return out


def sensor_plausibility(
    readings: pd.DataFrame,
    value: str = "pm25",
    max_value: float = 1000,
    stuck_run: int = 8,
    spike_factor: float = 10,
    spike_min: float = 100,
    spike_window: int = 9,
    id_col: str = "sensor_id",
    time_col: str = "timestamp",
) -> pd.DataFrame:
    """Screening flags of implausible readings, per sensor.

    These are screening rules, not EPA targets: a flag marks readings to
    examine, not proof of a fault.

    Args:
        readings: One row per reading.
        value: Column to check, such as "pm25" or "temp".
        max_value: Readings above it are flagged.
        stuck_run: Runs of at least this many equal consecutive readings are
            flagged as stuck (8 readings are 2 hours).
        spike_factor, spike_min: A reading above spike_factor times the
            median of the spike_window readings around it, and above
            spike_min, is a spike.
        spike_window: Readings in the centred window (odd); the median needs
            at least half of them.

    Returns:
        DataFrame with id_col, readings, negative_pct, zero_pct,
        above_max_pct, stuck_pct and spikes_pct (shares of the readings, %).
    """
    import pandas as pd

    rows = []
    for sensor, g in readings.dropna(subset=[time_col, value]).groupby(id_col):
        v = g.sort_values(time_col, kind="stable")[value].reset_index(drop=True)
        run = v.groupby((v != v.shift()).cumsum()).transform("size")
        around = v.rolling(spike_window, center=True, min_periods=spike_window // 2 + 1)
        spikes = (v > spike_factor * around.median()) & (v > spike_min)
        rows.append(
            {
                id_col: sensor,
                "readings": len(v),
                "negative_pct": 100 * (v < 0).mean(),
                "zero_pct": 100 * (v == 0).mean(),
                "above_max_pct": 100 * (v > max_value).mean(),
                "stuck_pct": 100 * (run >= stuck_run).mean(),
                "spikes_pct": 100 * spikes.mean(),
            }
        )
    columns = [id_col, "readings", "negative_pct", "zero_pct", "above_max_pct",
               "stuck_pct", "spikes_pct"]  # fmt: skip
    return pd.DataFrame(rows, columns=columns)


def collocated_precision(
    daily: pd.DataFrame,
    value: str = "pm25",
    min_sensors: int = 3,
    date_col: str = "date",
) -> pd.DataFrame:
    """Spread across collocated sensors on each day, as in the EPA protocol.

    Args:
        daily: Daily means of sensors at one place (readings_mean).
        min_sensors: Fewest sensors with a mean on a day.

    Returns:
        DataFrame with date_col, sensors, mean, sd (sample standard deviation
        across the sensors) and cv_pct, per day with enough sensors.
    """
    g = daily.dropna(subset=[value]).groupby(date_col)[value]
    out = g.agg(sensors="size", mean="mean", sd="std").reset_index()
    out["cv_pct"] = 100 * out["sd"] / out["mean"]
    return out[out["sensors"] >= min_sensors].reset_index(drop=True)


def peer_ratio(
    daily: pd.DataFrame,
    value: str = "pm25",
    min_sensors: int = 3,
    tolerance: float = 0.3,
    id_col: str = "sensor_id",
    date_col: str = "date",
) -> pd.DataFrame:
    """How far each collocated sensor departs from the others.

    On days with at least min_sensors sensors, each sensor's mean over the
    median of the other sensors.

    Returns:
        DataFrame with id_col, days, median_ratio and within_pct (days within
        ±tolerance of the others, %), sorted by median_ratio.
    """
    import pandas as pd

    wide = daily.pivot_table(index=date_col, columns=id_col, values=value)
    wide = wide[wide.notna().sum(axis=1) >= min_sensors]
    rows = []
    for sensor in wide.columns:
        ratio = (wide[sensor] / wide.drop(columns=sensor).median(axis=1)).dropna()
        rows.append(
            {
                id_col: sensor,
                "days": len(ratio),
                "median_ratio": ratio.median(),
                "within_pct": 100 * ((ratio - 1).abs() <= tolerance).mean(),
            }
        )
    out = pd.DataFrame(rows, columns=[id_col, "days", "median_ratio", "within_pct"])
    return out.sort_values(["median_ratio", id_col], kind="stable").reset_index(
        drop=True
    )


def sensor_accuracy(
    paired: pd.DataFrame,
    sensor: str = "pm25",
    reference: str = "reference",
    min_days: int = 30,
    id_col: str = "sensor_id",
) -> pd.DataFrame:
    """Accuracy of each sensor against a reference, with the EPA targets.

    Args:
        paired: One row per sensor and day with the sensor and the reference
            daily means.
        min_days: Fewest paired days for a sensor to be reported.

    Returns:
        DataFrame with id_col, days, slope and intercept (least squares of
        sensor on reference), r2, rmse, nrmse_pct (RMSE over the mean
        reference value), the targets met (slope_ok, intercept_ok, r2_ok,
        error_ok: RMSE or NRMSE) and targets_met (0 to 4).
    """
    import pandas as pd

    t = EPA_PM25_TARGETS
    rows = []
    for sid, g in paired.dropna(subset=[sensor, reference]).groupby(id_col):
        if len(g) < min_days:
            continue
        x, y = g[reference], g[sensor]
        slope = ((x - x.mean()) * (y - y.mean())).sum() / ((x - x.mean()) ** 2).sum()
        rmse = float(((y - x) ** 2).mean() ** 0.5)
        row = {
            id_col: sid,
            "days": len(g),
            "slope": slope,
            "intercept": y.mean() - slope * x.mean(),
            "r2": x.corr(y) ** 2,
            "rmse": rmse,
            "nrmse_pct": 100 * rmse / x.mean(),
        }
        row["slope_ok"] = t["slope"][0] <= row["slope"] <= t["slope"][1]
        row["intercept_ok"] = t["intercept"][0] <= row["intercept"] <= t["intercept"][1]
        row["r2_ok"] = row["r2"] >= t["r2"]
        row["error_ok"] = rmse <= t["rmse"] or row["nrmse_pct"] <= t["nrmse_pct"]
        row["targets_met"] = sum(
            row[k] for k in ("slope_ok", "intercept_ok", "r2_ok", "error_ok")
        )
        rows.append(row)
    columns = [id_col, "days", "slope", "intercept", "r2", "rmse", "nrmse_pct",
               "slope_ok", "intercept_ok", "r2_ok", "error_ok", "targets_met"]  # fmt: skip
    return pd.DataFrame(rows, columns=columns)


def ratio_by_humidity(
    hourly: pd.DataFrame,
    sensor: str = "sensor",
    reference: str = "reference",
    rh: str = "rh",
    breaks: Sequence[float] = HUMIDITY_BREAKS,
    min_reference: float = 5,
) -> pd.DataFrame:
    """Sensor-to-reference ratio by band of relative humidity.

    Low-cost optical sensors can read high in humid air. Hours with a
    reference value below min_reference are left out, as the ratio is
    unstable there.

    Returns:
        DataFrame with band ("40-50" for 40 < RH <= 50), hours, median_ratio,
        q25 and q75, one row per band with hours.
    """
    import pandas as pd

    df = hourly.dropna(subset=[sensor, reference, rh])
    df = df[df[reference] >= min_reference]
    labels = [f"{lo:g}-{hi:g}" for lo, hi in zip(breaks[:-1], breaks[1:])]
    band = pd.cut(df[rh], list(breaks), labels=labels)
    ratio = (df[sensor] / df[reference]).groupby(band, observed=True)
    out = pd.DataFrame(
        {
            "hours": ratio.size(),
            "median_ratio": ratio.median(),
            "q25": ratio.quantile(0.25),
            "q75": ratio.quantile(0.75),
        }
    )
    out.index = out.index.astype(str)
    return out.rename_axis("band").reset_index()
