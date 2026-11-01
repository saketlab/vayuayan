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
