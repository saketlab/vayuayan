"""
The CPCB station directory: states, cities and stations, and the lookup of
names and codes in it.

The directory is live when the CPCB_* credentials are set, else it is the
snapshot bundled in vayuayan/data, plus the RSS feed for newer stations.
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from importlib import resources
from itertools import chain
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    FrozenSet,
    Iterable,
    Iterator,
    List,
    NoReturn,
    Optional,
    Set,
    Tuple,
    cast,
)

import requests

from . import cpcb_common, http_client
from .constants import BASE_URL, LEGACY_FORM_HEADERS, get_cpcb_credentials
from .cpcb_common import RSSFeed
from .exceptions import AmbiguousMatchError, AuthenticationError
from .utils import find_station, iter_city_stations, station_data_to_dropdown

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

# Parallel requests of a live directory walk; few, to go easy on CPCB
PREFETCH_WORKERS = 8

CityEntry = Tuple[Dict[str, Any], Dict[str, Any]]
StationEntry = Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]

# level -> (custom query name, filter field) for the CPCB station directory
DIRECTORY_QUERIES = {
    "states": ("get-state-master-list-data", ""),
    "cities": ("get-city-master-list", "state_code"),
    "stations": ("get-site-station-master-data-list", "city_code"),
}


NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@lru_cache(maxsize=1)
def _station_directory() -> Dict[str, Any]:
    """Bundled snapshot of the CPCB station directory (states, cities, stations)."""
    path = resources.files("vayuayan").joinpath("data/cpcb_station_directory.json")
    return cast(Dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


@lru_cache(maxsize=1)
def _snapshot_station_ids() -> FrozenSet[str]:
    """IDs of every station in the bundled snapshot."""
    stations = _station_directory()["stations"].values()
    return frozenset(str(st["station_id"]) for st in chain.from_iterable(stations))


class CPCBDirectory(RSSFeed):
    """Base class of CPCBHistorical: authentication and the station directory."""

    # The directory answers without the feed, so its absence is not a problem
    _rss_failure_level = logging.INFO

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
        self._directory_sources: Set[str] = set()

    @property
    def directory_source(self) -> str:
        """Where the directory rows came from: "live", "snapshot" or "mixed".

        Before the first lookup it says what will be tried.
        """
        if len(self._directory_sources) > 1:
            return "mixed"
        if self._directory_sources:
            return next(iter(self._directory_sources))
        return "live" if self._live_directory else "snapshot"

    def _get_access_token(self) -> str:
        """The CPCB OAuth token, requested once per client.

        Raises:
            AuthenticationError: If the credentials are not set or CPCB does not
                give a token. The message never has the token URL, which carries
                the credentials.
        """
        token = self._access_token
        if token:
            return token
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
                # the password must never cross a connection that is not verified
                ssl_fallback=False,
            )
            body = response.json()
            token = body.get("access_token") if isinstance(body, dict) else None
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
        def send() -> requests.Response:
            return cpcb_common.send(
                method,
                url,
                session=self.session,
                headers=self._new_api_headers(auth),
                params=params,
                json=json_data,
                timeout=30,
                retries=0,  # callers fall back to the snapshot or the legacy API
                # the bearer token gets the same protection as the password
                ssl_fallback=not auth,
            )

        try:
            response = send()
        except requests.HTTPError as e:
            if not auth or http_client.failure_reason(e) != "401":
                raise
            # an expired token: ask for a new one and try once more
            self._access_token = None
            response = send()
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
                live: Optional[List[Dict[str, Any]]]
                try:
                    live = cpcb_common.attempt(
                        lambda: self._custom_query(
                            query_name, f"{field} IS '{code}'" if field else ""
                        ),
                        "CPCB station directory unavailable (%s); using snapshot",
                        logging.WARNING,
                    )
                except AuthenticationError as e:
                    # its text is written to carry no URL or credentials
                    logger.warning(
                        "CPCB station directory unavailable (%s); using snapshot", e
                    )
                    live = None
                if live is None:
                    self._live_directory = False
                rows = live or []
            self._directory_sources.add("live" if rows else "snapshot")
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
            pairs: Iterable[CityEntry] = [(state_entry, city_entry)]
        else:
            pairs = self._matching_cities(state, "")
        for state_entry, city_entry in pairs:
            for station in self._new_station_list(str(city_entry.get("city_code", ""))):
                yield state_entry, city_entry, station

    def _matching_cities(self, state: str, city: str) -> List[CityEntry]:
        """(state, city) entries for the filters, fetched before any station."""
        states = self._states(state)
        self._prefetch("cities", [str(s.get("state_code", "")) for s in states])
        wanted = city.lower()
        pairs = [
            (state_entry, city_entry)
            for state_entry in states
            for city_entry in self._new_city_list(
                str(state_entry.get("state_code", ""))
            )
            if not city
            or wanted
            in (
                str(city_entry.get("city_name", "")).lower(),
                str(city_entry.get("city_code", "")).lower(),
            )
        ]
        self._prefetch("stations", [str(c.get("city_code", "")) for _, c in pairs])
        return pairs

    def _station_catalogue(
        self, state: str = "", city: str = ""
    ) -> Iterator[StationEntry]:
        """Directory stations, then the stations only the RSS feed knows.

        States and cities are filtered before stations are fetched, and the
        feed is read only after the directory stations have been used, so an
        exact match in the directory needs no feed.

        Args:
            state: State name or code. Empty means all states.
            city: City name or code. Empty means all cities; a name can be in
                several states.
        """
        pairs = self._matching_cities(state, city)
        seen = set(_snapshot_station_ids())
        for state_entry, city_entry in pairs:
            for station in self._new_station_list(str(city_entry.get("city_code", ""))):
                seen.add(str(station.get("station_id", "")))
                yield state_entry, city_entry, station

        # The feed has names only, so a code is matched through its directory name
        states = {state.lower()} | {
            str(s.get("state_name", "")).lower() for s in self._states(state)
        }
        cities = {city.lower()} | {
            str(c.get("city_name", "")).lower() for _, c in pairs
        }
        for entry in self._rss_directory():
            station_id = str(entry[2]["station_id"])
            if (
                station_id
                and station_id not in seen
                and (not state or str(entry[0]["state_name"]).lower() in states)
                and (not city or str(entry[1]["city_name"]).lower() in cities)
            ):
                seen.add(station_id)
                yield entry

    def station_table(self, state: str = "", city: str = "") -> pd.DataFrame:
        """Stations of the CPCB directory and the RSS feed, one row each.

        Args:
            state: State name or code. Empty means all states.
            city: City name or code. Empty means all cities. Every city of
                that name is included unless state is given.

        Returns:
            DataFrame with station_id, station_name, city, state, latitude
            and longitude, sorted by state, city and station name. It has no
            rows if nothing matches.
        """
        import pandas as pd

        table = pd.DataFrame(
            [
                (
                    station.get("station_id"),
                    station.get("station_name"),
                    city_entry.get("city_name"),
                    state_entry.get("state_name"),
                    station.get("latitude"),
                    station.get("longitude"),
                )
                for state_entry, city_entry, station in self._station_catalogue(
                    state, city
                )
            ],
            columns=[
                "station_id",
                "station_name",
                "city",
                "state",
                "latitude",
                "longitude",
            ],
        )
        for column in ("latitude", "longitude"):
            table[column] = pd.to_numeric(table[column], errors="coerce")
        return table.sort_values(["state", "city", "station_name"], ignore_index=True)

    def _rss_directory(self) -> Iterator[StationEntry]:
        """RSS stations in directory shape, with their coordinates."""
        for city, st in iter_city_stations(self._rss_cities()):
            yield (
                {"state_name": city.get("stateID", "")},
                {"city_name": city.get("cityName", "")},
                {
                    "station_id": st.get("id", ""),
                    "station_name": st.get("name", ""),
                    "latitude": st.get("latitude"),
                    "longitude": st.get("longitude"),
                },
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
        found: List[CityEntry] = []
        for state_entry in states:
            state_code = str(state_entry.get("state_code", ""))
            for city_entry in self._new_city_list(state_code):
                if city_lower in {
                    str(city_entry.get("city_name", "")).lower(),
                    str(city_entry.get("city_code", "")).lower(),
                }:
                    found.append((state_entry, city_entry))
                    break
        if len(found) > 1:
            _raise_ambiguous_city(
                city, [str(s.get("state_name", "")) for s, _ in found]
            )
        return found[0] if found else (None, None)

    def _resolve_station(
        self,
        station_id: str,
        station_name: str = "",
        state: str = "",
        city: str = "",
    ) -> Tuple[
        Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]
    ]:
        """Find a station by ID, name or part of a name; see utils.find_station.

        state and city narrow the search, also among the stations of the feed.
        The directory and the feed are searched together, so a part of a name
        that fits a station of each is ambiguous.

        Raises:
            AmbiguousMatchError: If city is in several states and state is not
                given, or part of a name fits several stations.
        """
        if city:
            self._resolve_city(city, state)  # raises for a city in several states

        def entries() -> Iterator[Tuple[str, str, StationEntry]]:
            for entry in self._station_catalogue(state, city):
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

    def get_station_list(self, city: str, state: str = "") -> List[Dict[str, str]]:
        """Get the list of stations in a city that have AQI data.

        The list has the directory stations of the city, and the stations of
        the RSS feed that are newer than the directory.

        Args:
            city: City name or code.
            state: State name or code, for cities with the same name.

        Returns:
            List of {"label": station name, "value": station ID}, sorted by name.

        Raises:
            AmbiguousMatchError: If the city is in several states and state is
                not given.
        """
        _, city_entry = self._resolve_city(city, state)
        if not city_entry:
            return []
        # The code selects this one city, as a name could be in several states
        catalogue = self._station_catalogue(city=str(city_entry.get("city_code", "")))
        return sorted(
            (
                {"label": str(st["station_name"]), "value": str(st["station_id"])}
                for _, _, st in catalogue
                if st.get("station_id") and st.get("station_name")
            ),
            key=lambda x: x["label"],
        )

    def add_coords(self, stations: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Add lat and lon to get_station_list entries.

        Coordinates come from the bundled snapshot, then from the RSS feed,
        then from OpenStreetMap Nominatim (one request per second) for the
        stations that are in neither. lat and lon are None if all fail.
        """
        known: Dict[str, Tuple[Any, Any]] = {
            str(st["station_id"]): (st.get("latitude"), st.get("longitude"))
            for st in chain.from_iterable(_station_directory()["stations"].values())
        }
        out: List[Dict[str, Any]] = []
        for station in stations:
            lat, lon = known.get(station["value"], (None, None))
            out.append({**station, "lat": _float(lat), "lon": _float(lon)})
        if any(row["lat"] is None for row in out):
            feed = {
                str(s["station_id"]): (s["latitude"], s["longitude"])
                for _, _, s in self._rss_directory()
            }
            for row in out:
                if row["lat"] is None and row["value"] in feed:
                    row["lat"], row["lon"] = map(_float, feed[row["value"]])
        for row in out:
            if row["lat"] is None:
                row["lat"], row["lon"] = _nominatim(row.get("label", ""))
        found = sum(row["lat"] is not None for row in out)
        logger.info("%d/%d stations have coordinates", found, len(out))
        return out


def _raise_ambiguous_city(city: str, states: Iterable[str]) -> NoReturn:
    """Raise AmbiguousMatchError for a city name used in several states."""
    names = sorted(states)
    raise AmbiguousMatchError(
        f"City '{city}' is in more than one state, give the state: {'; '.join(names)}",
        names,
    )


def _state_key(state: Any) -> str:
    """A state name as letters only; the feed can spell a directory state differently."""
    return re.sub(r"[^a-z]", "", str(state).lower().replace("&", "and"))


def _float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Agency suffix of a station label: "Bandra, Mumbai - MPCB" -> "Bandra, Mumbai"
_AGENCY = re.compile(r"\s*-\s*(DPCC|CPCB|IMD|IITM|MPCB|BMC|APPCB|TSPCB|KSPCB).*$")


def _nominatim(label: str) -> Tuple[Optional[float], Optional[float]]:
    """(lat, lon) of a station label from Nominatim, or (None, None)."""
    query = _AGENCY.sub("", label)
    time.sleep(1)  # Nominatim allows one request per second
    try:
        result = http_client.request(
            "get",
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "vayuayan-python-package"},
            timeout=10,
        ).json()
    except (requests.RequestException, ValueError) as e:
        logger.info("Nominatim failed for %s: %s", query, http_client.failure_reason(e))
        return None, None
    if not result:
        logger.info("Nominatim: no result for %s", query)
        return None, None
    return _float(result[0].get("lat")), _float(result[0].get("lon"))
