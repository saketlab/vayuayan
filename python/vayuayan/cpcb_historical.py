"""
Historical CPCB data: the file paths of the data repository and the downloads.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from enum import Enum, auto
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    cast,
)

import requests

from . import aqi, cpcb_common, http_client, us_aqi_daily
from .constants import get_cache_dir
from .cpcb_batch import BATCH_ERRORS, _collect_stations
from .cpcb_city_reports import (
    CityReportsMixin,
    _copy_is_final,
    _first,
    _save_csv,
)
from .exceptions import (
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)
from .tidy import cpcb_raw_to_long, cpcb_tidy_daily

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

DOWNLOAD_WORKERS = 6

T = TypeVar("T")


# a year segment (of 2020-2021 the later year) or a name ending _YYYY.ext; not site_2025
_YEAR_SEGMENT = re.compile(r"(?:^|/)(?:(?:19|20)\d{2}-)?((?:19|20)\d{2})(?=/|$)")
_YEAR_IN_FILE_NAME = re.compile(r"(?<!site)_((?:19|20)\d{2})\.[^./]+$", re.IGNORECASE)

# Characters allowed in a cache path part
_SAFE_PART = re.compile(r"[^A-Za-z0-9_.-]")
_DOWNLOAD_TOKEN = re.compile(r"[A-Za-z0-9%+/=_-]+")

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
    "15min": "15M",
}


def _entry_has_month(entry: Dict[str, Any], month: str) -> bool:
    """Whether a file entry is for the month; station names can contain one."""
    entry_month = str(entry.get("month") or "").lower()
    if entry_month:
        return entry_month.startswith(month)
    return month in re.split(r"[^a-z]+", str(entry.get("filepath", "")).lower())


def _usable_body(body: bytes) -> bool:
    """False for the empty bodies and error pages CPCB can send with HTTP 200."""
    body = body.lstrip()
    return bool(body) and body[:1] not in (b"<", b"{")


class _Listing(Enum):
    """What a file-path route answered, so a failure cannot pass for no files."""

    FILES = auto()
    NONE = auto()
    FAILED = auto()


def _read_listing(parsed: Any) -> Tuple[_Listing, List[Dict[str, Any]]]:
    """The outcome and file entries of one route's parsed reply.

    None is the empty body of HTTP 204, with which CPCB says it has nothing.
    """
    if parsed is None:
        return _Listing.NONE, []
    if not isinstance(parsed, dict) or parsed.get("status") != "success":
        return _Listing.FAILED, []
    data = parsed.get("data", [])
    if not isinstance(data, list):
        return _Listing.FAILED, []
    entries = [cast(Dict[str, Any], e) for e in data if isinstance(e, dict)]
    return (_Listing.FILES if entries else _Listing.NONE), entries


def _repository_step(filepath: str, step: Callable[[], requests.Response]) -> Any:
    """One request of a repository download: 404 is no such file, else the network."""
    try:
        return step()
    except requests.RequestException as e:
        if http_client.failure_reason(e) == "404":
            raise DataNotFoundError(f"CPCB has no file {filepath}") from e
        raise NetworkError(f"CPCB could not send {filepath}") from e


class CPCBHistorical(CityReportsMixin):
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
        new_api = f"{self.base_url}/caaqms-common/dataRepository"
        self.new_file_path_endpoint = f"{new_api}/file-path"
        self.new_download_link_endpoint = f"{new_api}/get-download-link"
        self.new_download_endpoint = f"{new_api}/download-excel-fileEnc"

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
            CPCB says it has no files for the query.

        Raises:
            NetworkError: If no route gives a definite answer.
            AmbiguousMatchError: If the city is in several states and state is
                not given, or the name fits several stations.
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
        # Not cpcb_common.attempt: HTTP 204 means no files, which is not a failure
        answered_no_files = False
        failures: List[BaseException] = []
        for name, call in endpoints:
            try:
                parsed = call()
            except (requests.RequestException, ValueError) as e:
                logger.info("CPCB %s failed (%s)", name, http_client.failure_reason(e))
                failures.append(e)
                continue
            outcome, entries = _read_listing(parsed)
            # HTTP 204 can mean only this route is empty, so the other route is asked
            if outcome is _Listing.FILES or (
                outcome is _Listing.NONE and parsed is not None
            ):
                return entries
            answered_no_files = answered_no_files or outcome is _Listing.NONE
        if answered_no_files:
            return []
        # the outage, if any, decides how the batch loop reads this error
        cause = next((e for e in failures if cpcb_common.is_outage(e)), None)
        raise NetworkError("CPCB file-path endpoints are unavailable") from (
            cause or (failures[-1] if failures else None)
        )

    def _download_repository_file(self, filepath: str) -> io.BytesIO:
        cached = self._cache_path(filepath)
        if cached is not None and cached.exists():
            body = cached.read_bytes()
            if _usable_body(body):
                logger.debug("Using cached %s", cached)
                return io.BytesIO(body)
        link = _repository_step(
            filepath,
            lambda: cpcb_common.send(
                "get",
                self.new_download_link_endpoint,
                session=self.session,
                headers=self._new_api_headers(),
                params={"file_name": filepath},
            ),
        )
        token = link.content.decode("utf-8", "replace").strip()
        if not _DOWNLOAD_TOKEN.fullmatch(token):
            raise NetworkError(f"CPCB sent no download token for {filepath}")
        # token is already URL-encoded; params would re-encode it (HTTP 400)
        response = _repository_step(
            filepath,
            lambda: cpcb_common.send(
                "get",
                f"{self.new_download_endpoint}?file_name={token}",
                session=self.session,
                headers=self._new_api_headers(),
                timeout=60,
            ),
        )
        if not _usable_body(response.content):
            raise NetworkError(f"CPCB sent no usable file for {filepath}")
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            with http_client.atomic_path(cached) as part:
                part.write_bytes(response.content)
        return io.BytesIO(response.content)

    def _cache_path(self, filepath: str) -> Optional[Path]:
        """Cache file of a repository file, or None if it must not be cached.

        Only files of past years are cached: the year is the largest year in
        the path (see _YEAR_SEGMENT), and files of the
        current year change.
        """
        found = [
            year
            for pattern in (_YEAR_SEGMENT, _YEAR_IN_FILE_NAME)
            for year in pattern.findall(filepath)
        ]
        years = [int(y) for y in found]
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
        # Entries of another year are never used; those without a year may be
        candidates = [e for e in entries if not e.get("year") or str(e["year"]) == year]
        if month:
            month_lower = month.lower()
            return [e for e in candidates if _entry_has_month(e, month_lower)]
        return candidates

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
            if "Month" not in df.columns:
                df.insert(0, "Month", entry.get("month") or month)
            if "Year" not in df.columns:
                df.insert(0, "Year", int(entry.get("year") or year))
            frames.append(df)

        if not frames:
            raise DataNotFoundError(f"No downloadable files found for year {year}")
        return pd.concat(frames, ignore_index=True)

    def _read_year_excel(
        self, entries: List[Dict[str, Any]], year: str
    ) -> Optional[pd.DataFrame]:
        """Read the daily workbook of the year, or return None if there is none."""
        for entry in entries:
            if str(entry.get("year")) == str(year) and entry.get("filepath"):
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
            station_name: Optional station name, used if station_id does not match.
            city: Optional city name. The client then examines only this city.
            state: Optional state name, for cities with the same name.
            tidy: If True, return (and save) long rows with
                vayuayan.tidy.TIDY_COLUMNS instead of CPCB's wide table.

        Returns:
            DataFrame with the raw station observations.

        Raises:
            StationNotFoundError: If the station is not in the directory or the feed.
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
        candidates = self._select_repository_entry(data_file_paths, str(year))
        if not candidates:
            raise DataNotFoundError(
                f"Raw data not found for station {station_id} in year {year}"
            )
        filepath = candidates[0].get("filepath")
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
        """Station ID, name, city and state from the directory or the feed.

        Raises:
            StationNotFoundError: If no station matches.
        """
        info = self._resolved_station(station_id, station_name, state, city)
        if not info:
            raise StationNotFoundError(f"Station {station_id} not found")
        return info

    def _station_queries(
        self,
        station_ids: Optional[Iterable[str]],
        year: Optional[int],
        city: str,
        state: str,
    ) -> List[str]:
        """The stations of a batch call: those given, else the stations of the city.

        Raises:
            ValueError: If the year is missing, or both stations and city are.
            CityNotFoundError: If the city has no stations.
        """
        if year is None:
            raise ValueError("year is required")
        if isinstance(station_ids, str):
            return [station_ids]
        queries = list(station_ids or [])
        if queries:
            return queries
        if not city:
            raise ValueError("Give station_ids or a city")
        return [str(s) for s in self._city_stations(city, state)["station_id"]]

    def raw_readings(
        self,
        station_ids: Optional[Iterable[str]] = None,
        year: Optional[int] = None,
        pollutants: Optional[Iterable[str]] = None,
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Raw 15-minute data of several stations as one long table.

        Stations without a raw file for the year are skipped with a warning.
        An outage stops the run and keeps the stations already fetched. A
        status for each station, by the ID given or the station ID for a city,
        is in attrs["station_status"].

        Args:
            station_ids: Station IDs or names (or one). If None, every station
                of city.
            year: Year.
            pollutants: Optional pollutant names to keep, such as ["PM2.5", "RH"].
            city: City name or code. It narrows names given in station_ids.
            state: State name or code, for cities that share a name.

        Returns:
            DataFrame with TIDY_COLUMNS (see cpcb_raw_to_long).

        Raises:
            ValueError: If the year is missing, or both stations and city are.
            CityNotFoundError: If the city has no stations.
            AmbiguousMatchError: If the city is in several states and state is
                not given.
            NetworkError: If an outage stopped the run before any station.
        """
        import pandas as pd

        from .tidy import TIDY_COLUMNS

        ids = self._station_queries(station_ids, year, city, state)
        keep = None if pollutants is None else set(pollutants)

        def fetch(station: str) -> pd.DataFrame:
            long = self.download_raw_aqi_data_station_level(
                station, str(year), "", tidy=True, city=city, state=state
            )
            return long if keep is None else long[long["pollutant"].isin(keep)]

        batch = _collect_stations(ids, fetch, str, BATCH_ERRORS, stop_on_outage=True)
        batch.raise_if_unavailable()
        if not batch.frames:
            return batch.tagged(pd.DataFrame(columns=TIDY_COLUMNS))
        return batch.tagged(pd.concat(batch.frames, ignore_index=True))

    def daily_aqi(
        self,
        station_id: str,
        year: str,
        day_ends_at: int = 24,
        standard: str = "india",
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Daily AQI of a station, computed from its raw 15-minute data.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            day_ends_at: Hour at which each day's 24 hours end; 16 matches
                CPCB's 4 PM bulletin (see vayuayan.aqi.daily_aqi).
            standard: "india" for the National AQI (vayuayan.aqi.daily_aqi) or
                "us" for the US AQI (vayuayan.us_aqi_daily.daily_us_aqi).
            city: Optional city name or code, to narrow an ambiguous station name.
            state: Optional state name or code, as city.

        Returns:
            One row per day: the AQI, its category, the dominant pollutant and
            the sub-index of each pollutant. With day_ends_at below 24, 1
            January also uses 31 December of the previous year, if CPCB has it.

        Raises:
            ValueError: If standard is not "india" or "us".
            DataNotFoundError: If CPCB has no raw file for the station and year.
            NetworkError: If CPCB does not answer.
        """
        by_standard: Dict[str, Callable[..., pd.DataFrame]] = {
            "india": aqi.daily_aqi,
            "us": us_aqi_daily.daily_us_aqi,
        }
        compute = by_standard.get(standard)
        if compute is None:
            raise ValueError('standard must be "india" or "us"')
        long = self.download_raw_aqi_data_station_level(
            station_id, year, "", tidy=True, city=city, state=state
        )
        if day_ends_at < 24:
            long = self._with_previous_december_31(
                long, station_id, int(year), city, state
            )
        daily = compute(long, day_ends_at=day_ends_at)
        # A window that ends on Jan 1 of the next year is not in this year
        in_year = [d.year == int(year) for d in daily["date"]]
        return daily.loc[in_year].reset_index(drop=True)

    def _with_previous_december_31(
        self,
        long: pd.DataFrame,
        station_id: str,
        year: int,
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """long with 31 December of the year before, if its raw file is there."""
        import pandas as pd

        previous = year - 1
        errors: Tuple[Type[BaseException], ...] = (
            DataNotFoundError, NetworkError, *cpcb_common.SOURCE_ERRORS
        )  # fmt: skip
        # attempt() formats the message with %, so a % in the station id is escaped
        safe_id = station_id.replace("%", "%%")
        earlier = cpcb_common.attempt(
            lambda: self.download_raw_aqi_data_station_level(
                station_id, str(previous), "", tidy=True, city=city, state=state
            ),
            f"No raw data of {safe_id} for {previous}, so 1 January of {year} has "
            "no hours from 31 December: %s",
            logging.WARNING,
            errors,
        )
        if earlier is None:
            return long
        last_day = earlier[earlier["timestamp"] >= pd.Timestamp(previous, 12, 31)]
        return pd.concat([last_day, long], ignore_index=True)

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
            station_name: Optional station name, used if station_id does not match.
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

    def download_past_year_aqi_data_station_level(
        self,
        station_id: str,
        year: str,
        save_location: str,
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Download past AQI data for a specific station.

        Args:
            station_id: Station ID, name, or part of a name.
            year: Year for data.
            save_location: Path to save the downloaded data.
            city: Optional city name or code, to narrow an ambiguous station name.
            state: Optional state name or code, as city.

        Returns:
            The daily data of the year.

        Raises:
            StationNotFoundError: If the station ID is not in the directory.
            DataNotFoundError: If CPCB has no data for the station and year.
            NetworkError: If CPCB does not answer.
        """
        info = self._resolved_station(station_id, "", state, city)
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
        _save_csv(df, save_location)
        return df

    def station_daily(
        self,
        station_ids: Optional[Iterable[str]] = None,
        year: Optional[int] = None,
        cache_dir: Optional[str] = None,
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Daily station AQI in long format.

        Stations that are not found or have no data are skipped with a warning.
        An outage stops the run and keeps the stations already fetched. A
        status for each station, by the ID given or the station ID for a city,
        is in attrs["station_status"].

        Args:
            station_ids: Station IDs or names (or one). If None, every station
                of city.
            year: Year.
            cache_dir: Optional directory for CSV copies (<id>_<year>.csv), read
                back on later calls for past years.
            city: City name or code. It narrows names given in station_ids.
            state: State name or code, for cities that share a name.

        Returns:
            DataFrame with columns station_id, station_name, day, month, value.

        Raises:
            ValueError: If the year is missing, or both stations and city are.
            CityNotFoundError: If the city has no stations.
            AmbiguousMatchError: If the city is in several states and state is
                not given.
            NetworkError: If an outage stopped the run before any station.
        """
        import pandas as pd

        def fetch(query: str) -> pd.DataFrame:
            info = self._resolved_station(query, "", state, city)
            if not info:
                raise StationNotFoundError(f"Station {query} not found")
            path = self._csv_copy(cache_dir, f"{info['station_id']}_{year}.csv")
            if not _copy_is_final(path, year):
                with http_client.atomic_path(path) as part:
                    self.download_past_year_aqi_data_station_level(
                        info["station_id"], str(year), str(part), city, state
                    )
            return cpcb_tidy_daily(pd.read_csv(path)).assign(
                station_id=info["station_id"],
                station_name=info["station_name"],
            )

        batch = _collect_stations(
            self._station_queries(station_ids, year, city, state),
            fetch,
            str,
            BATCH_ERRORS,
            stop_on_outage=True,
        )
        batch.raise_if_unavailable()
        if not batch.frames:
            return batch.tagged(
                pd.DataFrame(
                    columns=["station_id", "station_name", "day", "month", "value"]
                )
            )
        return batch.tagged(
            _first(
                pd.concat(batch.frames, ignore_index=True),
                ["station_id", "station_name"],
            )
        )
