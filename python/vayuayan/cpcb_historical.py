"""
Historical CPCB data: the file paths of the data repository and the downloads.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple, cast

import requests

from . import aqi, cpcb_common, http_client
from .constants import get_cache_dir
from .cpcb_directory import CPCBDirectory
from .exceptions import DataNotFoundError, NetworkError, StationNotFoundError
from .tidy import cpcb_raw_to_long

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


# A four-digit year in a repository file path
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")

# Characters allowed in a cache path part
_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]")

# Frequency names of the package -> codes of the new CPCB file-path API
_FREQUENCY_CODES = {
    "hourly": "1H",
    "1_hour": "1H",
    "1h": "1H",
    "daily": "1D",
    "24_hours": "1D",
    "24h": "1D",
    "1d": "1D",
    "monthly": "1M",
    "1m": "1M",
    "15_minute": "15M",
    "15m": "15M",
}


def _save_csv(df: pd.DataFrame, save_location: str) -> None:
    """Write the DataFrame to save_location, if there is one."""
    if save_location:
        df.to_csv(save_location, index=False)


def _file_entries(parsed: Any) -> Optional[List[Dict[str, Any]]]:
    """Return the file entries of a successful file-path response, else None."""
    if not isinstance(parsed, dict) or parsed.get("status") != "success":
        return None
    data = parsed.get("data", [])
    if not isinstance(data, list):
        return None
    return [cast(Dict[str, Any], entry) for entry in data if isinstance(entry, dict)]


class CPCBHistorical(CPCBDirectory):
    """Client that gets historical Air Quality Index (AQI) data from CPCB."""

    def __init__(self, cache_dir: Optional[str] = None, use_cache: bool = True) -> None:
        """Initialize the AQI Client with CPCB endpoints and headers.

        Args:
            cache_dir: Directory for downloaded repository files. The default
                is the "cpcb" folder in get_cache_dir() (~/.cache/vayuayan).
            use_cache: If False, always download. Files of the current year
                are never cached, because CPCB still adds data to them.
        """
        super().__init__()
        self.cache_dir: Optional[Path] = (
            (Path(cache_dir) if cache_dir else get_cache_dir() / "cpcb")
            if use_cache
            else None
        )
        self.file_path_endpoint = f"{self.data_repository}file_Path"
        self.new_file_path_endpoint = (
            f"{self.base_url}/caaqms-common/dataRepository/file-path"
        )
        self.new_download_endpoint = (
            f"{self.base_url}/caaqms-common/dataRepository/download-excel-file"
        )

    def _normalize_frequency(self, frequency: str) -> str:
        return _FREQUENCY_CODES.get(frequency.lower(), frequency)

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
        """Get the data file paths for the query parameters.

        Args:
            station_id: Station ID, name, or part of a name.
            station_name: Station name.
            state: State name.
            city: City name.
            year: Year for data.
            frequency: Data frequency ('hourly' or 'daily').
            data_type: Type of data ('cityLevel', 'stationLevel' or 'raw').

        Returns:
            List of file entries, each with a file path. The list is empty if
            CPCB answers but has no files for the query.

        Raises:
            NetworkError: If no CPCB endpoint answers.
        """
        legacy_payload = {
            "station_id": station_id,
            "station_name": station_name,
            "state": state,
            "city": city,
            "year": year,
            "frequency": frequency,
            "dataType": data_type,
        }
        payload = {**legacy_payload, "frequency": self._normalize_frequency(frequency)}

        # The new API wants the directory spelling of the names
        if data_type == "cityLevel":
            state_entry, city_entry = self._resolve_city(city, state)
            if state_entry and city_entry:
                payload.update(
                    station_id="",
                    station_name="",
                    state=str(state_entry.get("state_name", "")),
                    city=str(city_entry.get("city_name", "")),
                )
        elif data_type in ("stationLevel", "raw"):
            info = self._resolved_station(station_id, station_name, state, city)
            if info:
                payload.update(info)
                legacy_payload.update(
                    station_id=info["station_id"], station_name=info["station_name"]
                )

        endpoints: List[Tuple[str, Callable[[], Any]]] = [
            (
                "file-path",
                lambda: self._new_api_json(
                    "post", self.new_file_path_endpoint, json_data=payload
                ),
            ),
            (
                "legacy file_Path",
                lambda: cpcb_common.legacy_post(
                    f"{self.base_url}{self.file_path_endpoint}",
                    legacy_payload,
                    headers=self.headers,
                    session=self.session,
                ),
            ),
        ]
        # Not cpcb_common.attempt: a None answer (HTTP 204) means CPCB answered
        # with no files, which must not look like a failure
        answered = False
        for name, call in endpoints:
            try:
                entries = _file_entries(call())
            except (requests.RequestException, ValueError) as e:
                logger.info("CPCB %s failed (%s)", name, http_client.failure_reason(e))
                continue
            answered = True
            if entries is not None:
                return entries
        if not answered:
            raise NetworkError("CPCB file-path endpoints are unavailable")
        return []

    def _download_repository_file(self, filepath: str) -> io.BytesIO:
        cached = self._cache_path(filepath)
        if cached is not None and cached.exists():
            logger.debug("Using cached %s", cached)
            return io.BytesIO(cached.read_bytes())
        response = cpcb_common.send(
            "get",
            self.new_download_endpoint,
            session=self.session,
            headers=self._new_api_headers(),
            params={"file_name": filepath},
            timeout=60,
        )
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            with http_client.atomic_path(cached) as part:
                part.write_bytes(response.content)
        return io.BytesIO(response.content)

    def _cache_path(self, filepath: str) -> Optional[Path]:
        """Cache file of a repository file, or None if it must not be cached.

        Only files of past years are cached: the year is the largest
        four-digit year in the path, and files of the current year change.
        """
        years = [int(y) for y in _YEAR.findall(filepath)]
        if self.cache_dir is None or not years or max(years) >= date.today().year:
            return None
        parts = [
            _SAFE_PART.sub("_", p)
            for p in filepath.split("/")
            if p not in ("", ".", "..")
        ]
        return self.cache_dir.joinpath(*parts) if parts else None

    def _read_repository_excel(self, filepath: str) -> pd.DataFrame:
        import pandas as pd

        return pd.read_excel(self._download_repository_file(filepath))

    def _read_repository_csv(self, filepath: str) -> pd.DataFrame:
        import pandas as pd

        return pd.read_csv(self._download_repository_file(filepath))

    def _select_repository_entry(
        self,
        entries: List[Dict[str, Any]],
        year: str,
        month: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if month:
            month_lower = month.lower()
            return [
                entry
                for entry in entries
                if str(entry.get("month", "")).lower() == month_lower
                or month_lower in str(entry.get("filepath", "")).lower()
            ]

        year_matches = [
            entry for entry in entries if str(entry.get("year", "")) == year
        ]
        if year_matches:
            return year_matches
        return entries

    def _combine_repository_excels(
        self, entries: List[Dict[str, Any]], year: str, month: Optional[str] = None
    ) -> pd.DataFrame:
        import pandas as pd

        selected_entries = self._select_repository_entry(entries, year, month)
        if not selected_entries:
            raise DataNotFoundError(
                f"Data not found for year {year}"
                + (f" and month {month}" if month else "")
            )

        frames = []
        for entry in selected_entries:
            filepath = entry.get("filepath")
            if not filepath:
                continue
            df = self._read_repository_excel(str(filepath))
            if entry.get("month") and "Month" not in df.columns:
                df.insert(0, "Month", entry.get("month"))
            if entry.get("year") and "Year" not in df.columns:
                df.insert(0, "Year", entry.get("year"))
            frames.append(df)

        if not frames:
            raise DataNotFoundError(f"No downloadable files found for year {year}")
        return pd.concat(frames, ignore_index=True)

    def _read_year_excel(
        self, entries: List[Dict[str, Any]], year: str
    ) -> Optional[pd.DataFrame]:
        """Read the daily workbook of the year, or return None if there is none."""
        for entry in entries:
            if str(entry.get("year")) == str(year):
                df = self._read_repository_excel(str(entry["filepath"]))
                return df.iloc[:31]  # Keep 31 rows: the maximum days in a month
        return None

    def download_raw_aqi_data_station_level(
        self,
        station_id: str,
        year: str,
        save_location: str,
        frequency: str = "15_minute",
        station_name: str = "",
        city: str = "",
        state: str = "",
        tidy: bool = False,
    ) -> pd.DataFrame:
        """Download raw CPCB station data, for example 15-minute observations.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            save_location: Path to save the CSV. If empty, no file is saved.
            frequency: Raw data interval. CPCB supports values such as
                "15_minute", "1H", and "1D" for raw station files.
            station_name: Optional station name. The client then does not look it up.
            city: Optional city name. The client then examines only this city.
            state: Optional state name, for cities with the same name.
            tidy: If True, return (and save) long rows with
                vayuayan.tidy.TIDY_COLUMNS instead of CPCB's wide table.

        Returns:
            DataFrame with the raw station observations.

        Raises:
            DataNotFoundError: If CPCB has no raw file for the station and year.
            NetworkError: If CPCB does not answer.
        """
        info = self._station_info(station_id, station_name, city, state)
        data_file_paths = self.get_file_path(
            info["station_id"],
            info["station_name"],
            info["state"],
            info["city"],
            year,
            frequency,
            "raw",
        )
        if not data_file_paths:
            raise DataNotFoundError(
                f"Raw data not found for station {station_id} in year {year}"
            )

        filepath = data_file_paths[0].get("filepath")
        if not filepath:
            raise DataNotFoundError(
                f"No downloadable raw file found for station {station_id}"
            )

        df = self._read_repository_csv(str(filepath))
        if tidy:
            df = cpcb_raw_to_long(df, info)
        _save_csv(df, save_location)
        return df

    def _resolved_station(
        self, station_id: str, station_name: str = "", state: str = "", city: str = ""
    ) -> Optional[Dict[str, str]]:
        """Directory spelling of the station ID, name, city and state, or None."""
        state_entry, city_entry, station = self._resolve_station(
            station_id, station_name, state, city
        )
        if not (state_entry and city_entry and station):
            return None
        return {
            "station_id": str(station.get("station_id", "")),
            "station_name": str(station.get("station_name", "")),
            "city": str(city_entry.get("city_name", "")),
            "state": str(state_entry.get("state_name", "")),
        }

    def _station_info(
        self, station_id: str, station_name: str = "", city: str = "", state: str = ""
    ) -> Dict[str, str]:
        """Station ID, name, city and state, from the directory where possible."""
        return self._resolved_station(station_id, station_name, state, city) or {
            "station_id": station_id,
            "station_name": station_name,
            "city": city,
            "state": state,
        }

    def daily_aqi(
        self, station_id: str, year: str, day_ends_at: int = 24
    ) -> pd.DataFrame:
        """Daily National AQI of a station, computed from its raw 15-minute data.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            day_ends_at: Hour at which each day's 24 hours end; 16 matches
                CPCB's 4 PM bulletin (see vayuayan.aqi.daily_aqi).

        Returns:
            One row per day: the AQI, its category, the dominant pollutant and
            the sub-index of each pollutant.

        Raises:
            DataNotFoundError: If CPCB has no raw file for the station and year.
            NetworkError: If CPCB does not answer.
        """
        long = self.download_raw_aqi_data_station_level(station_id, year, "", tidy=True)
        daily = aqi.daily_aqi(long, day_ends_at=day_ends_at)
        # A window that ends on Jan 1 of the next year is not in this year
        in_year = [d.year == int(year) for d in daily["date"]]
        return daily[in_year].reset_index(drop=True)

    def download_hourly_aqi_data_city_level(
        self,
        city: str,
        year: str,
        save_location: str,
        month: Optional[str] = None,
        state: str = "",
    ) -> pd.DataFrame:
        """Download hourly AQI data for a city.

        Args:
            city: City name.
            year: Year for data.
            save_location: Path to save the combined CSV. If empty, no file is saved.
            month: Optional month name, for example "January". If None, the
                client combines all the monthly workbooks for the year.
            state: Optional state name, for cities with the same name.

        Returns:
            DataFrame with hourly AQI data.
        """
        data_file_paths = self.get_file_path(
            "", "", state, city, year, "hourly", "cityLevel"
        )
        df = self._combine_repository_excels(data_file_paths, str(year), month)
        _save_csv(df, save_location)
        return df

    def download_hourly_aqi_data_station_level(
        self,
        station_id: str,
        year: str,
        save_location: str,
        month: Optional[str] = None,
        station_name: str = "",
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Download hourly AQI data for a station.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            save_location: Path to save the combined CSV. If empty, no file is saved.
            month: Optional month name, for example "January". If None, the
                client combines all the monthly workbooks for the year.
            station_name: Optional station name. The client then does not look it up.
            city: Optional city name. The client then examines only this city.
            state: Optional state name, for cities with the same name.

        Returns:
            DataFrame with hourly AQI data.
        """
        data_file_paths = self.get_file_path(
            station_id,
            station_name,
            state,
            city,
            year,
            "hourly",
            "stationLevel",
        )
        df = self._combine_repository_excels(data_file_paths, str(year), month)
        _save_csv(df, save_location)
        return df

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
            DataNotFoundError: If CPCB has no data for the city and year.
            NetworkError: If CPCB does not answer.
        """
        data_file_paths = self.get_file_path("", "", "", city, "", "daily", "cityLevel")
        df = self._read_year_excel(data_file_paths, year)
        if df is None:
            raise DataNotFoundError(f"Data not found for city {city} in year {year}")
        _save_csv(df, save_location)
        return df

    def download_past_year_aqi_data_station_level(
        self, station_id: str, year: str, save_location: str
    ) -> pd.DataFrame:
        """Download past AQI data for a specific station.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            save_location: Path to save the downloaded data.

        Returns:
            DataFrame preview of the downloaded data.

        Raises:
            StationNotFoundError: If the station ID is not in the directory.
            DataNotFoundError: If CPCB has no data for the station and year.
            NetworkError: If CPCB does not answer.
        """
        info = self._resolved_station(station_id)
        if not info:
            raise StationNotFoundError(f"Station {station_id} not found")

        data_file_paths = self.get_file_path(
            info["station_id"],
            info["station_name"],
            info["state"],
            info["city"],
            "",
            "daily",
            "stationLevel",
        )

        df = self._read_year_excel(data_file_paths, year)
        if df is None:
            raise DataNotFoundError(
                f"Data not found for station {station_id} in year {year}"
            )
        df.to_csv(save_location, index=False)
        return df.head()
