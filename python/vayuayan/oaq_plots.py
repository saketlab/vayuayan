"""
Figures of OAQ's daily records against the 15-minute readings (matplotlib).

Every function takes the output of compare_daily_records or
OAQClient.audit_daily_records (and readings for one day) and returns a Figure.
Blue is the daily mean of the readings, orange the last reading of the day,
greys the days that match both or neither. Needs pip install "vayuayan[plot]".
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

if TYPE_CHECKING:
    import pandas as pd
    from matplotlib.figure import Figure

# Validated colour-blind-safe pair (CVD ΔE 24.7) and neutral greys
MEAN, LAST, BOTH, NEITHER = "#2a78d6", "#eb6834", "#c3c2b7", "#52514e"
SURFACE, INK, INK_2, MUTED, GRID, AXIS = (
    "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7",
)  # fmt: skip
CLASS_COLOURS = {"mean": MEAN, "last": LAST, "both": BOTH, "neither": NEITHER}
CLASS_LABELS = {
    "mean": "Daily value = mean of the readings",
    "last": "Daily value = last reading of the day",
    "both": "Matches both (mean and last reading equal)",
    "neither": "Matches neither",
}
_RC = {
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "font.size": 10.5, "text.color": INK, "axes.labelcolor": INK_2, "axes.edgecolor": AXIS,
    "axes.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2,
    "ytick.labelcolor": INK_2, "xtick.major.size": 0, "ytick.major.size": 0,
    "legend.frameon": False, "axes.titlesize": 12, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.titlepad": 10,
}  # fmt: skip

Labels = Optional[Dict[str, str]]
Change = Optional[Any]


def plot_daily_record_day(
    readings: pd.DataFrame,
    check: Union[pd.DataFrame, pd.Series],
    value: str = "pm25",
    title: Optional[str] = None,
) -> Figure:
    """One day's 15-minute readings with their mean and OAQ's daily record.

    Args:
        readings: Readings of one sensor on one day (OAQClient.readings).
        check: The day's row of compare_daily_records / check_daily_records.
        value: Parameter plotted.
        title: Panel title (default: sensor and date).
    """
    import matplotlib.dates as mdates
    import pandas as pd
    from matplotlib.lines import Line2D

    row = check.iloc[0] if isinstance(check, pd.DataFrame) else check
    r = readings.dropna(subset=[value]).sort_values("timestamp")
    start = pd.Timestamp(row["date"])
    with _style():
        fig = _figure((8, 4.8))
        ax = fig.add_subplot()
        ax.plot(
            r["timestamp"], r[value], color=INK_2, lw=1.2, marker="o", ms=2.6, zorder=2
        )
        ax.axhline(row["mean"], color=MEAN, lw=2)
        ax.axhline(row["record"], color=LAST, lw=2)
        if len(r):
            ax.scatter(
                [r["timestamp"].iloc[-1]], [r[value].iloc[-1]], s=110, color=LAST,
                edgecolor=SURFACE, lw=2, zorder=4,
            )  # fmt: skip
        peak = r[value].max() if len(r) else 0
        ax.set_ylim(0, max(peak, row["record"], row["mean"]) * 1.15)
        ax.set_xlim(start, start + timedelta(hours=23, minutes=59))
        ax.set_title(title or f"Sensor {row['sensor_id']}, {_day(start)}")
        ax.set_ylabel(f"{value} (µg/m³)")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.xaxis.set_major_locator(mdates.HourLocator(byhour=range(0, 24, 4)))
        _legend(fig, [
            Line2D([], [], color=INK_2, marker="o", ms=3, label="15-minute readings"),
            Line2D([], [], color=MEAN, lw=2, label="Mean of the readings"),
            Line2D([], [], color=LAST, lw=2, label="OAQ daily value"),
        ], ncol=3)  # fmt: skip
        record = f"OAQ daily value {row['record']:g}"
        if row["record_is_last"] and len(r):
            record += f" = last reading ({r['timestamp'].iloc[-1]:%H:%M})"
        mean = f"Mean {row['mean']:.2f} ({int(row['n'])} readings)"
        for level, text in [(row["record"], record), (row["mean"], mean)]:
            _place_label(fig, ax, text, level, r["timestamp"], r[value], start)
    return fig


def plot_daily_record_timeline(
    audit: pd.DataFrame, change: Change = None, labels: Labels = None
) -> Figure:
    """Which statistic each day's record equals, one row per sensor.

    Args:
        audit: OAQClient.audit_daily_records (or compare_daily_records) output.
        change: Optional date to mark with a vertical line.
        labels: Optional row labels by sensor key ("provider sensor_id").
    """
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch

    a = _with_key(audit, labels)
    rows = list(dict.fromkeys(a["label"]))
    with _style():
        fig = _figure((13, 1.6 + 0.65 * len(rows)))
        ax = fig.add_subplot()
        for i, label in enumerate(rows):
            g = a[a["label"] == label]
            for cls, colour in CLASS_COLOURS.items():
                days = mdates.date2num(g.loc[g["class"] == cls, "day"])
                ax.broken_barh(
                    [(d - 0.5, 1) for d in days], (i - 0.34, 0.68),
                    facecolors=colour, edgecolor=SURFACE, lw=0.3,
                )  # fmt: skip
        _mark_change(ax, change, y=-0.75)
        ax.set_yticks(range(len(rows)), rows)
        ax.set_ylim(len(rows) - 0.4, -1)
        ax.grid(axis="y", visible=False)
        ax.spines["left"].set_visible(False)
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
        ax.set_title(
            "Which statistic of the day's 15-minute readings OAQ's daily value equals"
        )
        handles = [
            Patch(color=CLASS_COLOURS[c], label=CLASS_LABELS[c]) for c in CLASS_COLOURS
        ]
        _legend(fig, handles, ncol=4)
    return fig


def plot_daily_record_scatter(audit: pd.DataFrame) -> Figure:
    """The daily record against the mean (left) and the last reading (right)."""
    from matplotlib.lines import Line2D

    with _style():
        fig = _figure((12, 6.4))
        axes = fig.subplots(1, 2)
        for ax, stat, xlabel in [
            (axes[0], "mean", "Mean of the day's 15-minute readings"),
            (axes[1], "last", "Last 15-minute reading of the day"),
        ]:
            top = float(audit[[stat, "record"]].max().max()) * 1.03
            ax.plot([0, top], [0, top], color=AXIS, lw=1)
            for cls in ["neither", "both", "mean", "last"]:
                g = audit[audit["class"] == cls]
                ax.scatter(
                    g[stat], g["record"], s=16, color=CLASS_COLOURS[cls], alpha=0.75,
                    edgecolor=SURFACE, lw=0.4,
                )  # fmt: skip
            ax.set_xlim(0, top)
            ax.set_ylim(0, top)
            ax.set_aspect("equal")
            ax.set_xlabel(xlabel)
            ax.set_ylabel("OAQ daily value")
        axes[0].set_title("Against the daily mean")
        axes[1].set_title("Against the last reading")
        handles = [
            Line2D(
                [],
                [],
                ls="",
                marker="o",
                ms=7,
                color=CLASS_COLOURS[c],
                label=CLASS_LABELS[c],
            )
            for c in CLASS_COLOURS
        ]
        _legend(fig, handles, ncol=2, rows=2)
    return fig


def plot_daily_record_share(audit: pd.DataFrame, change: Change = None) -> Figure:
    """Share of days by month that the record equals each statistic."""
    import pandas as pd

    a = audit.assign(month=pd.to_datetime(audit["date"]).dt.to_period("M"))
    share = pd.crosstab(a["month"], a["class"], normalize="index")
    share = share.reindex(columns=list(CLASS_COLOURS), fill_value=0) * 100
    counts = a.groupby("month").size()
    with _style():
        fig = _figure((13, 5))
        ax = fig.add_subplot()
        bottom = pd.Series(0.0, index=share.index)
        for cls in CLASS_COLOURS:
            ax.bar(
                range(len(share)), share[cls], bottom=bottom, color=CLASS_COLOURS[cls],
                width=0.72, edgecolor=SURFACE, lw=2, label=CLASS_LABELS[cls],
            )  # fmt: skip
            bottom = bottom + share[cls]
        for i, n in enumerate(counts):
            ax.text(i, 101.5, str(n), ha="center", color=MUTED, fontsize=8.5)
        ax.set_xticks(range(len(share)), [p.strftime("%b\n%Y") for p in share.index])
        if change is not None:
            months = [str(p) for p in share.index]
            key = str(pd.Timestamp(change).to_period("M"))
            if key in months:
                ax.axvline(months.index(key) - 0.5, color=INK, lw=1)
        ax.set_ylim(0, 106)
        ax.set_ylabel("Share of days (%)")
        ax.grid(axis="x", visible=False)
        ax.set_title("Share of days by month (number of days above each bar)")
        _legend(fig, ax.get_legend_handles_labels()[0], ncol=4)
    return fig


def plot_daily_record_series(
    audit: pd.DataFrame,
    sensor_id: str,
    change: Change = None,
    title: Optional[str] = None,
    value: str = "pm25",
) -> Figure:
    """A sensor's daily record and daily mean over time."""
    import matplotlib.dates as mdates
    import pandas as pd

    a = audit[audit["sensor_id"].astype(str) == str(sensor_id)].copy()
    a["day"] = pd.to_datetime(a["date"])
    with _style():
        fig = _figure((13, 5))
        ax = fig.add_subplot()
        ax.plot(
            a["day"],
            a["mean"],
            color=MEAN,
            lw=2,
            label="Daily mean of the 15-minute readings",
        )
        ax.plot(a["day"], a["record"], color=LAST, lw=1.4, label="OAQ daily value")
        _mark_change(ax, change)
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b\n%Y"))
        ax.set_ylabel(f"{value} (µg/m³)")
        ax.set_title(
            title or f"Sensor {sensor_id}: OAQ's daily value against the daily mean"
        )
        _legend(fig, ax.get_legend_handles_labels()[0], ncol=2)
    return fig


def plot_daily_record_difference(
    audit: pd.DataFrame, change: Any, labels: Labels = None
) -> Figure:
    """Record minus mean per day and sensor, before and from the change date."""
    import pandas as pd
    from matplotlib.lines import Line2D

    when = pd.Timestamp(change)
    a = _with_key(audit, labels)
    a["after"] = a["day"] >= when
    a["difference"] = a["record"] - a["mean"]
    rows = list(dict.fromkeys(a["label"]))
    ticks: List[str] = []
    with _style():
        fig = _figure((13, 5.8))
        ax = fig.add_subplot()
        for i, label in enumerate(rows):
            medians = []
            for j, (after, colour) in enumerate([(False, MEAN), (True, LAST)]):
                diff = a.loc[
                    (a["label"] == label) & (a["after"] == after), "difference"
                ].tolist()
                if not diff:
                    medians.append("–")
                    continue
                x = i + (j - 0.5) * 0.36
                jitter = [
                    x + ((k * 37) % 23 - 11) / 23 * 0.13 for k in range(len(diff))
                ]
                ax.scatter(jitter, diff, s=10, color=colour, alpha=0.6, lw=0)
                medians.append(f"{statistics.median(abs(d) for d in diff):.2f}")
            ticks.append(f"{label}\nmedian absolute difference\n" + " → ".join(medians))
        ax.axhline(0, color=AXIS, lw=1)
        ax.set_yscale("symlog", linthresh=1)
        steps = [-100, -10, -1, 0, 1, 10, 100]
        ax.set_yticks(steps, [f"{t:g}" for t in steps])
        ax.set_xticks(range(len(rows)), ticks)
        ax.grid(axis="x", visible=False)
        ax.set_ylabel("OAQ daily value − daily mean (symlog)")
        ax.set_title(
            f"How far OAQ's daily value is from the daily mean, before and from {_day(when)}"
        )
        _legend(fig, [
            Line2D([], [], ls="", marker="o", ms=7, color=MEAN, label=f"Days before {_day(when)}"),
            Line2D([], [], ls="", marker="o", ms=7, color=LAST, label=f"Days from {_day(when)}"),
        ], ncol=2)  # fmt: skip
    return fig


def _style() -> Any:
    from matplotlib import rc_context

    return rc_context(cast(Any, _RC))


def _figure(size: Tuple[float, float]) -> Figure:
    """A figure made with pyplot, so that notebooks display it, and closed, so
    that a notebook shows the returned figure once and scripts do not collect
    open figures."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=size, dpi=100)
    plt.close(fig)
    return fig


def _day(when: Any) -> str:
    """'1 March 2026', without zero padding on any platform."""
    return f"{when.day} {when:%B %Y}"


def _legend(fig: Figure, handles: Any, ncol: int, rows: int = 1) -> None:
    """Lay the figure out with a strip at its bottom for the legend."""
    bottom = (0.25 + 0.3 * rows) / fig.get_figheight()
    fig.tight_layout(rect=(0, bottom, 1, 1))
    fig.legend(handles=handles, loc="lower center", ncol=ncol, fontsize=9.5,
               bbox_to_anchor=(0.5, 0.0))  # fmt: skip


def _with_key(audit: pd.DataFrame, labels: Labels) -> pd.DataFrame:
    import pandas as pd

    a = audit.copy()
    provider = a["provider"].astype(str) + " " if "provider" in a else ""
    a["key"] = provider + a["sensor_id"].astype(str)
    a["label"] = a["key"].map(lambda k: (labels or {}).get(k, k))
    a["day"] = pd.to_datetime(a["date"])
    return a


def _mark_change(ax: Any, change: Change, y: Optional[float] = None) -> None:
    import matplotlib.dates as mdates
    import pandas as pd

    if change is None:
        return
    when = pd.Timestamp(change)
    x = mdates.date2num(when)
    ax.axvline(x, color=INK, lw=1)
    if y is None:
        ax.text(
            x, 0.97, f"  {_day(when)}", transform=ax.get_xaxis_transform(), va="top"
        )
    else:
        ax.text(x, y, f"  {_day(when)}", va="center")


def _place_label(
    fig: Figure, ax: Any, text: str, level: float, times: pd.Series,
    values: pd.Series, start: Any,
) -> None:  # fmt: skip
    """Label a horizontal line at level where the readings leave room for it.

    Measures the label, then tries every start time of the day (every 15
    minutes) on both sides of the line, and keeps the place where the fewest
    readings run through the label box, and of those the one farthest from
    the readings. Call after the layout is final.
    """
    import matplotlib.dates as mdates
    import numpy as np
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    canvas = (
        fig.canvas if isinstance(fig.canvas, FigureCanvasAgg) else FigureCanvasAgg(fig)
    )
    day0 = mdates.date2num(start)
    label = ax.annotate(text, (day0, level), xytext=(0, 5), textcoords="offset points",
                        va="bottom")  # fmt: skip
    box = label.get_window_extent(canvas.get_renderer())
    (x0, _), (x1, y1) = ax.transData.inverted().transform(
        [[box.x0, box.y0], [box.x1, box.y1]]
    )
    width, height = x1 - x0, y1 - level
    t = np.asarray(mdates.date2num(times), dtype=float)
    v = values.to_numpy(dtype=float)
    quarter = 1 / 96
    # Best place: fewest readings through the label, then the widest gap
    best: Tuple[Tuple[int, float], float, bool] = (
        (-len(v) - 1, 0.0),
        day0 + quarter,
        True,
    )
    for lo in np.arange(day0 + quarter, day0 + 1 - width - quarter, quarter):
        near = v[(t >= lo - quarter) & (t <= lo + width + quarter)]
        for above in (True, False):
            band_lo, band_hi = (
                (level, level + height) if above else (level - height, level)
            )
            hits = int(((near >= band_lo) & (near <= band_hi)).sum())
            gap = (
                float(np.minimum(np.abs(near - band_lo), np.abs(near - band_hi)).min())
                if len(near)
                else np.inf
            )
            if (-hits, gap) > best[0]:
                best = ((-hits, gap), lo, above)
    _, x, above = best
    label.xy = (x, level)
    label.xyann = (0, 5 if above else -5)
    label.set_va("bottom" if above else "top")
