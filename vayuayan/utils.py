"""
Utility functions for CPCB data.

The functions clean data, send network requests, encode the base64 JSON of the
old CPCB endpoints, convert station data, and analyze station data.
"""

from __future__ import annotations

import json
import logging
import math
import re
from base64 import b64decode, b64encode
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    TypeVar,
    Union,
    cast,
)

import requests

from . import http_client
from .constants import (
    AQI_CATEGORIES,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    RSS_URL_WITH_COORDINATES,
)
from .exceptions import DataProcessingError, NetworkError, StationNotFoundError

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


def clean_station_name(station_name: str) -> str:
    """Convert a station name to a clean name with underscores.

    The function applies these rules:
    1. Remove or replace special characters and punctuation
    2. Replace spaces with underscores
    3. Remove multiple consecutive underscores
    4. Remove leading/trailing underscores
    5. Change frequent patterns, for example "City - Organization"

    Args:
        station_name: Original station name.

    Returns:
        Cleaned station name with underscores.

    Examples:
        >>> clean_station_name("Dr. Karni Singh Shooting Range, Delhi - DPCC")
        'Dr_Karni_Singh_Shooting_Range_Delhi_DPCC'
        >>> clean_station_name("ITO, Delhi - DPCC")
        'ITO_Delhi_DPCC'
    """
    if not station_name or not isinstance(station_name, str):
        return ""

    cleaned = station_name.strip()

    # Change the "City - Organization" pattern
    cleaned = re.sub(r"\s*-\s*", " ", cleaned)
    # Replace commas with a space
    cleaned = re.sub(r",\s*", " ", cleaned)
    # Remove dots but keep the text
    cleaned = re.sub(r"\.", "", cleaned)
    # Remove the other punctuation and special characters
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    # Replace two or more spaces with one space
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Replace spaces with underscores
    cleaned = cleaned.replace(" ", "_")
    # Replace two or more consecutive underscores with one
    cleaned = re.sub(r"_+", "_", cleaned)
    # Remove leading and trailing underscores
    cleaned = cleaned.strip("_")

    return cleaned


def sort_station_data(data: List[Dict]) -> List[Dict]:
    """Sort the station data by live status and city name.

    The function sorts the stations of each city by:
    1. Live status (live stations first: True before False)
    2. City name (alphabetical order)

    Args:
        data: List of cities with nested stations from CPCB API.

    Returns:
        Sorted list with the same structure, in order of live status and city name.
    """

    def get_live_status_priority(city_dict: Dict) -> Tuple[float, str]:
        """Calculate the sort priority. Live stations get a higher priority."""
        stations = city_dict.get("stationsInCity", [])
        live_count = sum(1 for station in stations if station.get("live", False))
        total_count = len(stations)

        # Calculate live percentage (0-100)
        live_percentage = (live_count / total_count * 100) if total_count > 0 else 0

        # Sort key: (live_percentage descending, city_name ascending)
        return (-live_percentage, city_dict.get("cityName", "").lower())

    # Sort the cities
    sorted_data = sorted(data, key=get_live_status_priority)

    # Sort the stations in each city by live status
    for city in sorted_data:
        if "stationsInCity" in city:
            city["stationsInCity"] = sorted(
                city["stationsInCity"],
                key=lambda station: (
                    not station.get("live", False),
                    station.get("name", ""),
                ),
            )

    return sorted_data


def parse_cpcb_rss_station_data(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert CPCB RSS JSON station data to the package station shape."""
    cities: List[Dict[str, Any]] = []

    for state in data.get("country", []):
        state_id = state.get("stateId", "")
        for city in state.get("citiesInState", []):
            stations = []
            for station in city.get("stationsInCity", []):
                # The live feed has a flat airQualityIndexValue; older feeds had
                # an airQualityIndex object with a value
                aqi = station.get("airQualityIndex") or {}
                avg = (
                    station.get("airQualityIndexValue")
                    or aqi.get("value")
                    or aqi.get("Value")
                    or ""
                )
                if not aqi and avg:
                    aqi = {"value": avg}
                station_id = station.get("siteId") or station.get("stationName", "")
                station_name = station.get("stationName", "")

                stations.append(
                    {
                        "id": station_id,
                        "siteId": station_id,
                        "name": station_name,
                        "stationName": station_name,
                        "latitude": station.get("latitude"),
                        "longitude": station.get("longitude"),
                        "live": bool(station.get("lastUpdate")),
                        "avg": avg,
                        "lastUpdate": station.get("lastUpdate", ""),
                        "pollutants": station.get("pollutants", []),
                        "airQualityIndex": aqi,
                    }
                )

            cities.append(
                {
                    "cityName": city.get("cityId", ""),
                    "cityID": city.get("cityId", ""),
                    "stateID": state_id,
                    "stationsInCity": stations,
                }
            )

    return sort_station_data(cities)


def station_data_to_dropdown(station_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Build historical-client dropdown data from normalized station data."""
    cities: Dict[str, List[Dict[str, str]]] = {}
    stations: Dict[str, List[Dict[str, str]]] = {}

    for city in station_data:
        state = str(city.get("stateID", ""))
        city_name = str(city.get("cityName", ""))
        if not city_name:
            continue

        cities.setdefault(state, [])
        if not any(entry.get("value") == city_name for entry in cities[state]):
            cities[state].append({"label": city_name, "value": city_name})

        city_stations = []
        for station in city.get("stationsInCity", []):
            station_id = str(station.get("id", ""))
            station_name = str(station.get("name", ""))
            if station_id and station_name:
                city_stations.append({"label": station_name, "value": station_id})
        stations[city_name] = sorted(city_stations, key=lambda item: item["label"])

    for state in cities:
        cities[state] = sorted(cities[state], key=lambda item: item["label"])

    return {"cities": cities, "stations": stations}


def fetch_cpcb_rss_station_data(timeout: int = DEFAULT_TIMEOUT) -> List[Dict[str, Any]]:
    """Get the current CPCB stations from the JSON RSS endpoint."""
    response = safe_get(
        RSS_URL_WITH_COORDINATES, timeout=timeout, allow_ssl_fallback=True
    )
    data = cast(Dict[str, Any], response.json())
    return parse_cpcb_rss_station_data(data)


def iter_city_stations(
    cities: List[Dict[str, Any]],
) -> Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """Yield (city, station) pairs from station data grouped by city."""
    for city in cities:
        for station in city.get("stationsInCity", []):
            yield city, station


def iter_station_coords(
    cities: List[Dict[str, Any]],
) -> Iterator[Tuple[Dict[str, Any], float, float]]:
    """Yield (station, latitude, longitude), skipping stations without coordinates."""
    for _, station in iter_city_stations(cities):
        try:
            yield station, float(station["latitude"]), float(station["longitude"])
        except (KeyError, TypeError, ValueError):
            continue


T = TypeVar("T")


def find_station(query: str, stations: Iterable[Tuple[str, str, T]]) -> Optional[T]:
    """The station whose ID or name is query, else the one whose name contains it.

    Args:
        query: Station ID, name, or part of a name. Case does not matter.
        stations: (station_id, station_name, item) for each station.

    Returns:
        The item of the matching station, or None if no station matches.

    Raises:
        StationNotFoundError: If query is part of the names of more than one station.
    """
    target = query.strip().lower()
    if not target:
        return None
    partial: Dict[str, Tuple[str, T]] = {}
    for station_id, name, item in stations:
        if target in (station_id.lower(), name.lower()):
            return item
        if target in name.lower():
            partial.setdefault(station_id.lower(), (name, item))
    if len(partial) > 1:
        names = "; ".join(sorted(name for name, _ in partial.values()))
        raise StationNotFoundError(f"'{query}' matches more than one station: {names}")
    return next((item for _, item in partial.values()), None)


def station_distances(
    cities: List[Dict[str, Any]], lat: float, lon: float
) -> List[Tuple[Dict[str, Any], float]]:
    """(station, haversine distance in km) for each station with coordinates."""
    target_lat, target_lon = float(lat), float(lon)
    return [
        (station, haversine_distance(target_lat, target_lon, s_lat, s_lon))
        for station, s_lat, s_lon in iter_station_coords(cities)
    ]


def get_aqi_category(aqi_value: float) -> str:
    """Convert a numeric AQI value to a category.

    Args:
        aqi_value: Numeric AQI value.

    Returns:
        AQI category string.
    """
    import pandas as pd

    if pd.isna(aqi_value):
        return "No Data"
    return next(
        (name for name, band in AQI_CATEGORIES.items() if aqi_value <= band["max"]),
        "Severe",
    )


def _safe_float_conversion(value: Any, default: float = float("nan")) -> float:
    """Convert a value to float, or return a default value.

    Args:
        value: Value to convert.
        default: Value to return if the conversion fails.

    Returns:
        Float value, or the default value.
    """
    if value == "" or value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def stations_to_dataframe(data: List[Dict]) -> pd.DataFrame:
    """Convert nested station data to a flat DataFrame.

    Args:
        data: List of cities with nested stations from CPCB API.

    Returns:
        DataFrame with columns: city_name, city_id, state_id, station_id,
                               station_name, longitude, latitude, live, avg_aqi.
    """
    import pandas as pd

    rows = []

    for city in data:
        city_name = city.get("cityName", "")
        city_id = city.get("cityID", "")
        state_id = city.get("stateID", "")

        for station in city.get("stationsInCity", []):
            rows.append(
                {
                    "city_name": city_name,
                    "city_id": city_id,
                    "state_id": state_id,
                    "station_id": station.get("id", ""),
                    "station_name": station.get("name", ""),
                    "longitude": _safe_float_conversion(station.get("longitude")),
                    "latitude": _safe_float_conversion(station.get("latitude")),
                    "live": station.get("live", False),
                    "avg_aqi": _safe_float_conversion(station.get("avg")),
                }
            )

    return pd.DataFrame(rows)


def stations_to_city_summary(data: List[Dict]) -> pd.DataFrame:
    """Convert station data to a DataFrame with a summary for each city.

    Args:
        data: List of cities with nested stations.

    Returns:
        DataFrame with aggregated statistics for each city.
    """
    import numpy as np
    import pandas as pd

    rows = []

    for city in data:
        stations = city.get("stationsInCity", [])
        total_stations = len(stations)
        live_stations = sum(1 for station in stations if station.get("live", False))

        # Calculate the average AQI of the live stations
        live_aqi_values = [
            _safe_float_conversion(station.get("avg"))
            for station in stations
            if station.get("live", False) and station.get("avg") not in ["", None]
        ]
        live_aqi_values = [val for val in live_aqi_values if not pd.isna(val)]

        avg_aqi = np.mean(live_aqi_values) if live_aqi_values else np.nan
        min_aqi = np.min(live_aqi_values) if live_aqi_values else np.nan
        max_aqi = np.max(live_aqi_values) if live_aqi_values else np.nan

        rows.append(
            {
                "city_name": city.get("cityName", ""),
                "city_id": city.get("cityID", ""),
                "state_id": city.get("stateID", ""),
                "total_stations": total_stations,
                "live_stations": live_stations,
                "offline_stations": total_stations - live_stations,
                "live_percentage": (
                    (live_stations / total_stations * 100) if total_stations > 0 else 0
                ),
                "avg_aqi": avg_aqi,
                "min_aqi": min_aqi,
                "max_aqi": max_aqi,
                "stations_with_data": len(live_aqi_values),
            }
        )

    return pd.DataFrame(rows)


def stations_to_coordinates_dataframe(data: List[Dict]) -> pd.DataFrame:
    """Convert station data to a DataFrame for maps.

    Args:
        data: List of cities with nested stations.

    Returns:
        DataFrame with the locations and the primary station data.
    """
    import pandas as pd

    rows = []

    for city in data:
        for station in city.get("stationsInCity", []):
            try:
                longitude = float(station["longitude"])
                latitude = float(station["latitude"])
                avg_aqi = _safe_float_conversion(station.get("avg"))

                rows.append(
                    {
                        "station_id": station.get("id", ""),
                        "station_name": station.get("name", ""),
                        "city_name": city.get("cityName", ""),
                        "state_id": city.get("stateID", ""),
                        "longitude": longitude,
                        "latitude": latitude,
                        "live": station.get("live", False),
                        "avg_aqi": avg_aqi,
                        "status": "Live" if station.get("live", False) else "Offline",
                        "aqi_category": get_aqi_category(avg_aqi),
                    }
                )
            except (ValueError, TypeError, KeyError):
                # Skip stations with invalid coordinates
                continue

    return pd.DataFrame(rows)


def convert_station_data_to_dataframe(
    data: List[Dict], method: str = "stations"
) -> pd.DataFrame:
    """Convert station data to a DataFrame in one of three formats.

    Args:
        data: List of cities with nested stations from CPCB API.
        method: Conversion method ('stations', 'city_summary', 'coordinates').

    Returns:
        DataFrame in the format of the given method.

    Methods:
        - 'stations': Flat DataFrame with one row for each station (default)
        - 'city_summary': Summary of each city, with aggregated statistics
        - 'coordinates': DataFrame for maps, with the station locations
    """
    methods = {
        "stations": stations_to_dataframe,
        "city_summary": stations_to_city_summary,
        "coordinates": stations_to_coordinates_dataframe,
    }

    if method not in methods:
        raise ValueError(f"Method must be one of: {list(methods.keys())}")

    return methods[method](data)


def analyze_station_data(data: List[Dict]) -> Dict[str, Any]:
    """Analyze the station data.

    Args:
        data: List of cities with nested stations.

    Returns:
        Dictionary with the results of the analysis.
    """
    import pandas as pd

    df = stations_to_dataframe(data)

    analysis = {
        "total_cities": len(data),
        "total_stations": len(df),
        "live_stations": int(df["live"].sum()),
        "offline_stations": int((~df["live"]).sum()),
        "states": df["state_id"].nunique(),
        "unique_states": sorted(df["state_id"].unique().tolist()),
        "stations_with_aqi_data": len(df[~pd.isna(df["avg_aqi"])]),
        "avg_aqi_overall": df["avg_aqi"].mean(),
        "min_aqi": df["avg_aqi"].min(),
        "max_aqi": df["avg_aqi"].max(),
        "stations_per_city": df.groupby("city_name").size().describe().to_dict(),
        "aqi_distribution": (
            df["avg_aqi"].describe().to_dict() if not df["avg_aqi"].empty else {}
        ),
    }

    # Add the distribution of AQI categories
    df_with_categories = df.copy()
    df_with_categories["aqi_category"] = df_with_categories["avg_aqi"].apply(
        get_aqi_category
    )
    analysis["aqi_categories"] = (
        df_with_categories["aqi_category"].value_counts().to_dict()
    )

    return analysis


def _log_if_verbose(message: str, verbose: bool) -> None:
    """Log the message at INFO level if verbose is True, else at DEBUG level.

    Args:
        message: Message to log.
        verbose: If True, verbose mode is on.
    """
    logger.log(logging.INFO if verbose else logging.DEBUG, message)


def safe_get(
    url: str,
    max_retries: int = DEFAULT_MAX_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = False,
    verbose: bool = False,
) -> requests.Response:
    """Send an HTTP GET request, and send it again if it fails.

    Args:
        url: URL of the request.
        max_retries: Maximum number of retries. 4xx statuses are not retried.
        timeout: Request timeout in seconds.
        verify_ssl: If True, verify the SSL certificates.
        allow_ssl_fallback: If True, send the request again without SSL
            verification when the verification fails.
        verbose: If True, log status messages at INFO level.

    Returns:
        requests.Response object.

    Raises:
        NetworkError: If all the retries fail.
    """
    _log_if_verbose(f"GET {url}", verbose)
    try:
        return http_client.request(
            "get",
            url,
            retries=max_retries,
            ssl_fallback=allow_ssl_fallback,
            headers=DEFAULT_HEADERS,
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as e:
        raise NetworkError(
            f"Failed to fetch data from {url} after {max_retries + 1} attempts: "
            f"{http_client.failure_reason(e)}"
        ) from e


def safe_post(
    url: str,
    headers: Dict[str, str],
    data: Union[Dict[str, Any], str, bytes],
    cookies: Optional[Dict[str, str]] = None,
    max_retries: int = 3,
    backoff_factor: float = 0.3,
    timeout: int = 30,
    verify_ssl: bool = True,
    allow_ssl_fallback: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """Send a POST request with retries, and decode the base64 response.

    Args:
        url: URL of the POST request.
        headers: Request headers.
        data: Request data (dict, string, or bytes).
        cookies: Optional cookies dict.
        max_retries: Maximum number of retry attempts. 4xx statuses are not
            retried.
        backoff_factor: Factor for the exponential delay between retries.
        timeout: Request timeout in seconds.
        verify_ssl: If True, verify the SSL certificates.
        allow_ssl_fallback: If True, send the request again without SSL
            verification when the verification fails.
        verbose: If True, log status messages at INFO level.

    Returns:
        Parsed JSON response, as a dictionary.

    Raises:
        NetworkError: If all retries fail, or there is a network problem.
        DataProcessingError: If the client cannot decode the base64 or parse the JSON.
        ValueError: If an input parameter is not valid.
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    if not headers or not isinstance(headers, dict):
        raise ValueError("Headers must be a non-empty dictionary")
    if cookies is not None and not isinstance(cookies, dict):
        raise ValueError("Cookies must be a dictionary or None")

    _log_if_verbose(f"POST {url}", verbose)
    try:
        response = http_client.request(
            "post",
            url,
            retries=max_retries,
            backoff_factor=backoff_factor,
            ssl_fallback=allow_ssl_fallback,
            headers=headers,
            data=data,
            cookies=cookies or {},
            timeout=timeout,
            verify=verify_ssl,
        )
    except requests.RequestException as e:
        raise NetworkError(f"POST {url} failed: {http_client.failure_reason(e)}") from e

    try:
        return cast(Dict[str, Any], decode_b64_json_response(response))
    except ValueError as e:
        raise DataProcessingError(f"Failed to decode base64 or parse JSON: {e}") from e


def url_encode(data_dict: Dict[str, Any]) -> str:
    """Encode a dictionary as a base64 JSON string.

    Args:
        data_dict: Dictionary to encode.

    Returns:
        Base64 encoded JSON string.
    """
    raw_body = json.dumps(data_dict)
    return b64encode(raw_body.encode()).decode("utf-8")


def decode_b64_json_response(response: requests.Response) -> Any:
    """Decode the base64 JSON body of an old CPCB endpoint.

    Raises:
        ValueError: If the body is empty, or not base64 JSON.
    """
    if not response.content:
        raise ValueError("Response content is empty")
    return json.loads(b64decode(response.content))


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points (haversine formula).

    For locations on the globe, this distance is more accurate than the
    Euclidean distance.

    Args:
        lat1, lon1: Latitude and longitude of first point.
        lat2, lon2: Latitude and longitude of second point.

    Returns:
        Distance in kilometers.
    """
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])

    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    # Earth's radius in kilometers
    return c * 6371
