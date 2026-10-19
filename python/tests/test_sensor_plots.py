"""plot_sensor_vs_reference and the figure theme."""

import pandas as pd
import pytest

pytest.importorskip("matplotlib")

from vayuayan import plot_sensor_vs_reference, set_theme  # noqa: E402
from vayuayan.plot_theme import FONTS, theme_rc  # noqa: E402


def _paired():
    dates = pd.date_range("2026-02-20", periods=20)
    return pd.DataFrame(
        {"date": dates, "pm25": range(20, 40), "reference": range(25, 45)}
    )


def test_plot_sensor_vs_reference_splits_at_the_change():
    fig = plot_sensor_vs_reference(_paired(), change="2026-03-01")
    scatter, series = fig.axes
    labels = [t.get_text() for t in scatter.get_legend().get_texts()]
    assert labels == ["Before 1 March 2026", "From 1 March 2026"]
    assert [len(c.get_offsets()) for c in scatter.collections] == [9, 11]
    assert fig.dpi == theme_rc()["figure.dpi"]


def test_plot_sensor_vs_reference_without_change():
    fig = plot_sensor_vs_reference(_paired(), sensor_label="Airnet")
    assert fig.axes[0].get_legend().get_texts()[0].get_text() == "Airnet"


def test_set_theme_names_the_fonts():
    import matplotlib as mpl

    with mpl.rc_context():
        set_theme()
        assert set(mpl.rcParams["font.family"]) <= set(FONTS) | {"sans-serif"}
        assert mpl.rcParams["savefig.dpi"] == 300


def test_plot_sensor_vs_reference_leaves_out_an_empty_side():
    fig = plot_sensor_vs_reference(_paired(), change="2026-01-01")
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert labels == ["From 1 January 2026"]
