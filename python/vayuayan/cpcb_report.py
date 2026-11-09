"""
CPCB's report export: a station's readings for any period as an Excel file.

The endpoint needs no login. Reports are built from the request, so they are
never cached.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Iterable, Mapping, Optional, Tuple

import requests

from . import cpcb_common, http_client
from .exceptions import DataNotFoundError, NetworkError
from .tidy import _finite_numeric, split_label

if TYPE_CHECKING:
    import pandas as pd

REPORT_PATH = "/cpcb-common-report/api/excel/export"
_CALL_ID = "get-real-time-report-excel"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Request key and raw-file label; the report's heading is the label's name in upper case
REPORT_POLLUTANTS: Tuple[Tuple[str, str], ...] = (
    ("PM25", "PM2.5 (µg/m³)"),
    ("PM10", "PM10 (µg/m³)"),
    ("NO", "NO (µg/m³)"),
    ("NO2", "NO2 (µg/m³)"),
    ("NOx", "NOx (ppb)"),
    ("NH3", "NH3 (µg/m³)"),
    ("SO2", "SO2 (µg/m³)"),
    ("CO", "CO (mg/m³)"),
    ("Ozone", "Ozone (µg/m³)"),
)

_PERIODS = {
    "15_minute": "15M", "15m": "15M",
    "30_minute": "30M", "30m": "30M",
    "hourly": "1H", "1_hour": "1H", "1h": "1H",
    "4_hour": "4H", "4h": "4H",
    "8_hour": "8H", "8h": "8H",
    "daily": "24H", "24_hours": "24H", "24h": "24H", "1d": "24H",
}  # fmt: skip


def _now() -> datetime:
    return datetime.now()


def _plain(name: str) -> str:
    return "".join(c for c in name.upper() if c.isalnum())


def _request_key(name: str) -> str:
    """The request key of a pollutant name such as "PM2.5", "NOx" or "O3"."""
    wanted = {"O3": "OZONE"}.get(_plain(name), _plain(name))
    for key, label in REPORT_POLLUTANTS:
        if wanted in (_plain(key), _plain(split_label(label)[0])):
            return key
    known = ", ".join(split_label(label)[0] for _, label in REPORT_POLLUTANTS)
    raise ValueError(f"{name!r} is not a pollutant of the CPCB report: {known}")


def report_payload(
    info: Mapping[str, str],
    start: Any,
    end: Any,
    frequency: str,
    pollutants: Optional[Iterable[str]],
) -> Dict[str, str]:
    """The JSON body of the export request; raises ValueError for bad arguments."""
    import pandas as pd

    period = _PERIODS.get(frequency.lower())
    if period is None:
        raise ValueError(
            f"{frequency!r} is not a report frequency: {', '.join(_PERIODS)}"
        )
    if pollutants is None:
        names = [key for key, _ in REPORT_POLLUTANTS]
    elif isinstance(pollutants, str):
        names = [pollutants]
    else:
        names = list(pollutants)
    keys = list(dict.fromkeys(_request_key(name) for name in names))
    if not keys:
        raise ValueError("pollutants is empty")
    now = _now()
    parameters = ",".join(keys)
    return {
        "reportDate": now.strftime("%d-%m-%Y"),
        "reportTime": now.strftime("%H:%M:%S"),
        "stationId": info["station_id"],
        "state": info["state"],
        "city": info["city"],
        "station": info["station_name"],
        "parameters": parameters,
        "columns": f"from_time,to_time,{parameters}",
        "avgPeriod": period,
        "fromDate": pd.Timestamp(start).strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": pd.Timestamp(end).strftime("%Y-%m-%d %H:%M:%S"),
        "callid": _CALL_ID,
        "templateId": _CALL_ID,
        "callIdArguments": "stationId,fromDate,toDate,avgPeriod,parameters",
    }


def _report_times(cells: pd.Series) -> pd.Series:
    """The times in From Date cells, NaT where a cell holds no date."""
    import pandas as pd

    stamped = cells.map(lambda cell: isinstance(cell, datetime)).astype(bool)
    text = cells.where(~stamped).astype("string").str.strip()
    times = pd.to_datetime(text, format="%d-%m-%Y %H:%M", errors="coerce")
    times[stamped] = pd.to_datetime(cells[stamped])
    return times


def parse_report(body: bytes) -> pd.DataFrame:
    """The readings of an export file, with the columns of the raw station file.

    Raises:
        DataNotFoundError: If the body is not such a file or has no readings.
    """
    import pandas as pd

    if body[:2] != b"PK":
        raise DataNotFoundError("CPCB sent no usable report")
    try:
        sheet = pd.read_excel(io.BytesIO(body), header=None, dtype=object)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile) as e:
        raise DataNotFoundError("CPCB sent no usable report") from e

    first = sheet.iloc[:, 0].astype(str).str.strip()
    headers = first.index[first == "From Date"]
    if headers.empty:
        raise DataNotFoundError("CPCB sent a report without a data table")
    header = headers[0]

    times = _report_times(sheet.iloc[header + 1 :, 0])
    # The footer rows after the data have no date in this column
    no_date = times.isna().to_numpy()
    n_rows = int(no_date.argmax()) if no_date.any() else no_date.size

    labels = {split_label(label)[0].upper(): label for _, label in REPORT_POLLUTANTS}
    table = pd.DataFrame(
        {"Timestamp": times.iloc[:n_rows].dt.strftime("%Y-%m-%d %H:%M:%S").to_numpy()}
    )
    data = sheet.iloc[header + 1 : header + 1 + n_rows]
    for position, heading in enumerate(sheet.iloc[header]):
        label = labels.get(split_label(str(heading))[0].upper())
        if label is not None:
            table[label] = _finite_numeric(data.iloc[:, position]).to_numpy()
    if table.drop(columns="Timestamp").notna().to_numpy().sum() == 0:
        raise DataNotFoundError("CPCB has no readings for this report")
    return table


def fetch_report(
    url: str,
    info: Mapping[str, str],
    start: Any,
    end: Any,
    frequency: str,
    pollutants: Optional[Iterable[str]],
    session: Optional[requests.Session] = None,
) -> pd.DataFrame:
    """Request one report and return its readings (see parse_report).

    Raises:
        DataNotFoundError: If CPCB cannot build the report (HTTP 500), or
            sends no usable file.
        NetworkError: If CPCB does not answer.
    """
    payload = report_payload(info, start, end, frequency, pollutants)
    try:
        response = cpcb_common.send(
            "post",
            url,
            headers={"Content-Type": "application/json", "Accept": _XLSX},
            json=payload,
            session=session,
            timeout=60,
        )
    except requests.RequestException as e:
        # CPCB answers 500 "Excel generation failed" when it has nothing to export
        if http_client.failure_reason(e) == "500":
            raise DataNotFoundError("CPCB could not build this report") from e
        raise NetworkError("CPCB report export is unavailable") from e
    return parse_report(response.content)
