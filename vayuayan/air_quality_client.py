"""
Air Quality Client module for interacting with CPCB AQI services.

This module provides client classes for fetching air quality data from India's
Central Pollution Control Board (CPCB) including AQI data, live monitoring data,
and PM2.5 satellite data.
"""

import base64
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from urllib.parse import urljoin

import geopandas as gpd
import numpy as np
import pandas as pd
import requests
import rioxarray  # noqa: F401
import urllib3
import xarray as xr
from geopy.distance import geodesic
from tqdm import tqdm

# Disable SSL warnings for CPCB endpoints with certificate issues
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _request_with_ssl_fallback(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Union[str, bytes]] = None,
    cookies: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    stream: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """Make HTTP request with SSL fallback on certificate errors.

    First attempts with SSL verification enabled. If that fails with an SSL error,
    retries with SSL verification disabled.

    Args:
        method: HTTP method ('get' or 'post').
        url: Request URL.
        headers: Optional request headers.
        data: Optional request data.
        cookies: Optional request cookies.
        timeout: Request timeout in seconds.
        stream: Whether to stream the response.
        **kwargs: Additional arguments to pass to requests.

    Returns:
        Response object.

    Raises:
        requests.RequestException: If request fails after SSL fallback attempt.
    """
    request_kwargs = {
        "timeout": timeout,
        "stream": stream,
        **kwargs,
    }
    if headers:
        request_kwargs["headers"] = headers
    if data is not None:
        request_kwargs["data"] = data
    if cookies:
        request_kwargs["cookies"] = cookies

    # Try with SSL verification first
    try:
        request_kwargs["verify"] = True
        if method.lower() == "get":
            response = requests.get(url, **request_kwargs)
        else:
            response = requests.post(url, **request_kwargs)
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError as e:
        # SSL verification failed, retry without verification
        print(f"SSL verification failed: {e}")
        print("Retrying with SSL verification disabled...")
        try:
            request_kwargs["verify"] = False
            if method.lower() == "get":
                response = requests.get(url, **request_kwargs)
            else:
                response = requests.post(url, **request_kwargs)
            response.raise_for_status()
            return response
        except Exception as fallback_error:
            raise requests.RequestException(
                f"Request failed even with SSL verification disabled: {fallback_error}"
            ) from fallback_error


class CPCBHistorical:
    """Client for fetching historical Air Quality Index (AQI) data from CPCB."""

    def __init__(self) -> None:
        """Initialize the AQI Client with CPCB endpoints and headers."""
        self.base_url = "https://airquality.cpcb.gov.in"
        self.base_path = f"{self.base_url}/dataRepository/download_file?file_name="
        self.data_repository = "/dataRepository/"
        self.dropdown_endpoint = f"{self.data_repository}all_india_stationlist"
        self.file_path_endpoint = f"{self.data_repository}file_Path"

        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "q=0.8;application/json;q=0.9",
        }

    def _encode_base64(self, data: bytes) -> str:
        """Encode bytes to base64 string.

        Args:
            data: Bytes to encode.

        Returns:
            Base64 encoded string.
        """
        return base64.b64encode(data).decode("utf-8")

    def _decode_base64(self, data: str) -> str:
        """Decode base64 string to UTF-8 string.

        Args:
            data: Base64 encoded string.

        Returns:
            Decoded UTF-8 string.
        """
        return base64.b64decode(data.encode("utf-8")).decode("utf-8")

    def get_complete_list(self) -> Dict[str, Any]:
        """Fetch the complete list of all India stations and cities.

        Returns:
            Dictionary containing station and city data.

        Raises:
            requests.RequestException: If the HTTP request fails.
            json.JSONDecodeError: If response cannot be parsed as JSON.
        """
        form_body = self._encode_base64(b"{}")
        response = _request_with_ssl_fallback(
            method="post",
            url=f"{self.base_url}{self.dropdown_endpoint}",
            data=form_body,
            timeout=30,
        )

        decoded_response = self._decode_base64(response.text)
        parsed_response = cast(Dict[str, Any], json.loads(decoded_response))

        if parsed_response.get("status") == "success":
            dropdown = parsed_response.get("dropdown", {})
            if isinstance(dropdown, dict):
                return dropdown
        return {}

    def get_state_list(self) -> List[str]:
        """Get list of states available for AQI data.

        Returns:
            Sorted list of state names.
        """
        try:
            complete_list = self.get_complete_list()
            return list(sorted(complete_list.get("cities", {})))
        except KeyError as e:
            print(f"KeyError in get_state_list: {e}")
            return []
        except Exception as e:
            print(f"Unexpected error in get_state_list: {e}")
            return []

    def get_city_list(self, state: str) -> List[str]:
        """Get list of cities available in given state for AQI data.

        Args:
            state: State name to get cities for.

        Returns:
            Sorted list of city names in the state.
        """
        try:
            complete_list = self.get_complete_list()
            cities = complete_list.get("cities", {})
            if cities and state in cities:
                return list(sorted([city["value"] for city in cities[state]]))
            return []
        except Exception:
            return []

    def get_station_list(self, city: str) -> List[Dict]:
        """Get station list available in given city for AQI data.

        Args:
            city: City name to get stations for.

        Returns:
            Sorted list of station dictionaries.
        """
        try:
            complete_list = self.get_complete_list()
            stations = complete_list.get("stations", {})
            if stations and city in stations:
                return list(sorted(stations[city], key=lambda x: x.get("label", "")))
            return []
        except Exception:
            return []

    def get_file_path(
        self,
        station_id: str,
        station_name: str,
        state: str,
        city: str,
        year: str,
        frequency: str,
        data_type: str,
    ) -> List[Dict[str, Any]]:
        """Get file path containing data for given query parameters.

        Args:
            station_id: Station ID.
            station_name: Station name.
            state: State name.
            city: City name.
            year: Year for data.
            frequency: Data frequency ('hourly' or 'daily').
            data_type: Type of data ('cityLevel' or 'stationLevel').

        Returns:
            Dictionary containing file path data.

        Raises:
            requests.RequestException: If the HTTP request fails.
        """
        payload = {
            "station_id": station_id,
            "station_name": station_name,
            "state": state,
            "city": city,
            "year": year,
            "frequency": frequency,
            "dataType": data_type,
        }

        payload_str = json.dumps(payload)
        encoded_payload = self._encode_base64(payload_str.encode("utf-8"))

        response = _request_with_ssl_fallback(
            method="post",
            url=f"{self.base_url}{self.file_path_endpoint}",
            data=encoded_payload,
            headers=self.headers,
            timeout=30,
        )

        decoded_response = self._decode_base64(response.text)
        parsed_response = cast(Dict[str, Any], json.loads(decoded_response))

        if parsed_response.get("status") == "success":
            data = parsed_response.get("data", [])
            if isinstance(data, list):
                return [
                    cast(Dict[str, Any], entry)
                    for entry in data
                    if isinstance(entry, dict)
                ]
        return []

    def download_past_year_aqi_data_city_level(
        self, city: str, year: str, save_location: str
    ) -> pd.DataFrame:
        """Download past AQI data for a specific city.

        Args:
            city: City name.
            year: Year for data.
            save_location: Path to save the downloaded data.

        Returns:
            DataFrame preview of the downloaded data.

        Raises:
            Exception: If data is not found or download fails.
        """
        data_file_paths = self.get_file_path("", "", "", city, "", "daily", "cityLevel")

        for entry in data_file_paths:
            if entry.get("year") == str(year):
                file_url = f"{self.base_path}{entry['filepath']}"
                df = pd.read_excel(file_url)
                df = df.iloc[:31]  # Limit to first 31 rows (max days in month)
                if save_location:
                    df.to_csv(save_location, index=False)
                return df

        raise Exception(f"Data not found for city {city} in year {year}")

    def download_past_year_aqi_data_station_level(
        self, station_id: str, year: str, save_location: str
    ) -> pd.DataFrame:
        """Download past AQI data for a specific station.

        Args:
            station_id: Station ID.
            year: Year for data.
            save_location: Path to save the downloaded data.

        Returns:
            DataFrame preview of the downloaded data.

        Raises:
            Exception: If station or data is not found.
        """
        complete_list = self.get_complete_list()
        station_list = complete_list.get("stations", [])

        # Find station name for the given station_id
        station_name = None
        for city_stations in station_list.values():
            for station in city_stations:
                if station.get("value") == station_id:
                    station_name = station.get("label")
                    break
            if station_name:
                break

        if not station_name:
            raise Exception(f"Station ID {station_id} not found")

        data_file_paths = self.get_file_path(
            station_id, station_name, "", "", "", "daily", "stationLevel"
        )

        for entry in data_file_paths:
            if entry.get("year") == year:
                file_url = f"{self.base_path}{entry['filepath']}"
                df = pd.read_excel(file_url)
                df = df.iloc[:31]  # Limit to first 31 rows (max days in month)
                df.to_csv(save_location, index=False)
                return df.head()

        raise Exception(f"Data not found for station {station_id} in year {year}")


class CPCBLive:
    """Client for fetching live air quality data from CPCB."""

    def __init__(self) -> None:
        """Initialize the Live AQI Client."""
        self.base_url = "https://airquality.cpcb.gov.in"
        self.coordinate_url = "http://ip-api.com/json"
        self.dashboard_path = "/aqi_dashboard/"
        self.station_url = f"{self.base_url}{self.dashboard_path}aqi_station_all_india"
        self.parameters_url = f"{self.base_url}{self.dashboard_path}aqi_all_Parameters"

        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "q=0.8;application/json;q=0.9",
        }
        self.cookies = {"ccr_public": "A"}

    def _make_request(
        self,
        url: str,
        headers: Dict[str, str],
        data: str,
        cookies: Dict[str, str],
    ) -> Dict[str, Any]:
        """Make a POST request and return base64 decoded JSON response.

        Args:
            url: Request URL.
            headers: Request headers.
            data: Request data.
            cookies: Request cookies.

        Returns:
            Parsed JSON response.

        Raises:
            requests.RequestException: If request fails.
            json.JSONDecodeError: If response cannot be decoded.
        """
        response = _request_with_ssl_fallback(
            method="post",
            url=url,
            headers=headers,
            data=data,
            cookies=cookies,
            timeout=30,
        )

        decoded_data = base64.b64decode(response.content)
        return cast(Dict[str, Any], json.loads(decoded_data))

    def _clean_pollution_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Clean and format pollution data.

        Args:
            data: Raw pollution data dictionary.

        Returns:
            Cleaned pollution data dictionary.
        """
        cleaned_data = data.copy()

        if "chartData" not in data:
            return cleaned_data

        cleaned_chart_data = []
        for i, series in enumerate(data["chartData"]):
            if not series or not isinstance(series, list) or len(series) < 2:
                continue

            rows = series[1:]  # Skip header
            live_data = []

            for row in rows:
                if len(row) < 2 or row[0] is None or row[1] is None:
                    continue
                live_data.append({"date": row[0], "val": row[1]})

            if i < len(cleaned_data.get("metrics", [])):
                series_name = cleaned_data["metrics"][i].get("name", f"Series {i}")
                cleaned_chart_data.append({"name": series_name, "data": live_data})

        cleaned_data["last_hours"] = cleaned_chart_data
        cleaned_data.pop("chartData", None)
        return cleaned_data

    def get_system_location(self) -> Tuple[float, float]:
        """Retrieve system's geolocation using IP-based lookup.

        Returns:
            Tuple of (latitude, longitude).

        Raises:
            Exception: If geolocation lookup fails.
        """
        try:
            response = _request_with_ssl_fallback(
                method="get", url=self.coordinate_url, timeout=30
            )
            data = response.json()

            if data.get("status") == "success":
                return (data.get("lat"), data.get("lon"))
            else:
                raise Exception(f"Geolocation lookup failed: {data.get('message')}")
        except Exception as e:
            raise Exception(f"Error retrieving system location: {e}") from e

    def get_nearest_station(
        self, coords: Optional[Tuple[float, float]] = None
    ) -> Tuple[str, str]:
        """Get the nearest air quality monitoring station.

        Args:
            coords: Optional tuple of (latitude, longitude). If None, uses IP
                geolocation.

        Returns:
            Tuple of (station_id, station_name).

        Raises:
            Exception: If no stations found or coordinates invalid.
        """
        try:
            cities = self.get_all_india()
            if not coords:
                coords = self.get_system_location()

            user_location = (float(coords[0]), float(coords[1]))
            min_distance = float("inf")
            nearest_station = None

            for city_data in cities:
                for station in city_data.get("stationsInCity", []):
                    try:
                        station_location = (
                            float(station["latitude"]),
                            float(station["longitude"]),
                        )
                        distance = geodesic(user_location, station_location).kilometers

                        if distance < min_distance:
                            min_distance = distance
                            nearest_station = (station.get("id"), station.get("name"))
                    except (TypeError, ValueError):
                        continue

            if nearest_station:
                return nearest_station
            raise Exception("No stations found or invalid station data.")
        except Exception as e:
            raise Exception(f"Error finding nearest station: {e}") from e

    def get_all_india(self) -> List[Dict[str, Any]]:
        """Get all air quality monitoring stations in India.

        Returns:
            List of station dictionaries.
        """
        body = "e30="
        try:
            response = self._make_request(
                self.station_url, self.headers, body, self.cookies
            )
            stations = response.get("stations", [])
            if isinstance(stations, list):
                return [
                    cast(Dict[str, Any], station)
                    for station in stations
                    if isinstance(station, dict)
                ]
        except Exception:
            response = self._make_request(
                self.station_url, self.headers, body, self.cookies
            )
            stations = response.get("stations", [])
            if isinstance(stations, list):
                return [
                    cast(Dict[str, Any], station)
                    for station in stations
                    if isinstance(station, dict)
                ]
        return []

    def get_live_aqi_data_for_station(
        self, station_id: str, date_time: str
    ) -> Dict[str, Any]:
        """Get live air quality data for a specific station.

        Args:
            station_id: Station ID.
            date_time: Date and time in 'YYYY-MM-DDTHH:00:00Z' format.

        Returns:
            Live air quality data dictionary.

        Raises:
            ValueError: If parameters are invalid.
            Exception: If request fails.
        """
        if not station_id or not date_time:
            raise ValueError("Both station_id and date_time must be provided.")

        raw_body = json.dumps({"station_id": station_id, "date": date_time})
        encoded_data = base64.b64encode(raw_body.encode()).decode("utf-8")

        return self._make_request(
            self.parameters_url, self.headers, encoded_data, self.cookies
        )

    def get_live_aqi_data(
        self,
        station_id: Optional[str] = None,
        coords: Optional[Tuple[float, float]] = None,
        date: Optional[str] = None,
        hour: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get live AQI data with flexible parameter options.

        Args:
            station_id: Optional station ID. If not provided, uses nearest station.
            coords: Optional (latitude, longitude) tuple.
            date: Optional date in 'YYYY-MM-DD' format. Defaults to today.
            hour: Optional hour (0-23). Defaults to current hour.

        Returns:
            Processed live AQI data dictionary.

        Raises:
            ValueError: If hour is invalid.
            Exception: If data retrieval fails.
        """
        # Determine station_id
        if not station_id:
            if coords:
                station_id = self.get_nearest_station(coords)[0]
            else:
                system_coords = self.get_system_location()
                station_id = self.get_nearest_station(system_coords)[0]

        # Determine date and hour
        now = datetime.now()
        if not date:
            date = now.strftime("%Y-%m-%d")

        if hour is not None:
            if not (0 <= hour <= 23):
                raise ValueError("Hour must be between 0 and 23")
            date_time = f"{date}T{hour:02d}:00:00Z"
        else:
            last_hour = now.replace(minute=0, second=0, microsecond=0)
            date_time = f"{date}T{last_hour.hour:02d}:00:00Z"

        aqi_data = self.get_live_aqi_data_for_station(station_id, date_time)
        return self._clean_pollution_data(aqi_data)


class PM25Client:
    """Client for processing PM2.5 satellite data from NetCDF files."""

    def __init__(self, cache_dir: str = "pm25_data") -> None:
        """Initialize the PM2.5 Client with data paths and AWS configuration.

        Args:
            cache_dir: Directory to cache downloaded NetCDF files.
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # AWS S3 configuration for WUSTL ACAG data (Global)
        self.aws_base_url = (
            "https://s3.us-west-2.amazonaws.com/v6.gl.02.04/V6.GL.02.04/GL/"
        )

        # Local paths (legacy support)
        self.annual_data_path = "examples/V6GL01.0p10.CNNPM25.Global"
        self.monthly_data_path = "examples/V6GL01.0p10.CNNPM25.Global"

    def _get_aws_filename(self, year: int, month: Optional[int] = None) -> str:
        """Generate AWS filename for given year and optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, returns annual filename.

        Returns:
            AWS filename for the NetCDF file.
        """
        if month is None:
            return f"V6GL02.04.CNNPM25.GL.{year}01-{year}12.nc"
        return f"V6GL02.04.CNNPM25.GL.{year}{month:02d}-{year}{month:02d}.nc"

    def _get_aws_url(self, year: int, month: Optional[int] = None) -> str:
        """Generate AWS URL for given year and optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, returns annual URL.

        Returns:
            Full AWS URL for the NetCDF file.
        """
        filename = self._get_aws_filename(year, month)
        if month is None:
            return urljoin(self.aws_base_url, f"Annual/{filename}")
        return urljoin(self.aws_base_url, f"Monthly/{year}/{filename}")

    def get_netcdf_path(self, year: int, month: Optional[int] = None) -> str:
        """Get NetCDF file path for given year and optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, returns annual data path.

        Returns:
            Path to NetCDF file (cached locally).
        """
        filename = self._get_aws_filename(year, month)
        cached_path = self.cache_dir / filename

        # Return cached path regardless of whether file exists
        # (download_netcdf_if_needed will handle downloading)
        return str(cached_path)

    def download_netcdf_if_needed(
        self, year: int, month: Optional[int] = None, force_download: bool = False
    ) -> str:
        """Download NetCDF file from AWS if not already cached.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, downloads annual data.
            force_download: Whether to re-download even if file exists.

        Returns:
            Path to the downloaded NetCDF file.

        Raises:
            requests.RequestException: If download fails.
            IOError: If file cannot be written.
        """
        cached_path = Path(self.get_netcdf_path(year, month))

        # Check if file already exists and is valid
        if cached_path.exists() and not force_download:
            file_size = cached_path.stat().st_size
            if file_size > 1024 * 1024:  # At least 1MB (reasonable for NetCDF)
                print(f"Using cached file: {cached_path}")
                return str(cached_path)
            else:
                print("Warning: Cached file appears incomplete, re-downloading...")

        # Download from AWS
        aws_url = self._get_aws_url(year, month)
        print("Downloading PM2.5 data from AWS...")
        print(f"Source: {aws_url}")
        print(f"Destination: {cached_path}")

        try:
            response = _request_with_ssl_fallback(
                method="get", url=aws_url, stream=True, timeout=300
            )

            # Ensure directory exists
            cached_path.parent.mkdir(parents=True, exist_ok=True)

            # Get file size for progress indication
            total_size = int(response.headers.get("content-length", 0))

            # Use tqdm progress bar
            chunk_size = 8192
            with open(cached_path, "wb") as f:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="Downloading",
                    ncols=80,
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            final_size = cached_path.stat().st_size
            print(f"✓ Download complete: {final_size / (1024*1024):.1f} MB")
            return str(cached_path)

        except requests.RequestException as e:
            if cached_path.exists():
                cached_path.unlink()  # Remove incomplete file
            raise requests.RequestException(
                f"Failed to download NetCDF data: {e}"
            ) from e
        except IOError as e:
            if cached_path.exists():
                cached_path.unlink()  # Remove incomplete file
            raise IOError(f"Failed to write NetCDF file: {e}") from e

    def get_pm25_stats(
        self,
        geojson_file: str,
        year: int,
        month: Optional[int] = None,
        group_by: Optional[str] = None,
    ) -> Union[Dict[str, float], pd.DataFrame]:
        """Compute PM2.5 statistics inside a polygon region from GeoJSON.

        This function automatically downloads the required NetCDF data from AWS
        if not cached locally.

        Args:
            geojson_file: Path to GeoJSON file with polygon.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            group_by: Optional column name(s) to group polygons by.
                     Can be a single column (e.g., 'state_name') or comma-separated
                     multiple columns (e.g., 'state_name,district_name').
                     If None, aggregates entire polygon boundary.
                     If specified, aggregates by unique combinations of values.

        Returns:
            If group_by is None: Dictionary with mean, std, min, and max PM2.5 values.
            If group_by is specified: DataFrame with statistics for each group.

        Raises:
            FileNotFoundError: If GeoJSON file not found.
            requests.RequestException: If NetCDF download fails.
            ValueError: If group_by column not found in GeoJSON.
        """
        # Check GeoJSON file first
        if not os.path.exists(geojson_file):
            raise FileNotFoundError(f"GeoJSON file not found: {geojson_file}")

        # Download NetCDF file if needed
        nc_file = self.download_netcdf_if_needed(year, month)

        # Read and process polygon first to get bounding box
        gdf = gpd.read_file(geojson_file)
        gdf = gdf.to_crs("EPSG:4326")

        # If group_by is specified, delegate to grouped processing
        if group_by is not None:
            # Parse comma-separated columns
            group_cols = [col.strip() for col in group_by.split(",")]

            # Validate all columns exist
            missing_cols = [col for col in group_cols if col not in gdf.columns]
            if missing_cols:
                available_columns = list(gdf.columns)
                raise ValueError(
                    f"Column(s) {missing_cols} not found in GeoJSON. "
                    f"Available columns: {available_columns}"
                )

            return self._get_pm25_stats_grouped(gdf, Path(nc_file), group_cols)

        # Otherwise, process as combined polygon
        polygon = gdf.union_all()  # Combine polygons if multiple
        bounds = polygon.bounds  # (minx, miny, maxx, maxy)

        with xr.open_dataset(nc_file) as ds:
            # Check if this is the new WUSTL format or old format
            if "PM25" in ds.variables:
                pm25_var = "PM25"
            elif "GWRPM25" in ds.variables:
                pm25_var = "GWRPM25"
            else:
                available_vars = list(ds.variables.keys())
                raise ValueError(
                    f"PM2.5 variable not found. Available variables: {available_vars}"
                )

            # Handle coordinate naming variations
            if "latitude" in ds.coords and "longitude" in ds.coords:
                lat_coord, lon_coord = "latitude", "longitude"
            elif "lat" in ds.coords and "lon" in ds.coords:
                lat_coord, lon_coord = "lat", "lon"
            else:
                raise ValueError(
                    "Could not find latitude/longitude coordinates in NetCDF file"
                )

            # Add small buffer to ensure we capture the polygon
            lat_buffer = 0.1
            lon_buffer = 0.1

            # Get the actual coordinate values to determine order
            lat_vals = ds[lat_coord].values
            lon_vals = ds[lon_coord].values

            # Determine if coordinates are ascending or descending
            lat_ascending = lat_vals[0] < lat_vals[-1]
            lon_ascending = lon_vals[0] < lon_vals[-1]

            if lat_ascending:
                lat_slice = slice(bounds[1] - lat_buffer, bounds[3] + lat_buffer)
            else:
                lat_slice = slice(bounds[3] + lat_buffer, bounds[1] - lat_buffer)

            if lon_ascending:
                lon_slice = slice(bounds[0] - lon_buffer, bounds[2] + lon_buffer)
            else:
                lon_slice = slice(bounds[2] + lon_buffer, bounds[0] - lon_buffer)

            ds_subset = ds.sel({lat_coord: lat_slice, lon_coord: lon_slice})

            # Extract the PM25 variable
            pm25 = ds_subset[pm25_var]

            # Load into memory
            pm25 = pm25.load()

            # Ensure coordinates are ascending (required by rioxarray)
            if not lat_ascending:
                pm25 = pm25.sortby(lat_coord)
            if not lon_ascending:
                pm25 = pm25.sortby(lon_coord)

            # Set spatial dimensions for rioxarray
            pm25 = pm25.rio.set_spatial_dims(x_dim=lon_coord, y_dim=lat_coord)
            pm25 = pm25.rio.write_crs("EPSG:4326")

            # Clip to polygon and calculate statistics
            clipped = pm25.rio.clip([polygon], crs="EPSG:4326", all_touched=True)

            # Get values and filter NaN
            values = clipped.values.flatten()
            values = values[~np.isnan(values)]

            if len(values) == 0:
                raise ValueError(
                    "No valid PM2.5 data found within the polygon boundary"
                )

            return {
                "mean": float(values.mean()),
                "std": float(values.std()),
                "min": float(values.min()),
                "max": float(values.max()),
            }

    def _get_pm25_stats_grouped(
        self, gdf: gpd.GeoDataFrame, nc_file: Path, group_by: Union[str, List[str]]
    ) -> pd.DataFrame:
        """Compute PM2.5 statistics grouped by column(s) in the GeoDataFrame.

        Args:
            gdf: GeoDataFrame with geometries (already in EPSG:4326).
            nc_file: Path to NetCDF file.
            group_by: Column name(s) to group by. Can be a string or list of strings.

        Returns:
            DataFrame with statistics for each unique value or combination in the
            group_by column(s).
        """
        # Ensure group_by is a list
        group_cols = [group_by] if isinstance(group_by, str) else group_by
        # Get overall bounding box for all geometries
        bbox = gdf.total_bounds  # [minx, miny, maxx, maxy]

        # Load dataset and subset to bounding box
        with xr.open_dataset(nc_file) as ds:
            # Check variable and coordinate names
            if "PM25" in ds.variables:
                pm25_var = "PM25"
            elif "GWRPM25" in ds.variables:
                pm25_var = "GWRPM25"
            else:
                available_vars = list(ds.variables.keys())
                raise ValueError(
                    f"PM2.5 variable not found. Available variables: {available_vars}"
                )

            if "latitude" in ds.coords and "longitude" in ds.coords:
                lat_coord, lon_coord = "latitude", "longitude"
            elif "lat" in ds.coords and "lon" in ds.coords:
                lat_coord, lon_coord = "lat", "lon"
            else:
                raise ValueError(
                    "Could not find latitude/longitude coordinates in NetCDF file"
                )

            # Get coordinate values to determine order
            lat_vals = ds[lat_coord].values
            lon_vals = ds[lon_coord].values
            lat_ascending = lat_vals[0] < lat_vals[-1]
            lon_ascending = lon_vals[0] < lon_vals[-1]

            # Create slice with correct ordering
            lat_buffer = 0.1
            lon_buffer = 0.1

            if lat_ascending:
                lat_slice = slice(bbox[1] - lat_buffer, bbox[3] + lat_buffer)
            else:
                lat_slice = slice(bbox[3] + lat_buffer, bbox[1] - lat_buffer)

            if lon_ascending:
                lon_slice = slice(bbox[0] - lon_buffer, bbox[2] + lon_buffer)
            else:
                lon_slice = slice(bbox[2] + lon_buffer, bbox[0] - lon_buffer)

            ds_subset = ds.sel({lat_coord: lat_slice, lon_coord: lon_slice})

            # Extract PM25 variable
            pm25 = ds_subset[pm25_var]
            pm25 = pm25.load()

            # Ensure coordinates are ascending
            if not lat_ascending:
                pm25 = pm25.sortby(lat_coord)
            if not lon_ascending:
                pm25 = pm25.sortby(lon_coord)

            # Set spatial dimensions for rioxarray
            pm25 = pm25.rio.set_spatial_dims(x_dim=lon_coord, y_dim=lat_coord)
            pm25 = pm25.rio.write_crs("EPSG:4326")

            # Group by the specified column(s) and process each group
            results = []
            # For single column, don't use list to avoid tuple wrapping
            groupby_arg = group_cols[0] if len(group_cols) == 1 else group_cols

            for group_name, group_gdf in gdf.groupby(groupby_arg):
                # Combine all polygons in this group
                combined_geom = group_gdf.union_all()

                try:
                    # Clip to the combined geometry
                    clipped = pm25.rio.clip(
                        [combined_geom], crs="EPSG:4326", all_touched=True
                    )

                    # Get values and filter NaN
                    values = clipped.values.flatten()
                    values = values[~np.isnan(values)]

                    # Create result dict with group columns
                    result = {}
                    if len(group_cols) == 1:
                        # Single column grouping - group_name is a scalar
                        result[group_cols[0]] = group_name
                    else:
                        # Multiple column grouping - group_name is a tuple
                        for i, col in enumerate(group_cols):
                            result[col] = group_name[i]

                    # Add statistics
                    if len(values) > 0:
                        result.update(
                            {
                                "mean": float(values.mean()),
                                "std": float(values.std()),
                                "min": float(values.min()),
                                "max": float(values.max()),
                                "count": len(values),
                            }
                        )
                    else:
                        result.update(
                            {
                                "mean": np.nan,
                                "std": np.nan,
                                "min": np.nan,
                                "max": np.nan,
                                "count": 0,
                            }
                        )

                    results.append(result)

                except Exception as e:
                    print(f"Warning: Error processing group '{group_name}': {e}")
                    result = {}
                    if len(group_cols) == 1:
                        result[group_cols[0]] = group_name
                    else:
                        for i, col in enumerate(group_cols):
                            result[col] = group_name[i]
                    result.update(
                        {
                            "mean": np.nan,
                            "std": np.nan,
                            "min": np.nan,
                            "max": np.nan,
                            "count": 0,
                        }
                    )
                    results.append(result)

            return pd.DataFrame(results)

    def get_pm25_stats_by_polygon(
        self,
        geojson_file: str,
        year: int,
        month: Optional[int] = None,
        id_field: Optional[str] = None,
    ) -> pd.DataFrame:
        """Compute PM2.5 statistics for each polygon in GeoJSON file.

        Args:
            geojson_file: Path to GeoJSON file with polygons.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            id_field: Optional field in GeoJSON properties to use as identifier.

        Returns:
            DataFrame with statistics for each polygon.

        Raises:
            FileNotFoundError: If NetCDF or GeoJSON file not found.

        This function automatically downloads the required NetCDF data from AWS
        if not cached locally.
        """
        # Check GeoJSON file first
        if not os.path.exists(geojson_file):
            raise FileNotFoundError(f"GeoJSON file not found: {geojson_file}")

        # Download NetCDF file if needed
        nc_file = self.download_netcdf_if_needed(year, month)

        # Read GeoJSON and get overall bounding box first
        gdf = gpd.read_file(geojson_file)
        gdf = gdf.to_crs("EPSG:4326")
        bbox = gdf.total_bounds  # [minx, miny, maxx, maxy]

        with xr.open_dataset(nc_file) as ds:
            # Check if this is the new WUSTL format or old format
            if "PM25" in ds.variables:
                pm25_var = "PM25"
            elif "GWRPM25" in ds.variables:
                pm25_var = "GWRPM25"
            else:
                available_vars = list(ds.variables.keys())
                raise ValueError(
                    f"PM2.5 variable not found. Available variables: {available_vars}"
                )

            # Handle coordinate naming variations
            if "latitude" in ds.coords and "longitude" in ds.coords:
                lat_coord, lon_coord = "latitude", "longitude"
            elif "lat" in ds.coords and "lon" in ds.coords:
                lat_coord, lon_coord = "lat", "lon"
            else:
                raise ValueError(
                    "Could not find latitude/longitude coordinates in NetCDF file"
                )

            lat_buffer = 0.1
            lon_buffer = 0.1

            lat_vals = ds[lat_coord].values
            lon_vals = ds[lon_coord].values
            lat_ascending = lat_vals[0] < lat_vals[-1]
            lon_ascending = lon_vals[0] < lon_vals[-1]

            if lat_ascending:
                lat_slice = slice(bbox[1] - lat_buffer, bbox[3] + lat_buffer)
            else:
                lat_slice = slice(bbox[3] + lat_buffer, bbox[1] - lat_buffer)

            if lon_ascending:
                lon_slice = slice(bbox[0] - lon_buffer, bbox[2] + lon_buffer)
            else:
                lon_slice = slice(bbox[2] + lon_buffer, bbox[0] - lon_buffer)

            ds_subset = ds.sel({lat_coord: lat_slice, lon_coord: lon_slice})

            # Extract the PM25 variable
            pm25 = ds_subset[pm25_var]
            pm25 = pm25.load()

            # Ensure coordinates are ascending
            if not lat_ascending:
                pm25 = pm25.sortby(lat_coord)
            if not lon_ascending:
                pm25 = pm25.sortby(lon_coord)

            # Set spatial dimensions for rioxarray
            pm25 = pm25.rio.set_spatial_dims(x_dim=lon_coord, y_dim=lat_coord)
            pm25 = pm25.rio.write_crs("EPSG:4326")

            # Determine column name once at the beginning
            if id_field and id_field in gdf.columns:
                column_name = id_field
            elif "NAME_1" in gdf.columns:
                column_name = "NAME_1"
            elif "name" in gdf.columns:
                column_name = "name"
            else:
                column_name = "index"

            results = []

            # Process each polygon
            for idx, row in gdf.iterrows():
                geom = row.geometry

                try:
                    clipped = pm25.rio.clip([geom], crs="EPSG:4326", all_touched=True)

                    # Get values and filter NaN
                    values = clipped.values.flatten()
                    values = values[~np.isnan(values)]

                    if values.size > 0:
                        mean_val = float(values.mean())
                        std_val = float(values.std())
                    else:
                        mean_val, std_val = np.nan, np.nan
                except Exception:
                    mean_val, std_val = np.nan, np.nan

                # Get feature identifier based on determined column
                if column_name == "index":
                    feature_id = idx
                else:
                    feature_id = row[column_name]

                results.append(
                    {
                        column_name: feature_id,
                        "mean": mean_val,
                        "std": std_val,
                    }
                )

            return pd.DataFrame(results)

    def clear_cache(self) -> None:
        """Clear all cached NetCDF files."""
        if self.cache_dir.exists():
            for file in self.cache_dir.glob("*.nc"):
                try:
                    file.unlink()
                    print(f"Removed: {file}")
                except Exception as e:
                    print(f"Warning: Could not remove {file}: {e}")
            print(f"Cache cleared: {self.cache_dir}")
        else:
            print("Cache directory does not exist")

    def list_cached_files(self) -> List[str]:
        """List all cached NetCDF files.

        Returns:
            List of cached file paths.
        """
        if not self.cache_dir.exists():
            return []

        cached_files = list(self.cache_dir.glob("*.nc"))
        if cached_files:
            print(f"Cached files in {self.cache_dir}:")
            for file in cached_files:
                size_mb = file.stat().st_size / (1024 * 1024)
                print(f"   {file.name} ({size_mb:.1f} MB)")
        else:
            print(f"No cached files in {self.cache_dir}")

        return [str(f) for f in cached_files]
