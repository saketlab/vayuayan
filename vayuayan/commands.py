"""
Command functions for vayuayan CLI.
"""

import json
from pathlib import Path
from typing import Optional

from .air_quality_client import CPCBHistorical, CPCBLive, PM25Client


def _print_error(message: str) -> None:
    """Print a formatted error message.

    Args:
        message: The error message to display.
    """
    print(f"Error: {message}")


def _print_list_items(title: str, items: list) -> None:
    """Print a formatted list of items.

    Args:
        title: The title to display above the list.
        items: List of items to display.
    """
    print(f"{title}:")
    for item in items:
        print(f" - {item}")


def get_state_list(client: CPCBHistorical) -> bool:
    """Display list of states available for AQI data.

    Args:
        client: The AQI client instance.

    Returns:
        True if successful, False otherwise.
    """
    try:
        complete_list = client.get_complete_list()
        states = list(sorted(complete_list.get("cities", {}).keys()))
        _print_list_items("Available states for AQI data", states)
        return True
    except Exception as e:
        _print_error(f"Error fetching state list: {e}")
        return False


def get_city_list(client: CPCBHistorical, state: str) -> bool:
    """Display list of cities available in given state for AQI data.

    Args:
        client: The AQI client instance.
        state: The state name to get cities for.

    Returns:
        True if successful, False otherwise.
    """
    try:
        complete_list = client.get_complete_list()
        cities_data = complete_list.get("cities", {})

        if state not in cities_data:
            _print_error(f"State '{state}' not found")
            return False

        cities = sorted([city["value"] for city in cities_data[state]])
        _print_list_items(f"Available cities in {state}", cities)
        return True
    except Exception as e:
        _print_error(f"Error fetching city list: {e}")
        return False


def get_station_list(client: CPCBHistorical, city: str) -> bool:
    """Display station list with IDs and names for given city.

    Args:
        client: The AQI client instance.
        city: The city name to get stations for.

    Returns:
        True if successful, False otherwise.
    """
    try:
        complete_list = client.get_complete_list()
        stations_data = complete_list.get("stations", {})

        if city not in stations_data:
            _print_error(f"City '{city}' not found")
            return False

        stations = sorted(
            [
                f"{station['value']}({station['label']})"
                for station in stations_data[city]
            ]
        )
        _print_list_items(f"Available stations in {city}", stations)
        return True
    except Exception as e:
        _print_error(f"Error fetching station list: {e}")
        return False


def get_city_data(client: CPCBHistorical, city: str, year: int, path: str) -> bool:
    """Download and display city-level AQI data for a specific year.

    Args:
        client: The AQI client instance.
        city: The city name.
        year: The year for which to fetch data.
        path: The file path to save the data.

    Returns:
        True if successful, False otherwise.
    """
    try:
        data = client.download_past_year_aqi_data_city_level(city, str(year), path)
        if isinstance(data, Exception):
            raise data

        print("City-level AQI data overview:")
        print(data)
        print(f"File saved to {path}")
        return True
    except Exception as e:
        _print_error(f"Error fetching city data: {e}")
        return False


def get_station_data(
    client: CPCBHistorical, station_id: str, year: int, path: str
) -> bool:
    """Download and display station-level AQI data for a specific year.

    Args:
        client: The AQI client instance.
        station_id: The station ID.
        year: The year for which to fetch data.
        path: The file path to save the data.

    Returns:
        True if successful, False otherwise.
    """
    try:
        data = client.download_past_year_aqi_data_station_level(
            station_id, str(year), path
        )
        if isinstance(data, Exception):
            raise data

        print("Station-level AQI data overview:")
        print(data)
        print(f"File saved to {path}")
        return True
    except Exception as e:
        _print_error(f"Error fetching station data: {e}")
        return False


def locate_me(client: CPCBLive) -> bool:
    """Fetch and display current geolocation based on IP address.

    Args:
        client: The LiveAQI client instance.

    Returns:
        True if successful, False otherwise.
    """
    try:
        coords = client.get_system_location()
        print(f"Current location (lat, lon): {coords}")
        return True
    except Exception as e:
        _print_error(f"Error fetching location: {e}")
        return False


def get_nearest_station(
    client: CPCBLive, lat: Optional[float] = None, lon: Optional[float] = None
) -> bool:
    """Fetch nearest station details using coordinates or IP-based geolocation.

    Args:
        client: The LiveAQI client instance.
        lat: Optional latitude coordinate.
        lon: Optional longitude coordinate.

    Returns:
        True if successful, False otherwise.
    """
    try:
        coords = (lat, lon) if lat is not None and lon is not None else None
        station_id, station_name = client.get_nearest_station(coords)

        print("Nearest station details:")
        print(f"   Station ID: {station_id}")
        print(f"   Station Name: {station_name}")
        return True
    except Exception as e:
        _print_error(f"Error fetching nearest station: {e}")
        return False


def _format_aqi_metrics(metrics: list) -> None:
    """Format and print AQI metrics in a table format.

    Args:
        metrics: List of metric dictionaries containing pollutant data.
    """
    print("Live AQI data:")
    print("Pollutant   Avg   Min   Max   Period")
    print("-" * 40)
    for metric in metrics:
        name = metric.get("name", "N/A")[:10]
        avg = str(metric.get("avg", "N/A"))[:5]
        min_val = str(metric.get("min", "N/A"))[:5]
        max_val = str(metric.get("max", "N/A"))[:5]
        period = metric.get("avgDesc", "N/A")
        print(f"{name:<10} {avg:<5} {min_val:<5} {max_val:<5} {period}")


def get_live_aqi(
    client: CPCBLive,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    station_id: Optional[str] = None,
    date: Optional[str] = None,
    hour: Optional[int] = None,
    path: Optional[str] = None,
) -> bool:
    """Fetch live AQI data for nearest station or specified station.

    Args:
        client: The LiveAQI client instance.
        lat: Optional latitude coordinate.
        lon: Optional longitude coordinate.
        station_id: Optional specific station ID.
        date: Optional date in YYYY-MM-DD format.
        hour: Optional hour (0-23).
        path: Optional file path to save data.

    Returns:
        True if successful, False otherwise.
    """
    try:
        coords = (lat, lon) if lat is not None and lon is not None else None
        aqi_data = client.get_live_aqi_data(
            station_id=station_id, coords=coords, date=date, hour=hour
        )

        metrics = aqi_data.get("metrics", [])
        if metrics:
            _format_aqi_metrics(metrics)
        else:
            print("Warning: No data available, possibly due to station being offline.")

        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(aqi_data, f, indent=4, ensure_ascii=False)
            print(f"File saved to {path}")

        return True
    except Exception as e:
        _print_error(f"Error fetching live AQI data: {e}")
        return False


def get_pm25_data(
    client: PM25Client,
    geojson_path: str,
    year: int,
    month: Optional[int] = None,
    group_by: Optional[str] = None,
) -> bool:
    """Fetch and process PM2.5 data for given polygon and time period.

    Args:
        client: The PM25 client instance.
        geojson_path: Path to the GeoJSON file with polygon data.
        year: The year for which to fetch data.
        month: Optional month (1-12). If None, annual data is used.
        group_by: Optional column name to group polygons by (e.g., 'state_name').

    Returns:
        True if successful, False otherwise.
    """
    try:
        data = client.get_pm25_stats(geojson_path, year, month, group_by)
        if group_by:
            print(f"PM2.5 data grouped by '{group_by}':")
        else:
            print("Combined PM2.5 data overview:")

        print(data)
        return True
    except Exception as e:
        _print_error(f"Error fetching PM2.5 data: {e}")
        return False
