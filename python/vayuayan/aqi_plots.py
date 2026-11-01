"""
Radial calendar of daily AQI (matplotlib).

Needs pip install "vayuayan[plot]".
"""

from __future__ import annotations

import calendar
import math
from typing import TYPE_CHECKING, Any, Dict, Optional

from .constants import AQI_CATEGORIES, AQI_COLORS
from .plot_theme import new_figure, theme_context
from .utils import aqi_category_index

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.figure import Figure

MISSING = "#d9d9d9"


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
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

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

    names = list(AQI_CATEGORIES)
    cmap = ListedColormap([AQI_COLORS[n] for n in names])
    cmap.set_bad(MISSING)
    norm = BoundaryNorm(np.arange(len(names) + 1) - 0.5, cmap.N)
    hole = 1.5
    month_angles = (np.arange(12) + 0.5) * 2 * math.pi / 12

    ncols = min(ncol, len(panels))
    nrows = math.ceil(len(panels) / ncols)
    with theme_context(), rc_context(theme or {}):
        fig = new_figure((5 * ncols, 5 * nrows + 1.2))
        for k, name in enumerate(panels):
            ax: Any = fig.add_subplot(nrows, ncols, k + 1, projection="polar")
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)
            for year in range(first, last + 1):
                days = pd.date_range(f"{year}-01-01", f"{year}-12-31")
                v = values.reindex(pd.MultiIndex.from_product([[name], days]))
                index = np.ma.masked_invalid(aqi_category_index(v.to_numpy()))
                # leap years also span the full circle
                theta = np.linspace(0, 2 * math.pi, len(days) + 1)
                ring = year - first + 1 + hole
                ax.pcolormesh(
                    theta, [ring - 0.45, ring + 0.45], index[None, :],
                    cmap=cmap, norm=norm, shading="flat",
                )  # fmt: skip
            ax.set_ylim(0, last - first + 1.5 + hole)
            ax.set_xticks(month_angles, list(calendar.month_abbr)[1:])
            ax.set_yticks([])
            ax.grid(False)
            ax.spines["polar"].set_visible(False)
            if name:
                ax.set_title(name, loc="center", fontsize=14, pad=22)
        bands = AQI_CATEGORIES.values()
        fig.legend(
            handles=[
                Patch(color=AQI_COLORS[n], label=f"{n}\n{b['min']}-{b['max']}")
                for n, b in zip(names, bands)
            ],
            loc="upper center", bbox_to_anchor=(0.5, 1 - 1.0 / fig.get_figheight()),
            ncol=len(names), handlelength=2.5, handleheight=1.2,
        )  # fmt: skip
        fig.text(0.02, 1 - 0.25 / fig.get_figheight(), "Daily Air Quality Index",
                 fontsize=20, fontweight="bold", va="top")  # fmt: skip
        fig.text(
            0.02, 1 - 0.65 / fig.get_figheight(),
            f"One ring per year: {first} at the centre, {last} at the edge", va="top",
        )  # fmt: skip
        fig.tight_layout(rect=(0, 0, 1, 1 - 1.6 / fig.get_figheight()))
        # tight_layout ignores polar tick labels
        fig.subplots_adjust(hspace=0.3)
    return fig
