"""Rich rendering of the history command: the year heatmap and its summaries."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any, Dict, Optional, Sequence

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .cli_results import CommandResult
from .cli_scale import SCALES, Scale

_WIDE_CELL_FROM = 100
_MONTH_LABEL_WIDTH = 5
_NO_AQI_REASONS = {
    "too_few_hours": "too few hours",
    "no_pm": "no PM2.5 or PM10",
    "too_few_pollutants": "too few pollutants",
    "no_sub_index": "no pollutant in range",
    "o3_beyond_table": "ozone beyond the 8-hour table",
}


def scale_legend(scale: Scale) -> Text:
    """The standard in use and one coloured chip per category, three to a row."""
    text = Text()
    text.append(f"Standard: {scale.label}", style="bold")
    for index, (band, name, value_range, style) in enumerate(scale.legend()):
        text.append("\n" if index % 3 == 0 else "  ")
        text.append(f" {band} {name} {value_range} ", style=style)
    text.append("  · no data", style="dim")
    return text


def _cell(mark: str, width: int) -> str:
    """A heatmap cell of the given width."""
    return f"{mark:>2}" if width == 2 else f"{mark:^3}"


def _day_label(day: int, width: int) -> str:
    """A column heading; narrow columns label only every fifth day to stay legible."""
    labelled = width > 2 or day == 1 or day % 5 == 0
    return _cell(str(day) if labelled else "", width)


def heatmap(
    days: Sequence[Dict[str, Any]],
    year: int,
    month: Optional[int],
    scale: Scale,
    console_width: int,
) -> Text:
    """Months down and days across, each cell in its category colour.

    Each cell holds the band number, so the map still reads without colour.
    """
    by_date = {day["date"]: day for day in days}
    width = 3 if console_width >= _WIDE_CELL_FROM else 2
    text = Text(no_wrap=True, overflow="ignore")
    text.append(" " * _MONTH_LABEL_WIDTH)
    text.append("".join(_day_label(d, width) for d in range(1, 32)), style="bold")
    for number in [month] if month else range(1, 13):
        text.append(
            f"\n{calendar.month_abbr[number]:<{_MONTH_LABEL_WIDTH}}", style="bold"
        )
        for day in range(1, 32):
            try:
                iso = date(year, number, day).isoformat()
            except ValueError:
                text.append(" " * width)
                continue
            entry = by_date.get(iso)
            if entry is None:
                text.append(_cell("·", width), style="dim")
            else:
                band = scale.band(entry["category"])
                text.append(
                    _cell(str(band), width), style=scale.style(entry["category"])
                )
    return text


def _title(data: Dict[str, Any]) -> str:
    """The place and period of a history result."""
    if data["place"] == "station":
        station = data["station"]
        place = f"{station['name']} ({station['id']})"
    else:
        place = f"{data['city']}, {data['state']} (city average)"
    period = str(data["year"])
    if data["month"]:
        period = f"{calendar.month_name[data['month']]} {data['year']}"
    return f"{place}, {period}"


def _chip(aqi: int, category: str, scale: Scale) -> Text:
    """An AQI and its category in the category's colour."""
    return Text(f" {aqi} {category} ", style=scale.style(category))


def _summary_table(summary: Dict[str, Any], scale: Scale) -> Table:
    """The mean, the worst and best days, and days with data."""
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", no_wrap=True)
    grid.add_column()
    mean = Text(f"{summary['mean']:.1f} ")
    mean.append(
        f" {summary['mean_category']} ", style=scale.style(summary["mean_category"])
    )
    grid.add_row("Mean AQI", mean)
    for label, key in (("Worst day", "worst"), ("Best day", "best")):
        day = summary[key]
        cell = Text.assemble(
            _chip(day["aqi"], day["category"], scale), f"  on {_pretty(day['date'])}"
        )
        grid.add_row(label, cell)
    grid.add_row(
        "Days with data",
        f"{summary['days_with_data']} of {summary['days_in_period']}",
    )
    return grid


def _pretty(iso: str) -> str:
    """An ISO date as a day, month and year."""
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%b %Y}"


def _counts_table(counts: Dict[str, int], scale: Scale) -> Table:
    """The days per category."""
    table = Table(title="Days per category", box=box.SIMPLE_HEAD, title_justify="left")
    table.add_column("Category")
    table.add_column("Range")
    table.add_column("Days", justify="right")
    for band, name, value_range, style in scale.legend():
        table.add_row(
            Text(f" {band} {name} ", style=style), value_range, str(counts[name])
        )
    return table


def _months_table(months: Sequence[Dict[str, Any]], scale: Scale) -> Table:
    """One row per month of a city."""
    table = Table(title="By month", box=box.SIMPLE_HEAD, title_justify="left")
    table.add_column("Month")
    table.add_column("Mean AQI", justify="right")
    table.add_column("Category")
    table.add_column("Worst", justify="right")
    table.add_column("Days", justify="right")
    for month in months:
        table.add_row(
            month["name"],
            f"{month['mean']:.1f}",
            Text(f" {month['category']} ", style=scale.style(month["category"])),
            str(month["worst"]["aqi"]),
            str(month["days_with_data"]),
        )
    return table


def _report(result: CommandResult, console: Console) -> None:
    """The concentrations of a report."""
    data = result.data
    place = data["station"]["name"] if data["place"] == "station" else data["city"]
    every = data["every"].replace("_", " ")
    table = Table(
        title=f"Readings of {place}, {data['from'][:16]} to {data['to'][:16]}, every {every}",
        box=box.SIMPLE_HEAD,
    )
    table.add_column("Pollutant")
    table.add_column("Unit")
    for label in ("Lowest", "Mean", "Highest", "Readings"):
        table.add_column(label, justify="right")
    for row in data["summary"]:
        table.add_row(
            row["pollutant"],
            row["unit"],
            f"{row['lowest']:.2f}",
            f"{row['mean']:.2f}",
            f"{row['highest']:.2f}",
            str(row["readings"]),
        )
    console.print(table)
    if result.message:
        console.print(Text(result.message, style="bold yellow"))
    console.print(
        Text(
            "These are measured concentrations, not AQI values.",
            style="bold",
        )
    )
    if data.get("saved"):
        console.print(f"Saved to {data['saved']}")
    else:
        console.print("Add --save FILE to keep every reading as a CSV.")


def render_history(result: CommandResult, console: Console) -> None:
    """The history command's output."""
    data = result.data
    if data.get("kind") == "report":
        _report(result, console)
        return

    scale = SCALES[data["standard"]]
    console.print(Text(_title(data), style="bold"))
    console.print(
        heatmap(data["days"], data["year"], data["month"], scale, console.width)
    )
    console.print()
    console.print(scale_legend(scale))
    source = (
        "Computed from raw 15-minute readings."
        if data["source"] == "computed"
        else "CPCB's published daily AQI."
    )
    console.print(Text(f"Source: {source}"))
    console.print()
    console.print(_summary_table(data["summary"], scale))
    console.print(_counts_table(data["summary"]["category_counts"], scale))
    if data.get("days_without_aqi"):
        reasons = ", ".join(
            f"{count} {_NO_AQI_REASONS.get(status, status)}"
            for status, count in data["days_without_aqi"].items()
        )
        console.print(Text(f"Days without an AQI: {reasons}", style="bold yellow"))
    if data["place"] == "city":
        console.print(_months_table(data["months"], scale))
    if data.get("saved"):
        console.print(f"Saved to {data['saved']}")
