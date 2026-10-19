"""Tests of OAQClient, CPCB daily sheets, add_coords and india_boundary (no network)."""

from datetime import date

import pandas as pd
import pytest
import requests

from vayuayan import (
    AuthenticationError,
    CPCBHistorical,
    DataNotFoundError,
    NetworkError,
    OAQClient,
    PM25Client,
    geo,
    oaq,
    oaq_city_tally,
    oaq_nearest_cpcb,
)
from vayuayan.tidy import parse_timestamps

from .fakes import FakeResponse


def test_oaq_handshake_signs_every_url(monkeypatch):
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((url, kwargs.get("params")))
        if url == oaq.BROKER_URL:
            return FakeResponse(
                json_data={"baseUrl": "https://x/v1/", "signature": "sig=1"}
            )
        return FakeResponse(json_data={"stations": [
            {"id": "s1", "lat": "12.9", "lon": "77.5", "pm25": "40", "city": "Bengaluru"},
            {"id": "s2", "lat": None, "lon": None, "pm25": "50", "city": "Bengaluru"},
        ]})  # fmt: skip

    monkeypatch.setattr(oaq.http_client, "request", fake_request)
    client = OAQClient("key")
    table = client.stations_table("AURASSURE")

    assert calls[0] == (oaq.BROKER_URL, {"action": "api_session", "token": "key"})
    assert calls[1][0] == (
        "https://x/v1/provider=aurassure/live/global/all_stations_latest.json?sig=1"
    )
    # stations without coordinates are dropped; number columns are numbers
    assert table["id"].tolist() == ["s1"]
    assert table["pm25"].tolist() == [40]
    assert table["provider"].tolist() == ["AURASSURE"]


def test_oaq_needs_a_key_and_hides_it_on_failure(monkeypatch):
    monkeypatch.delenv("OAQ_API_KEY", raising=False)
    with pytest.raises(AuthenticationError, match="not found"):
        OAQClient()

    def fail(*args, **kwargs):
        raise requests.HTTPError(
            "403 for url ...token=secret", response=FakeResponse(status=403)
        )

    monkeypatch.setattr(oaq.http_client, "request", fail)
    with pytest.raises(AuthenticationError) as err:
        OAQClient("secret")
    assert "secret" not in str(err.value) and "403" in str(err.value)


def test_pm25_regional_files(tmp_path):
    client = PM25Client("V5GL04", cache_dir=str(tmp_path), region="AS")
    assert client._get_aws_url(2022, 1) == (
        "https://satpmdata.s3.amazonaws.com/archive/V5GL04/GWRPM25/Monthly/Asia/"
        "V5GL04.HybridPM25.Asia.202201-202201.nc"
    )
    with pytest.raises(ValueError, match="Region AF"):
        PM25Client("V6", cache_dir=str(tmp_path), region="AF")


def test_add_coords_uses_snapshot_then_feed(monkeypatch):
    client = CPCBHistorical()
    feed = [
        {"stationsInCity": [{"id": "site_new", "latitude": "1.5", "longitude": "2"}]}
    ]
    monkeypatch.setattr(client, "_rss_cities", lambda: feed)
    out = client.add_coords(
        [
            {"label": "Anand Vihar", "value": "site_301"},
            {"label": "New", "value": "site_new"},
        ]
    )
    assert out[0]["lat"] == pytest.approx(28.647, abs=0.01)
    assert (out[1]["lat"], out[1]["lon"]) == (1.5, 2.0)


def test_city_daily_reuses_the_csv_copy(monkeypatch, tmp_path):
    client = CPCBHistorical()
    downloads = []

    def fake_download(city, year, path):
        downloads.append(city)
        pd.DataFrame({"Day": [1, 30], "February": [100, 200]}).to_csv(path, index=False)

    monkeypatch.setattr(client, "download_past_year_aqi_data_city_level", fake_download)
    for _ in range(2):
        out = client.city_daily("Delhi", 2023, cache_dir=str(tmp_path))
    assert downloads == ["Delhi"]
    assert out.to_dict("list") == {
        "city": ["Delhi", "Delhi"], "day": [1, 30], "month": [2, 2], "value": [100.0, 200.0]
    }  # fmt: skip


def test_station_daily_skips_unknown_stations(monkeypatch, tmp_path):
    client = CPCBHistorical()
    monkeypatch.setattr(client, "_resolved_station", lambda q: None)
    out = client.station_daily(["nowhere"], 2023, cache_dir=str(tmp_path))
    assert out.empty and list(out.columns)[:2] == ["station_id", "station_name"]


def test_india_boundary_unions_a_state(monkeypatch):
    import geopandas as gpd
    from shapely.geometry import box

    districts = gpd.GeoDataFrame(
        {"state_name": ["Delhi", "Delhi", "Goa"], "district_name": ["A", "B", "C"]},
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1), box(5, 5, 6, 6)],
        crs=4326,
    )
    monkeypatch.setattr(geo, "_districts", lambda: districts)
    assert geo.india_boundary(state="Delhi").bounds == (0, 0, 2, 1)
    with pytest.raises(ValueError):
        geo.india_boundary(district="Nowhere")


def test_timestamps_parse_each_value_on_its_own():
    out = parse_timestamps(
        pd.Series(["2024-01-01 10:00:00", "2024-01-01 10:00", "bad"])
    )
    assert out.tolist()[:2] == [pd.Timestamp("2024-01-01 10:00")] * 2
    assert pd.isna(out.iloc[2])


def test_oaq_data_errors_hide_the_signature(monkeypatch):
    def fake_request(method, url, **kwargs):
        if url == oaq.BROKER_URL:
            return FakeResponse(json_data={"signature": "sig=SECRET"})
        raise requests.HTTPError(f"404 for url: {url}")

    monkeypatch.setattr(oaq.http_client, "request", fake_request)
    with pytest.raises(NetworkError) as err:
        OAQClient("key").get_annual("cpcb", "s1", 2024)
    assert "SECRET" not in str(err.value)


def test_oaq_sensors_lists_every_provider(monkeypatch):
    client = OAQClient.__new__(OAQClient)  # no handshake
    monkeypatch.setattr(
        client,
        "list_providers",
        lambda: {"providers": [{"id": "cpcb"}, {"id": "airnet"}]},
    )
    asked = []
    monkeypatch.setattr(client, "stations_table", lambda p: asked.append(p) or "table")
    assert client.sensors() == "table" and asked == [["cpcb", "airnet"]]
    client.sensors("airnet")
    assert asked[-1] == "airnet"


def test_oaq_city_tally_counts_only_oaq_sensors():
    sensors = pd.DataFrame(
        {
            "id": ["a", "b", "c", "d"],
            "name": ["A", "B", "C", "D"],
            "city": ["Bengaluru", "Bengaluru", "Nowhere", "Delhi"],
            "lat": [12.99, 12.95, 21.49, 28.55],
            "lon": [77.58, 77.60, 83.87, 77.27],
            "provider": ["airnet", "airnet", "aurassure", "cpcb"],
        }
    )
    tally = oaq_city_tally(sensors)
    assert tally[["city", "provider", "sensors"]].values.tolist() == [
        ["Bengaluru", "airnet", 2],
        ["Nowhere", "aurassure", 1],
    ]
    assert tally["cpcb_stations"].tolist()[1] == 0
    nearest = oaq_nearest_cpcb(sensors, k=3)
    assert nearest.groupby("sensor_id")["rank"].max().eq(3).all()
    assert nearest.groupby("sensor_id")["distance_km"].is_monotonic_increasing.all()
    assert oaq_city_tally(sensors[sensors.provider == "cpcb"]).empty


def test_oaq_daily_means_need_enough_readings(monkeypatch):
    client = OAQClient.__new__(OAQClient)  # no handshake
    full = [{"date": f"t{i}", "pm25": 10.0 + i % 2, "pm10": None} for i in range(96)]
    short = [{"date": f"t{i}", "pm25": 50.0} for i in range(10)]

    def fake_daily(provider, sensor_id, year, month, day):
        if day == 3:
            raise NetworkError("no file")
        return {"data": full if day == 1 else short}

    monkeypatch.setattr(client, "get_daily", fake_daily)
    out = client.daily_means("airnet", "s1", ["2026-09-01", "2026-09-02", "2026-09-03"])
    assert out["date"].astype(str).tolist() == ["2026-09-01", "2026-09-02"]
    assert out["pm25"].iloc[0] == pytest.approx(10.5)
    assert pd.isna(out["pm25"].iloc[1]) and out["n_pm25"].tolist() == [96, 10]
    assert out["n_pm10"].iloc[0] == 0 and pd.isna(out["pm10"].iloc[0])


def test_oaq_readings_stack_days_in_local_time(monkeypatch):
    client = OAQClient.__new__(OAQClient)  # no handshake
    days = {
        1: [{"date": "2026-09-01T00:00:00+05:30", "pm25": "12.5", "pm10": None},
            {"date": "2026-09-01T00:15:00+05:30", "pm25": 13, "pm10": 40}],
        2: [{"date": "bad", "pm25": 1}],
    }  # fmt: skip

    def fake_daily(provider, sensor_id, year, month, day):
        if day not in days:
            raise NetworkError("no file")
        return {"data": days[day]}

    monkeypatch.setattr(client, "get_daily", fake_daily)
    out = client.readings("airnet", "s1", ["2026-09-01", "2026-09-02", "2026-09-03"])
    assert list(out.columns) == ["sensor_id", "timestamp", "pm25", "pm10"]
    assert out["timestamp"].astype(str).tolist() == [
        "2026-09-01 00:00:00",
        "2026-09-01 00:15:00",
    ]
    assert out["pm25"].tolist() == [12.5, 13.0] and pd.isna(out["pm10"].iloc[0])
    assert client.readings("airnet", "s1", ["2026-09-03"]).empty


def _fake_oaq(monkeypatch):
    """An OAQClient whose daily file of 2026-05-29 ends on a spike."""
    client = OAQClient.__new__(OAQClient)  # no handshake
    readings = [
        {"date": f"2026-05-29T{h:02d}:00:00+05:30", "pm25": 10.0} for h in range(23)
    ]
    readings.append({"date": "2026-05-29T23:45:00+05:30", "pm25": 300.0})

    def fake_annual(provider, sensor_id, year):
        if year != 2026:
            raise NetworkError("no file")
        return {"data": [{"date": "2026-05-29", "pm25": 300.0, "temp": "31"}]}

    def fake_daily(provider, sensor_id, year, month, day):
        if (month, day) != (5, 29):
            raise NetworkError("no file")
        return {"data": readings}

    monkeypatch.setattr(client, "get_annual", fake_annual)
    monkeypatch.setattr(client, "get_daily", fake_daily)
    return client


def test_oaq_daily_records_and_their_check(monkeypatch):
    client = _fake_oaq(monkeypatch)
    records = client.daily_records("cpcb", "164", [2025, 2026])
    assert records.to_dict("list") == {
        "sensor_id": ["164"], "date": [date(2026, 5, 29)], "pm25": [300.0], "temp": [31.0]
    }  # fmt: skip
    check = client.check_daily_records("cpcb", "164", ["2026-05-29", "2026-05-30"])
    row = check.iloc[0]
    assert len(check) == 1 and row["n"] == 24 and row["last"] == 300.0
    assert row["record_is_last"] and not row["record_is_mean"]
    assert row["mean"] == pytest.approx((23 * 10 + 300) / 24)


def test_oaq_readings_of_several_sensors(monkeypatch):
    client = _fake_oaq(monkeypatch)
    out = client.readings("cpcb", ["164", "165"], ["2026-05-29"])
    assert out.groupby("sensor_id").size().to_dict() == {"164": 24, "165": 24}


def test_raw_readings_skip_stations_without_data(monkeypatch):
    client = CPCBHistorical()

    def fake_raw(station, year, save_location, tidy=False):
        if station == "site_2":
            raise DataNotFoundError("none")
        return pd.DataFrame({"station_id": [station] * 2, "pollutant": ["PM2.5", "RH"],
                             "value": [1.0, 2.0]})  # fmt: skip

    monkeypatch.setattr(client, "download_raw_aqi_data_station_level", fake_raw)
    out = client.raw_readings(["site_1", "site_2"], 2026, pollutants=["PM2.5"])
    assert out.to_dict("list") == {
        "station_id": ["site_1"],
        "pollutant": ["PM2.5"],
        "value": [1.0],
    }
    assert client.raw_readings(["site_2"], 2026).empty


def test_oaq_data_requests_retry_network_errors_not_404(monkeypatch):
    monkeypatch.setattr("vayuayan.http_client.time.sleep", lambda s: None)
    client = OAQClient.__new__(OAQClient)  # no handshake
    client.base_url, client.sig_string = "https://x/v1", "sig=1"
    calls = []

    def flaky(method, url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            raise requests.ConnectionError("reset")
        return FakeResponse(json_data={"data": [1]})

    monkeypatch.setattr("vayuayan.http_client.requests.request", flaky)
    assert client.get_annual("cpcb", "1", 2026) == {"data": [1]} and len(calls) == 2

    calls.clear()
    monkeypatch.setattr(
        "vayuayan.http_client.requests.request",
        lambda *a, **k: calls.append(1) or FakeResponse(status=404),
    )
    with pytest.raises(NetworkError):
        client.get_annual("cpcb", "1", 2025)
    assert len(calls) == 1


def test_oaq_city_latest_uses_lower_case_paths(monkeypatch):
    client = OAQClient.__new__(OAQClient)  # no handshake
    paths = []
    monkeypatch.setattr(client, "_get", lambda path: paths.append(path) or {})
    client.get_city_latest("AIRNET", "Bengaluru")
    assert paths == ["provider=airnet/live/by_city/bengaluru/map_latest.json"]
