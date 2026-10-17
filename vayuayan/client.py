"""
Legacy client for Central Pollution Control Board (CPCB) web services.

The CPCBClient class gets station data and raw data files from CPCB.
It also finds the stations that are nearest to a location.
"""

import heapq
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, cast

import pandas as pd

from .constants import ALL_STATION_URL, DOWNLOAD_URL, POST_HEADERS
from .exceptions import CPCBError, NetworkError
from .utils import (
    clean_station_name,
    fetch_cpcb_rss_station_data,
    haversine_distance,
    safe_get,
    safe_post,
    sort_station_data,
    stations_to_dataframe,
)


class CPCBClient:
    """Legacy client that gets CPCB air quality data."""

    def __init__(self, use_test_endpoint: bool = True) -> None:
        """Initialize the CPCB Client.

        Args:
            use_test_endpoint: Not used. The parameter stays for
                compatibility.
        """
        self.station_url = ALL_STATION_URL
        self.cookies = {"ccr_public": "A"}

    def list_stations(
        self, as_dataframe: bool = False
    ) -> Union[List[Dict], pd.DataFrame]:
        """Get the list of all air quality monitoring stations.

        Args:
            as_dataframe: If True, return the data as a pandas DataFrame.

        Returns:
            List of station dictionaries or DataFrame if as_dataframe=True.

        Raises:
            CPCBError: If the client cannot get the station data.
        """
        try:
            data = "e30="
            response = safe_post(
                self.station_url, headers=POST_HEADERS, data=data, cookies=self.cookies
            )
            stations = response.get("stations", [])
            sorted_stations = sort_station_data(stations)
        except Exception:
            sorted_stations = fetch_cpcb_rss_station_data()

        if as_dataframe:
            return stations_to_dataframe(sorted_stations)
        return sorted_stations

    def _log_if_verbose(self, message: str, verbose: bool) -> None:
        """Print the message only if verbose mode is on.

        Args:
            message: Message to print.
            verbose: If True, verbose mode is on.
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
        """Make a filename for downloaded data.

        Args:
            url: Source URL.
            site_id: Station site ID.
            station_name: Station name.
            time_period: Time period.
            year: Year.
            filename: Custom filename.

        Returns:
            Filename with the .csv extension.
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

        # Add the year to the filename if it is not there
        if not filename.endswith(f"_{year}.csv"):
            filename = filename.replace(".csv", f"_{year}.csv")

        # Make sure that the extension is .csv
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
        """Download a CSV file from the CPCB data repository.

        Args:
            url: Direct URL of the file. If you give a URL, the client
                ignores the other parameters.
            site_id: Station site ID (necessary if url is None).
            station_name: Station name (necessary if url is None).
            time_period: Time period for data (necessary if url is None).
            year: Year for data (necessary if url is None).
            output_dir: Directory for the downloaded file.
            filename: Optional custom filename. If None, the client makes a filename.
            return_dataframe: If True, return a pandas DataFrame and not a
                file path.
            verbose: If True, print status messages.

        Returns:
            Path to the downloaded file, a DataFrame, or None if the download fails.

        Raises:
            CPCBError: If a necessary parameter is missing or the download fails.
            NetworkError: If the network request fails.

        Examples:
            >>> client = CPCBClient()
            >>> # Download with a direct URL
            >>> path = client.download_raw_data(
            ...     url="https://airquality.cpcb.gov.in/.../Delhi_Punjabi_Bagh_2024.csv"
            ... )
            >>> # Download with parameters
            >>> df = client.download_raw_data(
            ...     site_id="DL001",
            ...     station_name="Punjabi_Bagh",
            ...     time_period="2024",
            ...     year="2024",
            ...     return_dataframe=True
            ... )
        """
        # Make the URL if the caller did not give one
        if url is None:
            if not all([site_id, station_name, time_period, year]):
                raise CPCBError(
                    "Either 'url' must be provided, or all of 'site_id', "
                    "'station_name', 'time_period', and 'year' must be provided"
                )

            site_id_str = cast(str, site_id)
            station_name_str = cast(str, station_name)
            time_period_str = cast(str, time_period)
            year_str = cast(str, year)

            cleaned_station_name = clean_station_name(station_name_str)
            csv_filename = f"{site_id_str}_{cleaned_station_name}_{time_period_str}.csv"
            url = f"{DOWNLOAD_URL}/{time_period_str}/{year_str}/{csv_filename}"
            self._log_if_verbose(f"Constructed URL: {url}", verbose)

        self._log_if_verbose(f"Downloading CSV from: {url}", verbose)

        try:
            # Send the request with a longer timeout for file downloads
            response = safe_get(url, timeout=60, max_retries=3)

            # Examine the content type
            content_type = response.headers.get("content-type", "").lower()
            if (
                "text/csv" not in content_type
                and "application/octet-stream" not in content_type
            ):
                self._log_if_verbose(
                    f"Warning: Unexpected content type: {content_type}", verbose
                )

            # Make the filename
            generated_filename = self._generate_filename(
                url, site_id, station_name, time_period, year or "", filename
            )

            # Make the output directory and the file path
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            file_path = Path(output_dir) / generated_filename

            # Write file
            self._log_if_verbose(f"Saving to: {file_path}", verbose)
            with open(file_path, "wb") as f:
                f.write(response.content)

            self._log_if_verbose(f"Successfully downloaded: {file_path}", verbose)

            # Return a DataFrame if the caller asked for one
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
        """Find the station that is nearest to the given coordinates.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            return_distance: If True, return the distance and the station ID.

        Returns:
            Station ID of the nearest station, or a tuple of (station_id,
            distance) if return_distance is True.

        Raises:
            CPCBError: If the client cannot get the station data, or there are no
                stations.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        if not cities:
            raise CPCBError("No stations available")

        target_lat, target_lon = float(lat), float(lon)
        min_distance = float("inf")
        nearest_station_id: Optional[str] = None

        # Examine all stations one time
        for city in cities:
            for station in city.get("stationsInCity", []):
                try:
                    station_lat = float(station["latitude"])
                    station_lon = float(station["longitude"])

                    # Use the haversine distance, because it is accurate on the globe
                    distance = haversine_distance(
                        target_lat, target_lon, station_lat, station_lon
                    )

                    if distance < min_distance:
                        candidate_id = station.get("id")
                        if candidate_id is None:
                            continue
                        min_distance = distance
                        nearest_station_id = str(candidate_id)

                except (ValueError, KeyError, TypeError):
                    # Ignore stations that have invalid coordinates
                    continue

        if nearest_station_id is None:
            raise CPCBError("No valid stations found")

        if return_distance:
            return (nearest_station_id, min_distance)
        return nearest_station_id

    def get_k_nearest_stations(
        self, lat: float, lon: float, k: int = 5
    ) -> List[Tuple[Dict, float]]:
        """Find the k stations that are nearest to the given coordinates.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            k: Number of nearest stations to return.

        Returns:
            List of tuples: [(station_info, distance), ...], sorted by distance.
            Each station_info dict has: id, name, latitude, longitude,
            live, avg, cityID, and stateID.

        Raises:
            CPCBError: If the client cannot get the station data, or there are no
                stations.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        if not cities:
            raise CPCBError("No stations available")

        target_lat, target_lon = float(lat), float(lon)

        # A min-heap keeps the k nearest stations
        heap: List[Tuple[float, str, float, Dict[str, Any]]] = []

        for city in cities:
            for station in city.get("stationsInCity", []):
                try:
                    station_lat = float(station["latitude"])
                    station_lon = float(station["longitude"])

                    distance = haversine_distance(
                        target_lat, target_lon, station_lat, station_lon
                    )

                    station_id = str(station.get("id", ""))

                    if len(heap) < k:
                        # The heap is not full, so add the station
                        heapq.heappush(heap, (-distance, station_id, distance, station))
                    elif distance < -heap[0][0]:
                        # This station is nearer, so replace the farthest station
                        heapq.heapreplace(
                            heap, (-distance, station_id, distance, station)
                        )

                except (ValueError, KeyError, TypeError):
                    continue

        # Get the results and sort them by distance (nearest first)
        results: List[Tuple[Dict[str, Any], float]] = [
            (station_info, distance) for _, _, distance, station_info in heap
        ]
        return sorted(results, key=lambda x: x[1])

    def get_nearest_station_within_radius(
        self, lat: float, lon: float, max_distance_km: float = 100
    ) -> Optional[Tuple[str, float]]:
        """Find the nearest station in a given radius.

        Args:
            lat: Target latitude.
            lon: Target longitude.
            max_distance_km: Maximum radius in kilometers.

        Returns:
            Tuple of (station_id, distance), or None if no station is in the radius.

        Raises:
            CPCBError: If the client cannot get the station data.
        """
        try:
            cities = self.list_stations()
        except Exception as e:
            raise CPCBError(f"Failed to fetch station data: {str(e)}") from e

        target_lat, target_lon = float(lat), float(lon)

        # Calculate a bounding box to make the search faster
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

                    # Fast bounding box test, to ignore stations that are far away
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
