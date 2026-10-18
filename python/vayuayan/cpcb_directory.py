"""
The CPCB station directory: states, cities and stations, and the lookup of
names and codes in it.

The directory is live when the CPCB_* credentials are set, else it is the
snapshot bundled in vayuayan/data, plus the RSS feed for newer stations.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from importlib import resources
from itertools import chain
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, cast

import requests

from . import cpcb_common, http_client
from .constants import BASE_URL, LEGACY_FORM_HEADERS, get_cpcb_credentials
from .cpcb_common import RSSFeed
from .exceptions import AuthenticationError
from .utils import find_station, iter_city_stations, station_data_to_dropdown

logger = logging.getLogger(__name__)

# Parallel requests of a live directory walk; few, to go easy on CPCB
PREFETCH_WORKERS = 8

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


class CPCBDirectory(RSSFeed):
    """Base class of CPCBHistorical: authentication and the station directory."""

    def __init__(self) -> None:
        """Set up the CPCB session and the station directory caches."""
        self.base_url = BASE_URL
        self.data_repository = "/dataRepository/"
        self.dropdown_endpoint = f"{self.data_repository}all_india_stationlist"
        self.headers = dict(LEGACY_FORM_HEADERS)
        self.session = requests.Session()
        self._access_token: Optional[str] = None
        self.oauth_url = f"{self.base_url}/api/security/oauth/token"
        self.custom_query_base = f"{self.base_url}/projectworkflow/client/custom/query"
        self._live_directory = get_cpcb_credentials() is not None
        self._directory_cache: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    def _get_access_token(self) -> str:
        """The CPCB OAuth token, requested once per client.

        Raises:
            AuthenticationError: If the credentials are not set or CPCB does not
                give a token. The message never has the token URL, which carries
                the credentials.
        """
        if self._access_token:
            return self._access_token
        creds = get_cpcb_credentials()
        if creds is None:
            raise AuthenticationError("CPCB credentials are not set")

        try:
            response = cpcb_common.send(
                "post",
                self.oauth_url,
                session=self.session,
                params={"grant_type": "password", **creds},
                headers={"Content-Type": "application/json"},
                json={},
            )
            token = response.json().get("access_token")
        except (requests.RequestException, ValueError) as e:
            reason = http_client.failure_reason(e)
            raise AuthenticationError(f"CPCB token request failed ({reason})") from None
        if not token:
            raise AuthenticationError(
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
        response = cpcb_common.send(
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
                live = cpcb_common.attempt(
                    lambda: self._custom_query(
                        query_name, f"{field} IS '{code}'" if field else ""
                    ),
                    "CPCB station directory unavailable (%s); using snapshot",
                    logging.WARNING,
                    cpcb_common.SOURCE_ERRORS + (AuthenticationError,),
                )
                if live is None:
                    self._live_directory = False
                rows = live or []
            if not rows:
                snapshot = _station_directory()[level]
                rows = snapshot.get(code, []) if code else snapshot
            self._directory_cache[key] = rows
        return self._directory_cache[key]

    def _prefetch(self, level: str, codes: List[str]) -> None:
        """Fetch the live directory rows of many codes in parallel.

        A full walk of the live directory is about 360 requests; one after the
        other they take minutes. The rows go to the cache, so the walk then
        reads them in its own order and finds the same first match. The states
        list, which gets the token, is always fetched before, so the threads do
        not race for the token. Without credentials this does nothing.
        """
        missing = [c for c in codes if (level, c) not in self._directory_cache]
        if not self._live_directory or len(missing) < 2:
            return
        # requests.Session is used from several threads here; its connection
        # pool is thread-safe, and these requests set no cookies
        with ThreadPoolExecutor(max_workers=PREFETCH_WORKERS) as pool:
            list(pool.map(lambda code: self._directory(level, code), missing))

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
            if not (state_entry and city_entry):
                return
            pairs: Iterable[Tuple[Dict[str, Any], Dict[str, Any]]] = [
                (state_entry, city_entry)
            ]
        else:
            states = self._states(state)
            self._prefetch("cities", [str(s.get("state_code", "")) for s in states])
            pairs = [
                (state_entry, city_entry)
                for state_entry in states
                for city_entry in self._new_city_list(
                    str(state_entry.get("state_code", ""))
                )
            ]
            self._prefetch("stations", [str(c.get("city_code", "")) for _, c in pairs])
        for state_entry, city_entry in pairs:
            for station in self._new_station_list(str(city_entry.get("city_code", ""))):
                yield state_entry, city_entry, station

    def _rss_directory(self) -> Iterator[StationEntry]:
        """RSS stations in directory shape, for stations newer than the snapshot."""
        for city, st in iter_city_stations(self._rss_cities()):
            yield (
                {"state_name": city.get("stateID", "")},
                {"city_name": city.get("cityName", "")},
                {"station_id": st.get("id", ""), "station_name": st.get("name", "")},
            )

    def _states(self, state: str = "") -> List[Dict[str, Any]]:
        """The directory entry of one state (name or code), or all states."""
        if not state:
            return self._new_state_list()
        entry = self._resolve_state(state)
        return [entry] if entry else []

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
        states = self._states(state)
        self._prefetch("cities", [str(s.get("state_code", "")) for s in states])
        for state_entry in states:
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
        """Find a station by ID, name or part of a name; see utils.find_station."""

        def entries() -> Iterator[Tuple[str, str, StationEntry]]:
            # The state only narrows a city lookup; without a city every
            # state is searched
            directory = (
                self.iter_stations(state, city) if city else self.iter_stations()
            )
            for entry in chain(directory, self._rss_directory()):
                station = entry[2]
                sid = str(station.get("station_id", ""))
                yield sid, str(station.get("station_name", "")), entry

        for query in (station_id, station_name):
            found = find_station(query, entries())
            if found:
                return found
        return None, None, None

    def get_complete_list(self) -> Dict[str, Any]:
        """Get the complete list of stations and cities in India.

        Returns:
            Dictionary with the station data and the city data.

        The list is empty if neither the RSS feed nor the old endpoint answers.
        """
        cities = self._rss_cities()
        if cities:
            return station_data_to_dropdown(cities)

        parsed = cpcb_common.attempt(
            lambda: cpcb_common.legacy_post(
                f"{self.base_url}{self.dropdown_endpoint}", {}, session=self.session
            ),
            "CPCB station list unavailable (%s)",
            logging.WARNING,
        )
        if not isinstance(parsed, dict) or parsed.get("status") != "success":
            return {}
        dropdown = parsed.get("dropdown")
        return dropdown if isinstance(dropdown, dict) else {}

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

    def get_station_list(self, city: str) -> List[Dict[str, str]]:
        """Get the list of stations in a city that have AQI data.

        The list has the directory stations of the city, and the stations of
        the RSS feed that are newer than the directory.

        Args:
            city: City name or code.

        Returns:
            List of {"label": station name, "value": station ID}, sorted by name.
        """
        _, city_entry = self._resolve_city(city)
        if not city_entry:
            return []
        city_code = str(city_entry.get("city_code", ""))
        city_name = str(city_entry.get("city_name", "")).lower()
        stations = {
            str(st["station_id"]): str(st["station_name"])
            for st in self._new_station_list(city_code)
            if st.get("station_id") and st.get("station_name")
        }
        # Stations newer than the bundled snapshot are only in the RSS feed
        for _, rss_city, st in self._rss_directory():
            if str(rss_city.get("city_name", "")).lower() == city_name:
                stations.setdefault(str(st["station_id"]), str(st["station_name"]))
        return sorted(
            ({"label": name, "value": sid} for sid, name in stations.items() if sid),
            key=lambda x: x["label"],
        )
