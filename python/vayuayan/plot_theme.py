"""
The vayuayan figure theme for matplotlib: 300 pixels per inch, a system
sans-serif font, recessive grids and axes, and a colour-blind-safe palette.

set_theme() applies it to every figure; the plot_* functions use it on their
own. Slot 3 (aqua) is below 3:1 contrast on the surface, so figures that use
it need a legend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, cast

if TYPE_CHECKING:
    from matplotlib.figure import Figure

# Chart surface, ink, axis and grid
SURFACE, INK, INK_2, MUTED, GRID, AXIS = (
    "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7",
)  # fmt: skip

# categorical colours, assigned in this order
PALETTE: Tuple[str, ...] = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#6250d6", "#e34948",
)  # fmt: skip

# best first
FONTS = ["SF Pro Text", "Helvetica Neue", "Helvetica", "Inter", "Arial", "DejaVu Sans"]

# doubled by set_theme's retina output; saved figures use 300 dpi
DPI = 150


def _installed_fonts() -> List[str]:
    """The installed FONTS; a missing font in font.family warns on every text."""
    from matplotlib import font_manager

    installed = {f.name for f in font_manager.fontManager.ttflist}
    return [f for f in FONTS if f in installed] or ["sans-serif"]


def theme_rc(dpi: int = DPI) -> Dict[str, Any]:
    """The matplotlib rcParams of the theme."""
    from cycler import cycler

    return {
        "figure.dpi": dpi, "savefig.dpi": 300, "savefig.bbox": "tight",
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE, "figure.constrained_layout.use": False,
        "font.family": _installed_fonts(), "font.sans-serif": FONTS, "font.size": 10.5,
        "text.color": INK, "axes.labelcolor": INK_2, "axes.labelsize": 10.5,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
        "axes.axisbelow": True, "axes.prop_cycle": cycler(color=list(PALETTE)),
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.titlepad": 10, "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "lines.linewidth": 2, "lines.markersize": 4, "lines.solid_capstyle": "round",
        "scatter.edgecolors": "none", "legend.frameon": False, "legend.fontsize": 9.5,
    }  # fmt: skip


def set_theme(dpi: int = DPI) -> None:
    """Use the vayuayan theme for all matplotlib figures from now on.

    In a Jupyter notebook it also shows figures as retina PNG (see DPI).

    Args:
        dpi: Resolution of figures on screen before the retina doubling.

    Example:
        >>> from vayuayan import set_theme
        >>> set_theme()
    """
    import matplotlib as mpl

    mpl.rcParams.update(cast(Any, theme_rc(dpi)))
    try:
        from matplotlib_inline.backend_inline import (  # type: ignore[import-not-found,unused-ignore]
            set_matplotlib_formats,
        )

        set_matplotlib_formats("retina")
    except ImportError:  # not in a notebook
        pass


def theme_context(dpi: int = DPI) -> Any:
    """The theme for the figures made inside a with block."""
    from matplotlib import rc_context

    return rc_context(cast(Any, theme_rc(dpi)))


def new_figure(size: Tuple[float, float]) -> Figure:
    """A figure made with pyplot, so that notebooks display it, and closed, so
    that a notebook shows the returned figure once and scripts do not collect
    open figures."""
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=size)
    plt.close(fig)
    return fig


def day_label(when: Any) -> str:
    """'1 March 2026', without zero padding on any platform."""
    return f"{when.day} {when:%B %Y}"


def mark_change(ax: Any, change: Optional[Any], y: Optional[float] = None) -> None:
    """A vertical line at the date change, labelled, if change is given."""
    import matplotlib.dates as mdates
    import pandas as pd

    if change is None:
        return
    when = pd.Timestamp(change)
    x = mdates.date2num(when)
    ax.axvline(x, color=INK, lw=1)
    if y is None:
        ax.text(
            x,
            0.97,
            f"  {day_label(when)}",
            transform=ax.get_xaxis_transform(),
            va="top",
        )
    else:
        ax.text(x, y, f"  {day_label(when)}", va="center")
