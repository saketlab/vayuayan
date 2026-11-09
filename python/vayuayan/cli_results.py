"""The result every CLI command returns, and the exit code of each status."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping

import requests

from . import http_client
from .exceptions import (
    AmbiguousMatchError,
    CityNotFoundError,
    CPCBError,
    DataNotFoundError,
    PM25DownloadError,
    StationNotFoundError,
)
from .exceptions import FileNotFoundError as CPCBFileNotFoundError

# The documented exit code of each result status
EXIT_CODES: Dict[str, int] = {
    "ok": 0,
    "error": 1,
    "usage_error": 2,
    "not_found": 3,
    "ambiguous": 4,
    "no_data": 5,
    "network_error": 6,
    "location_unknown": 6,
}

CPCB_DOWN = "Could not reach CPCB. Check your internet connection and try again."


SAVE_SUFFIXES = (".csv", ".json", ".parquet")
_SORT_ORDER = (
    "state",
    "city",
    "station_name",
    "station_id",
    "year",
    "month",
    "date",
    "Timestamp",
    "timestamp",
    "pollutant",
)


@dataclass(frozen=True)
class CommandResult:
    """The outcome of a command: a status and JSON-ready data."""

    command: str
    status: str
    data: Dict[str, Any] = field(default_factory=dict)
    message: str = ""

    @property
    def exit_code(self) -> int:
        """The process exit code of this result."""
        return EXIT_CODES[self.status]

    def to_document(self) -> Dict[str, Any]:
        """The JSON document of this result."""
        document: Dict[str, Any] = _json_ready(
            {
                "status": self.status,
                "command": self.command,
                "message": self.message,
                **self.data,
            }
        )
        return document


def _json_ready(value: Any) -> Any:
    """Plain JSON types only; NaN becomes null, which strict parsers accept."""
    if isinstance(value, Mapping):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def error_result(command: str, error: BaseException) -> CommandResult:
    """The result of a command that raised, with a message fit for a user."""
    if isinstance(error, AmbiguousMatchError):
        data = {"matches": [], "candidates": list(error.candidates)}
        return CommandResult(command, "ambiguous", data, str(error))
    if isinstance(error, (StationNotFoundError, CityNotFoundError)):
        return CommandResult(command, "not_found", message=str(error))
    if isinstance(error, DataNotFoundError):
        return CommandResult(command, "no_data", message=str(error))
    if isinstance(error, (CPCBFileNotFoundError, FileNotFoundError)):
        return CommandResult(command, "not_found", message=f"File not found: {error}")
    if isinstance(error, PM25DownloadError):
        # its message is the manual download, which CPCB_DOWN would hide
        return CommandResult(command, "network_error", message=str(error))
    if isinstance(error, (CPCBError, requests.RequestException)):
        status = getattr(error, "station_status", None)
        data = {"station_status": status} if status else {}
        return CommandResult(command, "network_error", data, message=CPCB_DOWN)
    if isinstance(error, OSError):
        return CommandResult(command, "error", message=f"Could not write: {error}")
    return CommandResult(command, "error", message=f"Something went wrong: {error}")


def write_table(table: Any, path: str) -> None:
    """Write a table sorted ascending; the extension of path sets the format.

    Args:
        table: The DataFrame to write.
        path: A .csv, .json or .parquet file. Its folder is created if needed.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    keys = [column for column in _SORT_ORDER if column in table.columns]
    ordered = (
        table.sort_values(keys, ignore_index=True, kind="mergesort") if keys else table
    )
    suffix = target.suffix.lower()
    with http_client.atomic_path(target) as part:
        if suffix == ".json":
            ordered.to_json(
                part, orient="records", date_format="iso", indent=2, force_ascii=False
            )
        elif suffix == ".parquet":
            ordered.to_parquet(part, index=False)
        else:
            ordered.to_csv(part, index=False)


def write_rows(rows: List[Dict[str, Any]], path: str) -> None:
    """Write plain rows; see write_table."""
    import pandas as pd

    write_table(pd.DataFrame(rows), path)
