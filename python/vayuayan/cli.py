#!/usr/bin/env python3
"""
Command-line interface of the vayuayan package
"""

import argparse
import logging
import sys
from datetime import datetime

from . import CPCBHistorical, CPCBLive, PM25Client
from .commands import (
    get_city_data,
    get_city_list,
    get_daily_aqi,
    get_live_aqi,
    get_nearest_station,
    get_pm25_data,
    get_state_list,
    get_station_data,
    get_station_list,
    locate_me,
)
from .pm25_versions import PM25_VERSIONS

STATION_HELP = (
    "Station ID, name, or part of a name (e.g. site_301 or 'Anand Vihar, Delhi')"
)


def main() -> None:
    """Entry point of the CLI"""
    parser = argparse.ArgumentParser(
        description="vayuayan CLI - Get air quality monitoring data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  vayuayan list_states
  vayuayan list_cities "Maharashtra"
  vayuayan list_stations "Mumbai"
  vayuayan city_data --city "Mumbai" --year 2024 --path "output.json"
  vayuayan station_data --station_id "site_5964" --year 2024 --path "output.json"
  vayuayan daily_aqi --station_id "site_301" --year 2024 --path "daily_aqi.csv"
  vayuayan station_data --station "Anand Vihar, Delhi" --year 2024 --path "output.csv"

  vayuayan locate_me
  vayuayan nearest_station --lat 19.0760 --lon 72.8777
  vayuayan live_aqi --station_id "site_5964" --path "output.json"
  vayuayan live_aqi --date 2024-02-25 --hour 10 --path "output.json"
  vayuayan live_aqi --lat 19.0760 --lon 72.8777 --path "output.json"

  vayuayan pm25 --geojson_path "districts.geojson" --year 2019 --month 2
  vayuayan pm25 --geojson_path "districts.geojson" --year 2019 --month 2 \
      --group_by state_name
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Arguments that several commands share
    year_arg = argparse.ArgumentParser(add_help=False)
    year_arg.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Year (default: current year)",
    )
    coords_arg = argparse.ArgumentParser(add_help=False)
    coords_arg.add_argument("--lat", type=float, help="Latitude of geolocation")
    coords_arg.add_argument("--lon", type=float, help="Longitude of geolocation")

    # Each command builds only the client it needs: PM25Client may start
    # Earth Engine, and the clients make network sessions.
    # ------------------------------ AQI Commands ------------------------------ #
    subparsers.add_parser("list_states", help="List all states").set_defaults(
        run=lambda a: get_state_list(CPCBHistorical())
    )

    cmd = subparsers.add_parser("list_cities", help="List all cities in a state")
    cmd.add_argument("state", help="State name")
    cmd.set_defaults(run=lambda a: get_city_list(CPCBHistorical(), a.state))

    cmd = subparsers.add_parser("list_stations", help="List all stations in a city")
    cmd.add_argument("city", help="City name")
    cmd.set_defaults(run=lambda a: get_station_list(CPCBHistorical(), a.city))

    cmd = subparsers.add_parser(
        "city_data", help="Get city-level AQI data", parents=[year_arg]
    )
    cmd.add_argument("--city", required=True, help="City name")
    cmd.add_argument("--path", required=True, help="Path to output file")
    cmd.set_defaults(
        run=lambda a: get_city_data(CPCBHistorical(), a.city, a.year, a.path)
    )

    cmd = subparsers.add_parser(
        "station_data", help="Get station-level AQI data", parents=[year_arg]
    )
    cmd.add_argument(
        "--station", "--station_id", dest="station_id", required=True, help=STATION_HELP
    )
    cmd.add_argument("--path", required=True, help="Path to output file")
    cmd.set_defaults(
        run=lambda a: get_station_data(CPCBHistorical(), a.station_id, a.year, a.path)
    )

    cmd = subparsers.add_parser(
        "daily_aqi",
        help="Compute the daily National AQI of a station from its raw data",
        parents=[year_arg],
    )
    cmd.add_argument(
        "--station", "--station_id", dest="station_id", required=True, help=STATION_HELP
    )
    cmd.add_argument("--path", help="CSV file for the daily table")
    cmd.add_argument(
        "--bulletin",
        action="store_true",
        help="Days end at 4 PM, like CPCB's daily bulletin (default: calendar days)",
    )
    cmd.set_defaults(
        run=lambda a: get_daily_aqi(
            CPCBHistorical(), a.station_id, a.year, a.path, a.bulletin
        )
    )

    # ------------------------------ Live AQI Commands ------------------------------ #
    subparsers.add_parser(
        "locate_me", help="Fetch current geolocation based on IP address"
    ).set_defaults(run=lambda a: locate_me(CPCBLive()))

    subparsers.add_parser(
        "nearest_station",
        help=(
            "Fetch nearest station details using IP-based geolocation or "
            "provided coordinates"
        ),
        parents=[coords_arg],
    ).set_defaults(run=lambda a: get_nearest_station(CPCBLive(), a.lat, a.lon))

    cmd = subparsers.add_parser(
        "live_aqi",
        help="Fetch live AQI data for nearest station or specified station",
        parents=[coords_arg],
    )
    cmd.add_argument("--station", "--station_id", dest="station_id", help=STATION_HELP)
    cmd.add_argument("--date", type=str, help="Date for the AQI data (YYYY-MM-DD)")
    cmd.add_argument("--hour", type=int, help="Hour for the AQI data (0-23)")
    cmd.add_argument("--path", help="Path to output file")
    cmd.set_defaults(
        run=lambda a: get_live_aqi(
            CPCBLive(), a.lat, a.lon, a.station_id, a.date, a.hour, a.path
        )
    )

    # ------------------------------ PM2.5 Commands ------------------------------ #
    cmd = subparsers.add_parser(
        "pm25", help="Fetch PM2.5 data for given geographic polygon"
    )
    cmd.add_argument(
        "--geojson_path", required=True, help="Path to the GeoJSON file with polygon"
    )
    cmd.add_argument("--year", type=int, required=True, help="Year of the data")
    cmd.add_argument(
        "--month",
        type=int,
        help="Month of the data (1-12), if not provided, annual data is used",
    )
    cmd.add_argument(
        "--group_by",
        type=str,
        help=(
            "Column name(s) to group polygons by. Can be a single column "
            "(e.g., 'state_name') or comma-separated multiple columns "
            "(e.g., 'state_name,district_name')."
        ),
    )
    cmd.add_argument(
        "--version",
        type=str,
        choices=list(PM25_VERSIONS),
        default="V6GL03",
        help="Dataset version (default: V6GL03): "
        + ", ".join(
            f"{key} = {v.name}, {v.year_range[0]}-{v.year_range[1]}"
            for key, v in PM25_VERSIONS.items()
        ),
    )
    cmd.set_defaults(
        run=lambda a: get_pm25_data(
            PM25Client(version=a.version),
            a.geojson_path,
            a.year,
            a.month,
            a.group_by,
        )
    )

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # The library logs progress at INFO level; print it like the CLI output
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        ok = args.run(args)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Unexpected error: {e}")
        sys.exit(1)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
