"""
Figures of low-cost sensors against a reference station (matplotlib).

Needs pip install "vayuayan[plot]".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .plot_theme import (
    INK,
    INK_2,
    PALETTE,
    day_label,
    mark_change,
    new_figure,
    theme_context,
)

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.figure import Figure


def plot_sensor_vs_reference(
    paired: pd.DataFrame,
    value: str = "pm25",
    reference: str = "reference",
    change: Optional[Any] = None,
    sensor_label: str = "Sensors",
    reference_label: str = "Reference",
    unit: str = "PM2.5 (µg/m³)",
) -> Figure:
    """Daily sensor values against their reference station.

    The left panel plots each sensor-day against the reference, with the 1:1
    line. The right panel plots the median of the sensors and of the
    reference over time. With change, the days from that date are orange in
    the left panel and a line marks the date in the right panel.

    Args:
        paired: One row per sensor and day, with columns date, value and
            reference (for example readings_mean output merged with the
            daily means of the nearest reference station).
        value: Column of the sensor values.
        reference: Column of the reference values.
        change: Optional date to split the days at, such as "2026-03-01".
        sensor_label: Name of the sensors in the legends.
        reference_label: Name of the reference in the axis label and legend.
        unit: Quantity and unit, for the axis labels.
    """
    import matplotlib.dates as mdates
    import pandas as pd
    from matplotlib.lines import Line2D

    d = paired.dropna(subset=[value, reference]).assign(
        day=lambda x: pd.to_datetime(x["date"])
    )
    if change is None:
        groups = [(d, PALETTE[0], sensor_label)]
    else:
        when = pd.Timestamp(change)
        after = d["day"] >= when
        groups = [
            (d[~after], PALETTE[0], f"Before {day_label(when)}"),
            (d[after], PALETTE[1], f"From {day_label(when)}"),
        ]
    with theme_context():
        fig = new_figure((11, 4.6))
        ax, ts = fig.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.6]})
        for pts, colour, label in groups:
            if pts.empty:
                continue  # no days on one side of change
            ax.scatter(pts[reference], pts[value], s=9, alpha=0.55, color=colour,
                       label=label, zorder=2)  # fmt: skip
        top = float(max(d[value].max(), d[reference].max())) if len(d) else 1.0
        ax.plot([0, top], [0, top], color=INK_2, lw=1, ls=(0, (4, 3)), zorder=1)
        ax.annotate("1:1", (top, top), xytext=(-6, 2), textcoords="offset points",
                    ha="right", va="bottom", color=INK_2, fontsize=9)  # fmt: skip
        ax.set(xlim=(0, top * 1.03), ylim=(0, top * 1.03))
        ax.set_xlabel(f"{reference_label} daily {unit}")
        ax.set_ylabel(f"{sensor_label} daily {unit}")
        below = {"loc": "upper center", "bbox_to_anchor": (0.5, -0.16), "ncol": 2}
        ax.legend(markerscale=1.6, **below)

        median = d.groupby("day")[[value, reference]].median()
        ts.plot(median.index, median[reference], color=INK, lw=1.6)
        ts.plot(median.index, median[value], color=PALETTE[0], lw=1.6)
        mark_change(ts, change)
        ts.xaxis.set_major_locator(mdates.MonthLocator())
        ts.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
        ts.set_ylabel(unit)
        ts.set_title("Median of the sensors, day by day")
        ts.legend(handles=[
            Line2D([], [], color=PALETTE[0], lw=2, label=sensor_label),
            Line2D([], [], color=INK, lw=2, label=reference_label),
        ], **below)  # fmt: skip
        fig.tight_layout()
    return fig
