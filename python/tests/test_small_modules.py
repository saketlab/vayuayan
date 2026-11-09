"""Remaining pieces: India boundaries, raster helpers, version fields, validation."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from shapely.geometry import box

from vayuayan import aqi, geo, tidy
from vayuayan.pm25_raster import (
    calculate_stats,
    detect_coordinates,
    detect_pm25_variable,
    load_xarray,
    prepare_pm25_data,
)
from vayuayan.pm25_versions import PM25_VERSIONS, PM25Version

from .fakes import http_response

DISTRICTS_URL = (
    "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson"
)


@pytest.fixture
def clean_districts():
    geo._districts.cache_clear()
    yield
    geo._districts.cache_clear()


def _districts_geojson():
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"district_name": "A", "state_name": "S"},
                    "geometry": box(70, 20, 71, 21).__geo_interface__,
                }
            ],
        }
    ).encode()


def test_districts_are_downloaded_once(network, clean_districts):
    network.on("get", DISTRICTS_URL, http_response(_districts_geojson()))

    first = geo._districts()
    second = geo._districts()

    assert first is second
    assert first["district_name"].tolist() == ["A"]
    assert first.crs.to_epsg() == 4326
    assert network.urls() == [DISTRICTS_URL]


def test_india_boundary_needs_a_selection():
    with pytest.raises(ValueError, match="district or state"):
        geo.india_boundary()


def test_india_boundary_of_an_unknown_district(network, clean_districts):
    network.on("get", DISTRICTS_URL, http_response(_districts_geojson()))

    with pytest.raises(ValueError, match="No BharatViz"):
        geo.india_boundary(district="Atlantis")


def test_india_boundary_of_a_district(network, clean_districts):
    network.on("get", DISTRICTS_URL, http_response(_districts_geojson()))

    assert geo.india_boundary(district=["A"]).bounds == (70.0, 20.0, 71.0, 21.0)


def test_load_xarray_adds_the_rio_accessor():
    module = load_xarray()

    assert hasattr(module.DataArray([1]), "rio")


@pytest.mark.parametrize(
    "lat_name,lon_name",
    [("latitude", "longitude"), ("lat", "lon"), ("y", "x")],
)
def test_detect_coordinates(lat_name, lon_name):
    ds = xr.Dataset(coords={lat_name: [1.0], lon_name: [2.0]})

    assert detect_coordinates(ds) == (lat_name, lon_name)


def test_detect_coordinates_needs_known_names():
    with pytest.raises(ValueError, match="latitude/longitude"):
        detect_coordinates(xr.Dataset(coords={"a": [1.0]}))


def test_detect_variable_prefers_the_version_name():
    ds = xr.Dataset({"GWRPM25": ("x", [1.0]), "PM25": ("x", [2.0])})

    assert detect_pm25_variable(ds, "GWRPM25")[0] == "GWRPM25"
    assert detect_pm25_variable(ds)[0] == "PM25"


def test_detect_variable_drops_the_band_of_a_geotiff():
    ds = xr.Dataset({"band_data": (("band", "x"), [[1.0, 2.0]])})

    name, out = detect_pm25_variable(ds)

    assert name == "band_data"
    assert "band" not in out.dims


def test_detect_variable_lists_the_variables_when_there_is_none():
    ds = xr.Dataset({"other": ("x", [1.0])})

    with pytest.raises(ValueError, match="other"):
        detect_pm25_variable(ds)


@pytest.mark.parametrize("lat_step,lon_step", [(1.0, 1.0), (-1.0, -1.0)])
def test_prepare_data_crops_and_sorts_ascending(lat_step, lon_step):
    lat = np.arange(10.0, 20.0)[:: int(lat_step)]
    lon = np.arange(70.0, 80.0)[:: int(lon_step)]
    data = np.arange(lat.size * lon.size, dtype=float).reshape(lat.size, lon.size)
    ds = xr.Dataset({"PM25": (("lat", "lon"), data)}, coords={"lat": lat, "lon": lon})

    out = prepare_pm25_data(ds, "PM25", "lat", "lon", (72.0, 12.0, 74.0, 14.0))

    assert out["lat"].values.tolist() == [12.0, 13.0, 14.0]
    assert out["lon"].values.tolist() == [72.0, 73.0, 74.0]
    assert out.rio.crs.to_epsg() == 4326


def test_calculate_stats_of_values():
    stats = calculate_stats(xr.DataArray([1.0, 3.0, np.nan]), include_count=True)

    assert stats == {"mean": 2.0, "std": 1.0, "min": 1.0, "max": 3.0, "count": 2}


def test_calculate_stats_without_data():
    empty = xr.DataArray([np.nan])

    with pytest.raises(ValueError, match="No valid PM2.5"):
        calculate_stats(empty)
    allowed = calculate_stats(empty, include_count=True, allow_empty=True)
    assert allowed["count"] == 0 and np.isnan(allowed["mean"])
    assert "count" not in calculate_stats(empty, allow_empty=True)


def _version(**overrides):
    fields = dataclasses.asdict(PM25_VERSIONS["V5"])
    return PM25Version(**{**fields, **overrides})


def test_version_needs_all_gee_fields_or_none():
    with pytest.raises(ValueError, match="set all GEE fields"):
        _version(gee_monthly="collection")


def test_version_rejects_a_year_or_region_it_lacks():
    version = PM25_VERSIONS["V5GL04"]

    with pytest.raises(ValueError, match="outside valid range"):
        version.check_year(2023)
    with pytest.raises(ValueError, match="Region AF"):
        version.check_region("AF")
    version.check_year(2022)
    version.check_region("GL")


def test_gee_collection_is_annual_without_a_month():
    version = PM25_VERSIONS["V6"]

    assert version.gee_collection() == version.gee_annual
    assert version.gee_collection(3) == version.gee_monthly
    assert PM25_VERSIONS["V5"].gee_collection(3) is None


def test_aqi_result_is_sufficient_with_an_aqi():
    assert aqi.compute_aqi({"PM2.5": 45, "PM10": 80, "NO2": 30}).sufficient is True
    assert aqi.compute_aqi({"PM2.5": 45}).sufficient is False


def test_daily_aqi_rejects_a_bad_day_end():
    with pytest.raises(ValueError, match="day_ends_at"):
        aqi.daily_aqi(pd.DataFrame(), day_ends_at=25)


def test_daily_aqi_of_no_readings_has_the_columns():
    empty = pd.DataFrame(
        {"timestamp": ["2024-01-01"], "pollutant": ["CH4"], "value": [1.0]}
    )

    daily = aqi.daily_aqi(empty)

    assert daily.empty
    assert list(daily.columns)[:3] == ["station_id", "date", "aqi"]


def test_pollutant_category_rejects_unknown_pollutants():
    with pytest.raises(ValueError, match="not a NAQI pollutant"):
        aqi.pollutant_category("radon", 1.0)


def test_label_with_a_line_break_in_its_name_is_kept_whole():
    assert tidy.split_label(" PM\n2.5 ") == ("PM\n2.5", "")


def test_parse_timestamps_keeps_datetimes():
    values = pd.Series(pd.to_datetime(["2024-01-01"]))

    assert tidy.parse_timestamps(values) is values


def test_raw_to_long_needs_a_timestamp_column():
    with pytest.raises(ValueError, match="Timestamp"):
        tidy.cpcb_raw_to_long(pd.DataFrame({"PM2.5": [1]}))
