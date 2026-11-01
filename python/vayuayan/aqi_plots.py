"""
Radial AQI plots (matplotlib): daily calendar and 24-hour clock.

Needs pip install "vayuayan[plot]".
"""

from __future__ import annotations

import calendar
import math
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from .constants import AQI_CATEGORIES, AQI_COLORS
from .plot_theme import new_figure, theme_context
from .utils import aqi_category_index

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.figure import Figure

MISSING = "#d9d9d9"
IST = "Asia/Kolkata"  # CPCB and OAQ times are IST clock times
HOLE = 1.5  # empty centre, in rings, so the inner ring is not a point


def _aqi_cmap() -> Tuple[Any, Any]:
    """Colour map and norm for AQI category indices (0 = Good)."""
    import numpy as np
    from matplotlib.colors import BoundaryNorm, ListedColormap

    cmap = ListedColormap([AQI_COLORS[n] for n in AQI_CATEGORIES])
    cmap.set_bad(MISSING)
    return cmap, BoundaryNorm(np.arange(len(AQI_CATEGORIES) + 1) - 0.5, cmap.N)


def _radial_axes(panels: List[str], ncol: int) -> Tuple[Figure, List[Any]]:
    """One clockwise polar axis per panel, 0 at 12 o'clock."""
    ncols = min(ncol, len(panels))
    nrows = math.ceil(len(panels) / ncols)
    fig = new_figure((5 * ncols, 5 * nrows + 1.2))
    axes = []
    for k, name in enumerate(panels):
        ax: Any = fig.add_subplot(nrows, ncols, k + 1, projection="polar")
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        ax.grid(False)
        ax.spines["polar"].set_visible(False)
        if name:
            ax.set_title(name, loc="center", fontsize=14, pad=22)
        axes.append(ax)
    return fig, axes


def _legend_and_titles(fig: Figure, title: str, subtitle: str) -> None:
    from matplotlib.patches import Patch

    names = list(AQI_CATEGORIES)
    fig.legend(
        handles=[
            Patch(color=AQI_COLORS[n], label=f"{n}\n{b['min']}-{b['max']}")
            for n, b in zip(names, AQI_CATEGORIES.values())
        ],
        loc="upper center", bbox_to_anchor=(0.5, 1 - 1.0 / fig.get_figheight()),
        ncol=len(names), handlelength=2.5, handleheight=1.2,
    )  # fmt: skip
    fig.text(0.02, 1 - 0.25 / fig.get_figheight(), title,
             fontsize=20, fontweight="bold", va="top")  # fmt: skip
    fig.text(0.02, 1 - 0.65 / fig.get_figheight(), subtitle, va="top")
    fig.tight_layout(rect=(0, 0, 1, 1 - 1.6 / fig.get_figheight()))
    # tight_layout ignores polar tick labels
    fig.subplots_adjust(hspace=0.3)


def plot_aqi_radial(
    daily: pd.DataFrame, ncol: int = 2, theme: Optional[Dict[str, Any]] = None
) -> Figure:
    """Daily AQI as a radial calendar.

    Each year is one ring, with the first year at the centre and the last at
    the edge. January is at 12 o'clock and the months run clockwise. Cells
    take the colour of the CPCB AQI category; days without a value are grey.
    With a city column there is one circle per city.

    Args:
        daily: A numeric value column (daily AQI) and either a date column or
            year, month and day columns, such as CPCBHistorical.city_daily
            output. An optional city column gives one panel per city.
        ncol: Number of panel columns when there is more than one city.
        theme: matplotlib rcParams applied over the vayuayan theme, such as
            {"figure.facecolor": "#222222", "text.color": "white"}.

    Example:
        >>> daily = CPCBHistorical().city_daily(["Chennai"], range(2017, 2026))
        >>> plot_aqi_radial(daily).savefig("chennai.png")
    """
    import numpy as np
    import pandas as pd
    from matplotlib import rc_context

    if "date" in daily:
        dates = pd.to_datetime(daily["date"], errors="coerce")
    else:
        dates = pd.to_datetime(daily[["year", "month", "day"]], errors="coerce")
    panel = daily["city"].astype(str) if "city" in daily else ""
    d = pd.DataFrame({"panel": panel, "date": dates, "value": daily["value"]})
    d = d.dropna(subset=["date"]).drop_duplicates(["panel", "date"])
    if d.empty:
        raise ValueError("No dated rows in daily.")
    values = d.set_index(["panel", "date"])["value"]
    first, last = int(d["date"].dt.year.min()), int(d["date"].dt.year.max())
    panels = sorted(d["panel"].unique())

    cmap, norm = _aqi_cmap()
    month_angles = (np.arange(12) + 0.5) * 2 * math.pi / 12

    with theme_context(), rc_context(theme or {}):
        fig, axes = _radial_axes(panels, ncol)
        for ax, name in zip(axes, panels):
            for year in range(first, last + 1):
                days = pd.date_range(f"{year}-01-01", f"{year}-12-31")
                v = values.reindex(pd.MultiIndex.from_product([[name], days]))
                index = np.ma.masked_invalid(aqi_category_index(v.to_numpy()))
                # leap years also span the full circle
                theta = np.linspace(0, 2 * math.pi, len(days) + 1)
                ring = year - first + 1 + HOLE
                ax.pcolormesh(
                    theta, [ring - 0.45, ring + 0.45], index[None, :],
                    cmap=cmap, norm=norm, shading="flat",
                )  # fmt: skip
            ax.set_ylim(0, last - first + 1.5 + HOLE)
            ax.set_xticks(month_angles, list(calendar.month_abbr)[1:])
            ax.set_yticks([])
        _legend_and_titles(
            fig, "Daily Air Quality Index",
            f"One ring per year: {first} at the centre, {last} at the edge",
        )  # fmt: skip
    return fig


def plot_aqi_radial_hourly(
    hourly: pd.DataFrame,
    rings: str = "month",
    ncol: int = 2,
    theme: Optional[Dict[str, Any]] = None,
) -> Figure:
    """Hourly AQI as a 24-hour clock.

    The angle is the hour of the day: midnight at 12 o'clock and noon at 6
    o'clock, running clockwise like a clock face. With rings="month" each
    ring is a calendar month (January at the centre, December at the edge)
    and each cell is the mean AQI for that hour over all days of that month
    in all years. With rings="day" each ring is one date. Cells take the
    colour of the CPCB AQI category; cells without a value are grey. With a
    city column there is one clock per city.

    Args:
        hourly: A numeric value column (hourly AQI) and a timestamp (or date)
            column with the time of day. The clock is always in IST. Times
            without a time zone are IST clock times, as in CPCB and OAQ data;
            times with a time zone (for example UTC) are converted to IST.
            An optional city column gives one panel per city.
        rings: "month" or "day".
        ncol: Number of panel columns when there is more than one city.
        theme: matplotlib rcParams applied over the vayuayan theme.

    Example:
        >>> plot_aqi_radial_hourly(hourly).savefig("delhi_hourly.png")
    """
    import numpy as np
    import pandas as pd
    from matplotlib import rc_context

    if rings not in ("month", "day"):
        raise ValueError('rings must be "month" or "day"')
    column = "timestamp" if "timestamp" in hourly else "date"
    times = pd.to_datetime(hourly[column], errors="coerce")
    if times.dt.tz is not None:
        times = times.dt.tz_convert(IST).dt.tz_localize(None)
    panel = hourly["city"].astype(str) if "city" in hourly else ""
    d = pd.DataFrame({"panel": panel, "t": times, "value": hourly["value"]})
    d = d.dropna(subset=["t"])
    if d.empty:
        raise ValueError(f"No timestamped rows in hourly[{column!r}].")
    d["hour"] = d["t"].dt.hour
    if rings == "month":
        d["ring"] = d["t"].dt.month
        keys: List[Any] = list(range(1, 13))
        starts = list(range(12))
        labels = list(calendar.month_abbr)[1:]
        what = (
            "One ring per month, January at the centre; each cell is the mean"
            " AQI of that hour"
        )
        sub = 4  # sub-cells per hour round off month rings
    else:
        d["ring"] = d["t"].dt.normalize()
        keys = list(pd.date_range(d["ring"].min(), d["ring"].max()))
        yearly = len(keys) > 366  # one label per year, not per month
        starts = [
            i for i, k in enumerate(keys)
            if k.day == 1 and (k.month == 1 or not yearly)
        ] or [0]  # fmt: skip
        labels = [keys[i].strftime("%Y" if yearly else "%b") for i in starts]
        what = "One ring per day, first day at the centre"
        sub = 1
    cells = d.groupby(["panel", "ring", "hour"])["value"].mean()
    panels = sorted(d["panel"].unique())

    cmap, norm = _aqi_cmap()
    theta = np.linspace(0, 2 * math.pi, 24 * sub + 1)
    r = np.arange(len(keys) + 1) + HOLE
    hours = np.arange(0, 24, 3)

    with theme_context(), rc_context(theme or {}):
        fig, axes = _radial_axes(panels, ncol)
        for ax, name in zip(axes, panels):
            index = pd.MultiIndex.from_product([[name], keys, range(24)])
            v = cells.reindex(index).to_numpy(dtype=float)
            grid = aqi_category_index(v).reshape(-1, 24)
            ax.pcolormesh(
                theta, r, np.ma.masked_invalid(np.repeat(grid, sub, axis=1)),
                cmap=cmap, norm=norm, shading="flat", rasterized=rings == "day",
            )  # fmt: skip
            # quarter-day spokes help read the hour
            ax.vlines(
                np.arange(0, 24, 6) * math.pi / 12, HOLE, r[-1], color="white", lw=0.8
            )
            ax.set_ylim(0, r[-1])
            ax.set_xticks(hours * math.pi / 12, [f"{h:02d}:00" for h in hours])
            ax.set_yticks(r[starts] + 0.5, labels, fontsize=7)
            ax.set_rlabel_position(0)
            ax.set_axisbelow(False)  # ring labels over the cells
            for label in ax.get_yticklabels():
                label.set_bbox(
                    {"facecolor": "white", "alpha": 0.6, "pad": 0.5, "lw": 0}
                )
        _legend_and_titles(
            fig, "Hourly Air Quality Index",
            f"Hour of day (IST) clockwise from midnight at the top. {what}",
        )  # fmt: skip
    return fig
