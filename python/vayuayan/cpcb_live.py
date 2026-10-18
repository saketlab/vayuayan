"""
Live CPCB data: the station list, the nearest station and the latest readings.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from . import cpcb_common, http_client
from .constants import (
    ALL_PARAMETERS_URL,
    ALL_STATION_URL,
    LEGACY_FORM_HEADERS,
    PUBLIC_COOKIES,
)
from .cpcb_common import RSSFeed
from .exceptions import NetworkError, StationNotFoundError
from .utils import find_station, iter_city_stations, station_distances

logger = logging.getLogger(__name__)


class CPCBLive(RSSFeed):
    """Client that gets live air quality data from CPCB."""

    def __init__(self) -> None:
        """Initialize the Live AQI Client."""
        self.coordinate_url = "http://ip-api.com/json"
        self.station_url = ALL_STATION_URL
        self.parameters_url = ALL_PARAMETERS_URL

        self.headers = dict(LEGACY_FORM_HEADERS)
        self.cookies = dict(PUBLIC_COOKIES)
        self.session = requests.Session()

    def _make_request(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST a payload to a dashboard endpoint and return the JSON response.

        Raises:
            requests.RequestException: If the request fails.
            ValueError: If the client cannot decode the response.
        """
        data = cpcb_common.legacy_post(
            url, payload, self.headers, self.cookies, session=self.session
        )
        if not isinstance(data, dict):
            raise ValueError("CPCB response is not a JSON object")
        return data

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
            NetworkError: If the client cannot find the location.
        """
        try:
            response = http_client.request(
                "get", self.coordinate_url, session=self.session, timeout=30
            )
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            reason = http_client.failure_reason(e)
            raise NetworkError(f"Error retrieving system location: {reason}") from e
        if data.get("status") != "success":
            raise NetworkError(f"Geolocation lookup failed: {data.get('message')}")
        return (data.get("lat"), data.get("lon"))

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
            StationNotFoundError: If no station has valid coordinates.
            NetworkError: If no station list or location source answers.
        """
        cities = self.get_all_india()
        lat, lon = coords or self.get_system_location()
        candidates = station_distances(cities, lat, lon)
        if not candidates:
            raise StationNotFoundError("No stations found or invalid station data.")
        station, _ = min(candidates, key=lambda c: c[1])
        return (str(station.get("id", "")), str(station.get("name", "")))

    def get_all_india(self) -> List[Dict[str, Any]]:
        """Get all air quality monitoring stations in India.

        Returns:
            List of station dictionaries.

        Raises:
            NetworkError: If neither the dashboard nor the RSS feed answers.
        """
        response = cpcb_common.attempt(
            lambda: self._make_request(self.station_url, {}),
            "CPCB dashboard station list failed (%s)",
        )
        stations = (response or {}).get("stations")
        if isinstance(stations, list) and stations:
            return [s for s in stations if isinstance(s, dict)]

        cities = self._rss_cities()
        if not cities:
            raise NetworkError("No CPCB station list is available")
        return cities

    def _station_id_by_name(self, name: str) -> str:
        """The ID of the station whose name is, or contains, name."""
        stations = (
            (str(s.get("id", "")), str(s.get("name", "")), str(s.get("id", "")))
            for _, s in iter_city_stations(self.get_all_india())
        )
        station_id = find_station(name, stations)
        if not station_id:
            raise StationNotFoundError(f"Station {name} not found")
        return station_id

    def get_live_aqi_data_for_station(
        self, station_id: str, date_time: str
    ) -> Dict[str, Any]:
        """Get live air quality data for a specific station.

        If the dashboard endpoint fails, the client uses the latest reading of
        the station in the RSS feed instead.

        Args:
            station_id: Station ID, name, or part of a name.
            date_time: Date and time in 'YYYY-MM-DDTHH:00:00Z' format.

        Returns:
            Live air quality data dictionary.

        Raises:
            ValueError: If a parameter is not valid.
            NetworkError: If both the dashboard and the RSS feed fail.
            StationNotFoundError: If the RSS feed does not have the station.
        """
        if not station_id or not date_time:
            raise ValueError("Both station_id and date_time must be provided.")
        # ponytail: CPCB IDs are site_<n>, so only other values cost a station list
        if not station_id.startswith("site_"):
            station_id = self._station_id_by_name(station_id)

        payload = {"station_id": station_id, "date": date_time}
        data = cpcb_common.attempt(
            lambda: self._make_request(self.parameters_url, payload),
            "CPCB live parameters failed (%s)",
        )
        if data is not None:
            return data

        cities = self._rss_cities()
        if not cities:
            raise NetworkError("No CPCB live data source is available")
        for _, station in iter_city_stations(cities):
            if station_id in (station.get("id"), station.get("name")):
                return {
                    "station_id": station.get("id"),
                    "station_name": station.get("name"),
                    "lastUpdate": station.get("lastUpdate"),
                    "airQualityIndex": station.get("airQualityIndex", {}),
                    "metrics": [
                        {
                            "name": pollutant.get("indexId"),
                            "avg": pollutant.get("avg"),
                            "min": pollutant.get("min"),
                            "max": pollutant.get("max"),
                            "avgDesc": station.get("lastUpdate", date_time),
                        }
                        for pollutant in station.get("pollutants", [])
                    ],
                }
        raise StationNotFoundError(f"Station {station_id} not in the CPCB RSS feed")

    def get_live_aqi_data(
        self,
        station_id: Optional[str] = None,
        coords: Optional[Tuple[float, float]] = None,
        date: Optional[str] = None,
        hour: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Get live AQI data for a station or a location, a date, and an hour.

        Args:
            station_id: Optional station ID or name. If None, the client uses
                the nearest station.
            coords: Optional (latitude, longitude) tuple.
            date: Optional date in 'YYYY-MM-DD' format. The default is today.
            hour: Optional hour (0-23). The default is the current hour.

        Returns:
            Processed live AQI data dictionary.

        Raises:
            ValueError: If the hour is not valid.
            CPCBError: If the client cannot get the data.
        """
        if hour is not None and not (0 <= hour <= 23):
            raise ValueError("Hour must be between 0 and 23")
        station_id = station_id or self.get_nearest_station(coords)[0]

        now = datetime.now()
        date_time = (
            f"{date or now.strftime('%Y-%m-%d')}"
            f"T{now.hour if hour is None else hour:02d}:00:00Z"
        )
        aqi_data = self.get_live_aqi_data_for_station(station_id, date_time)
        return self._clean_pollution_data(aqi_data)
