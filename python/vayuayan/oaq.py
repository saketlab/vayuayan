"""
OAQ (Open Air Quality) low-cost sensor data.

The Data Broker exchanges an API key for a signed query string, valid for 24
hours, that every data URL carries.
"""

from __future__ import annotations

import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Tuple,
    Union,
)

import requests

from . import http_client
from .exceptions import AuthenticationError, DataParsingError, NetworkError
from .oaq_records import RECORD_COLUMNS, RECORD_TOLERANCE, compare_daily_records

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

BROKER_URL = "https://us-central1-oaqdms.cloudfunctions.net/brokerData"
DATA_BASE_URL = "https://oaq.notf.in/v1"
OAQ_TIMEOUT = 30
# Retries of a data request after a network error or a 5xx status (never a 404)
OAQ_RETRIES = 3
# Fewest 15-minute readings for a daily mean: 16 hours, as for the National AQI
MIN_READINGS = 64

Providers = Union[str, Iterable[str]]
Sensors = Union[str, Iterable[str]]
# Sensors fetched at the same time when several are asked for
OAQ_WORKERS = 8


class OAQClient:
    """Client for the OAQ sensor data of one API key."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        """Start an OAQ session (the handshake with the Data Broker).

        Args:
            api_key: OAQ API key. The default is the OAQ_API_KEY variable.

        Raises:
            AuthenticationError: If there is no key, or the broker rejects it.
        """
        key = api_key or os.environ.get("OAQ_API_KEY", "")
        if not key:
            raise AuthenticationError(
                "OAQ API key not found. Pass api_key or set OAQ_API_KEY."
            )
        try:
            response = http_client.request(
                "get",
                BROKER_URL,
                params={"action": "api_session", "token": key},
                timeout=OAQ_TIMEOUT,
            )
            data = response.json()
        except (requests.RequestException, ValueError) as e:
            # The URL carries the key, so name only the failure
            status = getattr(getattr(e, "response", None), "status_code", None)
            raise AuthenticationError(
                f"OAQ handshake failed (status {status})"
            ) from None
        signature = data.get("signature") or data.get("Signature")
        if not signature:
            raise AuthenticationError(
                "Unexpected OAQ broker response (missing signature)"
            )
        self.base_url = str(data.get("baseUrl") or DATA_BASE_URL).rstrip("/")
        self.sig_string = str(signature)

    def _url(self, path: str) -> str:
        """Signed URL of an object path relative to base_url."""
        return f"{self.base_url}/{path}?{self.sig_string}"

    def _get(self, path: str) -> Any:
        try:
            response = http_client.request(
                "get", self._url(path), retries=OAQ_RETRIES, timeout=OAQ_TIMEOUT
            )
        except requests.RequestException as e:
            # The URL carries the signature, so name only the path and reason
            raise NetworkError(
                f"OAQ request failed for {path} ({http_client.failure_reason(e)})"
            ) from None
        try:
            return response.json()
        except ValueError as e:
            raise DataParsingError(f"Failed to parse OAQ response: {path}") from e

    def list_providers(self) -> Dict[str, Any]:
        """All data providers, with id, name and attribution."""
        return self._get("meta/providers.json")  # type: ignore[no-any-return]

    def get_hierarchy(self, provider: str) -> Any:
        """Country > City > Sensor tree of a provider."""
        return self._get(f"provider={provider.lower()}/meta/hierarchy.json")

    def get_city_latest(self, provider: str, city: str) -> Any:
        """Latest map readings of all sensors in a city (any case: OAQ's paths
        use lower case, while its hierarchy writes "Bengaluru")."""
        return self._get(
            f"provider={provider.lower()}/live/by_city/{city.lower()}/map_latest.json"
        )

    def get_stations_latest(self, provider: str) -> Any:
        """Latest readings of all stations of a provider."""
        return self._get(
            f"provider={provider.lower()}/live/global/all_stations_latest.json"
        )

    def get_station_24h(self, provider: str, sensor_id: str) -> Any:
        """Last 24 hours of readings of a sensor."""
        return self._get(
            f"provider={provider.lower()}/live/sensors/{sensor_id}/last24h.json"
        )

    def get_daily(
        self, provider: str, sensor_id: str, year: int, month: int, day: int
    ) -> Any:
        """Daily data of a sensor for one date."""
        return self._get(
            f"provider={provider.lower()}/history/daily/{sensor_id}/"
            f"{int(year)}/{int(month):02d}/{int(day):02d}.json"
        )

    def get_monthly(
        self, provider: str, sensor_id: str, year: int, month: Union[int, str]
    ) -> Any:
        """Monthly aggregates of a sensor. The month is used as given ("03").

        Since about March 2026, OAQ's daily values are often the last reading of the day, not its mean; use daily_means or readings_mean on readings for daily means.
        """
        return self._get(
            f"provider={provider.lower()}/history/aggregates/{sensor_id}/"
            f"monthly_{year}_{month}.json"
        )

    def get_annual(self, provider: str, sensor_id: str, year: int) -> Any:
        """Annual aggregates of a sensor.

        Since about March 2026, OAQ's daily values are often the last reading of the day, not its mean; use daily_means or readings_mean on readings for daily means.
        """
        return self._get(
            f"provider={provider.lower()}/history/aggregates/{sensor_id}/"
            f"annual_{year}.json"
        )

    def sensors(self, provider: Optional[Providers] = None) -> pd.DataFrame:
        """Every sensor of the providers (all providers by default).

        Like stations_table, with type "Reference Station" for the CPCB
        stations that OAQ mirrors and "Sensor" for low-cost sensors.
        """
        if provider is None:
            provider = [p["id"] for p in self.list_providers().get("providers", [])]
        return self.stations_table(provider)

    def daily_records(
        self, provider: str, sensor_id: Sensors, years: Iterable[int]
    ) -> pd.DataFrame:
        """OAQ's own daily records of one or more sensors (get_annual).

        These are OAQ's values, which since about March 2026 are often the last reading of the day
        rather than its mean; see check_daily_records and daily_means.

        Returns:
            DataFrame with sensor_id, date (datetime.date) and one numeric
            column per parameter. Years that OAQ has no file for are left out.
        """
        import pandas as pd

        years = list(years)
        if not isinstance(sensor_id, str):
            return _each(lambda s: self.daily_records(provider, s, years), sensor_id)

        frames = []
        for year in years:
            try:
                data = self.get_annual(provider, sensor_id, year)
            except (NetworkError, DataParsingError) as e:
                logger.debug("OAQ %s %s: %s", sensor_id, year, e)
                continue
            rows = pd.DataFrame(data.get("data") if isinstance(data, dict) else None)
            if rows.empty or "date" not in rows:
                continue
            day = pd.to_datetime(
                rows["date"].astype(str).str.slice(0, 10), errors="coerce"
            )
            values = rows.drop(columns="date").apply(pd.to_numeric, errors="coerce")
            frames.append(values.assign(sensor_id=sensor_id, date=day.dt.date))
        if not frames:
            return pd.DataFrame(columns=["sensor_id", "date"])
        out = pd.concat(frames, ignore_index=True).dropna(subset=["date"])
        first = ["sensor_id", "date"]
        return out[first + [c for c in out.columns if c not in first]].reset_index(
            drop=True
        )

    def check_daily_records(
        self,
        provider: str,
        sensor_id: str,
        dates: Iterable[Union[str, date]],
        value: str = "pm25",
        tolerance: float = RECORD_TOLERANCE,
    ) -> pd.DataFrame:
        """OAQ's daily record of each day against that day's 15-minute readings.

        Fetches the records and readings and calls compare_daily_records.

        Returns:
            DataFrame as compare_daily_records: the record, statistics of the
            readings (mean, last, max, median, mean of the last 2 and 4),
            record_is_<statistic> and class. Days without a record or
            readings are left out.
        """
        import pandas as pd

        days = sorted({pd.Timestamp(d).date() for d in dates})
        records = self.daily_records(
            provider, sensor_id, sorted({d.year for d in days})
        )
        if records.empty or value not in records:
            return pd.DataFrame(columns=RECORD_COLUMNS)
        records = records[records["date"].isin(days)].dropna(subset=[value])
        readings = self.readings(provider, sensor_id, list(records["date"]))
        if readings.empty or value not in readings:
            return pd.DataFrame(columns=RECORD_COLUMNS)
        return compare_daily_records(readings, records, value, tolerance)

    def audit_daily_records(
        self,
        sensors: Iterable[Tuple[str, str]],
        years: Iterable[int],
        value: str = "pm25",
        tolerance: float = RECORD_TOLERANCE,
        until: Optional[Union[str, date]] = None,
    ) -> pd.DataFrame:
        """check_daily_records for every day of some years of several sensors.

        Args:
            sensors: (provider, sensor_id) pairs.
            years: Years.
            value: Parameter to compare.
            tolerance: Values within it count as equal.
            until: First day left out. The default is today in India (IST),
                whose values are still being written.

        Returns:
            DataFrame as compare_daily_records with a provider column.
        """
        import pandas as pd

        years = list(years)
        stop = pd.Timestamp(until).date() if until is not None else _today_ist()

        def audit(pair: Tuple[str, str]) -> pd.DataFrame:
            provider, sensor = pair
            days = self.daily_records(provider, sensor, years)["date"]
            out = self.check_daily_records(
                provider, sensor, [d for d in days if d < stop], value, tolerance
            )
            return out.assign(provider=provider)

        with ThreadPoolExecutor(OAQ_WORKERS) as pool:
            frames = [f for f in pool.map(audit, list(sensors)) if not f.empty]
        if not frames:
            return pd.DataFrame(columns=["provider"] + RECORD_COLUMNS)
        out = pd.concat(frames, ignore_index=True)
        return out[["provider"] + RECORD_COLUMNS]

    def readings(
        self, provider: str, sensor_id: Sensors, dates: Iterable[Union[str, date]]
    ) -> pd.DataFrame:
        """The 15-minute readings of one or more sensors on some days.

        Args:
            provider: Provider id, such as "airnet".
            sensor_id: Sensor id, or several (fetched in parallel).
            dates: Days, as dates or "YYYY-MM-DD".

        Returns:
            DataFrame with sensor_id, timestamp (local time, without time
            zone, as CPCB data) and one numeric column per parameter. Days
            that OAQ has no file for, and readings without a valid time, are
            left out.
        """
        import pandas as pd

        dates = list(dates)
        if not isinstance(sensor_id, str):
            return _each(lambda s: self.readings(provider, s, dates), sensor_id)
        frames = []
        for day in dates:
            day = pd.Timestamp(day).date()
            try:
                data = self.get_daily(provider, sensor_id, day.year, day.month, day.day)
            except (NetworkError, DataParsingError) as e:
                logger.debug("OAQ %s %s: %s", sensor_id, day, e)
                continue
            rows = pd.DataFrame(data.get("data") if isinstance(data, dict) else None)
            if rows.empty or "date" not in rows:
                continue
            # "2026-09-15T00:15:00+05:30": keep the local wall time
            timestamp = pd.to_datetime(
                rows["date"].astype(str).str.slice(0, 19),
                format="%Y-%m-%dT%H:%M:%S",
                errors="coerce",
            )
            values = rows.drop(columns="date").apply(pd.to_numeric, errors="coerce")
            frames.append(values.assign(sensor_id=sensor_id, timestamp=timestamp))
        if not frames:
            return pd.DataFrame(columns=["sensor_id", "timestamp"])
        out = pd.concat(frames, ignore_index=True).dropna(subset=["timestamp"])
        first = ["sensor_id", "timestamp"]
        return out[first + [c for c in out.columns if c not in first]].reset_index(
            drop=True
        )

    def daily_means(
        self,
        provider: str,
        sensor_id: Sensors,
        dates: Iterable[Union[str, date]],
        min_readings: int = MIN_READINGS,
    ) -> pd.DataFrame:
        """Daily means of the 15-minute readings of one or more sensors.

        OAQ's own daily aggregates (get_monthly, get_annual) are often the
        last reading of the day rather than its mean, so compute the means
        from the readings of get_daily instead.

        Args:
            provider: Provider id, such as "airnet".
            sensor_id: Sensor id, or several (fetched in parallel).
            dates: Days, as dates or "YYYY-MM-DD".
            min_readings: Fewest readings of a parameter for a daily mean;
                the default, 64, is 16 hours, as for the National AQI.

        Returns:
            DataFrame with sensor_id, date (datetime.date) and, for each
            parameter, its mean and its number of readings (n_<parameter>).
            Means with fewer than min_readings readings are NaN. Days that
            OAQ has no file for are left out.
        """
        import pandas as pd

        dates = list(dates)
        if not isinstance(sensor_id, str):
            return _each(
                lambda s: self.daily_means(provider, s, dates, min_readings), sensor_id
            )
        rows = []
        for day in dates:
            day = pd.Timestamp(day).date()
            try:
                data = self.get_daily(provider, sensor_id, day.year, day.month, day.day)
            except (NetworkError, DataParsingError) as e:
                logger.debug("OAQ %s %s: %s", sensor_id, day, e)
                continue
            readings = pd.DataFrame(
                data.get("data") if isinstance(data, dict) else None
            )
            if readings.empty:
                continue
            row: Dict[str, Any] = {"sensor_id": sensor_id, "date": day}
            for column in readings.columns.drop("date", errors="ignore"):
                values = pd.to_numeric(readings[column], errors="coerce").dropna()
                row[f"n_{column}"] = len(values)
                row[column] = values.mean() if len(values) >= min_readings else math.nan
            rows.append(row)
        return pd.DataFrame(rows)

    def stations_table(self, provider: Providers) -> pd.DataFrame:
        """Latest readings of one or more providers, with numeric columns.

        Stations without coordinates are dropped.
        """
        import pandas as pd

        frames = [
            pd.DataFrame(self.get_stations_latest(p).get("stations") or []).assign(
                provider=p
            )
            for p in _as_list(provider)
        ]
        out = _numeric(pd.concat(frames, ignore_index=True))
        if not {"lat", "lon"} <= set(out.columns):
            return out.iloc[0:0]
        return out.dropna(subset=["lat", "lon"]).reset_index(drop=True)

    def fetch_monthly_stations(
        self,
        provider: Providers,
        year: int,
        months: Optional[Iterable[str]] = None,
        city: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        """Daily records of every station of the providers for some months.

        Since about March 2026, OAQ's daily values are often the last reading of the day, not its mean; use daily_means or readings_mean on readings for daily means.

        Args:
            provider: One or more provider ids, such as "cpcb".
            year: Year.
            months: Zero-padded months, such as ["03", "04"]. Default all 12.
            city: Optional city names to keep.

        Returns:
            DataFrame of the daily records with station_id, a date column
            (datetime.date), numeric pollutant columns, and name, lat, lon,
            city and provider from the station list. Stations without data for
            a month are skipped.
        """
        import pandas as pd

        months = list(months or [f"{m:02d}" for m in range(1, 13)])
        frames = []
        for p in _as_list(provider):
            meta = self.stations_table(p)
            if city is not None:
                meta = meta[meta["city"].isin(list(city))]
            records = []
            for sid in meta.get("id", []):
                for month in months:
                    try:
                        data = self.get_monthly(p, sid, year, month).get("data")
                    except (NetworkError, DataParsingError) as e:
                        logger.debug("OAQ %s %s: %s", sid, month, e)
                        continue
                    if data:
                        records.append(pd.DataFrame(data).assign(station_id=sid))
            if not records:
                continue
            cols = [
                c for c in ("id", "name", "lat", "lon", "city", "provider") if c in meta
            ]
            station = meta[cols].rename(columns={"id": "station_id"})
            frames.append(
                pd.concat(records, ignore_index=True).merge(
                    station, on="station_id", how="left"
                )
            )
        if not frames:
            return pd.DataFrame()
        out = _numeric(pd.concat(frames, ignore_index=True))
        if "date" in out:
            out["date"] = pd.to_datetime(out["date"]).dt.date
        return out


def oaq_nearest_cpcb(sensors: pd.DataFrame, k: int = 1) -> pd.DataFrame:
    """The k nearest CPCB stations of each OAQ sensor.

    CPCB stations come from the bundled station directory, so the result does
    not depend on which stations are online.

    Args:
        sensors: Table from OAQClient.sensors or stations_table (id, name,
            city, lat, lon, provider).
        k: Number of CPCB stations per sensor.

    Returns:
        DataFrame with provider, sensor_id, sensor_name, city, rank,
        cpcb_station_id, cpcb_station_name, cpcb_city and distance_km,
        nearest first for each sensor.
    """
    from .utils import nearest_stations

    cpcb = _cpcb_stations()
    pairs = nearest_stations(sensors, cpcb, k=k, from_id="id", to_id="station_id")
    pairs = pairs.rename(
        columns={
            "from_id": "sensor_id",
            "to_id": "cpcb_station_id",
            "dist_km": "distance_km",
        }
    )
    meta = sensors[["id", "provider", "name", "city"]].rename(
        columns={"id": "sensor_id", "name": "sensor_name"}
    )
    out = pairs.merge(meta.drop_duplicates("sensor_id"), on="sensor_id", how="left")
    out = out.merge(
        cpcb[["station_id", "station_name", "city"]].rename(
            columns={
                "station_id": "cpcb_station_id",
                "station_name": "cpcb_station_name",
                "city": "cpcb_city",
            }
        ),
        on="cpcb_station_id",
        how="left",
    )
    columns = ["provider", "sensor_id", "sensor_name", "city", "rank",
               "cpcb_station_id", "cpcb_station_name", "cpcb_city", "distance_km"]  # fmt: skip
    return out[columns]


def oaq_city_tally(sensors: pd.DataFrame) -> pd.DataFrame:
    """OAQ-only sensors (not OAQ's copy of CPCB) by city and provider.

    Returns:
        DataFrame with city, provider, sensors (count), cpcb_stations (CPCB
        stations of the city in the station directory, 0 where CPCB has none)
        and median_km_to_cpcb (median distance of the sensors to their nearest
        CPCB station), most sensors first.
    """
    import pandas as pd

    own = sensors[sensors["provider"].str.lower() != "cpcb"]
    columns = ["city", "provider", "sensors", "cpcb_stations", "median_km_to_cpcb"]
    if own.empty:
        return pd.DataFrame(columns=columns)
    nearest = oaq_nearest_cpcb(own, k=1)
    tally = nearest.groupby(["city", "provider"], as_index=False).agg(
        sensors=("sensor_id", "size"), median_km_to_cpcb=("distance_km", "median")
    )
    per_city = _cpcb_stations()["city"].str.lower().value_counts()
    tally["cpcb_stations"] = (
        tally["city"].str.lower().map(per_city).fillna(0).astype(int)
    )
    tally = tally.sort_values(
        ["sensors", "city", "provider"], ascending=[False, True, True]
    )
    return tally[columns].reset_index(drop=True)


def _cpcb_stations() -> pd.DataFrame:
    """CPCB stations of the bundled directory, with coordinates."""
    import pandas as pd

    from .cpcb_directory import _station_directory

    rows = [
        st
        for city in _station_directory()["stations"].values()
        for st in city
        if st.get("latitude") is not None and st.get("longitude") is not None
    ]
    df = pd.DataFrame(rows)
    return df.assign(
        lat=df["latitude"].astype(float), lon=df["longitude"].astype(float)
    )[["station_id", "station_name", "city", "state", "lat", "lon"]]


def _each(
    fetch: Callable[[str], pd.DataFrame], sensor_ids: Iterable[str]
) -> pd.DataFrame:
    """fetch for each sensor in parallel, as one table in the order of the ids."""
    import pandas as pd

    with ThreadPoolExecutor(OAQ_WORKERS) as pool:
        frames: List[pd.DataFrame] = list(pool.map(fetch, list(sensor_ids)))
    filled = [f for f in frames if not f.empty]
    if not filled:
        return frames[0] if frames else pd.DataFrame(columns=["sensor_id"])
    return pd.concat(filled, ignore_index=True)


def _today_ist() -> date:
    """Today's date in India (IST, UTC+05:30)."""
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).date()


def _as_list(provider: Providers) -> list:
    return [provider] if isinstance(provider, str) else list(provider)


def _numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Columns that are all numbers as numbers."""
    import pandas as pd

    out = df.copy()
    for column in out.columns:
        converted = pd.to_numeric(out[column], errors="coerce")
        if converted.notna().sum() == out[column].notna().sum():
            out[column] = converted
    return out
