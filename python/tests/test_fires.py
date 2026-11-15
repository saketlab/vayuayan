"""FIRMS fire detections: source routing, parsing and daily counts (offline)."""

import datetime as dt
from typing import List

import pytest
import requests

from vayuayan import fires
from vayuayan.exceptions import ConfigurationError, DataParsingError

from .fakes import FakeResponse

MODIS = (
    "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_t31,frp,daynight,type\n"
    "30.84,74.66,318,1.1,1,2023-11-01,0457,Terra,MODIS,72,61.03,305,23.6,D,0\n"
    "30.20,76.50,318,1.1,1,2023-11-03,2010,Aqua,MODIS,50,61.03,305,10.0,N,0\n"
    "12.00,80.00,318,1.1,1,2023-11-03,0800,Aqua,MODIS,90,61.03,305,99.0,D,0\n"
    "30.50,75.00,318,1.1,1,2023-12-31,0800,Aqua,MODIS,90,61.03,305,5.0,D,0\n"
)
VIIRS_NRT = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "confidence,version,bright_ti5,frp,daynight\n"
    "28.70,77.10,331.3,0.4,0.37,{day},825,N,nominal,2.0NRT,288.8,2.0,D\n"
    "28.70,77.10,331.3,0.4,0.37,{day},1930,N,h,2.0NRT,288.8,3.0,N\n"
)


@pytest.fixture
def urls(monkeypatch) -> List[str]:
    """Record requested URLs; answer with canned CSV text."""
    seen: List[str] = []
    today = dt.datetime.now(dt.timezone.utc).date()

    def get_text(url: str) -> str:
        seen.append(url)
        if "/data/country/modis/2023/modis_2023_India" in url:
            return MODIS
        if "/data/country/modis/2023/" in url or "/viirs-snpp/2025/" in url:
            return MODIS.split("\n", 1)[0] + "\n"  # a neighbour without fires
        if "/data/country/" in url:
            raise requests.HTTPError(response=FakeResponse(status=404))
        if "/data_availability/" in url:
            return "data_id,min_date,max_date\nVIIRS_SNPP_SP,2012-01-20,2026-06-30\n"
        if "/active_fire/" in url:
            return VIIRS_NRT.format(day=today.isoformat())
        return ""

    monkeypatch.setattr(fires, "_get_text", get_text)
    return seen


def test_archive_year_is_filtered_cached_and_parsed(urls):
    got = fires.firms_fires(
        "2023-11-01", "2023-11-03", bbox=(73, 29, 78, 32.5), source="modis"
    )
    assert list(got.columns) == fires.FIRE_COLUMNS
    assert [str(d) for d in got["date"]] == ["2023-11-01", "2023-11-03"]
    assert got["datetime"].iloc[1].isoformat() == "2023-11-03T20:10:00+00:00"
    assert got["confidence"].tolist() == [72, 50]
    assert got["confidence"].dtype.kind == "i"  # empty neighbour files dropped
    assert sorted(u.rsplit("_", 1)[1] for u in urls) == [
        "Afghanistan.csv", "China.csv", "India.csv", "Pakistan.csv",
    ]  # fmt: skip
    fires.firms_fires("2023-11-01", bbox=(73, 29, 78, 32.5), source="modis")
    assert len(urls) == 4  # the second call read the cache


def test_a_range_across_new_year_reads_the_archive_then_the_api(urls):
    got = fires.firms_fires(
        "2025-12-30", "2026-01-02", bbox=(73, 29, 78, 32.5), map_key="K"
    )
    assert got.empty
    api = [u.split("/api/area/csv/K/")[1] for u in urls if "/api/area/" in u]
    assert api == ["VIIRS_SNPP_SP/73,29,78,32.5/2/2026-01-01"]


def test_noaa21_has_no_archive_so_past_years_use_the_api(urls):
    fires.firms_fires(
        "2024-11-01", bbox=(73, 29, 78, 32.5), source="viirs-noaa21", map_key="K"
    )
    assert any("/data/country/viirs-jpss2/2024/" in u for u in urls)
    api = [u.split("/api/area/csv/K/")[1] for u in urls if "/api/area/" in u]
    assert api == ["VIIRS_NOAA21_SP/73,29,78,32.5/1/2024-11-01"]


def test_a_firms_message_is_an_error_not_an_empty_table():
    with pytest.raises(DataParsingError, match="Invalid MAP_KEY"):
        fires._parse_firms_csv("Invalid MAP_KEY.")


def test_recent_days_use_the_7_day_file_without_a_key(urls, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    today = dt.datetime.now(dt.timezone.utc).date()
    got = fires.firms_fires(today - dt.timedelta(days=2), today)
    assert got["confidence"].tolist() == ["nominal", "high"]
    assert got["datetime"].iloc[0].strftime("%H:%M") == "08:25"
    assert all("/active_fire/" in u for u in urls)


def test_older_current_year_days_need_a_key(urls, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    old = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=30)
    with pytest.raises(ConfigurationError, match="FIRMS_MAP_KEY"):
        fires.firms_fires(old)


def test_api_requests_split_into_runs_and_pick_sp_or_nrt(urls):
    days = [dt.date(2026, 6, 27) + dt.timedelta(days=i) for i in range(7)]
    fires._api_frames("viirs-snpp", days, (73, 29, 78, 32.5), "KEY")
    api = [u.split("/api/area/csv/KEY/")[1] for u in urls if "/api/area/" in u]
    assert api == [
        "VIIRS_SNPP_SP/73,29,78,32.5/4/2026-06-27",  # ends 30 June, the last SP day
        "VIIRS_SNPP_NRT/73,29,78,32.5/3/2026-07-01",
    ]


def test_day_runs_break_on_gaps_and_size():
    d = dt.date(2026, 1, 1)
    days = [d + dt.timedelta(days=i) for i in (0, 1, 2, 3, 4, 5, 6, 9)]
    assert fires._day_runs(days, 5) == [
        (d, 5),
        (d + dt.timedelta(days=5), 2),
        (d + dt.timedelta(days=9), 1),
    ]


def test_unknown_source_and_reversed_dates():
    with pytest.raises(ValueError, match="source"):
        fires.firms_fires("2023-01-01", source="goes")
    with pytest.raises(ValueError, match="before"):
        fires.firms_fires("2023-01-02", "2023-01-01")


def test_daily_counts_fill_days_without_fires():
    table = fires._parse_firms_csv(MODIS)
    got = fires.fire_daily_counts(
        table, 30.5, 75.5, radius_km=150, end="2023-11-04", tz="UTC"
    )
    assert [str(d) for d in got["date"]] == [
        "2023-11-01", "2023-11-02", "2023-11-03", "2023-11-04",
    ]  # fmt: skip
    assert got["n_fires"].tolist() == [1, 0, 1, 0]
    assert got["frp_sum"].tolist() == [23.6, 0.0, 10.0, 0.0]
    ist = fires.fire_daily_counts(table, 30.5, 75.5, radius_km=150, end="2023-11-04")
    assert ist["n_fires"].tolist() == [1, 0, 0, 1]  # 20:10 UTC is 01:40 IST next day
    with pytest.raises(ValueError, match="before"):
        fires.fire_daily_counts(table, 30.5, 75.5, start="2023-11-04", end="2023-11-01")
    empty = fires.fire_daily_counts(fires._parse_firms_csv(""), 0, 0)
    assert list(empty.columns) == ["date", "n_fires", "frp_sum"] and empty.empty


def test_a_refused_key_error_does_not_show_the_key(monkeypatch):
    def refuse(method, url, **kwargs):
        raise requests.HTTPError(
            "401 for url " + url, response=FakeResponse(status=401)
        )

    monkeypatch.setattr(fires.http_client, "request", refuse)
    with pytest.raises(ConfigurationError, match="refused") as e:
        fires._get_text(
            f"{fires.FIRMS_URL}/api/area/csv/SECRET/VIIRS_SNPP_NRT/1,2,3,4/1"
        )
    assert "SECRET" not in str(e.value) and e.value.__cause__ is None
