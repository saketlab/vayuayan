"""Rich rendering of the live, find and stations results. Plain data in, text out."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from rich import box
from rich.align import Align
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .cli_render_history import render_history, scale_legend
from .cli_results import CommandResult
from .cli_scale import INDIA, Scale

__all__ = ["make_console", "render", "render_matches", "scale_legend"]

_PANEL_WIDTH = 78
_NO_READING_STYLE = "bold #FFFFFF on #555555"
_STATUS_TEXT = {
    "live": ("Live reading", "bold green"),
    "stale": ("Old reading: CPCB has not published a newer one", "bold yellow"),
    "offline": ("Offline: this station is not reporting", "bold red"),
    "no_reading": ("No AQI for the latest hour", "bold yellow"),
    "fetch_failed": ("Could not reach CPCB", "bold red"),
}
_PROBLEM_HINTS = {
    "not_found": "Try `vayuayan find <part of the name>` or `vayuayan stations`.",
    "network_error": "CPCB may be down. Try again in a few minutes.",
    "location_unknown": "Choose a place instead: `vayuayan live <place>`.",
}
_SOURCE_NAMES = {"dashboard": "CPCB dashboard", "rss": "CPCB RSS feed"}


def make_console(stderr: bool = False) -> Console:
    """A console that prints numbers plainly instead of highlighting them."""
    return Console(stderr=stderr, highlight=False)


def _age(minutes: Optional[int]) -> str:
    """An age in words."""
    if minutes is None:
        return "time unknown"
    if minutes < 1:
        return "just now"
    hours, mins = divmod(minutes, 60)
    if hours == 0:
        return f"{mins} min ago"
    if mins == 0:
        return f"{hours} hours ago" if hours > 1 else "1 hour ago"
    return f"{hours} h {mins} min ago"


def _clock(iso: Optional[str]) -> str:
    """An ISO time as a date and 12-hour time, with its zone."""
    if not iso:
        return "not reported"
    moment = datetime.fromisoformat(iso)
    hour = int(moment.strftime("%I"))
    return f"{moment.day} {moment:%b %Y}, {hour}:{moment:%M %p} IST"


def _banner(reading: Dict[str, Any], scale: Scale) -> RenderableType:
    """The large AQI number and category in the category's colour."""
    if reading["aqi"] is None:
        text, style = "No current reading", _NO_READING_STYLE
    else:
        category = reading["category"]
        text, style = (
            f"AQI {reading['aqi']}   {category}",
            f"bold {scale.style(category)}",
        )
    return Padding(Align.center(Text(text)), (1, 0), style=style, expand=True)


def _value(number: Optional[int], scale: Scale) -> Text:
    """A sub-index cell in the colour of its category, or a dash."""
    if number is None:
        return Text("-", justify="right", style="dim")
    return Text(str(number), justify="right", style=scale.style(scale.category(number)))


def _pollutant_table(pollutants: Sequence[Dict[str, Any]], scale: Scale) -> Table:
    """The pollutants of a reading, labelled as sub-indices."""
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, expand=True)
    table.add_column("Pollutant")
    for title in ("24-hour avg", "Latest hour", "Lowest hour", "Highest hour"):
        table.add_column(title, justify="right")
    for p in pollutants:
        table.add_row(
            p["name"],
            _value(p["average_24h"], scale),
            _value(p["latest_hour"], scale),
            _value(p["lowest_hour"], scale),
            _value(p["highest_hour"], scale),
        )
    return table


def _coordinates(station: Dict[str, Any]) -> str:
    """Latitude and longitude for display."""
    lat, lon = station["latitude"], station["longitude"]
    if lat is None or lon is None:
        return "not known"
    return f"{lat:.4f}, {lon:.4f}"


def _details(reading: Dict[str, Any]) -> Table:
    """The label and value rows of a station."""
    station = reading["station"]
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column(overflow="fold")
    if reading.get("dominant"):
        grid.add_row("Main pollutant", reading["dominant"])
    grid.add_row("Station", station["name"])
    grid.add_row("City", f"{station['city']}, {station['state']}")
    grid.add_row("Lat, long", _coordinates(station))
    grid.add_row("Station ID", station["id"])
    grid.add_row(
        "Collected",
        f"{_clock(reading['collected_at'])}, {_age(reading['age_minutes'])}",
    )
    if reading.get("source"):
        grid.add_row("Source", _SOURCE_NAMES.get(reading["source"], reading["source"]))
    return grid


def _station_panel(reading: Dict[str, Any], width: int) -> Panel:
    """A station's panel."""
    label, style = _STATUS_TEXT[reading["status"]]
    parts: List[RenderableType] = [
        _banner(reading, INDIA),
        Text(label, style=style),
        Text(),
        _details(reading),
    ]
    if reading["pollutants"]:
        parts += [
            Text(),
            Text(
                "Pollutant sub-indices, on the AQI scale of 0-500. These are "
                "not concentrations such as µg/m³. The AQI is the highest "
                "24-hour sub-index.",
                style="bold",
            ),
            _pollutant_table(reading["pollutants"], INDIA),
        ]
    return Panel(Group(*parts), title="Air quality", width=min(width, _PANEL_WIDTH))


def _nearest_line(data: Dict[str, Any]) -> Text:
    """Which station was picked for the user's location, and why."""
    name = data["reading"]["station"]["name"]
    how = (
        "located from your IP; use `vayuayan live <place>` to choose"
        if data["source"] == "ip"
        else "from the coordinates you gave"
    )
    return Text(
        f"Nearest to your location: {name}, about {data['distance_km']:.1f} km away ({how})"
    )


def _city_table(data: Dict[str, Any], console: Console) -> None:
    """A city's stations, worst AQI first, each row in its category colour."""
    table = Table(
        title=f"{data['city']}, {data['state']}: {len(data['readings'])} stations, worst first",
        box=box.SIMPLE_HEAD,
    )
    table.add_column("#", justify="right")
    table.add_column("Station", overflow="fold")
    table.add_column("AQI", justify="right")
    table.add_column("Category", overflow="fold")
    table.add_column("Main", overflow="fold")
    table.add_column("Collected", overflow="fold")
    for position, reading in enumerate(data["readings"], start=1):
        category = reading["category"]
        style = INDIA.style(category) if category else "dim"
        status = reading["status"]
        table.add_row(
            str(position),
            reading["station"]["name"],
            str(reading["aqi"]) if reading["aqi"] is not None else "-",
            category or status.replace("_", " "),
            reading["dominant"] or "-",
            _age(reading["age_minutes"]),
            style=style,
        )
    console.print(table)
    stale = sum(1 for r in data["readings"] if r["status"] == "stale")
    if stale:
        console.print(
            Text(
                f"{stale} of these readings are old: CPCB has not published newer ones.",
                style="bold yellow",
            )
        )


def _render_live(result: CommandResult, console: Console) -> None:
    """The live command's output."""
    data = result.data
    if data.get("place") == "nearest":
        console.print(_nearest_line(data))
        if result.message:
            console.print(Text(result.message, style="bold yellow"))
    if "reading" in data:
        console.print(_station_panel(data["reading"], console.width))
    elif "readings" in data:
        _city_table(data, console)
    console.print(scale_legend(INDIA))


def render_matches(
    matches: Sequence[Dict[str, Any]], console: Console, numbered: bool = True
) -> None:
    """A table of the candidates of an ambiguous place."""
    table = Table(box=box.SIMPLE_HEAD)
    if numbered:
        table.add_column("#", justify="right")
    table.add_column("Place", overflow="fold")
    table.add_column("City", overflow="fold")
    table.add_column("State", overflow="fold")
    for position, match in enumerate(matches, start=1):
        if match["kind"] == "city":
            count = match["station_count"]
            noun = "station" if count == 1 else "stations"
            cells = [f"{match['city']} ({count} {noun})", match["city"], match["state"]]
        else:
            cells = [match["name"], match["city"], match["state"]]
        table.add_row(*([str(position)] if numbered else []), *cells)
    console.print(table)


def _station_table(stations: Sequence[Dict[str, Any]], title: str) -> Table:
    """The ID, name, city, state and coordinates of each station."""
    table = Table(title=title, box=box.SIMPLE_HEAD)
    table.add_column("ID", no_wrap=True)
    table.add_column("Station", overflow="fold")
    table.add_column("City", overflow="fold")
    table.add_column("State", overflow="fold")
    table.add_column("Lat", justify="right")
    table.add_column("Long", justify="right")
    for station in stations:
        lat, lon = station["latitude"], station["longitude"]
        table.add_row(
            station["id"],
            station["name"],
            station["city"],
            station["state"],
            f"{lat:.4f}" if lat is not None else "-",
            f"{lon:.4f}" if lon is not None else "-",
        )
    return table


def _render_find(result: CommandResult, console: Console) -> None:
    """The find command's output."""
    title = f"{result.data['count']} stations match '{result.data['query']}'"
    console.print(_station_table(result.data["matches"], title))


def _render_stations(
    result: CommandResult, console: Console, limit: Optional[int]
) -> None:
    """The stations command's output, cut to limit rows."""
    stations = result.data["stations"]
    shown = stations if limit is None else stations[:limit]
    console.print(_station_table(shown, f"{len(stations)} stations"))
    if len(shown) < len(stations):
        console.print(
            Text(
                f"Showing {len(shown)} of {len(stations)}. Use --all to see them "
                "all, or --city / --state to narrow.",
                style="bold",
            )
        )
    if result.data.get("saved"):
        console.print(f"Saved to {result.data['saved']}")


def _render_pm25(result: CommandResult, console: Console) -> None:
    """The pm25 command's output."""
    rows = result.data["rows"]
    period = f"{result.data['year']}"
    if result.data.get("month"):
        period += f", month {result.data['month']}"
    table = Table(title=f"Satellite PM2.5, {period}", box=box.SIMPLE_HEAD)
    for column in rows[0]:
        table.add_column(str(column), overflow="fold")
    for row in rows:
        table.add_row(
            *(f"{v:.2f}" if isinstance(v, float) else str(v) for v in row.values())
        )
    console.print(table)


def render_problem(result: CommandResult, console: Console) -> None:
    """A short message for a result that could not be shown."""
    console.print(Text(result.message or result.status, style="bold red"))
    hint = _PROBLEM_HINTS.get(result.status)
    if hint:
        console.print(Text(hint))


def _render_ambiguous(result: CommandResult, console: Console) -> None:
    """The candidates of an ambiguous place when the user cannot choose."""
    console.print(Text(result.message, style="bold yellow"))
    # a library error names its candidates in the message
    if result.data.get("matches"):
        render_matches(result.data["matches"], console, numbered=False)
    console.print(Text("Use a longer name, or narrow with --city or --state."))


def render(
    result: CommandResult,
    out: Console,
    err: Console,
    limit: Optional[int] = None,
) -> None:
    """Print a result.

    Args:
        result: The result of a command.
        out: Console for results.
        err: Console for problems.
        limit: The most rows that the stations command shows.
    """
    if result.status == "ambiguous":
        _render_ambiguous(result, err)
    elif result.command == "live" and (
        "reading" in result.data or "readings" in result.data
    ):
        _render_live(result, out)
        if result.data.get("saved"):
            out.print(f"Saved to {result.data['saved']}", markup=False)
    elif result.status != "ok":
        render_problem(result, err)
    elif result.command == "history":
        render_history(result, out)
    elif result.command == "find":
        _render_find(result, out)
    elif result.command == "stations":
        _render_stations(result, out, limit)
    elif result.command == "pm25":
        _render_pm25(result, out)
