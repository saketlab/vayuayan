"""
OAQ's daily records against the 15-minute readings of the same day.

OAQ serves a daily value per sensor (history/aggregates) and the 15-minute
readings of each day (history/daily). Since about March 2026 the daily value is
often the last reading of the day instead of its mean. These functions compare
the two; OAQClient.check_daily_records and audit_daily_records fetch the data.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pandas as pd

# OAQ's daily values have 2 decimals: equal means within half the last decimal
RECORD_TOLERANCE = 0.005

# Statistics of a day's readings that a daily record is compared with
RECORD_STATISTICS = ["mean", "last", "max", "median", "last_2_mean", "last_4_mean"]

RECORD_COLUMNS = (
    ["sensor_id", "date", "record", "n"]
    + RECORD_STATISTICS
    + [f"record_is_{s}" for s in RECORD_STATISTICS]
    + ["class"]
)


def compare_daily_records(
    readings: pd.DataFrame,
    records: pd.DataFrame,
    value: str = "pm25",
    tolerance: float = RECORD_TOLERANCE,
) -> pd.DataFrame:
    """Each daily record against statistics of the same day's readings.

    Args:
        readings: 15-minute readings (OAQClient.readings): sensor_id,
            timestamp and value.
        records: Daily records (OAQClient.daily_records): sensor_id, date and
            value.
        value: Parameter to compare.
        tolerance: Values within it count as equal (0.005: the daily records
            have 2 decimals).

    Returns:
        DataFrame with RECORD_COLUMNS, one row per sensor-day with a record
        and readings: the record, the number of readings, the mean, last,
        maximum and median reading, the mean of the last 2 and last 4
        readings, record_is_<statistic> for each, and class: "mean", "last",
        "both" (equal to the mean and to the last reading) or "neither".
        Missing and NaN readings are left out.
    """
    import pandas as pd

    r = readings.dropna(subset=["timestamp", value]).sort_values(
        ["sensor_id", "timestamp"], kind="stable"
    )
    if r.empty:
        return pd.DataFrame(columns=RECORD_COLUMNS)
    r = r.assign(date=r["timestamp"].dt.date)
    by_day = r.groupby(["sensor_id", "date"])[value]
    stats = pd.DataFrame(
        {
            "n": by_day.size(),
            "mean": by_day.mean(),
            "last": by_day.last(),
            "max": by_day.max(),
            "median": by_day.median(),
            "last_2_mean": by_day.apply(lambda v: v.tail(2).mean()),
            "last_4_mean": by_day.apply(lambda v: v.tail(4).mean()),
        }
    ).reset_index()
    rec = records[["sensor_id", "date", value]].rename(columns={value: "record"})
    out = rec.dropna(subset=["record"]).merge(stats, on=["sensor_id", "date"])
    for stat in RECORD_STATISTICS:
        out[f"record_is_{stat}"] = (out["record"] - out[stat]).abs() <= tolerance
    out["class"] = "neither"
    out.loc[out["record_is_mean"], "class"] = "mean"
    out.loc[out["record_is_last"], "class"] = "last"
    out.loc[out["record_is_mean"] & out["record_is_last"], "class"] = "both"
    out = out.sort_values(["sensor_id", "date"], kind="stable")
    return out[RECORD_COLUMNS].reset_index(drop=True)


def daily_record_summary(audit: pd.DataFrame, min_gap: float = 1) -> pd.DataFrame:
    """When each sensor's daily records changed from the mean to the last reading.

    Only days whose mean and last reading differ by more than min_gap count,
    so that a record cannot match both by chance.

    Args:
        audit: compare_daily_records or OAQClient.audit_daily_records output,
            optionally with a provider column.
        min_gap: Smallest difference between the mean and the last reading.

    Returns:
        DataFrame with (provider,) sensor_id, year, days, clear_days, and of
        those mean, last and neither (days the record equals each), the first
        day equal to only the last reading (first_last_day) and the last day
        equal to only the mean before it (last_mean_day).
    """
    import pandas as pd

    keys = (["provider"] if "provider" in audit else []) + ["sensor_id", "year"]
    a = audit.assign(year=pd.to_datetime(audit["date"]).dt.year)
    clear = a[(a["mean"] - a["last"]).abs() > min_gap]
    rows = []
    for key, g in a.groupby(keys, sort=True):
        c = clear.merge(pd.DataFrame([dict(zip(keys, key))]), on=keys)
        last_days = c.loc[c["class"] == "last", "date"]
        first_last = last_days.min() if len(last_days) else None
        mean_days = c.loc[c["class"] == "mean", "date"]
        if first_last is not None:
            mean_days = mean_days[mean_days < first_last]
        rows.append(
            {
                **dict(zip(keys, key)),
                "days": len(g),
                "clear_days": len(c),
                "mean": int((c["class"] == "mean").sum()),
                "last": int((c["class"] == "last").sum()),
                "neither": int((c["class"] == "neither").sum()),
                "last_mean_day": mean_days.max() if len(mean_days) else None,
                "first_last_day": first_last,
            }
        )
    columns = keys + ["days", "clear_days", "mean", "last", "neither",
                      "last_mean_day", "first_last_day"]  # fmt: skip
    return pd.DataFrame(rows, columns=columns)
