"""PM25Client: S3 and Earth Engine downloads, points, polygons and the cache."""

from __future__ import annotations

import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import requests
from shapely.geometry import box

from vayuayan import pm25 as pm25_module
from vayuayan.air_quality_client import PM25Client

from .fakes import http_response, raise_connection_error, write_pm25_netcdf

GEE_ROOT = "projects/sat-io/open-datasets/GLOBAL-SATELLITE-PM25"
S3_V6 = (
    "https://satpmdata.s3.amazonaws.com/archive/V6GL0204/CNNPM25/Monthly/GL/"
    "V6GL02.04.CNNPM25.GL.202003-202003.nc"
)


@pytest.fixture
def v6(tmp_path):
    return PM25Client("V6", cache_dir=str(tmp_path / "cache"))


def _geojson(tmp_path, frame_columns, boxes):
    shapes = gpd.GeoDataFrame(frame_columns, geometry=boxes, crs="EPSG:4326")
    path = str(tmp_path / "shapes.geojson")
    shapes.to_file(path, driver="GeoJSON")
    return path


def test_invalid_version_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Invalid version: V9"):
        PM25Client("V9", cache_dir=str(tmp_path))


def test_invalid_region_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Region AF"):
        PM25Client("V6", cache_dir=str(tmp_path), region="AF")


def test_spec_values_are_exposed(v6):
    assert v6.variable_name == "PM25"
    assert v6.year_range == (1998, 2023)
    assert v6.gee_collection_monthly == f"{GEE_ROOT}/MONTHLY"
    assert v6.box_shared_folder.startswith("https://wustl.box.com")


def test_gee_skip_reason(v6, monkeypatch):
    v6._gee_initialized = True

    assert v6._gee_skip_reason(2020) is None
    assert "outside range" in v6._gee_skip_reason(1999)

    v6._gee_initialized = False
    assert "Not installed" in v6._gee_skip_reason(2020)


def test_versions_without_gee_are_skipped_before_ee_starts(tmp_path, monkeypatch):
    client = PM25Client("V6GL03", cache_dir=str(tmp_path))
    monkeypatch.setattr(pm25_module.gee, "initialize", lambda: pytest.fail("started"))

    assert "No GEE collection" in client._gee_skip_reason(2020)
    assert client._download_from_gee(2020, 1) is None


def test_gee_is_initialized_once(v6, monkeypatch):
    calls = []
    monkeypatch.setattr(pm25_module.gee, "is_available", lambda: True)
    monkeypatch.setattr(pm25_module.gee, "initialize", lambda: calls.append(1) or True)

    assert v6.gee_initialized is True
    assert v6.gee_initialized is True
    assert calls == [1]


def test_gee_not_installed_is_not_initialized(v6, monkeypatch):
    monkeypatch.setattr(pm25_module.gee, "is_available", lambda: False)
    monkeypatch.setattr(pm25_module.gee, "initialize", lambda: pytest.fail("started"))

    assert v6.gee_initialized is False


@pytest.mark.parametrize(
    "month,collection", [(3, f"{GEE_ROOT}/MONTHLY"), (None, f"{GEE_ROOT}/ANNUAL")]
)
def test_download_from_gee_uses_the_collection_and_a_tif_name(
    v6, monkeypatch, month, collection
):
    v6._gee_initialized = True
    asked = []

    def fake_download(*args):
        asked.append(args)
        return "out.tif"

    monkeypatch.setattr(pm25_module.gee, "download_geotiff", fake_download)

    assert v6._download_from_gee(2020, month) == "out.tif"
    collection_id, year, got_month, path, region = asked[0]
    assert (collection_id, year, got_month, region) == (collection, 2020, month, None)
    assert path.suffix == ".tif"
    assert path.parent == v6.cache_dir


def test_download_from_s3_writes_the_file(v6, network):
    network.on(
        "get",
        S3_V6,
        http_response(b"netcdf", headers={"content-length": "6"}),
    )

    path = v6.download_netcdf_if_needed(2020, 3)

    assert Path(path).read_bytes() == b"netcdf"
    assert network.urls() == [S3_V6]
    assert network.calls[0].kwargs["stream"] is True


@pytest.mark.parametrize("suffix", [".nc", ".tif"])
def test_cached_file_is_not_downloaded_again(v6, network, suffix):
    cached = Path(v6.get_netcdf_path(2020, 3)).with_suffix(suffix)
    cached.write_bytes(b"cached")

    assert v6.download_netcdf_if_needed(2020, 3) == str(cached)
    assert network.calls == []


def test_force_download_replaces_the_cached_file(v6, network):
    cached = Path(v6.get_netcdf_path(2020, 3))
    cached.write_bytes(b"old")
    network.on("get", S3_V6, http_response(b"new"))

    v6.download_netcdf_if_needed(2020, 3, force_download=True)

    assert cached.read_bytes() == b"new"


def test_s3_failure_falls_back_to_gee(v6, network, monkeypatch):
    network.on("get", S3_V6, http_response(status=403))
    monkeypatch.setattr(v6, "_download_from_gee", lambda year, month: "from-gee.tif")

    assert v6.download_netcdf_if_needed(2020, 3) == "from-gee.tif"


def test_all_sources_failing_explains_the_manual_download(v6, network, monkeypatch):
    network.on("get", S3_V6, requests.ConnectionError("down"))
    monkeypatch.setattr(v6, "_gee_skip_reason", lambda year: "Not authenticated")

    with pytest.raises(requests.RequestException) as error:
        v6.download_netcdf_if_needed(2020, 3)

    message = str(error.value)
    assert "Not authenticated" in message
    assert "https://wustl.box.com/v/ACAG-V6GL0204-CNNPM25" in message
    assert "archive/V6GL0204/CNNPM25/Monthly/GL" in message
    assert v6.get_netcdf_path(2020, 3) in message


def test_manual_message_when_gee_runs_but_the_download_fails(v6):
    v6._gee_initialized = True

    message = v6._manual_download_message(2020, None, RuntimeError("s3 down"))

    assert "Google Earth Engine: Download failed" in message
    assert "s3 down" in message


def test_year_outside_the_version_is_rejected(v6):
    with pytest.raises(ValueError, match="outside valid range"):
        v6.download_netcdf_if_needed(1990)


def test_value_at_a_point_is_the_nearest_cell(v6):
    write_pm25_netcdf(v6, value=42.5)

    assert v6.get_pm25_at_point(25.2, 75.2, 2020, 1) == 42.5


def test_point_without_data_raises(v6):
    write_pm25_netcdf(v6, nan_inside=(24.0, 70.0, 26.0, 85.0))

    with pytest.raises(ValueError, match="No PM2.5 data"):
        v6.get_pm25_at_point(25.0, 75.0, 2020, 1)


def test_point_outside_the_grid_raises(v6):
    write_pm25_netcdf(v6)

    with pytest.raises(ValueError, match="outside data bounds"):
        v6.get_pm25_at_point(60.0, 150.0, 2020, 1)


def test_stats_of_a_whole_region(v6, tmp_path):
    write_pm25_netcdf(v6, value=30.0)
    path = _geojson(tmp_path, {"state": ["A"]}, [box(72, 22, 73, 23)])

    stats = v6.get_pm25_stats(path, 2020, 1)

    assert (stats["mean"], stats["min"], stats["max"]) == (30.0, 30.0, 30.0)
    assert stats["std"] == 0.0
    assert stats["count"] > 0


def test_stats_group_by_several_columns(v6, tmp_path):
    write_pm25_netcdf(v6, value=30.0)
    path = _geojson(
        tmp_path,
        {"state": ["A", "A"], "district": ["x", "y"]},
        [box(72, 22, 73, 23), box(74, 22, 75, 23)],
    )

    table = v6.get_pm25_stats(path, 2020, 1, group_by="state, district")

    assert isinstance(table, pd.DataFrame)
    assert table[["state", "district"]].values.tolist() == [["A", "x"], ["A", "y"]]
    assert table["mean"].tolist() == [30.0, 30.0]


def test_stats_group_by_a_missing_column_lists_the_columns(v6, tmp_path):
    write_pm25_netcdf(v6)
    path = _geojson(tmp_path, {"state": ["A"]}, [box(72, 22, 73, 23)])

    with pytest.raises(ValueError, match="not found in GeoJSON.*state"):
        v6.get_pm25_stats(path, 2020, 1, group_by="nope")


def test_stats_need_the_geojson_file(v6):
    with pytest.raises(FileNotFoundError, match="missing.geojson"):
        v6.get_pm25_stats("missing.geojson", 2020, 1)


def test_group_over_cells_without_data_has_nan_stats_and_zero_count(v6, tmp_path):
    write_pm25_netcdf(v6, nan_inside=(21.0, 70.0, 24.0, 85.0))
    path = _geojson(tmp_path, {"state": ["A"]}, [box(72, 22, 73, 23)])

    row = v6.get_pm25_stats(path, 2020, 1, group_by="state").iloc[0]

    assert math.isnan(row["mean"])
    assert row["count"] == 0


def test_failed_clip_of_one_group_is_nan_not_an_error(v6, monkeypatch):
    def broken_clip(pm25, geom):
        raise RuntimeError("no data in bounds")

    monkeypatch.setattr(pm25_module, "clip_geometry", broken_clip)

    with_count = v6._zonal_stats(None, None, "label", include_count=True)
    without_count = v6._zonal_stats(None, None, "label")

    assert math.isnan(with_count["mean"]) and with_count["count"] == 0
    assert "count" not in without_count


def test_monthly_stats_are_empty_when_every_month_fails(v6, tmp_path, monkeypatch):
    monkeypatch.setattr(v6, "get_pm25_stats", raise_connection_error)

    table = v6.get_pm25_monthly_stats("x.geojson", 2020, months=[1, 2])

    assert table.empty
    assert list(table.columns) == ["year", "month", "mean", "std", "min", "max"]


@pytest.mark.parametrize(
    "columns,id_field,identifier,expected",
    [
        ({"code": ["c1", "c2"], "NAME_1": ["n1", "n2"]}, "code", "code", ["c1", "c2"]),
        ({"code": ["c1", "c2"], "NAME_1": ["n1", "n2"]}, "x", "NAME_1", ["n1", "n2"]),
        ({"name": ["a", "b"]}, None, "name", ["a", "b"]),
        ({"other": ["a", "b"]}, None, "index", [0, 1]),
    ],
)
def test_stats_by_polygon_picks_the_identifier(
    v6, tmp_path, columns, id_field, identifier, expected
):
    write_pm25_netcdf(v6, value=25.0)
    path = _geojson(tmp_path, columns, [box(72, 22, 73, 23), box(74, 22, 75, 23)])

    table = v6.get_pm25_stats_by_polygon(path, 2020, 1, id_field=id_field)

    assert table.columns.tolist() == [identifier, "mean", "std"]
    assert table[identifier].tolist() == expected
    assert table["mean"].tolist() == [25.0, 25.0]


def test_cached_files_are_listed_and_cleared(v6):
    (v6.cache_dir / "b.nc").write_bytes(b"1")
    (v6.cache_dir / "a.nc").write_bytes(b"1")
    (v6.cache_dir / "keep.tif").write_bytes(b"1")

    assert v6.list_cached_files() == [
        str(v6.cache_dir / "a.nc"),
        str(v6.cache_dir / "b.nc"),
        str(v6.cache_dir / "keep.tif"),
    ]

    v6.clear_cache()

    assert v6.list_cached_files() == []
    assert not (v6.cache_dir / "keep.tif").exists()


def test_cache_functions_accept_a_missing_folder(v6):
    v6.cache_dir.rmdir()

    assert v6.list_cached_files() == []
    v6.clear_cache()
    assert not v6.cache_dir.exists()


def test_clear_cache_continues_after_a_file_that_cannot_be_removed(v6, monkeypatch):
    (v6.cache_dir / "a.nc").write_bytes(b"1")

    def locked(self):
        raise OSError("locked")

    monkeypatch.setattr(Path, "unlink", locked)

    v6.clear_cache()

    assert (v6.cache_dir / "a.nc").exists()
