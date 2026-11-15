"""Hourly data of DPCC's Delhi stations from DPCC's website (dpccairdata.com).

CPCB's copies of these stations drop every 15-minute value above 1,000 ug/m3; DPCC's site keeps them.
The site serves hourly averages from 2025-01-01, at most 6 days per request, and its pages prohibit scraping.
"""

from __future__ import annotations

import base64
import datetime as dt
import re
import time
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote

from . import http_client
from .constants import IST_TZ, get_cache_dir
from .utils import DateLike, _as_date

if TYPE_CHECKING:
    import pandas as pd

DPCC_URL = "https://www.dpccairdata.com/dpccairdata/display/{page}.php?stName={code}"
DPCC_FIRST_DAY = dt.date(2025, 1, 1)  # the site refuses earlier start dates
DPCC_MAX_DAYS = 6  # the site refuses a 7-day window
DPCC_PAUSE = 3.0  # seconds between requests
DPCC_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; vayuayan; +https://vayuayan.saketlab.org)"
}

# site code -> station name; the site addresses a station by the base64 of its code
DPCC_STATIONS: Dict[str, str] = {
    "AnandVihar": "Anand Vihar", "Alipur": "Alipur", "AshokVihar": "Ashok Vihar",
    "CwgSports": "CWG Sports Complex, Akshardham", "DwarkaSectro8": "Dwarka, Sector 8",
    "Ignou": "IGNOU", "JLNStadium": "Jawaharlal Nehru Stadium", "Jahangirpuri": "Jahangirpuri", "Jnu": "JNU",
    "KarniSinghShootingRange": "Dr. Karni Singh Shooting Range", "Mandirmarg": "Mandir Marg", "Mundka": "Mundka",
    "Najafgarh": "Najafgarh", "Narela": "Narela", "NationalStadium": "Major Dhyan Chand National Stadium",
    "NehruNagar": "Nehru Nagar", "Nsut": "NSUT (West Campus)", "OkhlaPhase2": "Okhla Phase-2",
    "Patparganj": "Patparganj", "PoothKhurdBawana": "Pooth Khurd, Bawana", "PunjabiBagh": "Punjabi Bagh",
    "Pusa": "Pusa", "RKPuram": "R.K. Puram", "RohiniSector16": "Rohini", "SbvDelhi": "SBV Delhi Cantt",
    "SoniaVihar": "Sonia Vihar", "SpmSpc": "SPM-SPC Talkatora Garden", "SriAurbindoMarg": "Sri Aurobindo Marg",
    "Supersite": "Supersite (Rouse Avenue)", "VivekVihar": "Vivek Vihar", "Wazirpur": "Wazirpur",
}  # fmt: skip

# site parameter code -> (page, pollutant name as in CPCB data, unit)
_MET, _GAS = "AallAdvanceSearchMet", "AallAdvanceSearchCconc"
DPCC_PARAMETERS: Dict[str, Tuple[str, str, str]] = {
    "PM25": (_MET, "PM2.5", "µg/m³"), "PM10": (_MET, "PM10", "µg/m³"), "AT1": (_MET, "AT", "°C"),
    "BP": (_MET, "BP", "mmHg"), "RH": (_MET, "RH", "%"), "SR": (_MET, "SR", "W/mt2"),
    "WS": (_MET, "WS", "m/s"), "WD": (_MET, "WD", "deg"),
    "NH3": (_GAS, "NH3", "µg/m³"), "BEN": (_GAS, "Benzene", "µg/m³"), "CO": (_GAS, "CO", "mg/m³"),
    "NO2": (_GAS, "NO2", "µg/m³"), "NO1": (_GAS, "NO", "µg/m³"), "NOX": (_GAS, "NOx", "ppb"),
    "O3": (_GAS, "Ozone", "µg/m³"), "pXy": (_GAS, "p-Xylene", "µg/m³"), "SO2": (_GAS, "SO2", "µg/m³"),
    "Tol": (_GAS, "Toluene", "µg/m³"),
}  # fmt: skip
_last_request = 0.0  # time.monotonic() of the last request to the site


def dpcc_stations() -> "pd.DataFrame":
    """DPCC's stations: station_id (the site's code) and station_name."""
    import pandas as pd

    return pd.DataFrame(
        {
            "station_id": list(DPCC_STATIONS),
            "station_name": list(DPCC_STATIONS.values()),
        }
    )


def dpcc_hourly(
    stations: Union[str, Iterable[str]],
    start: DateLike,
    end: Optional[DateLike] = None,
    parameters: Union[str, Iterable[str]] = "PM2.5",
) -> "pd.DataFrame":
    """Hourly averages of DPCC stations from DPCC's website, from start to end (local days, inclusive).

    Args:
        stations: Station code or name (see dpcc_stations), or several.
        start: First day, 2025-01-01 or later, as a date or "YYYY-MM-DD".
        end: Last day; start if None.
        parameters: Pollutant names as in CPCB data ("PM2.5", "NO2", "Ozone") or
            DPCC's codes ("PM25", "O3"), one or several.

    Returns:
        DataFrame with TIDY_COLUMNS (city and state "Delhi"), one row per hour with
        a value. timestamp is the start of the hour in local time (IST), without a
        time zone, as in CPCB data.

    Raises:
        ValueError: For an unknown station or parameter, start before 2025-01-01,
            end before start, or a page that no longer has the expected chart.
        requests.RequestException: If a request fails.
    """
    import pandas as pd

    from .tidy import TIDY_COLUMNS, parse_timestamps

    codes = [
        _station_code(s)
        for s in ([stations] if isinstance(stations, str) else stations)
    ]
    pars = [
        _parameter_code(p)
        for p in ([parameters] if isinstance(parameters, str) else parameters)
    ]
    first = _as_date(start)
    last = _as_date(end) if end is not None else first
    if first < DPCC_FIRST_DAY:
        raise ValueError(f"DPCC's site has data from {DPCC_FIRST_DAY} only")
    if last < first:
        raise ValueError("end is before start")
    rows = []
    for code in codes:
        for par in pars:
            page, name, unit = DPCC_PARAMETERS[par]
            for w0, w1 in _windows(first, last):
                for when, value in parse_dpcc_page(_fetch(code, par, page, w0, w1)):
                    rows.append((code, DPCC_STATIONS[code], when, name, unit, value))
    out = pd.DataFrame(
        rows,
        columns=[
            "station_id",
            "station_name",
            "timestamp",
            "pollutant",
            "unit",
            "value",
        ],
    )
    out["timestamp"] = parse_timestamps(out["timestamp"])
    day0, day1 = pd.Timestamp(first), pd.Timestamp(last) + pd.Timedelta(days=1)
    out = out[(out["timestamp"] >= day0) & (out["timestamp"] < day1)]
    out = out.drop_duplicates(["station_id", "pollutant", "timestamp"]).assign(
        city="Delhi", state="Delhi"
    )
    return (
        out[TIDY_COLUMNS]
        .sort_values(["station_id", "pollutant", "timestamp"])
        .reset_index(drop=True)
    )


def parse_dpcc_page(page: str) -> List[Tuple[str, float]]:
    """(hour, value) pairs from a DPCC Advance Search result page (the hour as the site writes it)."""
    if "Search Result" not in page:
        raise ValueError("not a DPCC search result page; the site may have changed")
    cats = re.search(r"categories:\s*\[([^\]]*)\]", page)
    data = re.findall(r"data:\s*\[([^\]]*)\]", page)
    if cats is None or not data:
        return []
    hours = re.findall(r"'([^']+)'", cats[1])
    # the last data array is the series; earlier ones are commented out
    values = data[-1].split(",") if data[-1].strip() else []
    if len(values) != len(hours):
        raise ValueError("DPCC chart has different numbers of hours and values")
    out = []
    for h, v in zip(hours, values):
        try:
            out.append((h, float(v)))
        except ValueError:  # "null" or empty: no value that hour
            continue
    return out


def _windows(first: dt.date, last: dt.date) -> List[Tuple[dt.datetime, dt.datetime]]:
    """Request windows; the site returns the hours after the start time up to the end time."""
    w0 = dt.datetime.combine(first, dt.time()) - dt.timedelta(hours=1)
    stop = dt.datetime.combine(last, dt.time(23))
    out = []
    while w0 < stop:
        w1 = min(w0 + dt.timedelta(days=DPCC_MAX_DAYS), stop)
        out.append((w0, w1))
        w0 = w1
    return out


def _fetch(code: str, par: str, page: str, w0: dt.datetime, w1: dt.datetime) -> str:
    """One result page; windows that ended more than two days ago are cached."""
    path = get_cache_dir() / "dpcc" / f"{code}_{par}_{w0:%Y%m%d%H}_{w1:%Y%m%d%H}.html"
    if path.exists() and path.stat().st_size > 0:
        return path.read_text(encoding="utf-8")
    url = DPCC_URL.format(
        page=page, code=quote(base64.b64encode(code.encode()).decode())
    )
    form = {"parameters": par, "fDate": f"{w0:%Y-%m-%d %H:%M}", "eDate": f"{w1:%Y-%m-%d %H:%M}",
            "duration": "1", "graphType": "Line", "submit": "Search"}  # fmt: skip
    global _last_request
    time.sleep(max(0.0, _last_request + DPCC_PAUSE - time.monotonic()))
    try:
        text = http_client.request(
            "post", url, data=form, headers=DPCC_HEADERS, retries=2, timeout=90
        ).text
    finally:
        _last_request = time.monotonic()
    now = dt.datetime.now(IST_TZ).replace(tzinfo=None)  # the site's hours are IST
    if w1 < now - dt.timedelta(days=2) and "Search Result" in text:
        with http_client.atomic_path(path) as part:
            part.write_text(text, encoding="utf-8")
    return text


def _station_code(station: str) -> str:
    key = _squash(station)
    for code, name in DPCC_STATIONS.items():
        if key in (_squash(code), _squash(name)):
            return code
    raise ValueError(f"unknown DPCC station {station!r}; see dpcc_stations()")


def _parameter_code(parameter: str) -> str:
    key = _squash(parameter)
    for code, (_, name, _) in DPCC_PARAMETERS.items():
        if key in (_squash(code), _squash(name)):
            return code
    raise ValueError(
        f"unknown DPCC parameter {parameter!r}; one of {sorted(DPCC_PARAMETERS)}"
    )


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
