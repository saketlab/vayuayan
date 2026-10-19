"""
PM25Client: satellite PM2.5 from the WUSTL ACAG datasets, for points and polygons.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

import requests

from . import gee, http_client
from .constants import SATPM_BASE_URL
from .pm25_raster import (
    EMPTY_STATS,
    calculate_stats,
    clip_geometry,
    detect_coordinates,
    detect_pm25_variable,
    load_xarray,
    prepare_pm25_data,
)
from .pm25_versions import PM25_VERSIONS

if TYPE_CHECKING:
    import ee
    import geopandas as gpd
    import pandas as pd
    import xarray as xr

logger = logging.getLogger(__name__)


def _spec_property(field: str) -> Any:
    """A read-only attribute that returns self.spec.<field>."""
    return property(lambda self: getattr(self.spec, field))


class PM25Client:
    """Client that processes PM2.5 satellite data from NetCDF files.

    The client supports the WUSTL Atmospheric Composition Analysis Group
    (ACAG) datasets in PM25_VERSIONS. It downloads them from the satpmdata S3
    bucket, and falls back to Google Earth Engine.
    """

    def __init__(
        self, version: str = "V6GL03", cache_dir: str = "pm25_data", region: str = "GL"
    ) -> None:
        """Initialize the PM2.5 Client with data paths.

        Args:
            version: Dataset version to use. "V6GL03" (default) is V6.GL.03,
                the newest CNN version (1998-2024), for new studies, with no
                Google Earth Engine fallback. "V6" is V6.GL.02.04, the previous
                CNN version (1998-2023), with the Google Earth Engine fallback.
                "V5" is V5.GL.05.02, the GWR-based algorithm (1998-2023), to
                compare with published studies. "V5GL04" is V5.GL.04 (1998-2022).
            cache_dir: Directory for the cache of downloaded NetCDF files.
            region: "GL" (global, default), or a regional file: "AS", "EU",
                "NA" (and "AF" for V6GL03). Regional files are smaller; "AS"
                covers India.

        Raises:
            ValueError: If version is not a key of PM25_VERSIONS, or the
                version has no files for the region.

        Example:
            >>> client = PM25Client()  # V6.GL.03
            >>> client = PM25Client(version="V6")  # V6.GL.02.04, with GEE
        """
        if version not in PM25_VERSIONS:
            raise ValueError(
                f"Invalid version: {version}. Must be one of "
                f"{', '.join(PM25_VERSIONS)}."
            )

        self.version = version
        self.spec = PM25_VERSIONS[version]
        self.spec.check_region(region)
        self.region = region
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # GEE is initialized on first use: ee.Initialize can take seconds, and
        # cached NetCDF files never need it
        self._gee_initialized: Optional[bool] = None

    # Read-only views of self.spec, kept for compatibility
    aws_base_url = SATPM_BASE_URL
    gee_collection_monthly = _spec_property("gee_monthly")
    gee_collection_annual = _spec_property("gee_annual")
    variable_name = _spec_property("variable_name")
    year_range = _spec_property("year_range")
    gee_year_range = _spec_property("gee_year_range")
    box_shared_folder = _spec_property("manual_url")

    def _filename(self, year: int, month: Optional[int] = None) -> str:
        """NetCDF filename for a year and an optional month.

        Raises:
            ValueError: If the year is not in the range of the version.
        """
        self.spec.check_year(year)
        return self.spec.filename(year, month, self.region)

    def _get_aws_url(self, year: int, month: Optional[int] = None) -> str:
        """S3 HTTPS URL of the NetCDF file for a year and an optional month.

        Raises:
            ValueError: If the year is not in the range of the version.
        """
        self.spec.check_year(year)
        return urljoin(SATPM_BASE_URL, self.spec.key(year, month, self.region))

    def _gee_skip_reason(self, year: int) -> Optional[str]:
        """Why GEE cannot give data for the year, or None if it can.

        The year checks come first, so a year outside the GEE range does not
        start Earth Engine.
        """
        if self.spec.gee_year_range is None:
            return f"No GEE collection for {self.spec.name}"
        first, last = self.spec.gee_year_range
        if not (first <= year <= last):
            return f"Year {year} outside range ({first}-{last})"
        if not self.gee_initialized:
            return "Not installed or not authenticated"
        return None

    def _download_from_gee(
        self,
        year: int,
        month: Optional[int] = None,
        region: Optional[ee.Geometry] = None,
    ) -> Optional[str]:
        """Download PM2.5 data from Google Earth Engine, as a GeoTIFF.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the client downloads annual data.
            region: Optional ee.Geometry for the clip. If None, the client clips
                the image to the India bounds.

        Returns:
            Path to the downloaded GeoTIFF file, or None if GEE is not available
            for this version and year, or the download fails.
        """
        reason = self._gee_skip_reason(year)
        collection = self.spec.gee_collection(month)
        if reason or collection is None:
            logger.info("GEE skipped: %s", reason)
            return None
        tif_name = self._filename(year, month).replace(".nc", ".tif")
        return gee.download_geotiff(
            collection, year, month, self.cache_dir / tif_name, region
        )

    @property
    def gee_initialized(self) -> bool:
        """True if GEE is available for this version and initialized."""
        if self._gee_initialized is None:
            self._gee_initialized = bool(
                gee.is_available() and self.spec.gee_monthly and gee.initialize()
            )
        return self._gee_initialized

    def get_netcdf_path(self, year: int, month: Optional[int] = None) -> str:
        """Get the local cache path of the NetCDF file.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the function returns the annual
                data path.

        Returns:
            Path to NetCDF file (cached locally). The file may not exist yet;
            download_netcdf_if_needed downloads it.
        """
        return str(self.cache_dir / self._filename(year, month))

    def download_netcdf_if_needed(
        self, year: int, month: Optional[int] = None, force_download: bool = False
    ) -> str:
        """Download the NetCDF file if it is not in the cache.

        The client downloads from the satpmdata S3 bucket. If that fails, it
        downloads a GeoTIFF from Google Earth Engine.

        Args:
            year: Year for data.
            month: Optional month (1-12). If None, the client downloads annual data.
            force_download: If True, download the file again, also if it exists.

        Returns:
            Path to the downloaded NetCDF or GeoTIFF file.

        Raises:
            requests.RequestException: If every download source fails. The
                message explains the manual download.
            IOError: If the client cannot write the file.
        """
        cached_path = Path(self.get_netcdf_path(year, month))
        cached_tif_path = cached_path.with_suffix(".tif")  # from a GEE download
        if not force_download:
            for path in (cached_path, cached_tif_path):
                if path.exists():
                    logger.info("Using cached file: %s", path)
                    return str(path)

        s3_url = self._get_aws_url(year, month)
        logger.info("Downloading %s", s3_url)
        try:
            # The bucket is plain AWS; the SSL fallback is for networks that
            # intercept TLS
            response = http_client.request(
                "get", s3_url, ssl_fallback=True, stream=True, timeout=300
            )
            size = http_client.stream_to_file(
                response, cached_path, f"PM2.5 {self.version}"
            )
            logger.info("Download complete: %.1f MB", size / (1024 * 1024))
            return str(cached_path)
        except requests.RequestException as e:
            s3_error = e
            logger.warning(
                "S3 download failed (%s); trying GEE", http_client.failure_reason(e)
            )

        gee_path = self._download_from_gee(year, month)
        if gee_path:
            return gee_path
        raise requests.RequestException(
            self._manual_download_message(year, month, s3_error)
        ) from s3_error

    def _manual_download_message(
        self, year: int, month: Optional[int], s3_error: Exception
    ) -> str:
        gee_error = self._gee_skip_reason(year) or "Download failed"
        return (
            f"Automated PM2.5 download failed.\n"
            f"  S3: {s3_error}\n"
            f"  Google Earth Engine: {gee_error}\n"
            f"Download {self.spec.name} manually from {self.spec.manual_url}\n"
            f"  File: {self.spec.key(year, month, self.region)}\n"
            f"  Save it as: {self.get_netcdf_path(year, month)}"
        )

    def get_pm25_at_point(
        self,
        latitude: float,
        longitude: float,
        year: int,
        month: Optional[int] = None,
    ) -> float:
        """Get PM2.5 value at a specific latitude/longitude point.

        The function uses the grid cell that is nearest to the coordinates.

        Args:
            latitude: Latitude in decimal degrees.
            longitude: Longitude in decimal degrees.
            year: Year of the data.
            month: Optional month (1-12). If None, the function uses annual data.

        Returns:
            PM2.5 value in µg/m³ at the nearest grid cell.

        Raises:
            ValueError: If the point is outside the data bounds, or there is no data.
            requests.RequestException: If the download fails.

        Example:
            >>> client = PM25Client()
            >>> pm25 = client.get_pm25_at_point(28.6139, 77.2090, year=2020, month=1)
            >>> print(f"PM2.5: {pm25:.2f} µg/m³")
        """

        nc_file = self.download_netcdf_if_needed(year, month)

        with load_xarray().open_dataset(nc_file) as ds:
            pm25_var, ds = detect_pm25_variable(ds, self.spec.variable_name)
            lat_coord, lon_coord = detect_coordinates(ds)

            try:
                point_data = ds.sel(
                    {lat_coord: latitude, lon_coord: longitude}, method="nearest"
                )
            except (KeyError, ValueError) as e:
                raise ValueError(
                    f"Point ({latitude}, {longitude}) is outside data bounds"
                ) from e

            values = point_data[pm25_var].values
            pm25_value = float(values.item() if hasattr(values, "item") else values)

            if math.isnan(pm25_value):
                raise ValueError(
                    f"No PM2.5 data available at ({latitude}, {longitude})"
                )

            return pm25_value

    def get_pm25_stats(
        self,
        geojson_file: str,
        year: int,
        month: Optional[int] = None,
        group_by: Optional[str] = None,
        geometry: bool = False,
    ) -> Union[Dict[str, float], pd.DataFrame]:
        """Calculate PM2.5 statistics in a polygon region from a GeoJSON file.

        If the NetCDF data is not in the local cache, this function downloads
        it (see download_netcdf_if_needed).

        Args:
            geojson_file: Path to GeoJSON file with polygon.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            group_by: Optional column name or names for the polygon groups.
                     Give one column (for example 'state_name') or a comma-separated
                     list of columns (for example 'state_name,district_name').
                     If None, the function aggregates the full polygon boundary.
                     If given, the function aggregates each unique combination.
            geometry: With group_by, return a GeoDataFrame that also has the
                     merged polygon of each group, ready to plot as a map.

        Returns:
            If group_by is None: Dictionary with mean, std, min, max and count
            (number of grid cells) of the PM2.5 values.
            If group_by is given: DataFrame (GeoDataFrame if geometry is True)
            with statistics for each group.

        Raises:
            FileNotFoundError: If the GeoJSON file does not exist.
            requests.RequestException: If the NetCDF download fails.
            ValueError: If the GeoJSON file does not have the group_by column.
        """
        gdf, nc_file = self._load_inputs(geojson_file, year, month)

        if group_by is not None:
            group_cols = [col.strip() for col in group_by.split(",")]

            missing_cols = [col for col in group_cols if col not in gdf.columns]
            if missing_cols:
                available_columns = list(gdf.columns)
                raise ValueError(
                    f"Column(s) {missing_cols} not found in GeoJSON. "
                    f"Available columns: {available_columns}"
                )

            return self._get_pm25_stats_grouped(gdf, nc_file, group_cols, geometry)
        polygon = gdf.union_all()
        pm25 = self._load_pm25(nc_file, polygon.bounds)
        return calculate_stats(clip_geometry(pm25, polygon), include_count=True)

    def _load_inputs(
        self, geojson_file: str, year: int, month: Optional[int]
    ) -> Tuple[gpd.GeoDataFrame, str]:
        """Read the GeoJSON in EPSG:4326 and get the NetCDF file for the period."""
        import geopandas as gpd

        if not os.path.exists(geojson_file):
            raise FileNotFoundError(f"GeoJSON file not found: {geojson_file}")
        nc_file = self.download_netcdf_if_needed(year, month)
        return gpd.read_file(geojson_file).to_crs("EPSG:4326"), nc_file

    def _load_pm25(self, nc_file: Union[str, Path], bounds: Any) -> xr.DataArray:
        """Open the NetCDF file and return PM2.5 cropped to bounds, in memory."""
        with load_xarray().open_dataset(nc_file) as ds:
            pm25_var, ds = detect_pm25_variable(ds, self.spec.variable_name)
            lat_coord, lon_coord = detect_coordinates(ds)
            return prepare_pm25_data(ds, pm25_var, lat_coord, lon_coord, bounds)

    def _zonal_stats(
        self, pm25: xr.DataArray, geom: Any, label: Any, include_count: bool = False
    ) -> Dict[str, float]:
        """Statistics of PM2.5 in one geometry; NaN statistics if the clip fails."""
        try:
            return calculate_stats(
                clip_geometry(pm25, geom), include_count=include_count, allow_empty=True
            )
        except Exception as e:  # rioxarray raises several error types
            logger.warning("Error processing %r: %s", label, e)
            stats = dict(EMPTY_STATS)
            if include_count:
                stats["count"] = 0
            return stats

    def _get_pm25_stats_grouped(
        self,
        gdf: gpd.GeoDataFrame,
        nc_file: str,
        group_cols: List[str],
        geometry: bool = False,
    ) -> pd.DataFrame:
        """Calculate PM2.5 statistics for each group in the GeoDataFrame.

        Args:
            gdf: GeoDataFrame with geometries (already in EPSG:4326).
            nc_file: Path to NetCDF file.
            group_cols: Column names for the groups.

        Returns:
            DataFrame with statistics for each unique value or combination in the
            group_by column(s).
        """
        import pandas as pd

        pm25 = self._load_pm25(nc_file, gdf.total_bounds)

        results = []
        groupby_arg = group_cols[0] if len(group_cols) == 1 else group_cols

        for group_name, group_gdf in gdf.groupby(groupby_arg):
            keys = group_name if len(group_cols) > 1 else (group_name,)
            result: Dict[str, Any] = dict(zip(group_cols, keys))
            group_geometry = group_gdf.union_all()
            result.update(
                self._zonal_stats(pm25, group_geometry, group_name, include_count=True)
            )
            if geometry:
                result["geometry"] = group_geometry
            results.append(result)

        if geometry:
            import geopandas as gpd

            return gpd.GeoDataFrame(results, geometry="geometry", crs="EPSG:4326")
        return pd.DataFrame(results)

    def get_pm25_monthly_stats(
        self,
        geojson_file: str,
        year: int,
        months: Optional[List[int]] = None,
        group_by: Optional[str] = None,
    ) -> pd.DataFrame:
        """PM2.5 statistics of a region for each month of a year.

        Args:
            geojson_file: Path to GeoJSON file with polygons.
            year: Year of the data.
            months: Months (1-12) to compute. The default is all 12.
            group_by: Optional group column(s), as in get_pm25_stats.

        Returns:
            DataFrame with year and month columns, then the statistics (and
            the group columns) of get_pm25_stats. A month whose data cannot be
            downloaded is left out, with a warning in the log.
        """
        import pandas as pd

        frames = []
        for month in months or range(1, 13):
            try:
                stats = self.get_pm25_stats(geojson_file, year, month, group_by)
            except requests.RequestException as e:
                reason = http_client.failure_reason(e)
                logger.warning("No PM2.5 data for %d-%02d: %s", year, month, reason)
                continue
            frame = pd.DataFrame([stats]) if isinstance(stats, dict) else stats
            frame.insert(0, "month", month)
            frame.insert(0, "year", year)
            frames.append(frame)
        if not frames:
            return pd.DataFrame(columns=["year", "month", "mean", "std", "min", "max"])
        return pd.concat(frames, ignore_index=True)

    def get_pm25_stats_by_polygon(
        self,
        geojson_file: str,
        year: int,
        month: Optional[int] = None,
        id_field: Optional[str] = None,
    ) -> pd.DataFrame:
        """Calculate PM2.5 statistics for each polygon in a GeoJSON file.

        Args:
            geojson_file: Path to GeoJSON file with polygons.
            year: Year of the NetCDF data.
            month: Optional month of the NetCDF data.
            id_field: Optional GeoJSON property to use as the identifier.

        Returns:
            DataFrame with statistics for each polygon.

        Raises:
            FileNotFoundError: If the GeoJSON file does not exist.
            requests.RequestException: If the NetCDF download fails.

        If the NetCDF data is not in the local cache, this function downloads
        it (see download_netcdf_if_needed).
        """
        import pandas as pd

        gdf, nc_file = self._load_inputs(geojson_file, year, month)
        pm25 = self._load_pm25(nc_file, gdf.total_bounds)

        if id_field and id_field in gdf.columns:
            column_name = id_field
        elif "NAME_1" in gdf.columns:
            column_name = "NAME_1"
        elif "name" in gdf.columns:
            column_name = "name"
        else:
            column_name = "index"

        results = []

        for idx, row in gdf.iterrows():
            stats = self._zonal_stats(pm25, row.geometry, idx)
            mean_val, std_val = stats["mean"], stats["std"]

            if column_name == "index":
                feature_id = idx
            else:
                feature_id = row[column_name]

            results.append(
                {
                    column_name: feature_id,
                    "mean": mean_val,
                    "std": std_val,
                }
            )

        return pd.DataFrame(results)

    def clear_cache(self) -> None:
        """Clear all cached NetCDF files."""
        if not self.cache_dir.exists():
            logger.info("Cache directory does not exist")
            return
        for file in self.cache_dir.glob("*.nc"):
            try:
                file.unlink()
                logger.info("Removed: %s", file)
            except OSError as e:
                logger.warning("Could not remove %s: %s", file, e)
        logger.info("Cache cleared: %s", self.cache_dir)

    def list_cached_files(self) -> List[str]:
        """List all cached NetCDF files.

        Returns:
            List of cached file paths.
        """
        if not self.cache_dir.exists():
            return []
        cached_files = sorted(self.cache_dir.glob("*.nc"))
        for file in cached_files:
            size_mb = file.stat().st_size / (1024 * 1024)
            logger.info("Cached: %s (%.1f MB)", file.name, size_mb)
        return [str(f) for f in cached_files]
