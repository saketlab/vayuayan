#!/usr/bin/env python3
"""Dump full daily historical AQI for every CPCB station, all years, to parquet.

Walks every station in ``get_complete_list()``, enumerates available years via
``get_file_path()``, downloads each year's full Excel sheet, tags it with
station/city/year, and writes one parquet per station under ``--cache`` (so the
run is resumable -- a re-run skips stations already dumped). A final pass
concatenates everything into a single parquet.

    python scripts/dump_historical_aqi.py [out.parquet] [--cache DIR] [--frequency daily]

~489 stations x ~7 years = thousands of HTTP requests; expect a long run.
Uses ``_read_repository_excel`` directly (not the public download helper, which
caps each sheet at 31 rows -- unusable for a full-year dump).
"""

import argparse
import glob
import os
import time

import pandas as pd

from vayuayan import CPCBHistorical


def station_index(client: CPCBHistorical) -> list[dict]:
    """Flat list of {station_id, station_name, city} for every station."""
    stations = client.get_complete_list().get("stations", {})
    out = []
    for city, items in stations.items():
        for s in items:
            out.append(
                {
                    "station_id": s.get("value"),
                    "station_name": s.get("label"),
                    "city": str(city),
                }
            )
    return out


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Coerce mixed int/' ' object columns to numeric; keep real text as text.

    CPCB sheets pad empty cells with whitespace, so a numeric column arrives as
    object dtype and pyarrow refuses to serialize it. For each object column, try
    numeric: if every non-empty value parses, keep the numeric version.
    """
    for c in df.columns:
        if df[c].dtype != object:
            continue
        s = df[c].astype(str).str.strip().replace({"": None, "nan": None, "None": None})
        num = pd.Series(pd.to_numeric(s, errors="coerce"), index=df.index)
        df[c] = num if num.notna().sum() == s.notna().sum() else s
    return df


def dump_station(client: CPCBHistorical, st: dict, frequency: str) -> pd.DataFrame:
    """All available years for one station, concatenated and tagged."""
    paths = client.get_file_path(
        st["station_id"], st["station_name"], "", st["city"], "", frequency, "stationLevel"
    )
    frames = []
    for entry in paths:
        try:
            df = client._read_repository_excel(str(entry["filepath"]))  # ponytail: private, but public helper truncates to 31 rows
        except Exception as e:  # one bad sheet must not kill the station
            print(f"    ! {st['station_id']} {entry.get('year')}: {e}")
            continue
        df["year"] = entry.get("year")
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = _normalize(pd.concat(frames, ignore_index=True))
    out.insert(0, "city", st["city"])
    out.insert(0, "station_name", st["station_name"])
    out.insert(0, "station_id", st["station_id"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="cpcb_historical_aqi.parquet")
    ap.add_argument("--cache", default="cpcb_historical_parquet")
    ap.add_argument("--frequency", default="daily", choices=["daily", "hourly"])
    ap.add_argument("--sleep", type=float, default=0.2, help="delay between stations (s)")
    args = ap.parse_args()

    os.makedirs(args.cache, exist_ok=True)
    client = CPCBHistorical()
    stations = station_index(client)
    print(f"{len(stations)} stations")

    for i, st in enumerate(stations, 1):
        sid = st["station_id"]
        dest = os.path.join(args.cache, f"{sid}.parquet")
        if os.path.exists(dest):
            continue
        print(f"[{i}/{len(stations)}] {sid} {st['station_name']}")
        df = dump_station(client, st, args.frequency)
        # write even when empty, as a 0-row marker so re-runs skip it
        df.to_parquet(dest, index=False)
        time.sleep(args.sleep)

    # combine
    parts = [pd.read_parquet(f) for f in sorted(glob.glob(os.path.join(args.cache, "*.parquet")))]
    parts = [p for p in parts if len(p)]
    combined = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    combined.to_parquet(args.out, index=False)
    print(f"{len(combined)} rows, {combined['station_id'].nunique() if len(combined) else 0} stations -> {args.out}")


if __name__ == "__main__":
    main()
