"""
Legacy client for Central Pollution Control Board (CPCB) web services.

The CPCBClient class gets station data and raw data files from CPCB.
It also finds the stations that are nearest to a location.
"""

from __future__ import annotations

import heapq
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Union, cast

from .constants import (
    ALL_STATION_URL,
    DEFAULT_DOWNLOAD_DIR,
    DOWNLOAD_URL,
    PUBLIC_COOKIES,
)
from .cpcb_live import CPCBLive
from .exceptions import CPCBError, NetworkError
from .utils import (
    _log_if_verbose,
    clean_station_name,
    safe_get,
    sort_station_data,
    station_distances,
    stations_to_dataframe,
)

if TYPE_CHECKING:
    import pandas as pd


class CPCBClient:
    """Legacy client that gets CPCB air quality data."""

    def __init__(self, use_test_endpoint: bool = True) -> None:
        """Initialize the CPCB Client.

        Args:
            use_test_endpoint: Not used. The parameter stays for
                compatibility.
        """
        self.station_url = ALL_STATION_URL
        self.cookies = dict(PUBLIC_COOKIES)

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
        # Same source as CPCBLive: the dashboard list, else the RSS feed
        sorted_stations = sort_station_data(CPCBLive().get_all_india())

        if as_dataframe:
            return stations_to_dataframe(sorted_stations)
        return sorted_stations

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

        if not filename.endswith(f"_{year}.csv"):
            filename = filename.replace(".csv", f"_{year}.csv")

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
        output_dir: str = DEFAULT_DOWNLOAD_DIR,
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
            _log_if_verbose(f"Constructed URL: {url}", verbose)

        _log_if_verbose(f"Downloading CSV from: {url}", verbose)

        try:
            response = safe_get(url, timeout=60, max_retries=3, allow_ssl_fallback=True)

            content_type = response.headers.get("content-type", "").lower()
            if (
                "text/csv" not in content_type
                and "application/octet-stream" not in content_type
            ):
                _log_if_verbose(
                    f"Warning: Unexpected content type: {content_type}", verbose
                )

            generated_filename = self._generate_filename(
                url, site_id, station_name, time_period, year or "", filename
            )

            Path(output_dir).mkdir(parents=True, exist_ok=True)
            file_path = Path(output_dir) / generated_filename

            _log_if_verbose(f"Saving to: {file_path}", verbose)
            with open(file_path, "wb") as f:
                f.write(response.content)

            _log_if_verbose(f"Successfully downloaded: {file_path}", verbose)

            if return_dataframe:
                import pandas as pd

                try:
                    df = pd.read_csv(file_path)
                    _log_if_verbose(f"Loaded DataFrame with shape: {df.shape}", verbose)
                    return df
                except Exception as e:
                    _log_if_verbose(
                        f"Failed to load CSV as DataFrame: {e}; file saved at "
                        f"{file_path}",
                        verbose,
                    )
                    return None

            return str(file_path)

        except NetworkError:
            raise
        except Exception as e:
            raise CPCBError(f"Failed to download CSV: {str(e)}") from e

    def _station_distances(self, lat: float, lon: float) -> List[Tuple[Dict, float]]:
        """All stations with valid coordinates and their haversine distance in km.

        Raises:
            CPCBError: If the client cannot get the station data.
        """
        return station_distances(cast(List[Dict], self.list_stations()), lat, lon)

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
        candidates = [
            (station, distance)
            for station, distance in self._station_distances(lat, lon)
            if station.get("id") is not None
        ]
        if not candidates:
            raise CPCBError("No valid stations found")
        station, distance = min(candidates, key=lambda c: c[1])
        if return_distance:
            return (str(station["id"]), distance)
        return str(station["id"])

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
            CPCBError: If the client cannot get the station data.
        """
        return heapq.nsmallest(k, self._station_distances(lat, lon), key=lambda c: c[1])

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
        in_radius = [
            (station["id"], distance)
            for station, distance in self._station_distances(lat, lon)
            if distance <= max_distance_km and station.get("id") is not None
        ]
        return min(in_radius, key=lambda c: c[1]) if in_radius else None
