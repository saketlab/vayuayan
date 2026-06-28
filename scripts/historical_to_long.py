#!/usr/bin/env python3
"""Convert the wide CPCB historical dump to tidy long format.

Input is the wide parquet from ``dump_historical_aqi.py``: one row per
(station, year, day-of-month) with 12 month columns holding the daily AQI.
This melts the month columns into a real ``date`` and one ``aqi`` value per row,
drops impossible dates (e.g. 31 February) and empty readings, and sorts by
year, date, station_name, station_id.

    python scripts/historical_to_long.py [in.parquet] [out.parquet]
"""

import sys

import pandas as pd

MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11, "December": 12,
}


def to_long(wide: pd.DataFrame) -> pd.DataFrame:
    wide = wide.copy()
    # day-of-month column is "Day" in 2024 sheets but "Date" in <=2023 sheets
    cands = [pd.Series(pd.to_numeric(wide[c], errors="coerce")) for c in ("Day", "Date") if c in wide.columns]
    day = cands[0]
    for nxt in cands[1:]:
        day = day.fillna(nxt)
    wide["Day"] = day
    wide = wide[wide["Day"].between(1, 31)]

    id_cols = ["station_id", "station_name", "city", "year", "Day"]
    long = wide.melt(
        id_vars=id_cols,
        value_vars=list(MONTHS),
        var_name="month_name",
        value_name="aqi",
    )
    long["aqi"] = pd.to_numeric(long["aqi"], errors="coerce")
    long = long.dropna(subset=["aqi"])

    long["month"] = long["month_name"].map(MONTHS)
    long["date"] = pd.to_datetime(
        dict(
            year=long["year"].astype(int),
            month=long["month"],
            day=long["Day"].astype(int),
        ),
        errors="coerce",
    )
    long = long.dropna(subset=["date"])  # kills 31 Feb etc.

    long = long[["station_id", "station_name", "city", "year", "date", "aqi"]]
    long = long.sort_values(
        ["year", "date", "station_name", "station_id"], kind="stable"
    ).reset_index(drop=True)
    return long


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "cpcb_historical_aqi.parquet"
    out = sys.argv[2] if len(sys.argv) > 2 else "cpcb_historical_aqi_long.parquet"
    long = to_long(pd.read_parquet(src))
    long.to_parquet(out, index=False)
    print(
        f"{len(long)} rows, {long['station_id'].nunique()} stations, "
        f"{long['date'].min().date()}..{long['date'].max().date()} -> {out}"
    )


if __name__ == "__main__":
    main()
