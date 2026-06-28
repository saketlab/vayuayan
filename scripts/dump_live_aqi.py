#!/usr/bin/env python3
"""Fetch current live AQI for every CPCB station in India and write a parquet.

Output: a tidy long-format table, one row per (station, pollutant) reading.

    python scripts/dump_live_aqi.py [out.parquet]
"""

import sys

import pandas as pd

from vayuayan import CPCBLive


def fetch_live_long() -> pd.DataFrame:
    cities = CPCBLive().get_all_india()
    rows = []
    for city in cities:
        for st in city.get("stationsInCity", []):
            base = {
                "state": city.get("stateID"),
                "city": city.get("cityName"),
                "station_id": st.get("siteId") or st.get("id"),
                "station_name": st.get("stationName") or st.get("name"),
                "latitude": st.get("latitude"),
                "longitude": st.get("longitude"),
                "live": st.get("live"),
                "last_update": st.get("lastUpdate"),
            }
            pollutants = st.get("pollutants") or []
            if not pollutants:
                rows.append({**base, "pollutant": None})
                continue
            for p in pollutants:
                rows.append(
                    {
                        **base,
                        "pollutant": p.get("indexId"),
                        "min": p.get("min"),
                        "max": p.get("max"),
                        "avg": p.get("avg"),
                        "hourly_sub_index": p.get("Hourly_sub_index"),
                    }
                )
    return pd.DataFrame(rows)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "cpcb_live_aqi.parquet"
    df = fetch_live_long()
    df.to_parquet(out, index=False)
    print(f"{len(df)} rows, {df['station_id'].nunique()} stations -> {out}")


if __name__ == "__main__":
    main()
