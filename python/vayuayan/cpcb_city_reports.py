"""
Report exports and city-level downloads of CPCBHistorical.
"""

from __future__ import annotations

import logging
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
)

from . import cpcb_report, http_client
from .cpcb_batch import BATCH_ERRORS, _collect_stations
from .cpcb_directory import CPCBDirectory, _raise_ambiguous_city, _state_key
from .exceptions import (
    CityNotFoundError,
    DataNotFoundError,
    StationNotFoundError,
)
from .tidy import cpcb_raw_to_long, cpcb_tidy_daily

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)


def _save_csv(df: pd.DataFrame, save_location: str) -> None:
    """Write the DataFrame to save_location, if there is one."""
    if save_location:
        df.to_csv(save_location, index=False)


def _copy_is_final(path: Path, year: Any) -> bool:
    """True if a CSV copy can be used: a past year does not change any more."""
    return path.exists() and int(year) < date.today().year


def _first(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    """df with the columns moved to the front."""
    return df[columns + [c for c in df.columns if c not in columns]]


def _download_workers() -> int:
    """The parallel downloads; read late so a patch of the module constant applies."""
    from . import cpcb_historical

    return cpcb_historical.DOWNLOAD_WORKERS


class CityReportsMixin(CPCBDirectory):
    """The report export and the city-level downloads of CPCBHistorical."""

    if TYPE_CHECKING:

        def _resolved_station(
            self,
            station_id: str,
            station_name: str = "",
            state: str = "",
            city: str = "",
        ) -> Optional[Dict[str, str]]: ...

        def get_file_path(
            self,
            station_id: str,
            station_name: str,
            state: str,
            city: str,
            year: str,
            frequency: str,
            data_type: str,
        ) -> List[Dict[str, Any]]: ...

        def _combine_repository_excels(
            self, entries: List[Dict[str, Any]], year: str, month: Optional[str] = None
        ) -> pd.DataFrame: ...

        def _read_year_excel(
            self, entries: List[Dict[str, Any]], year: str
        ) -> Optional[pd.DataFrame]: ...

    def download_station_report(
        self,
        station_id: str,
        start: Any,
        end: Any,
        frequency: str = "15_minute",
        pollutants: Optional[Iterable[str]] = None,
        save_location: str = "",
        tidy: bool = False,
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Station data for any period, from CPCB's report export (no login).

        Args:
            station_id: Station ID, name, or part of a name.
            start: First time (text, date or datetime). A date is its 00:00.
            end: Last time, as start. The report holds the periods that end
                by this time, so use 00:00 of the next day for a whole day.
            frequency: "15_minute", "30_minute", "hourly", "4_hour", "8_hour"
                or "daily", or CPCB's 15M, 30M, 1H, 4H, 8H, 24H.
            pollutants: Pollutants such as ["PM2.5", "NOx", "Ozone"]. The
                default is all nine of the report.
            save_location: Path to save the CSV. If empty, no file is saved.
            tidy: If True, return (and save) long rows with
                vayuayan.tidy.TIDY_COLUMNS instead of the wide table.
            city: Optional city name or code, to narrow an ambiguous station name.
            state: Optional state name or code, as city.

        Returns:
            The columns of the raw station file: Timestamp (the start of each
            period) and one "<name> (<unit>)" column per pollutant. Never cached.

        Raises:
            ValueError: If frequency or a pollutant is not known.
            StationNotFoundError: If the station is not in the directory.
            DataNotFoundError: If CPCB has no data or sends an unusable file.
            NetworkError: If CPCB does not answer.
        """
        info = self._resolved_station(station_id, "", state, city)
        if not info:
            raise StationNotFoundError(f"Station {station_id} not found")
        df = cpcb_report.fetch_report(
            f"{self.base_url}{cpcb_report.REPORT_PATH}",
            info,
            start,
            end,
            frequency,
            pollutants,
            self.session,
        )
        if tidy:
            df = cpcb_raw_to_long(df, info)
        _save_csv(df, save_location)
        return df

    def download_city_report(
        self,
        city: str,
        start: Any,
        end: Any,
        frequency: str = "15_minute",
        pollutants: Optional[Iterable[str]] = None,
        state: str = "",
        save_location: str = "",
        tidy: bool = False,
    ) -> pd.DataFrame:
        """Report export of every station of a city, as one table.

        Stations with no report are skipped with a warning. After a timeout,
        a connection failure or an HTTP 5xx the remaining stations are not
        tried, and the stations that succeeded are still returned. A status for
        each station, by station ID, is in attrs["station_status"].

        Args:
            city: City name or code.
            start: First time; see download_station_report.
            end: Last time; see download_station_report.
            frequency: Interval; see download_station_report.
            pollutants: Pollutants; see download_station_report.
            state: State name or code, for cities that share a name.
            save_location: Path to save the CSV. If empty, no file is saved.
            tidy: If True, return (and save) long rows instead of the wide table.

        Returns:
            The table of download_station_report for each station. The wide
            table starts with station_id and station_name.

        Raises:
            CityNotFoundError: If no station of the directory is in the city.
            AmbiguousMatchError: If the city is in several states and state is
                not given.
            DataNotFoundError: If CPCB has no report for any of its stations.
            NetworkError: If an outage stopped the run before any station.
        """
        import pandas as pd

        def fetch(station: Any) -> pd.DataFrame:
            df = self.download_station_report(
                station.station_id,
                start,
                end,
                frequency,
                pollutants,
                tidy=tidy,
                city=city,
                state=state,
            )
            if not tidy:
                df.insert(0, "station_name", station.station_name)
                df.insert(0, "station_id", station.station_id)
            return df

        batch = _collect_stations(
            list(self._city_stations(city, state).itertuples()),
            fetch,
            lambda station: str(station.station_name),
            BATCH_ERRORS,
            _download_workers(),
            stop_on_outage=True,
            key=lambda station: str(station.station_id),
        )
        batch.raise_if_unavailable()
        if not batch.frames:
            raise DataNotFoundError(f"CPCB has no report for city {city}")
        out = batch.tagged(pd.concat(batch.frames, ignore_index=True))
        _save_csv(out, save_location)
        return out

    def _city_stations(self, city: str, state: str = "") -> pd.DataFrame:
        """The station_table rows of a city.

        Raises:
            CityNotFoundError: If the city has no stations.
            AmbiguousMatchError: If the city is in several states and state is
                not given. station_table lists both; this chooses one.
        """
        stations = self.station_table(state, city)
        if stations.empty:
            raise CityNotFoundError(f"City {city} not found")
        if not state:
            by_key = {_state_key(name): str(name) for name in stations["state"]}
            if len(by_key) > 1:
                _raise_ambiguous_city(city, by_key.values())
        return stations

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

    def download_past_year_aqi_data_city_level(
        self, city: str, year: str, save_location: str, state: str = ""
    ) -> pd.DataFrame:
        """Download past AQI data for a specific city.

        Args:
            city: City name.
            year: Year for data.
            save_location: Path to save the downloaded data.
            state: Optional state name, for cities with the same name.

        Returns:
            The daily data of the year.

        Raises:
            DataNotFoundError: If CPCB has no data for the city and year.
            NetworkError: If CPCB does not answer.
        """
        data_file_paths = self.get_file_path(
            "", "", state, city, "", "daily", "cityLevel"
        )
        df = self._read_year_excel(data_file_paths, year)
        if df is None:
            raise DataNotFoundError(f"Data not found for city {city} in year {year}")
        _save_csv(df, save_location)
        return df

    def city_daily(
        self,
        cities: Iterable[str],
        year: Union[int, Iterable[int]],
        cache_dir: Optional[str] = None,
        state: str = "",
    ) -> pd.DataFrame:
        """Daily city AQI in long format.

        Args:
            cities: City names (or one name).
            year: Year, or several years.
            cache_dir: Optional directory for CSV copies of the sheets
                (<city>_aqi_<year>.csv, or <state>_<city>_aqi_<year>.csv with a
                state), read back on later calls for past years. The default
                is a temporary directory of this client.
            state: State name or code, for cities that share a name.

        Returns:
            DataFrame with columns city, year, day, month, value and date
            (datetime.date), sorted by city and date.

        Raises:
            AmbiguousMatchError: If a city is in several states and state is
                not given.
        """
        import pandas as pd

        years = [int(year)] if isinstance(year, int) else [int(y) for y in year]
        # two states' cities of one name must not share a copy
        stem = f"{state}_" if state else ""
        sheets = [
            (city, y, self._csv_copy(cache_dir, f"{(stem + city).lower()}_aqi_{y}.csv"))
            for city in ([cities] if isinstance(cities, str) else cities)
            for y in years
        ]
        missing = [sheet for sheet in sheets if not _copy_is_final(sheet[2], sheet[1])]
        # one listing per city covers all its years
        listings = {
            city: self.get_file_path("", "", state, city, "", "daily", "cityLevel")
            for city in dict.fromkeys(city for city, _, _ in missing)
        }

        def fetch(sheet: Tuple[str, int, Path]) -> None:
            city, y, path = sheet
            df = self._read_year_excel(listings[city], str(y))
            if df is None:
                raise DataNotFoundError(f"Data not found for city {city} in year {y}")
            with http_client.atomic_path(path) as part:
                _save_csv(df, str(part))

        # the shared Session is thread-safe for these cookie-less requests
        with ThreadPoolExecutor(max_workers=_download_workers()) as pool:
            list(pool.map(fetch, missing))
        frames = [
            cpcb_tidy_daily(pd.read_csv(path), y).assign(city=city, year=y)
            for city, y, path in sheets
        ]
        return _first(pd.concat(frames, ignore_index=True), ["city", "year"])

    _csv_tmp: Optional[Path] = None

    def _csv_copy(self, cache_dir: Optional[str], name: str) -> Path:
        """Path of a CSV copy in cache_dir, or in a temporary folder of this
        client, so stale or planted files in the shared temporary directory
        are never read."""
        if cache_dir:
            folder = Path(cache_dir)
            folder.mkdir(parents=True, exist_ok=True)
        else:
            if self._csv_tmp is None:
                self._csv_tmp = Path(tempfile.mkdtemp(prefix="vayuayan_"))
            folder = self._csv_tmp
        return folder / name
