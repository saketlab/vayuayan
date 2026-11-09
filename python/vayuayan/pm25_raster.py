"""
xarray helpers of PM25Client: find the PM2.5 variable, crop, clip and summarize.

xarray and rioxarray take a long time to import, so load_xarray() imports them
on first use.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, cast

if TYPE_CHECKING:
    import xarray as xr

EMPTY_STATS: Dict[str, float] = {
    "mean": float("nan"),
    "std": float("nan"),
    "min": float("nan"),
    "max": float("nan"),
}


OUTSIDE_GRID = "The polygon is entirely outside the PM2.5 grid"


def load_xarray() -> Any:
    """xarray, with the rioxarray .rio accessor. Imported on first use (slow)."""
    import rioxarray  # noqa: F401
    import xarray

    return xarray


def clip_geometry(pm25: xr.DataArray, geom: Any) -> xr.DataArray:
    """Clip PM2.5 to the cells whose centres fall inside one geometry.

    rio.clip masks the whole raster before it crops, so cropping first makes
    clipping many small polygons out of a large raster much cheaper. A polygon
    that holds no cell centre uses the cells it touches.

    Raises:
        ValueError: If the geometry touches no cell of the grid.
    """
    from rioxarray.exceptions import NoDataInBounds

    dx, dy = (abs(r) for r in pm25.rio.resolution())
    minx, miny, maxx, maxy = geom.bounds
    try:
        # auto_expand: a window at the grid edge can hold a single row or column
        window = pm25.rio.clip_box(
            minx - dx, miny - dy, maxx + dx, maxy + dy, auto_expand=True
        )
        try:
            clipped = window.rio.clip([geom], crs="EPSG:4326", all_touched=False)
        except NoDataInBounds:
            clipped = window.rio.clip([geom], crs="EPSG:4326", all_touched=True)
    except NoDataInBounds as e:
        raise ValueError(OUTSIDE_GRID) from e
    return cast("xr.DataArray", clipped)


def detect_pm25_variable(
    ds: xr.Dataset, preferred: Optional[str] = None
) -> Tuple[str, xr.Dataset]:
    """Find the PM2.5 variable name and prepare the dataset.

    Args:
        ds: xarray Dataset.
        preferred: Variable name of the dataset version, tried first.

    Returns:
        Tuple of (variable_name, processed_dataset).

    Raises:
        ValueError: If the dataset has no known PM2.5 variable.
    """
    # band_data is the variable of a GeoTIFF from GEE
    for name in (preferred, "band_data", "PM25", "GWRPM25"):
        if name and name in ds.variables:
            if name == "band_data" and "band" in ds.dims:
                ds = ds.squeeze("band", drop=True)
            return name, ds
    raise ValueError(
        f"PM2.5 variable not found. Available variables: {list(ds.variables)}"
    )


def detect_coordinates(ds: xr.Dataset) -> Tuple[str, str]:
    """Find the coordinate names in the dataset.

    Args:
        ds: xarray Dataset.

    Returns:
        Tuple of (latitude_coord, longitude_coord).
    """
    if "latitude" in ds.coords and "longitude" in ds.coords:
        return "latitude", "longitude"
    elif "lat" in ds.coords and "lon" in ds.coords:
        return "lat", "lon"
    elif "y" in ds.coords and "x" in ds.coords:
        return "y", "x"
    else:
        raise ValueError("Could not find latitude/longitude coordinates in file")


def _grid_positions(values: Any, low: float, high: float) -> Any:
    """Positions of the grid lines in [low, high], at least two if there is one.

    rioxarray cannot find the resolution of a raster that is one cell wide, so
    a selection of one grid line at the edge also takes its neighbour.
    """
    import numpy as np

    inside = np.flatnonzero((values >= low) & (values <= high))
    if inside.size == 0 and values.size >= 2:
        # A polygon smaller than a cell can lie between two grid lines
        middle = (low + high) / 2
        return np.sort(np.argsort(np.abs(values - middle))[:2])
    if inside.size != 1 or values.size < 2:
        return inside
    i = int(inside[0])
    return np.array(sorted((i, i - 1 if i == values.size - 1 else i + 1)))


def _outside(values: Any, low: float, high: float) -> bool:
    """True if [low, high] is beyond the cell edges of the grid lines in values."""
    half = abs(float(values[1]) - float(values[0])) / 2 if values.size > 1 else 0.0
    return bool(high < float(values.min()) - half or low > float(values.max()) + half)


def prepare_pm25_data(
    ds: xr.Dataset,
    pm25_var: str,
    lat_coord: str,
    lon_coord: str,
    bbox: Tuple[float, float, float, float],
    buffer: float = 0.1,
) -> xr.DataArray:
    """Load and prepare PM2.5 data for a bounding box.

    Args:
        ds: xarray Dataset.
        pm25_var: Name of PM2.5 variable.
        lat_coord: Name of latitude coordinate.
        lon_coord: Name of longitude coordinate.
        bbox: Bounding box as (minx, miny, maxx, maxy).
        buffer: Buffer around the bbox, in degrees.

    Returns:
        PM2.5 DataArray that is ready for the clip.

    Raises:
        ValueError: If the bounding box is entirely outside the grid.
    """
    lat_vals = ds[lat_coord].values
    lon_vals = ds[lon_coord].values
    if _outside(lat_vals, bbox[1], bbox[3]) or _outside(lon_vals, bbox[0], bbox[2]):
        raise ValueError(OUTSIDE_GRID)

    ds_subset = ds.isel(
        {
            lat_coord: _grid_positions(lat_vals, bbox[1] - buffer, bbox[3] + buffer),
            lon_coord: _grid_positions(lon_vals, bbox[0] - buffer, bbox[2] + buffer),
        }
    )
    pm25 = ds_subset[pm25_var].load().sortby([lat_coord, lon_coord])

    pm25 = pm25.rio.set_spatial_dims(x_dim=lon_coord, y_dim=lat_coord)
    pm25 = pm25.rio.write_crs("EPSG:4326")

    return cast("xr.DataArray", pm25)


def calculate_stats(
    clipped: xr.DataArray,
    include_count: bool = False,
    allow_empty: bool = False,
) -> Dict[str, float]:
    """Calculate statistics from clipped PM2.5 data.

    Args:
        clipped: Clipped PM2.5 DataArray.
        include_count: If True, add the count to the results.
        allow_empty: If True, return NaN stats for empty data. If False, raise
            an error.

    Returns:
        Dictionary with mean, std, min, and max statistics. It also has the count
        if include_count is True.

    Raises:
        ValueError: If there is no valid data and allow_empty=False.
    """
    import numpy as np

    values = clipped.values.flatten()
    values = values[np.isfinite(values)]

    if len(values) == 0:
        if not allow_empty:
            raise ValueError("No valid PM2.5 data found within the polygon boundary")
        stats = dict(EMPTY_STATS)
        if include_count:
            stats["count"] = 0
        return stats

    stats = {
        "mean": float(values.mean()),
        "std": float(values.std()),
        "min": float(values.min()),
        "max": float(values.max()),
    }
    if include_count:
        stats["count"] = len(values)
    return stats
