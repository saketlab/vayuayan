"""Which grid cells a polygon selects: centres inside, or those it touches."""

from __future__ import annotations

import numpy as np
import pytest
import rioxarray  # noqa: F401
import xarray as xr
from shapely.geometry import Polygon, box

from vayuayan.pm25_raster import (
    OUTSIDE_GRID,
    calculate_stats,
    clip_geometry,
    prepare_pm25_data,
)


@pytest.fixture
def grid():
    lat = np.arange(30.0, 20.0, -0.5)
    lon = np.arange(70.0, 85.0, 0.5)
    values = np.arange(lat.size * lon.size, dtype=float).reshape(lat.size, lon.size)
    return xr.Dataset(
        {"PM25": (("lat", "lon"), values)}, coords={"lat": lat, "lon": lon}
    )


def _stats(ds, polygon):
    pm25 = prepare_pm25_data(ds, "PM25", "lat", "lon", polygon.bounds)
    return calculate_stats(clip_geometry(pm25, polygon), include_count=True)


def test_counts_the_cells_whose_centres_are_inside(grid):
    # centres at 72.5-73.5 and 22.5-23.5 are inside; those on the boundary are not
    assert _stats(grid, box(72, 22, 74, 24))["count"] == 16


def test_a_polygon_between_centres_uses_the_cells_it_touches(grid):
    stats = _stats(grid, box(72.1, 22.1, 72.2, 22.2))
    # the single cell centred at 72.0, 22.0
    row = int((30.0 - 22.0) / 0.5)
    column = int((72.0 - 70.0) / 0.5)
    assert stats["count"] == 1
    assert stats["mean"] == grid["PM25"].values[row, column]


def test_a_polygon_between_grid_lines_uses_the_cells_it_touches(grid):
    # bounds are further than the 0.1 degree buffer from every grid line
    stats = _stats(grid, box(72.24, 22.24, 72.26, 22.26))
    assert stats["count"] >= 1


@pytest.mark.parametrize(
    "polygon",
    [
        box(100, 40, 101, 41),
        box(69.4, 22, 69.6, 23),
        box(85, 22, 86, 23),
    ],
)
def test_a_polygon_outside_the_grid_is_a_value_error(grid, polygon):
    with pytest.raises(ValueError, match=OUTSIDE_GRID):
        _stats(grid, polygon)


def test_a_polygon_outside_with_bounds_over_the_grid_is_a_value_error(grid):
    triangle = Polygon([(69.6, 30.4), (69.85, 30.4), (69.6, 30.15)])
    with pytest.raises(ValueError, match=OUTSIDE_GRID):
        _stats(grid, triangle)
