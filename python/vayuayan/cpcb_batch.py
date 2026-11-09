"""
The one loop of the batch downloads: raw_readings, station_daily and the city
report. Each station ends in exactly one named status.
"""

from __future__ import annotations

import logging
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import (
    TYPE_CHECKING,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
)

import requests

from . import cpcb_common, http_client
from .exceptions import (
    AmbiguousMatchError,
    CityNotFoundError,
    CPCBError,
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)

if TYPE_CHECKING:
    import pandas as pd

logger = logging.getLogger(__name__)

T = TypeVar("T")

# What can go wrong with one station; a corrupt workbook is a BadZipFile
BATCH_ERRORS: Tuple[Type[BaseException], ...] = (
    CPCBError,
    *cpcb_common.SOURCE_ERRORS,
    zipfile.BadZipFile,
)

# Same strings and order as the R package
STATION_STATUSES = (
    "ok",
    "no_data",
    "not_found",
    "ambiguous",
    "outage",
    "not_attempted",
    "error",
)


def _failure_status(error: BaseException) -> str:
    """The status of a station whose fetch raised error."""
    if isinstance(error, AmbiguousMatchError):
        return "ambiguous"
    if isinstance(error, (StationNotFoundError, CityNotFoundError)):
        return "not_found"
    if cpcb_common.is_outage(error):
        return "outage"
    if isinstance(error, DataNotFoundError) or _is_http_404(error):
        return "no_data"
    return "error"


def _is_http_404(error: BaseException) -> bool:
    return isinstance(error, requests.HTTPError) and (
        http_client.failure_reason(error) == "404"
    )


def _reason(error: BaseException) -> str:
    """Text for a log: a package error's own, which keeps a name's candidates."""
    if isinstance(error, CPCBError):
        return str(error)
    return http_client.failure_reason(error)


@dataclass(frozen=True)
class StationBatch:
    """The frames fetched by a batch and the status of each station."""

    frames: List[pd.DataFrame]
    status: Dict[str, str]
    outage_reason: Optional[str] = None

    @property
    def outage(self) -> bool:
        """True if an outage stopped the run."""
        return self.outage_reason is not None

    def counts(self) -> str:
        """The number of stations in each status, as text."""
        values = list(self.status.values())
        return ", ".join(
            f"{values.count(name)} {name}"
            for name in STATION_STATUSES
            if name in values
        )

    def raise_if_unavailable(self) -> None:
        """Raise NetworkError if nothing was fetched and an outage occurred.

        Raises:
            NetworkError: Carrying station_status, so that a caller can see
                which stations were reached.
        """
        if self.outage and not self.frames:
            error = NetworkError(
                f"CPCB is unavailable: {self.outage_reason} ({self.counts()})"
            )
            error.station_status = dict(self.status)  # type: ignore[attr-defined]
            raise error

    def tagged(self, table: pd.DataFrame) -> pd.DataFrame:
        """table with the status of each station in its attrs."""
        table.attrs["station_status"] = dict(self.status)
        return table


def _collect_stations(
    stations: Sequence[T],
    fetch: Callable[[T], Optional[pd.DataFrame]],
    name: Callable[[T], str],
    skip: Tuple[Type[BaseException], ...],
    workers: int = 1,
    stop_on_outage: bool = False,
    key: Optional[Callable[[T], str]] = None,
) -> StationBatch:
    """Fetch each station, skipping those that fail with a warning.

    Args:
        stations: The stations.
        fetch: Returns the table of a station, or None for no data.
        name: The name of a station, for the warning.
        skip: The errors that skip a station. Other errors propagate.
        workers: Parallel requests.
        stop_on_outage: After the first timeout, connection failure or 5xx,
            mark the remaining stations not_attempted.
        key: The key of a station in the status; the default is name.

    Returns:
        The StationBatch. A partial result logs one warning with the counts.
    """
    outage = threading.Event()
    reasons: List[str] = []
    key_of = key or name

    def one(station: T) -> Tuple[Optional[pd.DataFrame], str]:
        if stop_on_outage and outage.is_set():
            return None, "not_attempted"
        try:
            frame = fetch(station)
        except skip as e:
            status = _failure_status(e)
            if status == "outage" and stop_on_outage:
                reasons.append(_reason(e))
                outage.set()
            else:
                logger.warning("Skipped %s: %s", name(station), _reason(e))
            return None, status
        return frame, "ok" if frame is not None else "no_data"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, stations))

    batch = StationBatch(
        [frame for frame, _ in results if frame is not None],
        {key_of(station): status for station, (_, status) in zip(stations, results)},
        reasons[0] if reasons else None,
    )
    _warn_partial(batch)
    return batch


def _warn_partial(batch: StationBatch) -> None:
    """One warning for a partial result; an empty outage is raised by the caller."""
    all_ok = all(status == "ok" for status in batch.status.values())
    if all_ok or (batch.outage and not batch.frames):
        return
    if batch.outage:
        logger.warning(
            "CPCB outage stopped the run: %s (%s)", batch.outage_reason, batch.counts()
        )
    else:
        logger.warning("Partial result: %s", batch.counts())
