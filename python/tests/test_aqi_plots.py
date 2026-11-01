"""plot_aqi_radial."""

import pandas as pd
import pytest

pytest.importorskip("matplotlib")

from vayuayan import plot_aqi_radial  # noqa: E402
from vayuayan.constants import AQI_COLORS  # noqa: E402


def test_plot_aqi_radial_draws_a_ring_per_year_and_panel_per_city():
    daily = pd.DataFrame(
        {
            "city": ["A", "A", "B"],
            "year": [2023, 2024, 2024],
            "month": [1, 12, 2],
            "day": [1, 31, 29],
            "value": [40, 450, None],
        }
    )
    fig = plot_aqi_radial(daily)
    assert [ax.get_title() for ax in fig.axes] == ["A", "B"]
    rings = fig.axes[0].collections
    assert len(rings) == 2  # 2023 and 2024
    first = rings[0].get_array()[0]
    assert first[0] == 0 and first.mask[1]  # 1 January Good, 2 January missing
    assert rings[1].get_array().shape == (1, 366)
    legend = [t.get_text().split("\n")[0] for t in fig.legends[0].get_texts()]
    assert legend == list(AQI_COLORS)


def test_plot_aqi_radial_takes_rc_overrides():
    daily = pd.DataFrame({"date": ["2024-03-01"], "value": [120]})
    fig = plot_aqi_radial(daily, theme={"figure.facecolor": "#222222"})
    assert fig.get_facecolor()[:3] == pytest.approx((34 / 255,) * 3)


def test_plot_aqi_radial_hourly_bins_hours_into_month_rings():
    from vayuayan import plot_aqi_radial_hourly

    hourly = pd.DataFrame(
        {
            "city": ["A", "A", "A", "B"],
            "timestamp": [
                "2023-01-01 05:00", "2024-01-09 05:30", "2023-12-31 23:00",
                "2024-06-01 12:00",
            ],
            "value": [40, 80, 450, 120],
        }
    )  # fmt: skip
    fig = plot_aqi_radial_hourly(hourly)
    assert [ax.get_title() for ax in fig.axes] == ["A", "B"]
    cells = fig.axes[0].collections[0].get_array().reshape(12, 96)[:, ::4]
    assert cells[0, 5] == 1  # mean of 40 and 80 is Satisfactory
    assert cells[11, 23] == 5  # Severe
    assert cells.mask[1:11].all()
    legend = [t.get_text().split("\n")[0] for t in fig.legends[0].get_texts()]
    assert legend == list(AQI_COLORS)


def test_plot_aqi_radial_hourly_day_rings():
    from vayuayan import plot_aqi_radial_hourly

    hourly = pd.DataFrame(
        {"date": ["2024-03-01 01:00", "2024-03-03 02:00"], "value": [30, 330]}
    )
    cells = plot_aqi_radial_hourly(hourly, rings="day").axes[0].collections[0]
    grid = cells.get_array().reshape(3, 24)  # day rings: one cell per hour
    assert grid[0, 1] == 0 and grid[2, 2] == 4 and grid.mask[1].all()
    with pytest.raises(ValueError):
        plot_aqi_radial_hourly(hourly, rings="week")


def test_theme_fonts_skip_families_without_a_bold_face(monkeypatch):
    from types import SimpleNamespace

    from matplotlib import font_manager

    from vayuayan.plot_theme import _installed_fonts

    fake = [
        SimpleNamespace(name="Helvetica", weight=400),  # .ttc read as regular only
        SimpleNamespace(name="Arial", weight=400),
        SimpleNamespace(name="Arial", weight="bold"),
    ]
    monkeypatch.setattr(font_manager.fontManager, "ttflist", fake)
    assert _installed_fonts() == ["Arial"]


def test_plot_aqi_radial_hourly_draws_zone_aware_times_in_ist():
    from vayuayan import plot_aqi_radial_hourly

    # 23:00 UTC on 31 Dec is 04:30 IST on 1 Jan; naive times are IST already
    aware = pd.DataFrame(
        {"timestamp": pd.to_datetime(["2023-12-31 23:00"]).tz_localize("UTC"),
         "value": [450]}
    )  # fmt: skip
    naive = pd.DataFrame({"timestamp": ["2023-01-01 04:00"], "value": [450]})
    for df in (aware, naive):
        fig = plot_aqi_radial_hourly(df)
        cells = fig.axes[0].collections[0].get_array().reshape(12, 96)[:, ::4]
        assert cells[0, 4] == 5 and cells.count() == 1  # January, 04:00 IST
