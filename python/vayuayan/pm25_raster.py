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


def load_xarray() -> Any:
    """xarray, with the rioxarray .rio accessor. Imported on first use (slow)."""
    import rioxarray  # noqa: F401
    import xarray

    return xarray


def clip_geometry(pm25: xr.DataArray, geom: Any) -> xr.DataArray:
    """Clip PM2.5 to one geometry, cropping to its padded bounds first.

    rio.clip masks the whole raster before it crops, so cropping first makes
    clipping many small polygons out of a large raster much cheaper.
    """
    dx, dy = (abs(r) for r in pm25.rio.resolution())
    minx, miny, maxx, maxy = geom.bounds
    window = pm25.rio.clip_box(minx - dx, miny - dy, maxx + dx, maxy + dy)
    return cast(
        "xr.DataArray", window.rio.clip([geom], crs="EPSG:4326", all_touched=True)
    )


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
    """
    lat_vals = ds[lat_coord].values
    lon_vals = ds[lon_coord].values
    lat_ascending = lat_vals[0] < lat_vals[-1]
    lon_ascending = lon_vals[0] < lon_vals[-1]

    if lat_ascending:
        lat_slice = slice(bbox[1] - buffer, bbox[3] + buffer)
    else:
        lat_slice = slice(bbox[3] + buffer, bbox[1] - buffer)

    if lon_ascending:
        lon_slice = slice(bbox[0] - buffer, bbox[2] + buffer)
    else:
        lon_slice = slice(bbox[2] + buffer, bbox[0] - buffer)

    ds_subset = ds.sel({lat_coord: lat_slice, lon_coord: lon_slice})
    pm25 = ds_subset[pm25_var].load()

    if not lat_ascending:
        pm25 = pm25.sortby(lat_coord)
    if not lon_ascending:
        pm25 = pm25.sortby(lon_coord)

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
    values = values[~np.isnan(values)]

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
