"""
Client classes for CPCB air quality data and PM2.5 satellite data.

The classes get AQI data and live station data from the Central Pollution
Control Board (CPCB) of India. They also get PM2.5 satellite data.
"""

import base64
import io
import json
import os
import zipfile
from datetime import datetime
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union, cast
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

try:
    import ee

    GEE_AVAILABLE = True
except ImportError:
    GEE_AVAILABLE = False

try:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config

    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False

from .constants import get_cpcb_credentials, get_gee_project_file
from .utils import fetch_cpcb_rss_station_data, station_data_to_dropdown

# Disable SSL warnings, because some CPCB endpoints have bad certificates
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def setup_earth_engine(project_id: Optional[str] = None) -> bool:
    """Set up Google Earth Engine with a Cloud project.

    This function sets up the Earth Engine authentication and saves the
    project ID.

    Args:
        project_id: Optional Google Cloud project ID. If None, the
                   function asks the user for the ID.

    Returns:
        True if setup succeeded, False otherwise.

    Example:
        >>> from vayuayan import setup_earth_engine
        >>> setup_earth_engine()
        # Follow the prompts to enter your project ID
    """
    if not GEE_AVAILABLE:
        print("✗ Earth Engine library not installed")
        print("  Install it with: pip install earthengine-api")
        return False

    print("=" * 70)
    print("Google Earth Engine Setup")
    print("=" * 70)
    print()

    # Use the authentication that exists, if there is one
    if project_id:
        print(f"Using project ID: {project_id}")
    else:
        try:
            # Initialize without a project to find the authentication status
            ee.Initialize()
            print("✓ Already authenticated!")
            print("\nNote: You still need a project ID for the new API.")
            print("Visit https://code.earthengine.google.com/ to register.")
            print()
        except Exception:
            pass

        print("STEP-BY-STEP INSTRUCTIONS:")
        print("-" * 70)
        print()
        print("1. Open this URL in your browser:")
        print("   https://code.earthengine.google.com/")
        print()
        print("2. Click 'Register a Noncommercial or Commercial Cloud project'")
        print()
        print("3. Select or create a Google Cloud project")
        print("   - If you don't have one, it will create one for you")
        print("   - Choose 'Noncommercial' (free for research/education)")
        print()
        print("4. Copy the project ID (e.g., 'ee-myproject123')")
        print()
        print("-" * 70)
        print()

        try:
            project_id = input("Enter your Google Cloud project ID: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nSetup cancelled.")
            return False

        if not project_id:
            print("\n✗ No project ID provided. Exiting.")
            return False

    print(f"\nUsing project: {project_id}")
    print("\nAuthenticating with Earth Engine...")
    print("(A browser window will open for authentication)")
    print()

    try:
        # Authenticate
        ee.Authenticate(force=True)

        # Initialize with the project
        print(f"\nInitializing Earth Engine with project '{project_id}'...")
        ee.Initialize(project=project_id)

        # Do a test of the access
        print("\nTesting data access...")
        collection = ee.ImageCollection(
            "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25/MONTHLY"
        )
        count = collection.size().getInfo()

        print("\n" + "=" * 70)
        print("✓ SUCCESS!")
        print("=" * 70)
        print(f"\n✓ Earth Engine authenticated with project: {project_id}")
        print(f"✓ Can access PM2.5 data collection ({count} images)")

        gee_project_file = get_gee_project_file()
        gee_project_file.write_text(project_id)
        print(f"✓ Project ID saved to {gee_project_file}")

        print()
        print("You can now use PM25Client to download data!")
        print()
        print("Example:")
        print("  >>> from vayuayan import PM25Client")
        print("  >>> client = PM25Client()")
        print("  >>> data = client.get_pm25_at_point(28.6139, 77.2090, 2020, 1)")
        print()

        return True

    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        return False
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print()
        print("Troubleshooting:")
        print("1. Make sure you registered at https://code.earthengine.google.com/")
        print("2. Verify your project ID is correct")
        print("3. Wait a few minutes for permissions to propagate")
        print("4. Try running setup_earth_engine() again")
        return False


def _request_with_ssl_fallback(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    data: Optional[Union[str, bytes]] = None,
    cookies: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    stream: bool = False,
    session: Optional[requests.Session] = None,
    **kwargs: Any,
) -> requests.Response:
    """Send an HTTP request, and send it again without SSL if SSL fails.

    The function first sends the request with SSL verification. If an SSL error
    occurs, the function sends the request again without SSL verification.

    Args:
        method: HTTP method ('get' or 'post').
        url: Request URL.
        headers: Optional request headers.
        data: Optional request data.
        cookies: Optional request cookies.
        timeout: Request timeout in seconds.
        stream: If True, stream the response.
        session: Optional session to send the request through.
        **kwargs: More arguments for requests.

    Returns:
        Response object.

    Raises:
        requests.RequestException: If the request without SSL verification fails.
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

    send = session.request if session else requests.request
    try:
        request_kwargs["verify"] = True
        response = send(method, url, **request_kwargs)  # nosec B113
        response.raise_for_status()
        return response
    except requests.exceptions.SSLError as e:
        print(f"SSL verification failed: {e}")
        print("Retrying with SSL verification disabled...")
        try:
            request_kwargs["verify"] = False
            response = send(method, url, **request_kwargs)  # nosec B113
            response.raise_for_status()
            return response
        except Exception as fallback_error:
            raise requests.RequestException(
                f"Request failed even with SSL verification disabled: {fallback_error}"
            ) from fallback_error


StationEntry = Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]

# level -> (custom query name, filter field) for the CPCB station directory
DIRECTORY_QUERIES = {
    "states": ("get-state-master-list-data", ""),
    "cities": ("get-city-master-list", "state_code"),
    "stations": ("get-site-station-master-data-list", "city_code"),
}


@lru_cache(maxsize=1)
def _station_directory() -> Dict[str, Any]:
    """Bundled snapshot of the CPCB station directory (states, cities, stations)."""
    path = resources.files("vayuayan").joinpath("data/cpcb_station_directory.json")
    return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _file_entries(parsed: Any) -> Optional[List[Dict[str, Any]]]:
    """Return the file entries of a successful file-path response, else None."""
    if not isinstance(parsed, dict) or parsed.get("status") != "success":
        return None
    data = parsed.get("data", [])
    if not isinstance(data, list):
        return None
    return [cast(Dict[str, Any], entry) for entry in data if isinstance(entry, dict)]


class CPCBHistorical:
    """Client that gets historical Air Quality Index (AQI) data from CPCB."""

    def __init__(self) -> None:
        """Initialize the AQI Client with CPCB endpoints and headers."""
        self.base_url = "https://airquality.cpcb.gov.in"
        self.data_repository = "/dataRepository/"
        self.dropdown_endpoint = f"{self.data_repository}all_india_stationlist"
        self.file_path_endpoint = f"{self.data_repository}file_Path"

        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "q=0.8;application/json;q=0.9",
        }
        self.session = requests.Session()
        self._access_token: Optional[str] = None
        self.oauth_url = f"{self.base_url}/api/security/oauth/token"
        self.custom_query_base = f"{self.base_url}/projectworkflow/client/custom/query"
        self.new_file_path_endpoint = (
            f"{self.base_url}/caaqms-common/dataRepository/file-path"
        )
        self.new_download_endpoint = (
            f"{self.base_url}/caaqms-common/dataRepository/download-excel-file"
        )
        self._live_directory = get_cpcb_credentials() is not None
        self._directory_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        self._rss_cache: Optional[List[Dict[str, Any]]] = None

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

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        creds = get_cpcb_credentials()
        if creds is None:
            raise requests.RequestException("CPCB credentials are not set")

        response = _request_with_ssl_fallback(
            "post",
            self.oauth_url,
            session=self.session,
            params={"grant_type": "password", **creds},
            headers={"Content-Type": "application/json"},
            json={},
            timeout=30,
        )
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise requests.RequestException(
                "CPCB token response did not include access_token"
            )
        self._access_token = str(token)
        return self._access_token

    def _new_api_headers(self, auth: bool = False) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if auth:
            headers["Authorization"] = self._get_access_token()
        return headers

    def _new_api_json(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        auth: bool = False,
    ) -> Any:
        response = _request_with_ssl_fallback(
            method,
            url,
            session=self.session,
            headers=self._new_api_headers(auth),
            params=params,
            json=json_data,
            timeout=30,
        )
        # CPCB answers 204 with an empty body when a query matches nothing
        if not response.content:
            return None
        return response.json()

    def _custom_query(
        self, query_name: str, filter_query: str = ""
    ) -> List[Dict[str, Any]]:
        # Only the directory queries need a token. File-path and download do not.
        data = self._new_api_json(
            "get",
            f"{self.custom_query_base}/{query_name}/data",
            params={
                "pageNo": -1,
                "perPage": -1,
                "filterQuery": filter_query,
            },
            auth=True,
        )
        if isinstance(data, list):
            return [cast(Dict[str, Any], row) for row in data if isinstance(row, dict)]
        return []

    def _directory(self, level: str, code: str = "") -> List[Dict[str, Any]]:
        """Directory rows for a level, live when credentials work, else the snapshot."""
        key = (level, code)
        if key not in self._directory_cache:
            rows: List[Dict[str, Any]] = []
            if self._live_directory:
                query_name, field = DIRECTORY_QUERIES[level]
                try:
                    rows = self._custom_query(
                        query_name, f"{field} IS '{code}'" if field else ""
                    )
                except (requests.RequestException, ValueError) as e:
                    # the token URL carries the credentials, so never print the error
                    status = getattr(getattr(e, "response", None), "status_code", None)
                    print(
                        f"CPCB station directory unavailable "
                        f"({status or type(e).__name__}); using snapshot"
                    )
                    self._live_directory = False
            if not rows:
                snapshot = _station_directory()[level]
                rows = snapshot.get(code, []) if code else snapshot
            self._directory_cache[key] = rows
        return self._directory_cache[key]

    def _new_state_list(self) -> List[Dict[str, Any]]:
        return self._directory("states")

    def _new_city_list(self, state_code: str) -> List[Dict[str, Any]]:
        return self._directory("cities", state_code)

    def _new_station_list(self, city_code: str) -> List[Dict[str, Any]]:
        return self._directory("stations", city_code)

    def iter_stations(self, state: str = "", city: str = "") -> Iterator[StationEntry]:
        """Yield (state, city, station) directory entries, with optional filters.

        Args:
            state: State name or code. Empty means all states.
            city: City name or code. Empty means all cities.
        """
        if city:
            state_entry, city_entry = self._resolve_city(city, state)
            pairs: Iterator[Tuple[Dict[str, Any], Dict[str, Any]]] = iter(
                [(state_entry, city_entry)] if state_entry and city_entry else []
            )
        else:
            states = [self._resolve_state(state)] if state else self._new_state_list()
            pairs = (
                (state_entry, city_entry)
                for state_entry in states
                if state_entry
                for city_entry in self._new_city_list(
                    str(state_entry.get("state_code", ""))
                )
            )
        for state_entry, city_entry in pairs:
            for station in self._new_station_list(str(city_entry.get("city_code", ""))):
                yield state_entry, city_entry, station

    def _rss_cities(self) -> List[Dict[str, Any]]:
        """The public RSS station feed. Each client gets it one time."""
        if self._rss_cache is None:
            try:
                self._rss_cache = fetch_cpcb_rss_station_data(timeout=30)
            except Exception as e:
                print(f"CPCB RSS feed unavailable ({e})")
                self._rss_cache = []
        return self._rss_cache

    def _rss_directory(self) -> Iterator[StationEntry]:
        """RSS stations in directory shape, for stations newer than the snapshot."""
        for city in self._rss_cities():
            for st in city.get("stationsInCity", []):
                yield (
                    {"state_name": city.get("stateID", "")},
                    {"city_name": city.get("cityName", "")},
                    {
                        "station_id": st.get("id", ""),
                        "station_name": st.get("name", ""),
                    },
                )

    def _normalize_frequency(self, frequency: str) -> str:
        frequency_map = {
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
        return frequency_map.get(frequency.lower(), frequency)

    def _resolve_state(self, state: str) -> Optional[Dict[str, Any]]:
        if not state:
            return None
        state_lower = state.lower()
        for entry in self._new_state_list():
            if state_lower in {
                str(entry.get("state_name", "")).lower(),
                str(entry.get("state_code", "")).lower(),
            }:
                return entry
        return None

    def _resolve_city(
        self, city: str, state: str = ""
    ) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        city_lower = city.lower()
        states = [self._resolve_state(state)] if state else self._new_state_list()
        for state_entry in states:
            if not state_entry:
                continue
            state_code = str(state_entry.get("state_code", ""))
            for city_entry in self._new_city_list(state_code):
                if city_lower in {
                    str(city_entry.get("city_name", "")).lower(),
                    str(city_entry.get("city_code", "")).lower(),
                }:
                    return state_entry, city_entry
        return None, None

    def _resolve_station(
        self,
        station_id: str,
        station_name: str = "",
        state: str = "",
        city: str = "",
    ) -> Tuple[
        Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]
    ]:
        target_id = station_id.lower()
        target_name = station_name.lower()

        def matches(station_entry: Dict[str, Any]) -> bool:
            sid = str(station_entry.get("station_id", "")).lower()
            sname = str(station_entry.get("station_name", "")).lower()
            return bool(target_id and target_id == sid) or bool(
                target_name and target_name == sname
            )

        directory = self.iter_stations(state, city) if city else self.iter_stations()
        for state_entry, city_entry, station_entry in directory:
            if matches(station_entry):
                return state_entry, city_entry, station_entry
        for state_entry, city_entry, station_entry in self._rss_directory():
            if matches(station_entry):
                return state_entry, city_entry, station_entry
        return None, None, None

    def get_complete_list(self) -> Dict[str, Any]:
        """Get the complete list of stations and cities in India.

        Returns:
            Dictionary with the station data and the city data.

        Raises:
            requests.RequestException: If the HTTP request fails.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        cities = self._rss_cities()
        if cities:
            return station_data_to_dropdown(cities)

        form_body = self._encode_base64(b"{}")
        try:
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
        except Exception:
            pass

        return {}

    def get_state_list(self) -> List[str]:
        """Get the list of states that have AQI data.

        Returns:
            Sorted list of state names.
        """
        states = [str(state.get("state_name", "")) for state in self._new_state_list()]
        return sorted(state for state in states if state)

    def get_city_list(self, state: str) -> List[str]:
        """Get the list of cities in a state that have AQI data.

        Args:
            state: State name.

        Returns:
            Sorted list of city names in the state.
        """
        state_entry = self._resolve_state(state)
        if not state_entry:
            return []
        state_code = str(state_entry.get("state_code", ""))
        return sorted(
            str(city.get("city_name", ""))
            for city in self._new_city_list(state_code)
            if city.get("city_name")
        )

    def get_station_list(self, city: str) -> List[Dict]:
        """Get the list of stations in a city that have AQI data.

        Args:
            city: City name.

        Returns:
            Sorted list of station dictionaries.
        """
        _, city_entry = self._resolve_city(city)
        if not city_entry:
            return []
        city_code = str(city_entry.get("city_code", ""))
        stations = [
            {
                "label": str(station.get("station_name", "")),
                "value": str(station.get("station_id", "")),
            }
            for station in self._new_station_list(city_code)
            if station.get("station_id") and station.get("station_name")
        ]
        return sorted(stations, key=lambda x: x.get("label", ""))

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
            station_id: Station ID.
            station_name: Station name.
            state: State name.
            city: City name.
            year: Year for data.
            frequency: Data frequency ('hourly' or 'daily').
            data_type: Type of data ('cityLevel', 'stationLevel' or 'raw').

        Returns:
            List of file entries, each with a file path.

        Raises:
            requests.RequestException: If the HTTP request fails.
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

        try:
            if data_type == "cityLevel":
                state_entry, city_entry = self._resolve_city(city, state)
                if state_entry and city_entry:
                    payload.update(
                        {
                            "station_id": "",
                            "station_name": "",
                            "state": str(state_entry.get("state_name", "")),
                            "city": str(city_entry.get("city_name", "")),
                        }
                    )
            elif data_type in ("stationLevel", "raw"):
                state_entry, city_entry, station_entry = self._resolve_station(
                    station_id, station_name, state, city
                )
                if state_entry and city_entry and station_entry:
                    payload.update(
                        {
                            "station_id": str(station_entry.get("station_id", "")),
                            "station_name": str(station_entry.get("station_name", "")),
                            "state": str(state_entry.get("state_name", "")),
                            "city": str(city_entry.get("city_name", "")),
                        }
                    )

            entries = _file_entries(
                self._new_api_json(
                    "post", self.new_file_path_endpoint, json_data=payload
                )
            )
            if entries is not None:
                return entries
        except Exception:
            pass

        payload_str = json.dumps(legacy_payload)
        encoded_payload = self._encode_base64(payload_str.encode("utf-8"))

        try:
            response = _request_with_ssl_fallback(
                method="post",
                url=f"{self.base_url}{self.file_path_endpoint}",
                data=encoded_payload,
                headers=self.headers,
                timeout=30,
            )

            decoded_response = self._decode_base64(response.text)
            entries = _file_entries(json.loads(decoded_response))
            if entries is not None:
                return entries
        except Exception:
            pass
        return []

    def _download_repository_file(self, filepath: str) -> io.BytesIO:
        response = _request_with_ssl_fallback(
            "get",
            self.new_download_endpoint,
            session=self.session,
            headers=self._new_api_headers(),
            params={"file_name": filepath},
            timeout=60,
        )
        return io.BytesIO(response.content)

    def _read_repository_excel(self, filepath: str) -> pd.DataFrame:
        return pd.read_excel(self._download_repository_file(filepath))

    def _read_repository_csv(self, filepath: str) -> pd.DataFrame:
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
        selected_entries = self._select_repository_entry(entries, year, month)
        if not selected_entries:
            raise Exception(
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
            raise Exception(f"No downloadable files found for year {year}")
        return pd.concat(frames, ignore_index=True)

    def download_raw_aqi_data_station_level(
        self,
        station_id: str,
        year: str,
        save_location: str,
        frequency: str = "15_minute",
        station_name: str = "",
        city: str = "",
        state: str = "",
    ) -> pd.DataFrame:
        """Download raw CPCB station data, for example 15-minute observations.

        Args:
            station_id: Station ID.
            year: Year for data.
            save_location: Path to save the CSV. If empty, no file is saved.
            frequency: Raw data interval. CPCB supports values such as
                "15_minute", "1H", and "1D" for raw station files.
            station_name: Optional station name. The client then does not look it up.
            city: Optional city name. The client then examines only this city.
            state: Optional state name, for cities with the same name.

        Returns:
            DataFrame with the raw station observations.
        """
        data_file_paths = self.get_file_path(
            station_id,
            station_name,
            state,
            city,
            year,
            frequency,
            "raw",
        )
        if not data_file_paths:
            raise Exception(
                f"Raw data not found for station {station_id} in year {year}"
            )

        filepath = data_file_paths[0].get("filepath")
        if not filepath:
            raise Exception(f"No downloadable raw file found for station {station_id}")

        df = self._read_repository_csv(str(filepath))
        if save_location:
            df.to_csv(save_location, index=False)
        return df

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
        if save_location:
            df.to_csv(save_location, index=False)
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
            station_id: Station ID.
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
        if save_location:
            df.to_csv(save_location, index=False)
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
            Exception: If the client cannot find or download the data.
        """
        data_file_paths = self.get_file_path("", "", "", city, "", "daily", "cityLevel")

        for entry in data_file_paths:
            if entry.get("year") == str(year):
                df = self._read_repository_excel(str(entry["filepath"]))
                df = df.iloc[:31]  # Keep 31 rows: the maximum days in a month
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
            Exception: If the client cannot find the station or the data.
        """
        state_entry, city_entry, station = self._resolve_station(station_id)
        if not (state_entry and city_entry and station):
            raise Exception(f"Station ID {station_id} not found")

        data_file_paths = self.get_file_path(
            station_id,
            str(station.get("station_name", "")),
            str(state_entry.get("state_name", "")),
            str(city_entry.get("city_name", "")),
            "",
            "daily",
            "stationLevel",
        )

        for entry in data_file_paths:
            if entry.get("year") == year:
                df = self._read_repository_excel(str(entry["filepath"]))
                df = df.iloc[:31]  # Keep 31 rows: the maximum days in a month
                df.to_csv(save_location, index=False)
                return df.head()

        raise Exception(f"Data not found for station {station_id} in year {year}")


class CPCBLive:
    """Client that gets live air quality data from CPCB."""

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
        """Send a POST request and return the decoded base64 JSON response.

        Args:
            url: Request URL.
            headers: Request headers.
            data: Request data.
            cookies: Request cookies.

        Returns:
            Parsed JSON response.

        Raises:
            requests.RequestException: If the request fails.
            json.JSONDecodeError: If the client cannot decode the response.
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
        """Get the location of this system from its IP address.

        Returns:
            Tuple of (latitude, longitude).

        Raises:
            Exception: If the client cannot find the location.
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
            coords: Optional tuple of (latitude, longitude). If None, the client
                finds the location from the IP address.

        Returns:
            Tuple of (station_id, station_name).

        Raises:
            Exception: If there is no station, or the coordinates are not valid.
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
            if isinstance(stations, list) and stations:
                return [
                    cast(Dict[str, Any], station)
                    for station in stations
                    if isinstance(station, dict)
                ]
        except Exception:
            pass

        return fetch_cpcb_rss_station_data(timeout=30)

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
            ValueError: If a parameter is not valid.
            Exception: If the request fails.
        """
        if not station_id or not date_time:
            raise ValueError("Both station_id and date_time must be provided.")

        raw_body = json.dumps({"station_id": station_id, "date": date_time})
        encoded_data = base64.b64encode(raw_body.encode()).decode("utf-8")

        try:
            return self._make_request(
                self.parameters_url, self.headers, encoded_data, self.cookies
            )
        except Exception:
            for city in fetch_cpcb_rss_station_data(timeout=30):
                for station in city.get("stationsInCity", []):
                    if (
                        station.get("id") == station_id
                        or station.get("name") == station_id
                    ):
                        metrics = []
                        for pollutant in station.get("pollutants", []):
                            metrics.append(
                                {
                                    "name": pollutant.get("indexId"),
                                    "avg": pollutant.get("avg"),
                                    "min": pollutant.get("min"),
                                    "max": pollutant.get("max"),
                                    "avgDesc": station.get("lastUpdate", date_time),
                                }
                            )
                        return {
                            "station_id": station.get("id"),
                            "station_name": station.get("name"),
                            "lastUpdate": station.get("lastUpdate"),
                            "airQualityIndex": station.get("airQualityIndex", {}),
                            "metrics": metrics,
                        }
            raise

    def get_live_aqi_data(
        self,
        station_id: Optional[str] = None,
        coords: Optional[Tuple[float, float]] = None,
        date: Optional[str] = None,
        hour: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get live AQI data for a station or a location, a date, and an hour.

        Args:
            station_id: Optional station ID. If None, the client uses the nearest
                station.
            coords: Optional (latitude, longitude) tuple.
            date: Optional date in 'YYYY-MM-DD' format. The default is today.
            hour: Optional hour (0-23). The default is the current hour.

        Returns:
            Processed live AQI data dictionary.

        Raises:
            ValueError: If the hour is not valid.
            Exception: If the client cannot get the data.
        """
        if not station_id:
            if coords:
                station_id = self.get_nearest_station(coords)[0]
            else:
                system_coords = self.get_system_location()
                station_id = self.get_nearest_station(system_coords)[0]

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
    """Client that processes PM2.5 satellite data from NetCDF files.

    The client supports the V5.GL.05.02 (GWR) and V6.GL.02.04 (CNN) datasets
    from the WUSTL Atmospheric Composition Analysis Group (ACAG).
    """

    def __init__(self, version: str = "V6", cache_dir: str = "pm25_data") -> None:
        """Initialize the PM2.5 Client with data paths and AWS configuration.

        Args:
            version: Dataset version to use. Options:
                - "V6" (default): V6.GL.02.04 - CNN-based algorithm (1998-2023)
                  The most accurate model. Use it for new studies.
                - "V5": V5.GL.05.02 - GWR-based algorithm (1998-2024)
                  The older model. Use it to compare with published studies.
            cache_dir: Directory for the cache of downloaded NetCDF files.

        Raises:
            ValueError: If version is not "V5" or "V6".

        Example:
            >>> # Use V6 (default, recommended)
            >>> client = PM25Client()

            >>> # Use V5
            >>> client = PM25Client(version="V5")
        """
        if version not in ["V5", "V6"]:
            raise ValueError(
                f"Invalid version: {version}. Must be 'V5' or 'V6'. "
                f"V6 (default) is recommended for new studies."
            )

        self.version = version
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Set the data source for the version
        if version == "V6":
            # V6.GL.02.04: CNN-based algorithm (most accurate)
            # Primary: AWS S3 Open Data Registry
            self.aws_base_url = (
                "https://s3.us-west-2.amazonaws.com/v6.gl.02.04/V6.GL.02.04/GL/"
            )
            # GEE Fallback: Google Earth Engine Community Catalog (V6.GL.02, 2000-2022)
            self.gee_collection_monthly: Optional[str] = (
                "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25/MONTHLY"
            )
            self.gee_collection_annual: Optional[str] = (
                "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25/ANNUAL"
            )
            self.variable_name = "PM25"  # V6 uses "PM25"
            self.year_range = (1998, 2023)
            # GEE has a smaller range of years
            self.gee_year_range: Optional[Tuple[int, int]] = (2000, 2022)
        else:  # V5
            # V5.GL.05.02: GWR-based algorithm (older, with many validation studies)
            self.aws_base_url = (
                "https://s3.us-west-2.amazonaws.com/acag-data/V5.GL.05.02/GL/"
            )
            # GEE does not have V5
            self.gee_collection_monthly = None
            self.gee_collection_annual = None
            self.variable_name = "GWRPM25"  # V5 uses "GWRPM25"
            self.year_range = (1998, 2024)
            self.gee_year_range = None

        # Initialize GEE if it is available
        self.gee_initialized = False
        if GEE_AVAILABLE and self.gee_collection_monthly:
            self.gee_initialized = self._initialize_gee()

        # Local paths for old versions
        self.annual_data_path = f"examples/{version}GL01.0p10.PM25.Global"
        self.monthly_data_path = f"examples/{version}GL01.0p10.PM25.Global"

        # Box shared folder URLs for manual downloads
        if version == "V6":
            self.box_shared_folder = "https://wustl.box.com/v/ACAG-V6GL0204-CNNPM25"
        else:  # V5
            self.box_shared_folder = "https://wustl.box.com/v/ACAG-V5GL0502-GWRPM25"

    def _initialize_gee(self) -> bool:
        """Initialize Google Earth Engine, and find and set the project.

        Returns:
            True if initialization succeeded, False otherwise.
        """
        try:
            gee_project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get(
                "GEE_PROJECT"
            )

            if not gee_project:
                gee_project_file = get_gee_project_file()
                if gee_project_file.exists():
                    gee_project = gee_project_file.read_text().strip()
                else:
                    legacy_file = Path(".gee_project")
                    if legacy_file.exists():
                        gee_project = legacy_file.read_text().strip()
                        try:
                            gee_project_file.write_text(gee_project)
                            print(f"✓ Migrated config to {gee_project_file}")
                        except Exception:
                            pass

            if gee_project:
                try:
                    ee.Initialize(
                        project=gee_project,
                        opt_url="https://earthengine-highvolume.googleapis.com",
                    )
                    print(
                        f"✓ Google Earth Engine initialized (project: {gee_project}, high-volume)"
                    )
                    return True
                except Exception:
                    pass

                try:
                    ee.Initialize(project=gee_project)
                    print(f"✓ Google Earth Engine initialized (project: {gee_project})")
                    return True
                except Exception:
                    pass

            try:
                ee.Initialize(project="earthengine-legacy")
                print("✓ Google Earth Engine initialized (earthengine-legacy)")
                return True
            except Exception:
                pass

            try:
                ee.Initialize()
                print("✓ Google Earth Engine initialized")
                return True
            except Exception:
                pass

            print("\n" + "=" * 70)
            print("Google Earth Engine Setup Required")
            print("=" * 70)
            print("\nTo download PM2.5 data from Google Earth Engine, you need to:")
            print()
            print("1. Register at: https://code.earthengine.google.com/")
            print("   - Click 'Register a Noncommercial or Commercial Cloud project'")
            print("   - Select 'Noncommercial' (free for research/education)")
            print("   - Create or select a Google Cloud project")
            print()
            print("2. Set up authentication:")
            print("   Run this in Python:")
            print()
            print("   >>> from vayuayan import setup_earth_engine")
            print("   >>> setup_earth_engine()")
            print()
            print("   Or set your project ID:")
            print("   export GEE_PROJECT=your-project-id")
            print()
            print("=" * 70)
            print()

            return False

        except Exception as e:
            print(f"ℹ GEE initialization failed: {e}")
            return False

    def _get_aws_filename(self, year: int, month: Optional[int] = None) -> str:
        """Make the AWS filename for a year and an optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the function returns the annual
                filename.

        Returns:
            AWS filename for the NetCDF file.

        Raises:
            ValueError: If the year is not in the range of the version.
        """
        if not (self.year_range[0] <= year <= self.year_range[1]):
            raise ValueError(
                f"Year {year} is outside valid range for {self.version}: "
                f"{self.year_range[0]}-{self.year_range[1]}"
            )

        if self.version == "V6":
            # V6 filename pattern: V6GL02.04.CNNPM25.GL.YYYYMM-YYYYMM.nc
            if month is None:
                return f"V6GL02.04.CNNPM25.GL.{year}01-{year}12.nc"
            return f"V6GL02.04.CNNPM25.GL.{year}{month:02d}-{year}{month:02d}.nc"
        else:  # V5
            # V5 filename pattern: V5GL05.02.GWRPM25.GL.YYYYMM-YYYYMM.nc
            if month is None:
                return f"V5GL05.02.GWRPM25.GL.{year}01-{year}12.nc"
            return f"V5GL05.02.GWRPM25.GL.{year}{month:02d}-{year}{month:02d}.nc"

    def _get_aws_url(self, year: int, month: Optional[int] = None) -> str:
        """Make the AWS URL for a year and an optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the function returns the annual URL.

        Returns:
            Full AWS URL for the NetCDF file.
        """
        filename = self._get_aws_filename(year, month)
        if month is None:
            return urljoin(self.aws_base_url, f"Annual/{filename}")
        return urljoin(self.aws_base_url, f"Monthly/{year}/{filename}")

    def _download_from_s3_boto3(
        self, year: int, month: Optional[int] = None, cached_path: Optional[Path] = None
    ) -> Optional[str]:
        """Download PM2.5 data from AWS S3 with boto3 and anonymous access.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the client downloads annual data.
            cached_path: Path for the file.

        Returns:
            Path to downloaded file if successful, None otherwise.
        """
        if not BOTO3_AVAILABLE:
            return None

        if cached_path is None:
            cached_path = Path(self.get_netcdf_path(year, month))

        try:
            s3 = boto3.client(
                "s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED)
            )

            filename = self._get_aws_filename(year, month)
            if month is None:
                s3_key = f"V6.GL.02.04/GL/Annual/{filename}"
            else:
                s3_key = f"V6.GL.02.04/GL/Monthly/{year}/{filename}"

            bucket_name = "v6.gl.02.04"

            print(f"Downloading from S3: s3://{bucket_name}/{s3_key}")

            try:
                head_response = s3.head_object(Bucket=bucket_name, Key=s3_key)
                total_size = head_response["ContentLength"]
            except Exception:
                total_size = 0

            with open(cached_path, "wb") as f:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="Downloading (boto3)",
                    ncols=80,
                ) as pbar:
                    s3.download_fileobj(
                        bucket_name,
                        s3_key,
                        f,
                        Callback=lambda bytes_transferred: pbar.update(
                            bytes_transferred
                        ),
                    )

            final_size = cached_path.stat().st_size
            print(
                f"✓ S3 download complete (boto3): {final_size / (1024 * 1024):.1f} MB"
            )
            return str(cached_path)

        except Exception as e:
            print(f"⚠ S3 boto3 download failed: {e}")
            if cached_path and cached_path.exists():
                cached_path.unlink()
            return None

    def _download_from_gee(
        self,
        year: int,
        month: Optional[int] = None,
        region: Optional[ee.Geometry] = None,
    ) -> Optional[str]:
        """Download PM2.5 data from Google Earth Engine.

        Note: GEE has a download limit of 32768x32768 pixels. For global data,
        give a region for the clip, or use the export-to-Drive API.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the client downloads annual data.
            region: Optional ee.Geometry for the clip. If None and the image is
                    too large, the client clips the image to the India bounds.

        Returns:
            Path to the downloaded GeoTIFF file, or None if GEE is not available.

        Raises:
            ValueError: If the year is not in the GEE data range.
        """
        if not self.gee_initialized or self.gee_year_range is None:
            return None

        if not (self.gee_year_range[0] <= year <= self.gee_year_range[1]):
            print(
                f"⚠ Year {year} outside GEE range "
                f"({self.gee_year_range[0]}-{self.gee_year_range[1]})"
            )
            return None

        try:
            if month is None:
                collection = ee.ImageCollection(self.gee_collection_annual)
                date_filter = ee.Filter.calendarRange(year, year, "year")
            else:
                collection = ee.ImageCollection(self.gee_collection_monthly)
                date_filter = ee.Filter.And(
                    ee.Filter.calendarRange(year, year, "year"),
                    ee.Filter.calendarRange(month, month, "month"),
                )

            image = collection.filter(date_filter).first()

            if image is None:
                print(f"⚠ No GEE data found for {year}-{month or 'annual'}")
                return None

            # If there is no region, use the India bounds.
            # The client downloads the full India raster one time and keeps it
            # in the cache. All stations then get their values from this file.
            # This is faster than one clip for each station.
            if region is None:
                print("ℹ Downloading India region raster (will be cached for reuse)")
                region = ee.Geometry.Rectangle([68.0, 8.0, 98.0, 37.0])  # India

            image = image.clip(region)

            base_filename = self._get_aws_filename(year, month)
            tif_filename = base_filename.replace(".nc", ".tif")
            output_path = self.cache_dir / tif_filename

            print(f"Requesting download URL from Google Earth Engine...")
            print(f"Region: {region.bounds().getInfo()}")
            url = image.getDownloadURL(
                {
                    "scale": 10000,  # ~0.1 degree at equator (0.1° x 0.1° resolution)
                    "crs": "EPSG:4326",
                    "fileFormat": "GeoTIFF",
                    "region": region,
                }
            )

            # GEE's getDownloadURL() returns a ZIP archive, not a raw GeoTIFF
            zip_path = output_path.with_suffix(".zip")
            print(f"Downloading from GEE...")
            print(f"Destination: {zip_path}")

            response = requests.get(url, stream=True, timeout=300)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0))

            with open(zip_path, "wb") as f:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="Downloading",
                    ncols=80,
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            final_size = zip_path.stat().st_size
            print(f"✓ GEE download complete: {final_size / (1024 * 1024):.1f} MB")

            print(f"Extracting GeoTIFF from ZIP archive...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_contents = zip_ref.namelist()
                print(f"  ZIP contents: {zip_contents}")

                tif_files = [f for f in zip_contents if f.endswith(".tif")]
                if not tif_files:
                    raise ValueError(
                        f"No .tif file found in GEE download: {zip_contents}"
                    )

                tif_name = tif_files[0]
                zip_ref.extract(tif_name, self.cache_dir)

                extracted_path = self.cache_dir / tif_name
                if extracted_path != output_path:
                    extracted_path.rename(output_path)

            zip_path.unlink()

            print(f"✓ GeoTIFF extracted: {output_path}")
            return str(output_path)

        except Exception as e:
            print(f"✗ GEE download failed: {e}")
            if output_path.exists():
                output_path.unlink()
            return None

    def get_netcdf_path(self, year: int, month: Optional[int] = None) -> str:
        """Get NetCDF file path for given year and optional month.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the function returns the annual
                data path.

        Returns:
            Path to NetCDF file (cached locally).
        """
        filename = self._get_aws_filename(year, month)
        cached_path = self.cache_dir / filename

        # Return the cache path, also if the file does not exist.
        # download_netcdf_if_needed downloads the file.
        return str(cached_path)

    def download_netcdf_if_needed(
        self, year: int, month: Optional[int] = None, force_download: bool = False
    ) -> str:
        """Download the NetCDF file from AWS if it is not in the cache.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the client downloads annual data.
            force_download: If True, download the file again, also if it exists.

        Returns:
            Path to the downloaded NetCDF or GeoTIFF file.

        Raises:
            requests.RequestException: If the download fails.
            IOError: If the client cannot write the file.
        """
        cached_path = Path(self.get_netcdf_path(year, month))

        # Also look for a GeoTIFF file (from GEE downloads)
        cached_tif_path = cached_path.with_suffix(".tif")

        # Look for the NetCDF file
        if cached_path.exists() and not force_download:
            file_size = cached_path.stat().st_size
            if file_size > 1024 * 1024:  # Minimum 1MB for a valid NetCDF file
                print(f"Using cached file: {cached_path}")
                return str(cached_path)
            else:
                print("Warning: Cached file appears incomplete, re-downloading...")

        # Look for a GeoTIFF file from an earlier GEE download
        if cached_tif_path.exists() and not force_download:
            file_size = cached_tif_path.stat().st_size
            if file_size > 100 * 1024:  # Minimum 100KB for a valid GeoTIFF file
                print(f"Using cached GeoTIFF file: {cached_tif_path}")
                return str(cached_tif_path)

        cached_path.parent.mkdir(parents=True, exist_ok=True)

        # First, use AWS S3 with boto3 (anonymous access)
        print(f"Attempting download from AWS S3...")

        s3_result = self._download_from_s3_boto3(year, month, cached_path)
        if s3_result:
            return s3_result

        aws_url = self._get_aws_url(year, month)
        print(f"Trying S3 download via HTTP (fallback)...")
        print(f"Source: {aws_url}")

        try:
            response = _request_with_ssl_fallback(
                method="get", url=aws_url, stream=True, timeout=300
            )

            total_size = int(response.headers.get("content-length", 0))

            chunk_size = 8192
            with open(cached_path, "wb") as f:
                with tqdm(
                    total=total_size,
                    unit="B",
                    unit_scale=True,
                    unit_divisor=1024,
                    desc="Downloading (HTTP)",
                    ncols=80,
                ) as pbar:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))

            final_size = cached_path.stat().st_size
            print(f"✓ AWS download complete: {final_size / (1024 * 1024):.1f} MB")
            return str(cached_path)

        except requests.RequestException as aws_error:
            print(f"⚠ AWS download failed: {aws_error}")
            print(f"Trying fallback: Google Earth Engine...")

            if cached_path.exists():
                cached_path.unlink()

            gee_path = self._download_from_gee(year, month)
            if gee_path:
                return gee_path

            filename = self._get_aws_filename(year, month)
            if month is None:
                wustl_path = f"GL/Annual/{filename}"
            else:
                wustl_path = f"GL/Monthly/{year}/{filename}"

            if not self.gee_initialized or self.gee_year_range is None:
                gee_error = "Not authenticated (run 'earthengine authenticate')"
            elif not (self.gee_year_range[0] <= year <= self.gee_year_range[1]):
                gee_error = f"Year {year} outside range ({self.gee_year_range[0]}-{self.gee_year_range[1]})"
            else:
                gee_error = "Download failed"

            manual_instructions = (
                f"\n{'=' * 80}\n"
                f"AUTOMATED DOWNLOAD FAILED\n"
                f"{'=' * 80}\n\n"
                f"All automated download sources are currently unavailable:\n"
                f"  ✗ AWS S3: {aws_error}\n"
                f"  ✗ Google Earth Engine: {gee_error}\n\n"
                f"MANUAL DOWNLOAD REQUIRED:\n\n"
                f"Visit the WUSTL data portal and download manually:\n\n"
                f"V6 Data (0.01° resolution, 1998-2023):\n"
                f"  URL: {self.box_shared_folder}\n"
                f"  Path: {wustl_path}\n\n"
                f"V5 Data (0.01° resolution, 1998-2024):\n"
                f"  URL: https://wustl.box.com/v/ACAG-V5GL0502-GWRPM25\n"
                f"  Path: {wustl_path}\n\n"
                f"After download:\n"
                f"  1. Save file as: {cached_path}\n"
                f"  2. Re-run your script\n\n"
                f"{'=' * 80}\n"
            )

            raise requests.RequestException(manual_instructions) from aws_error

    def _detect_pm25_variable(self, ds: xr.Dataset) -> Tuple[str, xr.Dataset]:
        """Find the PM2.5 variable name and prepare the dataset.

        Args:
            ds: xarray Dataset.

        Returns:
            Tuple of (variable_name, processed_dataset).
        """
        if "band_data" in ds.variables:
            pm25_var = "band_data"
            if "band" in ds.dims:
                ds = ds.squeeze("band", drop=True)
        elif "PM25" in ds.variables:
            pm25_var = "PM25"
        elif "GWRPM25" in ds.variables:
            pm25_var = "GWRPM25"
        else:
            available_vars = list(ds.variables.keys())
            raise ValueError(
                f"PM2.5 variable not found. Available variables: {available_vars}"
            )
        return pm25_var, ds

    def _detect_coordinates(self, ds: xr.Dataset) -> Tuple[str, str]:
        """Find the coordinate names in the dataset.

        Args:
            ds: xarray Dataset.

        Returns:
            Tuple of (latitude_coord, longitude_coord).
        """
        if "latitude" in ds.coords and "longitude" in ds.coords:
            return "latitude", "longitude"
        elif "lat" in ds.coords and "lon" in ds.coords:
            return "lat", "lon"
        elif "y" in ds.coords and "x" in ds.coords:
            return "y", "x"
        else:
            raise ValueError("Could not find latitude/longitude coordinates in file")

    def _prepare_pm25_data(
        self,
        ds: xr.Dataset,
        pm25_var: str,
        lat_coord: str,
        lon_coord: str,
        bbox: Tuple[float, float, float, float],
        buffer: float = 0.1,
    ) -> xr.DataArray:
        """Load and prepare PM2.5 data for a bounding box.

        Args:
            ds: xarray Dataset.
            pm25_var: Name of PM2.5 variable.
            lat_coord: Name of latitude coordinate.
            lon_coord: Name of longitude coordinate.
            bbox: Bounding box as (minx, miny, maxx, maxy).
            buffer: Buffer around the bbox, in degrees.

        Returns:
            PM2.5 DataArray that is ready for the clip.
        """
        lat_vals = ds[lat_coord].values
        lon_vals = ds[lon_coord].values
        lat_ascending = lat_vals[0] < lat_vals[-1]
        lon_ascending = lon_vals[0] < lon_vals[-1]

        if lat_ascending:
            lat_slice = slice(bbox[1] - buffer, bbox[3] + buffer)
        else:
            lat_slice = slice(bbox[3] + buffer, bbox[1] - buffer)

        if lon_ascending:
            lon_slice = slice(bbox[0] - buffer, bbox[2] + buffer)
        else:
            lon_slice = slice(bbox[2] + buffer, bbox[0] - buffer)

        ds_subset = ds.sel({lat_coord: lat_slice, lon_coord: lon_slice})
        pm25 = ds_subset[pm25_var].load()

        if not lat_ascending:
            pm25 = pm25.sortby(lat_coord)
        if not lon_ascending:
            pm25 = pm25.sortby(lon_coord)

        pm25 = pm25.rio.set_spatial_dims(x_dim=lon_coord, y_dim=lat_coord)
        pm25 = pm25.rio.write_crs("EPSG:4326")

        return cast(xr.DataArray, pm25)

    def _calculate_stats(
        self,
        clipped: xr.DataArray,
        include_count: bool = False,
        allow_empty: bool = False,
    ) -> Dict[str, float]:
        """Calculate statistics from clipped PM2.5 data.

        Args:
            clipped: Clipped PM2.5 DataArray.
            include_count: If True, add the count to the results.
            allow_empty: If True, return NaN stats for empty data. If False, raise
                an error.

        Returns:
            Dictionary with mean, std, min, and max statistics. It also has the count
            if include_count is True.

        Raises:
            ValueError: If there is no valid data and allow_empty=False.
        """
        values = clipped.values.flatten()
        values = values[~np.isnan(values)]

        if len(values) == 0:
            if not allow_empty:
                raise ValueError(
                    "No valid PM2.5 data found within the polygon boundary"
                )
            stats = {
                "mean": np.nan,
                "std": np.nan,
                "min": np.nan,
                "max": np.nan,
            }
            if include_count:
                stats["count"] = 0
            return stats

        stats = {
            "mean": float(values.mean()),
            "std": float(values.std()),
            "min": float(values.min()),
            "max": float(values.max()),
        }
        if include_count:
            stats["count"] = len(values)
        return stats

    def get_pm25_at_point(
        self,
        latitude: float,
        longitude: float,
        year: int,
        month: Optional[int] = None,
    ) -> float:
        """Get PM2.5 value at a specific latitude/longitude point.

        The function uses the grid cell that is nearest to the coordinates.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            year: Year of the data.
            month: Optional month (1-12). If None, the function uses annual data.

        Returns:
            PM2.5 value in µg/m³ at the nearest grid cell.

        Raises:
            ValueError: If the point is outside the data bounds, or there is no data.
            requests.RequestException: If the download fails.

        Example:
            >>> client = PM25Client()
            >>> pm25 = client.get_pm25_at_point(28.6139, 77.2090, year=2020, month=1)
            >>> print(f"PM2.5: {pm25:.2f} µg/m³")
        """
        nc_file = self.download_netcdf_if_needed(year, month)

        with xr.open_dataset(nc_file) as ds:
            pm25_var, ds = self._detect_pm25_variable(ds)
            lat_coord, lon_coord = self._detect_coordinates(ds)

            try:
                point_data = ds.sel(
                    {lat_coord: latitude, lon_coord: longitude}, method="nearest"
                )
            except (KeyError, ValueError) as e:
                raise ValueError(
                    f"Point ({latitude}, {longitude}) is outside data bounds"
                ) from e

            values = point_data[pm25_var].values
            pm25_value = float(values.item() if hasattr(values, "item") else values)

            if np.isnan(pm25_value):
                raise ValueError(
                    f"No PM2.5 data available at ({latitude}, {longitude})"
                )

            return pm25_value

    def get_pm25_stats(
        self,
        geojson_file: str,
        year: int,
        month: Optional[int] = None,
        group_by: Optional[str] = None,
    ) -> Union[Dict[str, float], pd.DataFrame]:
        """Calculate PM2.5 statistics in a polygon region from a GeoJSON file.

        If the NetCDF data is not in the local cache, this function downloads
        the data from AWS.

        Args:
            geojson_file: Path to GeoJSON file with polygon.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            group_by: Optional column name or names for the polygon groups.
                     Give one column (for example 'state_name') or a comma-separated
                     list of columns (for example 'state_name,district_name').
                     If None, the function aggregates the full polygon boundary.
                     If given, the function aggregates each unique combination.

        Returns:
            If group_by is None: Dictionary with mean, std, min, and max PM2.5 values.
            If group_by is given: DataFrame with statistics for each group.

        Raises:
            FileNotFoundError: If the GeoJSON file does not exist.
            requests.RequestException: If the NetCDF download fails.
            ValueError: If the GeoJSON file does not have the group_by column.
        """
        if not os.path.exists(geojson_file):
            raise FileNotFoundError(f"GeoJSON file not found: {geojson_file}")

        nc_file = self.download_netcdf_if_needed(year, month)

        gdf = gpd.read_file(geojson_file)
        gdf = gdf.to_crs("EPSG:4326")

        # If group_by is given, use the group method
        if group_by is not None:
            group_cols = [col.strip() for col in group_by.split(",")]

            missing_cols = [col for col in group_cols if col not in gdf.columns]
            if missing_cols:
                available_columns = list(gdf.columns)
                raise ValueError(
                    f"Column(s) {missing_cols} not found in GeoJSON. "
                    f"Available columns: {available_columns}"
                )

            return self._get_pm25_stats_grouped(gdf, Path(nc_file), group_cols)
        # Combine the polygons if there is more than one
        polygon = gdf.union_all()
        bounds = polygon.bounds

        with xr.open_dataset(nc_file) as ds:
            pm25_var, ds = self._detect_pm25_variable(ds)
            lat_coord, lon_coord = self._detect_coordinates(ds)
            pm25 = self._prepare_pm25_data(ds, pm25_var, lat_coord, lon_coord, bounds)

            clipped = pm25.rio.clip([polygon], crs="EPSG:4326", all_touched=True)
            return self._calculate_stats(clipped)

    def _get_pm25_stats_grouped(
        self, gdf: gpd.GeoDataFrame, nc_file: Path, group_by: Union[str, List[str]]
    ) -> pd.DataFrame:
        """Calculate PM2.5 statistics for each group in the GeoDataFrame.

        Args:
            gdf: GeoDataFrame with geometries (already in EPSG:4326).
            nc_file: Path to NetCDF file.
            group_by: Column name or names for the groups. A string or a list of
                strings.

        Returns:
            DataFrame with statistics for each unique value or combination in the
            group_by column(s).
        """
        group_cols = [group_by] if isinstance(group_by, str) else group_by
        bbox = gdf.total_bounds

        with xr.open_dataset(nc_file) as ds:
            pm25_var, ds = self._detect_pm25_variable(ds)
            lat_coord, lon_coord = self._detect_coordinates(ds)
            pm25 = self._prepare_pm25_data(ds, pm25_var, lat_coord, lon_coord, bbox)

            results = []
            groupby_arg = group_cols[0] if len(group_cols) == 1 else group_cols

            for group_name, group_gdf in gdf.groupby(groupby_arg):
                combined_geom = group_gdf.union_all()

                try:
                    clipped = pm25.rio.clip(
                        [combined_geom], crs="EPSG:4326", all_touched=True
                    )

                    result = {}
                    if len(group_cols) == 1:
                        result[group_cols[0]] = group_name
                    else:
                        for i, col in enumerate(group_cols):
                            result[col] = group_name[i]

                    result.update(
                        self._calculate_stats(
                            clipped, include_count=True, allow_empty=True
                        )
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
        """Calculate PM2.5 statistics for each polygon in a GeoJSON file.

        Args:
            geojson_file: Path to GeoJSON file with polygons.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            id_field: Optional GeoJSON property to use as the identifier.

        Returns:
            DataFrame with statistics for each polygon.

        Raises:
            FileNotFoundError: If the NetCDF file or the GeoJSON file does not exist.

        If the NetCDF data is not in the local cache, this function downloads
        the data from AWS.
        """
        if not os.path.exists(geojson_file):
            raise FileNotFoundError(f"GeoJSON file not found: {geojson_file}")

        nc_file = self.download_netcdf_if_needed(year, month)

        gdf = gpd.read_file(geojson_file)
        gdf = gdf.to_crs("EPSG:4326")
        bbox = gdf.total_bounds

        with xr.open_dataset(nc_file) as ds:
            pm25_var, ds = self._detect_pm25_variable(ds)
            lat_coord, lon_coord = self._detect_coordinates(ds)
            pm25 = self._prepare_pm25_data(ds, pm25_var, lat_coord, lon_coord, bbox)

            # Find the column name one time, before the loop
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
                    stats = self._calculate_stats(clipped, allow_empty=True)
                    mean_val, std_val = stats["mean"], stats["std"]
                except Exception:
                    mean_val, std_val = np.nan, np.nan

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
