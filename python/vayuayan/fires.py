"""Active fire detections over South Asia from NASA FIRMS (MODIS and VIIRS).

Past years come from yearly country archives and the last 7 days from near-real-time files, both keyless;
other days need a FIRMS MAP_KEY (map_key or FIRMS_MAP_KEY).
"""

from __future__ import annotations

import datetime as dt
import io
import logging
import os
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

import requests

from . import http_client
from .constants import IST, get_cache_dir
from .exceptions import ConfigurationError, DataParsingError
from .utils import DateLike, _as_date

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov"
# source -> (archive folder, 7-day file path, API source prefix)
FIRMS_SOURCES: Dict[str, Tuple[str, str, str]] = {
    "modis": ("modis", "modis-c6.1/csv/MODIS_C6_1_South_Asia_7d.csv", "MODIS"),
    "viirs-snpp": (
        "viirs-snpp",
        "suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_South_Asia_7d.csv",
        "VIIRS_SNPP",
    ),
    "viirs-noaa20": (
        "viirs-jpss1",
        "noaa-20-viirs-c2/csv/J1_VIIRS_C2_South_Asia_7d.csv",
        "VIIRS_NOAA20",
    ),
    # no country archive (404), so past years go to the API; science data starts March 2023
    "viirs-noaa21": (
        "viirs-jpss2",
        "noaa-21-viirs-c2/csv/J2_VIIRS_C2_South_Asia_7d.csv",
        "VIIRS_NOAA21",
    ),
}
INDIA_BBOX = (68.0, 6.5, 97.5, 37.5)
# archive name -> rough (west, south, east, north); a past year reads every file whose box meets bbox
# South Asia and neighbours only; a box elsewhere goes to the API
ARCHIVE_COUNTRIES: Dict[str, Tuple[float, float, float, float]] = {
    "India": (68.1, 6.7, 97.4, 35.7),
    "Pakistan": (60.8, 23.6, 77.9, 37.1),
    "Nepal": (80.0, 26.3, 88.2, 30.5),
    "Bangladesh": (88.0, 20.6, 92.7, 26.7),
    "Bhutan": (88.7, 26.7, 92.2, 28.3),
    "Sri_Lanka": (79.6, 5.9, 81.9, 9.9),
    "Myanmar": (92.2, 9.8, 101.2, 28.6),
    "Afghanistan": (60.5, 29.3, 75.0, 38.5),
    "China": (73.5, 18.1, 134.8, 53.6),
}
FIRE_COLUMNS = [
    "latitude", "longitude", "date", "datetime", "satellite",
    "confidence", "frp", "daynight",
]  # fmt: skip
API_DAYS = 5  # most days per FIRMS area API request
NRT_DAYS = 7
VIIRS_CONFIDENCE = {"l": "low", "n": "nominal", "h": "high"}

BBox = Sequence[float]


def firms_fires(
    start: DateLike,
    end: Optional[DateLike] = None,
    bbox: Optional[BBox] = None,
    source: str = "viirs-snpp",
    map_key: Optional[str] = None,
) -> "pd.DataFrame":
    """Fire detections from NASA FIRMS between two dates.

    Args:
        start: First day (UTC), as a date or "YYYY-MM-DD".
        end: Last day (UTC), inclusive; start if None.
        bbox: (west, south, east, north) in degrees; a box around India
            (with parts of its neighbours) if None.
        source: "modis" (2000 on), "viirs-snpp" (2012 on, 375 m),
            "viirs-noaa20" (2018 on) or "viirs-noaa21" (2023 on; FIRMS has no
            yearly archive for it, so past years need map_key).
        map_key: FIRMS MAP_KEY, else $FIRMS_MAP_KEY. Needed only for days
            of the current year older than 7 days.

    Returns:
        DataFrame with FIRE_COLUMNS: date is the UTC day, datetime the UTC
        overpass time, confidence 0-100 for MODIS and low/nominal/high for
        VIIRS, frp the fire radiative power (MW). Sorted by datetime.

    Raises:
        ValueError: If source is unknown or end is before start.
        ConfigurationError: If a day needs the API and there is no MAP_KEY.
        DataParsingError: If FIRMS answers with a message (such as an
            invalid MAP_KEY) instead of fire data.
        requests.RequestException: If a download fails.
    """
    import pandas as pd

    if source not in FIRMS_SOURCES:
        raise ValueError(f"source must be one of {sorted(FIRMS_SOURCES)}")
    first = _as_date(start)
    last = _as_date(end) if end is not None else first
    if last < first:
        raise ValueError("end is before start")
    box = tuple(bbox) if bbox is not None else INDIA_BBOX

    today = dt.datetime.now(dt.timezone.utc).date()
    nrt_from = today - dt.timedelta(days=NRT_DAYS - 1)
    frames: List[pd.DataFrame] = []
    api_days: List[dt.date] = []
    for year in range(first.year, last.year + 1):
        lo, hi = max(first, dt.date(year, 1, 1)), min(last, dt.date(year, 12, 31))
        if year < today.year:
            texts: List[str] = []
            for country in _countries(box):
                text = _archive_csv(source, year, country)
                # a year without an archive goes to the API
                if text is None:
                    texts = []
                    break
                texts.append(text)
            if texts:
                frames += [_parse_firms_csv(t) for t in texts]
                continue
        days = [lo + dt.timedelta(days=i) for i in range((hi - lo).days + 1)]
        if any(d >= nrt_from for d in days):
            frames.append(_parse_firms_csv(_nrt_csv(source)))
        api_days += [d for d in days if d < nrt_from]
    if api_days:
        frames += _api_frames(source, api_days, box, map_key)

    # an empty frame would turn confidence to object
    frames = [f for f in frames if len(f)]
    fires = pd.concat(frames, ignore_index=True) if frames else _parse_firms_csv("")
    keep = (
        (fires["date"] >= first)
        & (fires["date"] <= last)
        & fires["longitude"].between(box[0], box[2])
        & fires["latitude"].between(box[1], box[3])
    )
    fires = fires[keep].drop_duplicates()
    return fires.sort_values("datetime", kind="stable").reset_index(drop=True)


def fire_daily_counts(
    fires: "pd.DataFrame",
    lat: float,
    lon: float,
    radius_km: float = 100.0,
    start: Optional[DateLike] = None,
    end: Optional[DateLike] = None,
    tz: str = IST,
) -> "pd.DataFrame":
    """Fires and their radiative power within radius_km of a point, per day.

    Args:
        fires: Output of firms_fires.
        lat, lon: The point, such as a CPCB station.
        radius_km: Great-circle distance from the point.
        start, end: Days to report; the first and last day in fires if None.
            Days without fires have n_fires 0 and frp_sum 0.
        tz: Time zone of the days, IST by default to match CPCB's daily
            PM2.5; "UTC" for FIRMS's own acq_date.

    Returns:
        DataFrame with date (day in tz), n_fires and frp_sum (MW).

    Raises:
        ValueError: If end is before start.
    """
    import numpy as np
    import pandas as pd

    local = pd.to_datetime(fires["datetime"], utc=True).dt.tz_convert(tz).dt.date
    first = _as_date(start) if start is not None else min(local, default=None)
    last = _as_date(end) if end is not None else max(local, default=None)
    if first is None or last is None:
        return pd.DataFrame({"date": [], "n_fires": [], "frp_sum": []})
    if last < first:
        raise ValueError("end is before start")

    near = _haversine_km(lat, lon, fires["latitude"], fires["longitude"]) <= radius_km
    grouped = fires["frp"][near].groupby(local[near]).agg(["size", "sum"])
    dates = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    grouped = grouped.reindex(dates, fill_value=0)
    return pd.DataFrame(
        {
            "date": dates,
            "n_fires": grouped["size"].to_numpy(dtype=np.int64),
            "frp_sum": grouped["sum"].to_numpy(dtype=float),
        }
    )


def _haversine_km(
    lat: float, lon: float, lats: "pd.Series", lons: "pd.Series"
) -> "pd.Series":
    import numpy as np

    p1, p2 = np.radians(lat), np.radians(lats)
    a = (
        np.sin((p2 - p1) / 2) ** 2
        + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lons - lon) / 2) ** 2
    )
    return 2 * 6371 * np.arcsin(np.sqrt(a))


def _parse_firms_csv(text: str) -> "pd.DataFrame":
    """FIRMS CSV (archive, 7-day file or API) -> FIRE_COLUMNS."""
    import pandas as pd

    head = text.lstrip().split("\n", 1)[0]
    if head and "latitude" not in head:
        raise DataParsingError(f"FIRMS answered {head[:200]!r} instead of fire data")
    if not head:
        empty = pd.DataFrame({c: pd.Series(dtype=object) for c in FIRE_COLUMNS})
        return empty.astype({"latitude": float, "longitude": float, "frp": float})
    raw = pd.read_csv(io.StringIO(text), dtype={"acq_time": str, "satellite": str})
    when = pd.to_datetime(
        raw["acq_date"] + raw["acq_time"].str.zfill(4), format="%Y-%m-%d%H%M", utc=True
    )
    conf = raw["confidence"]
    # VIIRS: l/n/h in the archive, words in NRT files
    if not pd.api.types.is_numeric_dtype(conf):
        conf = conf.str[0].str.lower().map(VIIRS_CONFIDENCE)
    return pd.DataFrame(
        {
            "latitude": raw["latitude"].astype(float),
            "longitude": raw["longitude"].astype(float),
            "date": when.dt.date,
            "datetime": when,
            "satellite": raw["satellite"],
            "confidence": conf,
            "frp": raw["frp"].astype(float),
            "daynight": raw["daynight"],
        }
    )


def _get_text(url: str) -> str:
    if "/api/" not in url:
        return http_client.request("get", url, retries=2, timeout=300).text
    # API URLs carry the MAP_KEY: no retries (their log names the path), no URL in errors
    try:
        return http_client.request("get", url, timeout=300).text
    except requests.RequestException as e:
        reason = http_client.failure_reason(e)
        if reason in ("401", "403"):
            raise ConfigurationError(
                f"FIRMS refused the MAP_KEY (HTTP {reason})"
            ) from None
        raise requests.RequestException(
            f"FIRMS API request failed ({reason})"
        ) from None


def _countries(bbox: BBox) -> List[str]:
    """ARCHIVE_COUNTRIES whose box meets bbox."""
    w, s, e, n = bbox
    return [
        c for c, (cw, cs, ce, cn) in ARCHIVE_COUNTRIES.items()
        if cw <= e and ce >= w and cs <= n and cn >= s
    ]  # fmt: skip


def _archive_csv(source: str, year: int, country: str) -> Optional[str]:
    """Yearly country archive text, cached; None if FIRMS has no file yet."""
    folder = FIRMS_SOURCES[source][0]
    name = f"{folder}_{year}_{country}.csv"
    path = get_cache_dir() / "fires" / name
    if path.exists() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8")
    url = f"{FIRMS_URL}/data/country/{folder}/{year}/{name}"
    logger.info("Downloading FIRMS %s %d %s archive", source, year, country)
    try:
        text = _get_text(url)
    except requests.HTTPError as e:
        if http_client.failure_reason(e) == "404":
            return None  # the year is not archived yet; the API has it
        raise
    with http_client.atomic_path(path) as part:
        part.write_text(text, encoding="utf-8")
    return text


def _nrt_csv(source: str) -> str:
    return _get_text(f"{FIRMS_URL}/data/active_fire/{FIRMS_SOURCES[source][1]}")


def _api_frames(
    source: str, days: List[dt.date], bbox: BBox, map_key: Optional[str]
) -> List["pd.DataFrame"]:
    key = map_key or os.environ.get("FIRMS_MAP_KEY", "")
    if not key:
        raise ConfigurationError(
            f"FIRMS has {days[0]} to {days[-1]} only through its API: set "
            "FIRMS_MAP_KEY (free at https://firms.modaps.eosdis.nasa.gov/api/map_key/)"
        )
    prefix = FIRMS_SOURCES[source][2]
    sp_until = _sp_max_date(key, f"{prefix}_SP")
    area = ",".join(f"{v:g}" for v in bbox)
    frames = []
    is_sp = [sp_until is not None and d <= sp_until for d in days]
    for product, group in (
        (f"{prefix}_SP", [d for d, sp in zip(days, is_sp) if sp]),
        (f"{prefix}_NRT", [d for d, sp in zip(days, is_sp) if not sp]),
    ):
        for lo, n in _day_runs(group, API_DAYS):
            url = (
                f"{FIRMS_URL}/api/area/csv/{key}/{product}/{area}/{n}/{lo.isoformat()}"
            )
            frames.append(_parse_firms_csv(_get_text(url)))
    return frames


def _sp_max_date(key: str, product: str) -> Optional[dt.date]:
    """Last day of the standard (science) product; NRT covers the days after."""
    text = _get_text(f"{FIRMS_URL}/api/data_availability/csv/{key}/{product}")
    lines = text.strip().splitlines()
    if len(lines) < 2 or "max_date" not in lines[0]:
        return None
    header = lines[0].split(",")
    return dt.date.fromisoformat(lines[1].split(",")[header.index("max_date")])


def _day_runs(days: List[dt.date], size: int) -> List[Tuple[dt.date, int]]:
    """Consecutive days as (first day, length) runs of at most size days."""
    runs: List[Tuple[dt.date, int]] = []
    for d in sorted(days):
        if runs and runs[-1][1] < size and runs[-1][0] + dt.timedelta(runs[-1][1]) == d:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((d, 1))
    return runs
