"""
CPCB Client module for interacting with Central Pollution Control Board services.

This module provides the main client class for fetching air quality monitoring data
from CPCB web services, including station data, raw data downloads, and geographic
station lookups.
"""

import heapq
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from .constants import ALL_STATION_URL, DOWNLOAD_URL, POST_HEADERS
from .exceptions import CPCBError, NetworkError
from .utils import (clean_station_name, haversine_distance, safe_get,
                    safe_post, sort_station_data, stations_to_dataframe,
                    url_encode)


class CPCBClient:
    """Main client for fetching air quality data from Central Pollution Control Board."""

    def __init__(self, use_test_endpoint: bool = True) -> None:
        """Initialize the CPCB Client.

        Args:
            use_test_endpoint: Whether to use the test endpoint (unused, kept for compatibility).
        """
        self.station_url = ALL_STATION_URL
        self.cookies = {"ccr_public": "A"}

    def list_stations(
        self, as_dataframe: bool = False
    ) -> Union[List[Dict], pd.DataFrame]:
        """Get list of all available air quality monitoring stations.

        Args:
            as_dataframe: Whether to return data as pandas DataFrame.

        Returns:
            List of station dictionaries or DataFrame if as_dataframe=True.

        Raises:
            CPCBError: If failed to fetch station data.
        """
        try:
            data = "e30="
            response = safe_post(
                self.station_url, headers=POST_HEADERS, data=data, cookies=self.cookies
            )
            stations = response.get("stations", [])
            sorted_stations = sort_station_data(stations)

            if as_dataframe:
                return stations_to_dataframe(sorted_stations)
            return sorted_stations
        except Exception as e:
            raise CPCBError(f"Failed to fetch stations: {str(e)}") from e

    def _log_if_verbose(self, message: str, verbose: bool) -> None:
        """Print message only if verbose mode is enabled.

        Args:
            message: Message to print.
            verbose: Whether verbose mode is enabled.
        """
        if verbose:
            print(message)

    def _generate_filename(
        self,
        url: Optional[str],
        site_id: Optional[str],
        station_name: Optional[str],
        time_period: Optional[str],
        year: str,
        filename: Optional[str],
    ) -> str:
        """Generate filename for downloaded data.

        Args:
            url: Source URL.
            site_id: Station site ID.
            station_name: Station name.
            time_period: Time period.
            year: Year.
            filename: Custom filename.

        Returns:
            Generated filename with .csv extension.
        """
        if filename is None:
            if url:
                filename = url.split("/")[-1]
                if "?" in filename:
                    filename = filename.split("?")[0]
                if not filename.endswith(".csv"):
                    filename += ".csv"
            else:
                filename = f"{site_id}_{station_name}_{time_period}.csv"

        # Add year to filename if not already present
        if not filename.endswith(f"_{year}.csv"):
            filename = filename.replace(".csv", f"_{year}.csv")

        # Ensure .csv extension
        if not filename.endswith(".csv"):
            filename += ".csv"

        return filename

    def download_raw_data(
        self,
        url: Optional[str] = None,
        site_id: Optional[str] = None,
        station_name: Optional[str] = None,
        time_period: Optional[str] = "15Min",
        year: Optional[str] = None,
        output_dir: str = "downloads",
        filename: Optional[str] = None,
        return_dataframe: bool = False,
        verbose: bool = False,
    ) -> Union[str, pd.DataFrame, None]:
        """Download CSV file from CPCB data repository.

        Args:
            url: Direct URL to download from (if provided, other parameters are ignored).
            site_id: Station site ID (required if url not provided).
            station_name: Station name (required if url not provided).
            time_period: Time period for data (required if url not provided).
            year: Year for data (required if url not provided).
            output_dir: Directory to save downloaded file.
            filename: Custom filename (optional, auto-generated if not provided).
            return_dataframe: Whether to return pandas DataFrame instead of file path.
            verbose: Whether to print status messages.

        Returns:
            Path to downloaded file, DataFrame, or None if download fails.

        Raises:
            CPCBError: If required parameters are missing or download fails.
            NetworkError: If network request fails.

        Examples:
            >>> client = CPCBClient()
            >>> # Download using direct URL
            >>> path = client.download_raw_data(
            ...     url="https://airquality.cpcb.gov.in/.../Delhi_Punjabi_Bagh_2024.csv"
            ... )
            >>> # Download using parameters
            >>> df = client.download_raw_data(
            ...     site_id="DL001",
            ...     station_name="Punjabi_Bagh",
            ...     time_period="2024",
            ...     year="2024",
            ...     return_dataframe=True
            ... )
        """
        # Construct URL if not provided directly
        if url is None:
            if not all([site_id, station_name, time_period, year]):
                raise CPCBError(
                    "Either 'url' must be provided, or all of 'site_id', 'station_name', "
                    "'time_period', and 'year' must be provided"
                )

            cleaned_station_name = clean_station_name(station_name)
            csv_filename = f"{site_id}_{cleaned_station_name}_{time_period}.csv"
            url = f"{DOWNLOAD_URL}/{time_period}/{year}/{csv_filename}"
            self._log_if_verbose(f"Constructed URL: {url}", verbose)

        self._log_if_verbose(f"Downloading CSV from: {url}", verbose)

        try:
            # Make the request with longer timeout for file downloads
            response = safe_get(url, timeout=60, max_retries=3)

            # Check content type
            content_type = response.headers.get("content-type", "").lower()
            if (
                "text/csv" not in content_type
                and "application/octet-stream" not in content_type
            ):
                self._log_if_verbose(
                    f"Warning: Unexpected content type: {content_type}", verbose
                )

            # Generate filename
            generated_filename = self._generate_filename(
                url, site_id, station_name, time_period, year or "", filename
            )

            # Create output directory and file path
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            file_path = Path(output_dir) / generated_filename

            # Write file
            self._log_if_verbose(f"Saving to: {file_path}", verbose)
            with open(file_path, "wb") as f:
                f.write(response.content)

            self._log_if_verbose(f"Successfully downloaded: {file_path}", verbose)

            # Return DataFrame if requested
            if return_dataframe:
                try:
                    df = pd.read_csv(file_path)
                    self._log_if_verbose(
                        f"Loaded DataFrame with shape: {df.shape}", verbose
                    )
                    return df
                except Exception as e:
                    self._log_if_verbose(
                        f"Failed to load CSV as DataFrame: {e}", verbose
                    )
                    if verbose:
                        print(f"File saved at: {file_path}")
                    return None

            return str(file_path)

        except NetworkError:
            raise
        except Exception as e:
            raise CPCBError(f"Failed to download CSV: {str(e)}") from e

    def get_nearest_station(
        self, lat: float, lon: float, return_distance: bool = False
    ) -> Union[str, Tuple[str, float]]:
        """Find the nearest station to given coordinates using optimized algorithms.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            return_distance: Whether to return distance along with station ID.

        Returns:
            Station ID of nearest station, or tuple of (station_id, distance) if return_distance=True.

        Raises:
            CPCBError: If failed to fetch station data or no stations available.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        if not cities:
            raise CPCBError("No stations available")

        target_lat, target_lon = float(lat), float(lon)
        min_distance = float("inf")
        nearest_station_id = None

        # Single pass through all stations
        for city in cities:
            for station in city.get("stationsInCity", []):
                try:
                    station_lat = float(station["latitude"])
                    station_lon = float(station["longitude"])

                    # Use haversine distance for accurate geographical distance
                    distance = haversine_distance(
                        target_lat, target_lon, station_lat, station_lon
                    )

                    if distance < min_distance:
                        min_distance = distance
                        nearest_station_id = station["id"]

                except (ValueError, KeyError, TypeError):
                    # Skip stations with invalid coordinates
                    continue

        if nearest_station_id is None:
            raise CPCBError("No valid stations found")

        if return_distance:
            return (nearest_station_id, min_distance)
        return nearest_station_id

    def get_k_nearest_stations(
        self, lat: float, lon: float, k: int = 5
    ) -> List[Tuple[Dict, float]]:
        """Find the k nearest stations to given coordinates.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            k: Number of nearest stations to return.

        Returns:
            List of tuples: [(station_info, distance), ...] sorted by distance.
            Each station_info dict contains: id, name, latitude, longitude, live, avg, cityID, stateID.

        Raises:
            CPCBError: If failed to fetch station data or no stations available.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        if not cities:
            raise CPCBError("No stations available")

        target_lat, target_lon = float(lat), float(lon)

        # Use a min-heap to efficiently track k nearest stations
        heap = []

        for city in cities:
            for station in city.get("stationsInCity", []):
                try:
                    station_lat = float(station["latitude"])
                    station_lon = float(station["longitude"])

                    distance = haversine_distance(
                        target_lat, target_lon, station_lat, station_lon
                    )

                    if len(heap) < k:
                        # Heap not full, add station
                        heapq.heappush(
                            heap, (-distance, station["id"], distance, station)
                        )
                    elif distance < -heap[0][0]:
                        # Found closer station, replace farthest
                        heapq.heapreplace(
                            heap, (-distance, station["id"], distance, station)
                        )

                except (ValueError, KeyError, TypeError):
                    continue

        # Extract results and sort by distance (closest first)
        results = [(station_info, distance) for _, _, distance, station_info in heap]
        return sorted(results, key=lambda x: x[1])

    def get_nearest_station_within_radius(
        self, lat: float, lon: float, max_distance_km: float = 100
    ) -> Optional[Tuple[str, float]]:
        """Find nearest station within a specified radius.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            max_distance_km: Maximum search radius in kilometers.

        Returns:
            Tuple of (station_id, distance) or None if no station found within radius.

        Raises:
            CPCBError: If failed to fetch station data.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        target_lat, target_lon = float(lat), float(lon)

        # Calculate bounding box for optimization
        # 1 degree latitude ≈ 111 km
        # 1 degree longitude ≈ 111 km * cos(latitude)
        lat_delta = max_distance_km / 111.0
        lon_delta = max_distance_km / (111.0 * math.cos(math.radians(target_lat)))

        min_lat = target_lat - lat_delta
        max_lat = target_lat + lat_delta
        min_lon = target_lon - lon_delta
        max_lon = target_lon + lon_delta

        min_distance = float("inf")
        nearest_station = None

        for city in cities:
            for station in city.get("stationsInCity", []):
                try:
                    station_lat = float(station["latitude"])
                    station_lon = float(station["longitude"])

                    # Quick bounding box check for optimization
                    if not (
                        min_lat <= station_lat <= max_lat
                        and min_lon <= station_lon <= max_lon
                    ):
                        continue

                    distance = haversine_distance(
                        target_lat, target_lon, station_lat, station_lon
                    )

                    if distance <= max_distance_km and distance < min_distance:
                        min_distance = distance
                        nearest_station = (station["id"], distance)

                except (ValueError, KeyError, TypeError):
                    continue

        return nearest_station
