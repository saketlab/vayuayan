#!/usr/bin/env python3
"""Dump the full CPCB station directory to parquet.

Source of truth is CPCB's master-data tables (via CPCBHistorical), which carry
district / address / pin_code / network_type on top of state, city and
coordinates. Live status (live flag + last_update) is merged in from the
real-time all-India feed. Sorted by state, district, city, station name.

    python scripts/dump_stations.py [out.parquet]
"""

import sys

import pandas as pd

from vayuayan import CPCBHistorical, CPCBLive

COLS = [
    "station_id", "station_name", "state", "district", "city",
    "address", "pin_code", "latitude", "longitude", "network_type",
    "state_code", "city_code", "live", "last_update",
]


def master_stations(c: CPCBHistorical) -> pd.DataFrame:
    """Every station across every state/city in the master-data tables."""
    rows = []
    for state in c._new_state_list():
        for city in c._new_city_list(str(state.get("state_code", ""))):
            rows.extend(c._new_station_list(str(city.get("city_code", ""))))
    return pd.DataFrame(rows).drop_duplicates(subset="station_id")


def live_status() -> pd.DataFrame:
    rows = []
    for city in CPCBLive().get_all_india():
        for st in city.get("stationsInCity", []):
            rows.append(
                {
                    "station_id": st.get("siteId") or st.get("id"),
                    "live": st.get("live"),
                    "last_update": st.get("lastUpdate"),
                }
            )
    return pd.DataFrame(rows).drop_duplicates(subset="station_id")


def build() -> pd.DataFrame:
    df = master_stations(CPCBHistorical()).merge(live_status(), on="station_id", how="left")
    for col in COLS:
        if col not in df.columns:
            df[col] = None
    df = df[COLS]
    return df.sort_values(
        ["state", "district", "city", "station_name"], na_position="last"
    ).reset_index(drop=True)


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "data/cpcb_stations.parquet"
    df = build()
    df.to_parquet(out, index=False)
    print(
        f"{len(df)} stations | {df['state'].nunique()} states | "
        f"{df['district'].nunique()} districts | {df['city'].nunique()} cities -> {out}"
    )


if __name__ == "__main__":
    main()
