#!/usr/bin/env python3
"""
Command-line interface for vayuayan package
"""

import argparse
import sys
from datetime import datetime

from . import CPCBHistorical, CPCBLive, PM25Client
from .commands import (get_city_data, get_city_list, get_live_aqi,
                       get_nearest_station, get_pm25_data, get_state_list,
                       get_station_data, get_station_list, locate_me)


def main():
    """Main CLI entry point"""
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

  vayuayan locate_me                       # Return lat, lon based on IP
  vayuayan nearest_station                 # Uses IP-based geolocation
  vayuayan nearest_station --lat 19.0760 --lon 72.8777
  vayuayan live_aqi --date 2024-02-25 --hour 10 --path "output.json"   # Uses IP-based geolocation
  vayuayan live_aqi --lat 19.0760 --lon 72.8777 --path "output.json"
  vayuayan live_aqi --station_id "site_5964" --path "output.json"

  For PM2.5 data:
  vayuayan pm25 --geojson_path "districts.geojson" --year 2019 --month 2
  vayuayan pm25 --geojson_path "districts.geojson" --year 2019 --month 2 --group_by state_name
  vayuayan pm25 --geojson_path "districts.geojson" --year 2019 --month 2 --group_by state_name,district_name
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    ## ------------------------------ AQI Commands ------------------------------ ##
    # List states command
    list_states_parser = subparsers.add_parser("list_states", help="List all states")

    # List cities command
    list_cities_parser = subparsers.add_parser(
        "list_cities", help="List all cities in a state"
    )
    list_cities_parser.add_argument("state", help="State name")

    # List stations command
    list_stations_parser = subparsers.add_parser(
        "list_stations", help="List all stations in a city"
    )
    list_stations_parser.add_argument("city", help="City name")

    # City data command
    city_data_parser = subparsers.add_parser(
        "city_data", help="Get city-level AQI data"
    )
    city_data_parser.add_argument("--city", required=True, help="City name")
    city_data_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Year (default: current year)",
    )
    city_data_parser.add_argument("--path", required=True, help="Path to output file")

    # Station data command
    station_data_parser = subparsers.add_parser(
        "station_data", help="Get station-level AQI data"
    )
    station_data_parser.add_argument("--station_id", required=True, help="Station ID")
    station_data_parser.add_argument(
        "--year",
        type=int,
        default=datetime.now().year,
        help="Year (default: current year)",
    )
    station_data_parser.add_argument(
        "--path", required=True, help="Path to output file"
    )

    ## ------------------------------ Live AQI Commands ------------------------------ ##
    locate_me_parser = subparsers.add_parser(
        "locate_me", help="Fetch current geolocation based on IP address"
    )
    nearest_station_parser = subparsers.add_parser(
        "nearest_station",
        help="Fetch nearest station details using IP-based geolocation or provided coordinates",
    )
    nearest_station_parser.add_argument(
        "--lat", type=float, help="Latitude of geolocation"
    )
    nearest_station_parser.add_argument(
        "--lon", type=float, help="Longitude of geolocation"
    )

    live_aqi_parser = subparsers.add_parser(
        "live_aqi", help="Fetch live AQI data for nearest station or specified station"
    )
    live_aqi_parser.add_argument("--lat", type=float, help="Latitude of geolocation")
    live_aqi_parser.add_argument("--lon", type=float, help="Longitude of geolocation")
    live_aqi_parser.add_argument(
        "--station_id", help="Station ID for specific station data"
    )
    live_aqi_parser.add_argument(
        "--date", type=str, help="Date for the AQI data (format: YYYY-MM-DD)"
    )
    live_aqi_parser.add_argument(
        "--hour", type=int, help="Hour for the AQI data (0-23)"
    )
    live_aqi_parser.add_argument("--path", help="Path to output file")

    ## ------------------------------ PM2.5 Commands ------------------------------ ##
    pm25_parser = subparsers.add_parser(
        "pm25", help="Fetch PM2.5 data for given geographic polygon"
    )
    pm25_parser.add_argument(
        "--geojson_path", required=True, help="Path to the GeoJSON file with polygon"
    )
    pm25_parser.add_argument(
        "--year", type=int, required=True, help="Year of the netCDF data"
    )
    pm25_parser.add_argument(
        "--month",
        type=int,
        help="Month of the data (1-12), if not provided, annual data is used",
    )
    pm25_parser.add_argument(
        "--group_by",
        type=str,
        help="Column name(s) to group polygons by. Can be a single column (e.g., 'state_name') or comma-separated multiple columns (e.g., 'state_name,district_name').",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize client
    aqi_client = CPCBHistorical()
    live_aqi_client = CPCBLive()
    pm25_client = PM25Client()

    # Execute command
    try:
        if args.command == "list_states":
            get_state_list(aqi_client)
        elif args.command == "list_cities":
            get_city_list(aqi_client, args.state)
        elif args.command == "list_stations":
            get_station_list(aqi_client, args.city)
        elif args.command == "city_data":
            get_city_data(aqi_client, args.city, args.year, args.path)
        elif args.command == "station_data":
            get_station_data(aqi_client, args.station_id, args.year, args.path)

        elif args.command == "locate_me":
            locate_me(live_aqi_client)
        elif args.command == "nearest_station":
            get_nearest_station(live_aqi_client, args.lat, args.lon)
        elif args.command == "live_aqi":
            get_live_aqi(
                live_aqi_client,
                args.lat,
                args.lon,
                args.station_id,
                args.date,
                args.hour,
                args.path,
            )

        elif args.command == "pm25":
            get_pm25_data(
                pm25_client, args.geojson_path, args.year, args.month, args.group_by
            )

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
