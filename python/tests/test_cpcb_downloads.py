"""Historical CPCB downloads, from the file listing to the returned table."""

from __future__ import annotations

import io
import tempfile
from datetime import date

import pandas as pd
import pytest

from vayuayan import CPCBHistorical
from vayuayan.cpcb_historical import _Listing, _read_listing
from vayuayan.exceptions import (
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)

from .cpcb_urls import DOWNLOAD_FILE, DOWNLOAD_LINK, FILE_PATH
from .fakes import http_response


def _workbook(days: int = 40) -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame({"Day": range(1, days + 1), "January": [10] * days}).to_excel(
        buffer, index=False
    )
    return buffer.getvalue()


def _serve_listing(network, entries):
    network.on(
        "post",
        FILE_PATH,
        http_response(json_data={"status": "success", "data": entries}),
    )
    network.on("get", DOWNLOAD_LINK, http_response(b"token"))


def test_past_year_city_data_end_to_end(network, tmp_path):
    entries = [
        {"filepath": "/AQI_daily/delhi/2019/delhi.xlsx", "year": "2019"},
        {"filepath": "/AQI_daily/delhi/2020/delhi.xlsx", "year": "2020"},
    ]
    _serve_listing(network, entries)
    network.on("get", DOWNLOAD_FILE, http_response(_workbook()))
    output = tmp_path / "city.csv"

    df = CPCBHistorical(use_cache=False).download_past_year_aqi_data_city_level(
        "Delhi", "2020", str(output)
    )

    assert len(df) == 31  # a sheet has at most 31 days; CPCB adds summary rows
    assert pd.read_csv(output)["January"].tolist() == [10] * 31
    payload = network.calls[0].kwargs["json"]
    assert (payload["year"], payload["frequency"]) == ("", "1D")
    assert network.calls[1].kwargs["params"] == {
        "file_name": "/AQI_daily/delhi/2020/delhi.xlsx"
    }


def test_past_year_city_data_without_the_year_raises(network, tmp_path):
    _serve_listing(network, [{"filepath": "/x/2019.xlsx", "year": "2019"}])

    with pytest.raises(DataNotFoundError, match="2020"):
        CPCBHistorical().download_past_year_aqi_data_city_level(
            "Delhi", "2020", str(tmp_path / "x.csv")
        )
    assert not (tmp_path / "x.csv").exists()


def test_past_year_station_data_end_to_end(network, tmp_path):
    _serve_listing(network, [{"filepath": "/s/2020.xlsx", "year": 2020}])
    network.on("get", DOWNLOAD_FILE, http_response(_workbook()))
    output = tmp_path / "station.csv"

    data = CPCBHistorical(use_cache=False).download_past_year_aqi_data_station_level(
        "site_301", "2020", str(output)
    )

    assert len(data) == 31
    assert len(pd.read_csv(output)) == 31
    payload = network.calls[0].kwargs["json"]
    assert payload["station_name"] == "Anand Vihar, Delhi - DPCC"
    assert payload["dataType"] == "stationLevel"


def test_past_year_station_data_needs_no_save_path(network):
    _serve_listing(network, [{"filepath": "/s/2020.xlsx", "year": 2020}])
    network.on("get", DOWNLOAD_FILE, http_response(_workbook()))

    data = CPCBHistorical(use_cache=False).download_past_year_aqi_data_station_level(
        "site_301", "2020", ""
    )

    assert len(data) == 31


def test_past_year_station_data_of_an_unknown_station_raises(rss_feed):
    rss_feed([])

    with pytest.raises(StationNotFoundError):
        CPCBHistorical().download_past_year_aqi_data_station_level(
            "site_404", "2020", "unused.csv"
        )


def test_past_year_station_data_without_the_year_raises(network):
    _serve_listing(network, [])

    with pytest.raises(DataNotFoundError, match="site_301"):
        CPCBHistorical().download_past_year_aqi_data_station_level(
            "site_301", "2020", "unused.csv"
        )


def test_year_entry_without_a_filepath_means_no_data():
    client = CPCBHistorical()
    client.get_file_path = lambda *a: [{"year": "2020"}]

    with pytest.raises(DataNotFoundError):
        client.download_past_year_aqi_data_city_level("Delhi", "2020", "")


def _raw_csv(day: str, pm25: float = 90, pm10: float = 100, no2: float = 40) -> str:
    times = pd.date_range(f"{day} 00:00", f"{day} 23:45", freq="15min")
    table = pd.DataFrame(
        {
            "Timestamp": times.strftime("%Y-%m-%d %H:%M:%S"),
            "PM2.5 (µg/m³)": pm25,
            "PM10 (µg/m³)": pm10,
            "NO2 (µg/m³)": no2,
        }
    )
    return table.to_csv(index=False)


def _serve_raw(client, day):
    client.get_file_path = lambda *a, **k: [{"filepath": "/Raw/15Min/x.csv"}]
    client._read_repository_csv = lambda path: pd.read_csv(io.StringIO(_raw_csv(day)))


def test_daily_aqi_from_raw_data():
    client = CPCBHistorical()
    _serve_raw(client, "2024-03-01")

    daily = client.daily_aqi("site_301", "2024")

    row = daily.iloc[0]
    assert len(daily) == 1
    assert row["date"] == date(2024, 3, 1)
    assert (row["aqi"], row["category"], row["dominant_pollutant"]) == (
        200,
        "Moderate",
        "PM2.5",
    )


def test_daily_aqi_leaves_out_a_window_that_ends_next_year():
    client = CPCBHistorical()
    _serve_raw(client, "2024-12-31")

    daily = client.daily_aqi("site_301", "2024", day_ends_at=16)

    assert list(daily["date"]) == [date(2024, 12, 31)]


def test_daily_aqi_without_readings_keeps_its_columns():
    client = CPCBHistorical()
    client.get_file_path = lambda *a, **k: [{"filepath": "/Raw/x.csv"}]
    client._read_repository_csv = lambda path: pd.DataFrame(
        {"Timestamp": ["2024-01-01 00:00:00"], "PM2.5 (µg/m³)": [None]}
    )

    daily = client.daily_aqi("site_301", "2024")

    assert daily.empty
    assert {"date", "aqi", "category"} <= set(daily.columns)


def test_raw_download_tidy_rows_are_saved(tmp_path):
    client = CPCBHistorical()
    _serve_raw(client, "2024-03-01")
    output = tmp_path / "tidy.csv"

    long = client.download_raw_aqi_data_station_level(
        "site_301", "2024", str(output), tidy=True
    )

    assert set(long["pollutant"]) == {"PM2.5", "PM10", "NO2"}
    assert set(long["station_id"]) == {"site_301"}
    assert set(long["state"]) == {"Delhi"}
    assert len(pd.read_csv(output)) == len(long)


def test_raw_download_without_a_listing_raises():
    client = CPCBHistorical()
    client.get_file_path = lambda *a, **k: []

    with pytest.raises(DataNotFoundError, match="site_301"):
        client.download_raw_aqi_data_station_level("site_301", "2024", "")


def test_raw_download_of_an_entry_without_a_filepath_raises():
    client = CPCBHistorical()
    client.get_file_path = lambda *a, **k: [{"year": "2024"}]

    with pytest.raises(DataNotFoundError, match="site_301"):
        client.download_raw_aqi_data_station_level("site_301", "2024", "")


def test_station_info_raises_for_an_unknown_station(rss_feed):
    rss_feed([])
    client = CPCBHistorical()

    with pytest.raises(StationNotFoundError):
        client._station_info("site_404", "Name", "City", "State")


def test_file_path_keeps_the_input_for_an_unknown_station_and_city(rss_feed, network):
    rss_feed([])
    data = {"status": "success", "data": []}
    network.on("post", FILE_PATH, http_response(json_data=data))
    client = CPCBHistorical()

    client.get_file_path("", "", "Nowhere", "Atlantis", "2024", "daily", "cityLevel")
    client.get_file_path("site_404", "", "", "", "2024", "daily", "stationLevel")

    city, station = [c.kwargs["json"] for c in network.calls]
    assert (city["state"], city["city"]) == ("Nowhere", "Atlantis")
    assert station["station_id"] == "site_404"


def test_file_path_of_another_data_type_does_not_look_up_the_station(network):
    data = {"status": "success", "data": []}
    network.on("post", FILE_PATH, http_response(json_data=data))

    assert (
        CPCBHistorical().get_file_path("site_404", "", "", "", "2024", "daily", "other")
        == []
    )


@pytest.mark.parametrize("parsed", [None, [1], {"status": "failed"}, {"status": 1}])
def test_listing_of_a_failed_response_is_failed(parsed):
    if parsed is None:
        assert _read_listing(parsed) == (_Listing.NONE, [])
    else:
        assert _read_listing(parsed) == (_Listing.FAILED, [])


def test_listing_without_data_is_none():
    assert _read_listing({"status": "success"}) == (_Listing.NONE, [])


def test_city_daily_raises_when_the_city_has_no_file_for_the_year():
    client = CPCBHistorical()
    client.get_file_path = lambda *a: [{"year": "2019", "filepath": "/a"}]

    with pytest.raises(DataNotFoundError, match="Delhi"):
        client.city_daily("Delhi", 2020)


def test_station_daily_downloads_once_and_reads_the_copy(tmp_path):
    client = CPCBHistorical()
    client._read_year_excel = lambda entries, year: pd.DataFrame(
        {"Day": [1], "January": [55]}
    )
    listings = []

    def listing(*args):
        listings.append(args[0])
        return [{"year": "2023", "filepath": "/a"}]

    client.get_file_path = listing

    for _ in range(2):
        out = client.station_daily(["site_301"], 2023, cache_dir=str(tmp_path))

    assert listings == ["site_301"]
    assert out.to_dict("records") == [
        {
            "station_id": "site_301",
            "station_name": "Anand Vihar, Delhi - DPCC",
            "day": 1,
            "month": 1,
            "value": 55.0,
        }
    ]


def test_station_daily_skips_a_station_when_cpcb_is_down(tmp_path, rss_feed):
    rss_feed([])
    client = CPCBHistorical()

    def down(*args):
        raise NetworkError("down")

    client.get_file_path = down

    out = client.station_daily("site_301", 2023, cache_dir=str(tmp_path))

    assert out.empty
    assert list(out.columns) == [
        "station_id",
        "station_name",
        "day",
        "month",
        "value",
    ]


def test_csv_copy_uses_one_private_folder_per_client(monkeypatch, tmp_path):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    client = CPCBHistorical()

    first = client._csv_copy(None, "a.csv")
    second = client._csv_copy(None, "b.csv")

    assert first.parent == second.parent
    assert first.parent.parent == tmp_path
    assert CPCBHistorical()._csv_copy(None, "a.csv").parent != first.parent


def test_save_csv_does_nothing_without_a_location(tmp_path, monkeypatch):
    from vayuayan.cpcb_historical import _save_csv

    monkeypatch.chdir(tmp_path)
    _save_csv(pd.DataFrame({"a": [1]}), "")

    assert list(tmp_path.iterdir()) == []
