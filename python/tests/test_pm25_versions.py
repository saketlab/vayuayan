"""Tests for the PM2.5 dataset locations (no downloads)."""

from vayuayan.air_quality_client import PM25Client


def test_s3_urls_match_the_satpmdata_layout(tmp_path):
    v6 = PM25Client("V6", cache_dir=str(tmp_path))
    v5 = PM25Client("V5", cache_dir=str(tmp_path))

    # Keys as listed in s3://satpmdata in October 2026
    assert v6._get_aws_url(2020, 3) == (
        "https://satpmdata.s3.amazonaws.com/archive/V6GL0204/CNNPM25/Monthly/GL/"
        "V6GL02.04.CNNPM25.GL.202003-202003.nc"
    )
    assert v5._get_aws_url(2020) == (
        "https://satpmdata.s3.amazonaws.com/archive/V5GL0502/GWRPM25/Annual/Global/"
        "V5GL0502.HybridPM25.Global.202001-202012.nc"
    )
    assert PM25Client("V6GL03", cache_dir=str(tmp_path))._get_aws_url(2024) == (
        "https://satpmdata.s3.amazonaws.com/V6GL03/CNNPM25/Annual/GL/"
        "V6GL03.CNNPM25.GL.202401-202412.nc"
    )
    # Cache names of V6 stay the same, so existing caches are reused
    assert v6.get_netcdf_path(2020).endswith("V6GL02.04.CNNPM25.GL.202001-202012.nc")


def test_client_does_not_start_earth_engine_until_needed(tmp_path):
    client = PM25Client(cache_dir=str(tmp_path))
    assert client._gee_initialized is None


def _write_month(client, year, month, value):
    import numpy as np
    import xarray as xr

    lat = np.arange(30.0, 20.0, -0.1)
    lon = np.arange(70.0, 85.0, 0.1)
    data = np.full((lat.size, lon.size), float(value))
    ds = xr.Dataset({"PM25": (("lat", "lon"), data)}, coords={"lat": lat, "lon": lon})
    ds.to_netcdf(client.get_netcdf_path(year, month))


def test_monthly_stats_and_map_geometry(tmp_path, monkeypatch):
    import geopandas as gpd
    import requests
    from shapely.geometry import box

    client = PM25Client("V6", cache_dir=str(tmp_path))
    _write_month(client, 2020, 1, 40)
    _write_month(client, 2020, 2, 60)
    real_download = client.download_netcdf_if_needed

    def offline(year, month=None, force_download=False):
        if month == 3:
            raise requests.RequestException("not downloaded\nmore lines")
        return real_download(year, month)

    monkeypatch.setattr(client, "download_netcdf_if_needed", offline)
    shapes = gpd.GeoDataFrame(
        {"state": ["A", "A", "B"]},
        geometry=[box(72, 22, 73, 23), box(73, 22, 74, 23), box(80, 25, 81, 26)],
        crs="EPSG:4326",
    )
    geojson = str(tmp_path / "shapes.geojson")
    shapes.to_file(geojson, driver="GeoJSON")

    monthly = client.get_pm25_monthly_stats(geojson, 2020, months=[1, 2, 3])
    assert monthly[["year", "month", "mean"]].values.tolist() == [
        [2020, 1, 40.0],
        [2020, 2, 60.0],
    ]

    by_state = client.get_pm25_stats(geojson, 2020, 1, group_by="state", geometry=True)
    assert isinstance(by_state, gpd.GeoDataFrame)
    assert by_state["state"].tolist() == ["A", "B"]
    assert by_state.geometry.iloc[0].bounds == (72.0, 22.0, 74.0, 23.0)
