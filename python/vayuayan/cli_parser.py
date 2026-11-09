"""The argparse definition of the vayuayan command line."""

from __future__ import annotations

import argparse
import calendar
import importlib.util
from datetime import datetime, timedelta
from pathlib import PurePath
from typing import NoReturn, Optional

from . import __version__
from .cli_results import SAVE_SUFFIXES
from .commands_report import FREQUENCIES
from .pm25_versions import PM25_VERSIONS

EXIT_CODES_HELP = """\
Exit codes:
  0    success
  1    other error, such as a file that could not be written
  2    wrong command or options
  3    place or file not found
  4    the name matches several places
  5    the place exists but has no data
  6    network failure, CPCB down, or location lookup failed
  130  stopped with Ctrl-C
"""

_MAIN_EPILOG = f"""\
Examples:
  vayuayan                          open the menu
  vayuayan live                     air quality near you
  vayuayan live anand vihar         one station (no quotes needed)
  vayuayan live mumbai              every station of a city, worst first
  vayuayan history powai 2025       a year as a calendar heatmap
  vayuayan history powai --standard us
  vayuayan history delhi --from 2026-11-08 --to 2026-11-09 --hourly --save x.csv
  vayuayan find anand vihar
  vayuayan stations --state Kerala

For scripts and agents: add --json for one JSON document on stdout, and
--no-input to forbid prompts. Progress and warnings go to stderr.

Privacy: `vayuayan live` with no place sends your IP address to ip-api.com to
find your approximate location. The IP is never shown or stored.

{EXIT_CODES_HELP}"""

_LIVE_EPILOG = """\
Examples:
  vayuayan live
  vayuayan live powai
  vayuayan live site_5112
  vayuayan live mumbai --state Maharashtra
  vayuayan live --lat 19.07 --lon 72.87

With no place, this command sends your IP address to ip-api.com to find your
approximate location. Give a place or --lat and --lon to avoid that.
"""

_HISTORY_EPILOG = """\
Examples:
  vayuayan history powai 2025
  vayuayan history powai 2025 --month 11
  vayuayan history powai 2025 --standard us
  vayuayan history delhi 2024 --save delhi.csv
  vayuayan history powai 2025 --computed --bulletin
  vayuayan history delhi --from 2026-11-08 --to 2026-11-09 --hourly --save x.csv

YEAR defaults to the last complete year. --standard us and --computed download
a year of raw readings for one station, so they take longer. --to with a date
includes that whole day.
"""

_MONTHS = {
    name.lower(): number
    for names in (calendar.month_name, calendar.month_abbr)
    for number, name in enumerate(names)
    if name
}


class UsageError(Exception):
    """A wrong command line; the message is ready to show."""

    def __init__(self, message: str, usage: str = "") -> None:
        super().__init__(message)
        self.usage = usage


class _Parser(argparse.ArgumentParser):
    """argparse with errors raised, so --json can report them as JSON."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(message, self.format_usage())


_SAVE_HELP = "write a .csv, .json or .parquet file, sorted ascending"


def save_path(text: str) -> str:
    """A file to save to, checked before any data is fetched."""
    # argparse also passes the empty default through this check
    if not text:
        return text
    suffix = PurePath(text).suffix.lower()
    if suffix not in SAVE_SUFFIXES:
        raise argparse.ArgumentTypeError("use a .csv, .json or .parquet file")
    if suffix == ".parquet" and importlib.util.find_spec("pyarrow") is None:
        raise argparse.ArgumentTypeError(
            '.parquet needs pyarrow: pip install "vayuayan[parquet]"'
        )
    return text


def month_number(text: str) -> int:
    """A month number from 1-12 or a name."""
    value = _MONTHS.get(text.lower()) or (int(text) if text.isdigit() else 0)
    if not 1 <= value <= 12:
        raise argparse.ArgumentTypeError(f"not a month: {text}")
    return value


def start_time(text: str) -> datetime:
    """A date, or a date and time."""
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"not a date: {text} (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM')"
        ) from None


def end_time(text: str, now: Optional[datetime] = None) -> datetime:
    """A --to value; a bare date means through the end of that day."""
    moment = start_time(text)
    if len(text) <= 10:
        moment += timedelta(days=1)
    # The export holds nothing after the last whole hour
    limit = (now or datetime.now()).replace(minute=0, second=0, microsecond=0)
    return min(moment, limit)


def _common_options() -> _Parser:
    """Options that every command accepts, before or after its name."""
    parent = _Parser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="print one JSON document on stdout and nothing else",
    )
    parent.add_argument(
        "--no-input",
        action="store_true",
        default=argparse.SUPPRESS,
        help="never prompt; exit with code 4 on an ambiguous name",
    )
    parent.add_argument(
        "--debug",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show the full error when something fails",
    )
    return parent


def _add_history_options(cmd: argparse.ArgumentParser) -> None:
    """The options of the history command."""
    cmd.add_argument(
        "words", nargs="+", metavar="PLACE [YEAR]", help="station or city, then a year"
    )
    cmd.add_argument("--city", default="", help="only this city")
    cmd.add_argument("--state", default="", help="only this state")
    cmd.add_argument("--month", type=month_number, help="one month, 1-12 or a name")
    cmd.add_argument(
        "--standard",
        choices=("india", "us"),
        default="india",
        help="india (published, default) or us (computed from raw readings)",
    )
    cmd.add_argument(
        "--save", default="", type=save_path, metavar="FILE", help=_SAVE_HELP
    )
    cmd.add_argument(
        "--computed",
        action="store_true",
        help="compute India's AQI from raw readings, not CPCB's published value",
    )
    cmd.add_argument(
        "--bulletin",
        action="store_true",
        help="days end at 4 PM, like CPCB's bulletin; implies --computed",
    )
    cmd.add_argument("--from", dest="start", type=start_time, help="start of a period")
    cmd.add_argument("--to", dest="end", type=end_time, help="end of a period")
    cmd.add_argument(
        "--every",
        choices=tuple(FREQUENCIES),
        help="interval of the readings in a period (default: hourly)",
    )
    cmd.add_argument("--hourly", action="store_true", help="same as --every hourly")
    cmd.add_argument("--pollutants", help="comma-separated, such as PM2.5,NOx")


def build_parser() -> argparse.ArgumentParser:
    """The whole command line."""
    parser = _Parser(
        prog="vayuayan",
        description="vayuayan CLI: air quality in India from CPCB and satellites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_MAIN_EPILOG,
        allow_abbrev=False,
        parents=[_common_options()],
    )
    # set_defaults changes the option objects, so the commands get their own copies
    common = _common_options()
    parser.set_defaults(json=False, no_input=False, debug=False)
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    def add(name: str, summary: str, epilog: str = "") -> argparse.ArgumentParser:
        return subparsers.add_parser(
            name,
            help=summary,
            description=summary,
            epilog=epilog,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            allow_abbrev=False,
            parents=[common],
        )

    cmd = add("live", "Current air quality near you or for a place", _LIVE_EPILOG)
    cmd.add_argument("words", nargs="*", metavar="PLACE", help="station, city or ID")
    cmd.add_argument("--city", default="", help="only this city")
    cmd.add_argument("--state", default="", help="only this state")
    cmd.add_argument("--lat", type=float, help="latitude, instead of your IP location")
    cmd.add_argument("--lon", type=float, help="longitude, with --lat")
    cmd.add_argument(
        "--save", default="", type=save_path, metavar="FILE", help=_SAVE_HELP
    )

    _add_history_options(
        add("history", "Daily AQI of a place for a year or a period", _HISTORY_EPILOG)
    )

    cmd = add(
        "find", "Find stations by name", "Example:\n  vayuayan find anand vihar\n"
    )
    cmd.add_argument("words", nargs="+", metavar="QUERY", help="name, city or ID")
    cmd.add_argument(
        "--save", default="", type=save_path, metavar="FILE", help=_SAVE_HELP
    )

    cmd = add(
        "stations",
        "List monitoring stations",
        "Examples:\n  vayuayan stations --state Kerala\n  vayuayan stations --all\n",
    )
    cmd.add_argument("--city", default="", help="only this city")
    cmd.add_argument("--state", default="", help="only this state")
    cmd.add_argument(
        "--save", default="", type=save_path, metavar="FILE", help=_SAVE_HELP
    )
    cmd.add_argument("--limit", type=int, default=40, help="rows to show (default: 40)")
    cmd.add_argument("--all", action="store_true", help="show every station")

    cmd = add(
        "pm25",
        "Satellite PM2.5 for the polygons of a GeoJSON file",
        "Example:\n  vayuayan pm25 districts.geojson 2023 --month 11 --group-by state_name\n",
    )
    cmd.add_argument("geojson", help="GeoJSON file")
    cmd.add_argument("year", type=int, help="year of the data")
    cmd.add_argument(
        "--month", type=month_number, help="month; annual data if left out"
    )
    cmd.add_argument("--group-by", help="column(s) to group polygons by")
    cmd.add_argument(
        "--version",
        choices=list(PM25_VERSIONS),
        default="V6GL03",
        help="dataset version (default: V6GL03)",
    )
    cmd.add_argument(
        "--region",
        choices=["GL", "AS", "EU", "NA", "AF"],
        default="GL",
        help="region file (default: GL, global)",
    )
    return parser
