#!/usr/bin/env python3
"""Data-completeness report for the long CPCB historical parquet.

Measures coverage against the ideal of one AQI reading per station per calendar
day, and lists which stations/years are missing. Writes a markdown report.

    python scripts/historical_completeness_report.py [long.parquet] [report.md]
"""

import sys

import pandas as pd

# stations that exist in the live network but returned zero historical sheets
# are not in the long table; pass the wide dump's station universe to count them
WIDE_DEFAULT = "data/cpcb_historical_aqi.parquet"


def days_in_year(y: int) -> int:
    return 366 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 365


def build_report(long: pd.DataFrame) -> str:
    long = long.copy()
    long["y"] = long["date"].dt.year
    years = sorted(long["y"].unique())
    L = []
    w = L.append

    w("# CPCB Historical AQI — Data Completeness Report\n")
    w(f"- Rows (station-days with a reading): **{len(long):,}**")
    w(f"- Stations with any data: **{long['station_id'].nunique()}**")
    w(f"- Cities: **{long['city'].nunique()}**")
    w(f"- Date span: **{long['date'].min().date()} → {long['date'].max().date()}**")
    w(f"- Years: **{years[0]}–{years[-1]}** ({len(years)} years)\n")

    # per-year coverage
    w("## Per-year coverage\n")
    w("| Year | Stations | Readings | Days/station (mean) | Completeness vs full year |")
    w("|---|---|---|---|---|")
    for y in years:
        g = long[long["y"] == y]
        nst = g["station_id"].nunique()
        readings = len(g)
        per = g.groupby("station_id")["date"].nunique()
        mean_days = per.mean()
        pct = 100 * mean_days / days_in_year(y)
        w(f"| {y} | {nst} | {readings:,} | {mean_days:.0f} | {pct:.0f}% |")
    w("")

    # years-per-station distribution
    w("## Years observed per station\n")
    yps = long.groupby("station_id")["y"].nunique()
    w("| # years | # stations |")
    w("|---|---|")
    for k, v in yps.value_counts().sort_index().items():
        w(f"| {k} | {v} |")
    w("")

    # station-year completeness: how full is each station-year that exists
    w("## Station-year completeness (only station-years that have data)\n")
    sy = long.groupby(["station_id", "y"])["date"].nunique().reset_index(name="days")
    sy["full"] = sy["y"].map(days_in_year)
    sy["pct"] = 100 * sy["days"] / sy["full"]
    buckets = pd.cut(
        sy["pct"], [0, 25, 50, 75, 90, 100.01],
        labels=["0-25%", "25-50%", "50-75%", "75-90%", "90-100%"], include_lowest=True,
    )
    w("| Coverage bucket | # station-years |")
    w("|---|---|")
    for k, v in buckets.value_counts().sort_index().items():
        w(f"| {k} | {v} |")
    w(f"\n- Total station-years present: **{len(sy):,}**")
    w(f"- Median station-year completeness: **{sy['pct'].median():.0f}%**")
    w(f"- Mean station-year completeness: **{sy['pct'].mean():.0f}%**\n")

    # worst-covered station-years
    w("## 15 least-complete station-years\n")
    worst = sy.sort_values("pct").head(15)
    w("| Station | Year | Days | Completeness |")
    w("|---|---|---|---|")
    for _, r in worst.iterrows():
        w(f"| {r['station_id']} | {r['y']} | {int(r['days'])} | {r['pct']:.0f}% |")
    w("")
    return "\n".join(L)


def stations_without_history(long: pd.DataFrame, wide_path: str) -> str:
    try:
        wide = pd.read_parquet(wide_path, columns=["station_id"])
    except Exception:
        return ""
    have = set(long["station_id"].unique())
    wide_ids = set(wide["station_id"].unique())
    empty = wide_ids - have
    return (
        f"\n## Coverage gaps\n\n"
        f"- Station IDs in wide dump: **{len(wide_ids)}**\n"
        f"- Station IDs with at least one daily reading: **{len(have)}**\n"
        f"- Station-IDs present in wide dump but with no usable readings: **{len(empty)}**\n"
    )


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "data/cpcb_historical_aqi_long.parquet"
    out = sys.argv[2] if len(sys.argv) > 2 else "data/cpcb_historical_completeness.md"
    long = pd.read_parquet(src)
    report = build_report(long) + stations_without_history(long, WIDE_DEFAULT)
    with open(out, "w") as f:
        f.write(report + "\n")
    print(f"wrote {out}")
    print(report)


if __name__ == "__main__":
    main()
