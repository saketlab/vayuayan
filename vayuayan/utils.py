"""
Utility functions for CPCB data.

The functions clean data, send network requests, parse dates, convert station
data, and analyze station data.
"""

import json
import math
import re
import time
from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import numpy as np
import pandas as pd
import requests
import urllib3

from .constants import (
    DATE_FORMATS,
    DEFAULT_BACKOFF_FACTOR,
    DEFAULT_HEADERS,
    DEFAULT_MAX_RETRIES,
    DEFAULT_TIMEOUT,
    MONTH_ABBREV,
    RSS_URL_WITH_COORDINATES,
)
from .exceptions import NetworkError

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class DataProcessingError(Exception):
    """Error when the client cannot process the data."""

    pass


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
                aqi = station.get("airQualityIndex") or {}
                avg = aqi.get("value") or aqi.get("Value") or ""
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


def get_aqi_category(aqi_value: float) -> str:
    """Convert a numeric AQI value to a category.

    Args:
        aqi_value: Numeric AQI value.

    Returns:
        AQI category string.
    """
    if pd.isna(aqi_value):
        return "No Data"
    elif aqi_value <= 50:
        return "Good"
    elif aqi_value <= 100:
        return "Satisfactory"
    elif aqi_value <= 200:
        return "Moderate"
    elif aqi_value <= 300:
        return "Poor"
    elif aqi_value <= 400:
        return "Very Poor"
    else:
        return "Severe"


def _safe_float_conversion(value: Any, default: float = np.nan) -> float:
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
                        "aqi_category": (
                            get_aqi_category(avg_aqi)
                            if not pd.isna(avg_aqi)
                            else "No Data"
                        ),
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
    """Print the message only if verbose mode is on.

    Args:
        message: Message to print.
        verbose: If True, verbose mode is on.
    """
    if verbose:
        print(message)


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
        max_retries: Maximum number of retries.
        timeout: Request timeout in seconds.
        verify_ssl: If True, verify the SSL certificates.
        allow_ssl_fallback: If True, send the request again without SSL
            verification when the verification fails.
        verbose: If True, print status messages.

    Returns:
        requests.Response object.

    Raises:
        NetworkError: If all the retries fail.
    """
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(
                url, headers=DEFAULT_HEADERS, timeout=timeout, verify=verify_ssl
            )
            response.raise_for_status()
            return response

        except requests.exceptions.SSLError as e:
            _log_if_verbose(
                f"SSL Error on attempt {attempt + 1}/{max_retries + 1}: {e}", verbose
            )

            if allow_ssl_fallback and attempt < max_retries:
                try:
                    _log_if_verbose(
                        "Retrying with SSL verification disabled (per config)...",
                        verbose,
                    )
                    response = requests.get(
                        url,
                        headers=DEFAULT_HEADERS,
                        timeout=timeout,
                        verify=False,  # nosec B501
                    )
                    response.raise_for_status()
                    _log_if_verbose(
                        "Request succeeded with SSL verification disabled", verbose
                    )
                    return response
                except Exception as fallback_error:
                    _log_if_verbose(f"Fallback also failed: {fallback_error}", verbose)

            if attempt == max_retries:
                raise NetworkError(
                    f"SSL verification failed after {max_retries + 1} attempts: {e}"
                ) from e

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as e:
            _log_if_verbose(
                f"Request error on attempt {attempt + 1}/{max_retries + 1}: {e}",
                verbose,
            )

        # Wait before the next retry (exponential backoff)
        if attempt < max_retries:
            wait_time = DEFAULT_BACKOFF_FACTOR * (2**attempt)
            _log_if_verbose(f"Waiting {wait_time:.1f} seconds before retry...", verbose)
            time.sleep(wait_time)

    raise NetworkError(
        f"Failed to fetch data from {url} after {max_retries + 1} attempts"
    )


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
        max_retries: Maximum number of retry attempts.
        backoff_factor: Factor for the exponential delay between retries.
        timeout: Request timeout in seconds.
        verify_ssl: If True, verify the SSL certificates.
        allow_ssl_fallback: If True, send the request again without SSL
            verification when the verification fails.
        verbose: If True, print status messages.

    Returns:
        Parsed JSON response, as a dictionary.

    Raises:
        NetworkError: If all retries fail, or there is a network problem.
        DataProcessingError: If the client cannot decode the base64 or parse the JSON.
        ValueError: If an input parameter is not valid.
    """
    # Validate the input
    if not url or not isinstance(url, str):
        raise ValueError("URL must be a non-empty string")
    if not headers or not isinstance(headers, dict):
        raise ValueError("Headers must be a non-empty dictionary")
    if cookies is None:
        cookies = {}
    elif not isinstance(cookies, dict):
        raise ValueError("Cookies must be a dictionary or None")

    for attempt in range(max_retries + 1):
        try:
            _log_if_verbose(
                f"Attempt {attempt + 1}/{max_retries + 1}: POST {url}", verbose
            )

            response = requests.post(
                url=url,
                headers=headers,
                data=data,
                cookies=cookies,
                timeout=timeout,
                verify=verify_ssl,
            )
            response.raise_for_status()

            _log_if_verbose(
                f"Request successful (Status: {response.status_code})", verbose
            )

            # Process the response
            try:
                if not response.content:
                    raise DataProcessingError("Response content is empty")

                decoded_data = b64decode(response.content)
                json_data = cast(Dict[str, Any], json.loads(decoded_data))
                return json_data

            except Exception as decode_error:
                raise DataProcessingError(
                    f"Failed to decode base64 or parse JSON: {decode_error}"
                ) from decode_error

        except requests.exceptions.SSLError as e:
            _log_if_verbose(
                f"SSL Error on attempt {attempt + 1}/{max_retries + 1}: {e}", verbose
            )

            if allow_ssl_fallback and attempt < max_retries:
                try:
                    _log_if_verbose(
                        "Retrying with SSL verification disabled (per config)...",
                        verbose,
                    )
                    response = requests.post(
                        url=url,
                        headers=headers,
                        data=data,
                        cookies=cookies,
                        timeout=timeout,
                        verify=False,  # nosec B501
                    )
                    response.raise_for_status()

                    decoded_data = b64decode(response.content)
                    json_data = cast(Dict[str, Any], json.loads(decoded_data))
                    _log_if_verbose(
                        "Request succeeded with SSL verification disabled", verbose
                    )
                    return json_data

                except Exception as fallback_error:
                    _log_if_verbose(
                        f"SSL fallback also failed: {fallback_error}", verbose
                    )

            if attempt == max_retries:
                raise NetworkError(
                    f"SSL verification failed after {max_retries + 1} attempts: {e}"
                ) from e

        except requests.exceptions.HTTPError as e:
            _log_if_verbose(
                f"HTTP Error on attempt {attempt + 1}/{max_retries + 1}: {e}", verbose
            )
            # Do not retry client errors (4xx)
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise NetworkError(f"HTTP {e.response.status_code} error: {e}") from e

        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ) as e:
            _log_if_verbose(
                f"Request error on attempt {attempt + 1}/{max_retries + 1}: {e}",
                verbose,
            )

        except DataProcessingError:
            # Do not retry data processing errors
            raise

        # Wait before the next retry (exponential backoff)
        if attempt < max_retries:
            wait_time = backoff_factor * (2**attempt)
            _log_if_verbose(f"Waiting {wait_time:.1f} seconds before retry...", verbose)
            time.sleep(wait_time)

    raise NetworkError(
        f"Failed to fetch data from {url} after {max_retries + 1} attempts"
    )


def url_encode(data_dict: Dict[str, Any]) -> str:
    """Encode a dictionary as a base64 JSON string.

    Args:
        data_dict: Dictionary to encode.

    Returns:
        Base64 encoded JSON string.
    """
    raw_body = json.dumps(data_dict)
    return b64encode(raw_body.encode()).decode("utf-8")


def time_to_isodate(timestamp: int) -> str:
    """Convert a timestamp to the ISO date format.

    Args:
        timestamp: Unix timestamp in milliseconds.

    Returns:
        ISO formatted date string.
    """
    datetime_object = datetime.utcfromtimestamp(timestamp / 1000)
    return datetime_object.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def euclidean_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate simple Euclidean distance.

    This function is faster than haversine_distance, but less accurate for long
    distances.

    Args:
        lat1, lon1: Latitude and longitude of first point.
        lat2, lon2: Latitude and longitude of second point.

    Returns:
        Euclidean distance (arbitrary units).
    """
    return math.sqrt((lat1 - lat2) ** 2 + (lon1 - lon2) ** 2)


def parse_date(date_text: str) -> Optional[str]:
    """Parse a date in one of many formats to the standard format.

    Args:
        date_text: Raw date text.

    Returns:
        Date in YYYY-MM-DD format, or None if the parse fails.
    """
    if not date_text:
        return None

    # Clean the date text
    date_text = re.sub(r"[^\w\s\/\-,:]", "", date_text.strip())

    for fmt in DATE_FORMATS:
        try:
            parsed_date = datetime.strptime(date_text, fmt)
            return parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def clean_city_name(city_text: str) -> Optional[str]:
    """Clean a city name and make it standard.

    Args:
        city_text: Raw city text.

    Returns:
        Cleaned city name.
    """
    if not city_text:
        return None

    # Remove extra spaces
    city = re.sub(r"\s+", " ", city_text.strip())
    # Remove the text in parentheses
    city = re.sub(r"\s*\([^)]*\)", "", city)
    # Remove frequent prefixes and suffixes
    city = re.sub(r"^(For|Weather|Report|Forecast):\s*", "", city, flags=re.IGNORECASE)
    city = re.sub(r"\s*(Weather|Report|Forecast)$", "", city, flags=re.IGNORECASE)
    # Remove HTML artifacts
    city = re.sub(r"[<>]", "", city)
    # Use the correct capital letters
    city = city.title()
    # Normalize hyphens
    city = re.sub(r"\s*-\s*", "-", city)

    return city.strip()


def convert_date_to_iso(date_str: str) -> Optional[str]:
    """Convert dates such as "27-May" and "2-Jun" to the YYYY-MM-DD format.

    Args:
        date_str: Date string in the "DD-MMM" format (for example "27-May").

    Returns:
        Date in YYYY-MM-DD format, or None if the parse fails.
    """
    if not date_str:
        return None

    current_year = datetime.now().year

    try:
        # Split at the dash and clean the parts
        parts = date_str.strip().replace("-", " ").replace("  ", " ").split(" ")
        if len(parts) != 2:
            return None

        day, month_abbr = parts
        day = day.zfill(2)  # Convert to the 2-digit format

        # Convert the month abbreviation to a number
        month_key = month_abbr.lower()[:3]
        if month_key not in MONTH_ABBREV:
            return None

        month = MONTH_ABBREV[month_key]
        return f"{current_year}-{month}-{day}"

    except Exception:
        return None
