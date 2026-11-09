"""Every CPCB request: exact URL, method and payload.

The URLs are written out here, not taken from the package constants, so a
changed or removed route fails a test.
"""

import pytest

from vayuayan import CPCBHistorical, CPCBLive, cpcb_common
from vayuayan.client import CPCBClient
from vayuayan.exceptions import DataNotFoundError

from .cpcb_urls import (
    CUSTOM_QUERY,
    DASHBOARD_PARAMETERS,
    DASHBOARD_STATIONS,
    DOWNLOAD_FILE,
    DOWNLOAD_LINK,
    FILE_PATH,
    FILES,
    FORM_HEADERS,
    JSON_HEADERS,
    LEGACY_FILE_PATH,
    LEGACY_STATION_LIST,
    OAUTH,
    RSS,
    RSS_FEED,
)
from .fakes import b64_body, b64_decode, http_response


def test_file_path_posts_json_to_the_new_route(network):
    network.on("post", FILE_PATH, http_response(json_data=FILES))

    entries = CPCBHistorical().get_file_path(
        "site_301", "", "", "Delhi", "2024", "hourly", "stationLevel"
    )

    assert entries == FILES["data"]
    [call] = network.calls
    assert (call.method, call.url) == ("post", FILE_PATH)
    assert call.kwargs["json"] == {
        "station_id": "site_301",
        "station_name": "Anand Vihar, Delhi - DPCC",
        "state": "Delhi",
        "city": "Delhi",
        "year": "2024",
        "frequency": "1H",
        "dataType": "stationLevel",
    }
    assert call.kwargs["headers"] == JSON_HEADERS
    assert call.kwargs["params"] is None


def test_file_path_for_a_city_sends_the_directory_names(network):
    network.on("post", FILE_PATH, http_response(json_data=FILES))

    CPCBHistorical().get_file_path("", "", "delhi", "DELHI", "", "daily", "cityLevel")

    assert network.calls[0].kwargs["json"] == {
        "station_id": "",
        "station_name": "",
        "state": "Delhi",
        "city": "Delhi",
        "year": "",
        "frequency": "1D",
        "dataType": "cityLevel",
    }


def test_file_path_for_raw_data_uses_the_raw_type_and_15_minute_code(network):
    network.on("post", FILE_PATH, http_response(json_data=FILES))

    CPCBHistorical().get_file_path(
        "site_301", "", "", "Delhi", "2024", "15_minute", "raw"
    )

    payload = network.calls[0].kwargs["json"]
    assert (payload["dataType"], payload["frequency"]) == ("raw", "15M")
    assert payload["station_name"] == "Anand Vihar, Delhi - DPCC"


def test_legacy_file_path_gets_base64_json_and_the_package_frequency(network):
    network.on("post", FILE_PATH, http_response(status=404))
    network.on("post", LEGACY_FILE_PATH, http_response(b64_body(FILES)))

    entries = CPCBHistorical().get_file_path(
        "site_301", "", "", "Delhi", "2024", "hourly", "stationLevel"
    )

    assert entries == FILES["data"]
    assert network.urls() == [FILE_PATH, LEGACY_FILE_PATH]
    legacy = network.calls[1]
    assert legacy.method == "post"
    assert legacy.kwargs["headers"] == FORM_HEADERS
    assert b64_decode(legacy.kwargs["data"]) == {
        "station_id": "site_301",
        "station_name": "Anand Vihar, Delhi - DPCC",
        "state": "",
        "city": "Delhi",
        "year": "2024",
        "frequency": "hourly",
        "dataType": "stationLevel",
    }


def test_download_asks_for_a_link_then_sends_the_token_unchanged(network):
    token = "abc%3D%2Fd+e="
    network.on("get", DOWNLOAD_LINK, http_response(f" {token}\n".encode()))
    network.on("get", DOWNLOAD_FILE, http_response(b"workbook"))

    body = CPCBHistorical(use_cache=False)._download_repository_file("/AQI/2024/x.xlsx")

    assert body.read() == b"workbook"
    link, download = network.calls
    assert (link.method, link.url) == ("get", DOWNLOAD_LINK)
    assert link.kwargs["params"] == {"file_name": "/AQI/2024/x.xlsx"}
    assert link.kwargs["headers"] == JSON_HEADERS
    assert (download.method, download.url) == (
        "get",
        f"{DOWNLOAD_FILE}?file_name={token}",
    )
    assert "params" not in download.kwargs
    assert download.kwargs["headers"] == JSON_HEADERS
    assert download.kwargs["timeout"] == 60


@pytest.mark.parametrize(
    "level,code,query,filter_query",
    [
        ("states", "", "get-state-master-list-data", ""),
        ("cities", "ST-10", "get-city-master-list", "state_code IS 'ST-10'"),
        (
            "stations",
            "CTY-1",
            "get-site-station-master-data-list",
            "city_code IS 'CTY-1'",
        ),
    ],
)
def test_directory_queries_carry_the_oauth_token(
    network, cpcb_credentials, level, code, query, filter_query
):
    rows = [{"name": "row"}]
    network.on("post", OAUTH, http_response(json_data={"access_token": "tok"}))
    network.on("get", f"{CUSTOM_QUERY}/{query}/data", http_response(json_data=rows))

    assert CPCBHistorical()._directory(level, code) == rows

    token, directory = network.calls
    assert (token.method, token.url) == ("post", OAUTH)
    assert token.kwargs["params"] == {
        "grant_type": "password",
        "username": "x",
        "password": "x",
        "client_id": "x",
        "client_secret": "x",
    }
    assert token.kwargs["json"] == {}
    assert token.kwargs["headers"] == {"Content-Type": "application/json"}
    assert directory.method == "get"
    assert directory.kwargs["params"] == {
        "pageNo": -1,
        "perPage": -1,
        "filterQuery": filter_query,
    }
    assert directory.kwargs["headers"] == {**JSON_HEADERS, "Authorization": "tok"}


def test_dashboard_station_list_route(network):
    cities = [{"cityName": "Delhi", "stationsInCity": []}]
    network.on(
        "post", DASHBOARD_STATIONS, http_response(b64_body({"stations": cities}))
    )

    assert CPCBLive().get_all_india() == cities

    [call] = network.calls
    assert (call.method, call.url) == ("post", DASHBOARD_STATIONS)
    assert b64_decode(call.kwargs["data"]) == {}
    assert call.kwargs["headers"] == FORM_HEADERS
    assert call.kwargs["cookies"] == {"ccr_public": "A"}


def test_dashboard_parameters_route(network):
    reply = {
        "station_id": "site_1",
        "airQualityIndex": {"value": "88"},
        "metrics": [{"name": "PM2.5"}],
    }
    network.on("post", DASHBOARD_PARAMETERS, http_response(b64_body(reply)))

    data = CPCBLive().get_live_aqi_data_for_station("site_1", "2026-01-01T10:00:00Z")

    assert data["airQualityIndex"] == {"value": 88.0}
    [call] = network.calls
    assert (call.method, call.url) == ("post", DASHBOARD_PARAMETERS)
    assert b64_decode(call.kwargs["data"]) == {
        "station_id": "site_1",
        "date": "2026-01-01T10:00:00Z",
    }
    assert call.kwargs["headers"] == FORM_HEADERS
    assert call.kwargs["cookies"] == {"ccr_public": "A"}


def test_rss_feed_route(network):
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    cities = CPCBLive()._rss_cities()

    assert cities[0]["stationsInCity"][0]["id"] == "site_1"
    [call] = network.calls
    assert (call.method, call.url) == ("get", RSS)
    assert "Mozilla" in call.kwargs["headers"]["User-Agent"]
    assert call.kwargs["timeout"] == 30


def test_legacy_station_list_route(network):
    network.on("get", RSS, http_response(status=404))
    dropdown = {"cities": {"Delhi": []}}
    reply = {"status": "success", "dropdown": dropdown}
    network.on("post", LEGACY_STATION_LIST, http_response(b64_body(reply)))

    assert CPCBHistorical().get_complete_list() == dropdown

    call = network.calls[-1]
    assert (call.method, call.url) == ("post", LEGACY_STATION_LIST)
    assert b64_decode(call.kwargs["data"]) == {}


def test_legacy_client_builds_downloads_through_the_repository_api(
    network, tmp_path, rss_feed
):
    rss_feed([])
    network.on(
        "post",
        FILE_PATH,
        http_response(
            json_data={
                "status": "success",
                "data": [
                    {"filepath": "/Raw_data/15Min/2024/DL001.csv", "year": "2024"}
                ],
            }
        ),
    )
    network.on("get", DOWNLOAD_LINK, http_response(b"token123"))
    network.on("get", DOWNLOAD_FILE, http_response(b"a\n1\n"))

    path = CPCBClient().download_raw_data(
        site_id="DL001",
        station_name="Punjabi Bagh - DPCC",
        time_period="15Min",
        year="2024",
        output_dir=str(tmp_path),
    )

    assert network.urls() == [
        FILE_PATH,
        DOWNLOAD_LINK,
        f"{DOWNLOAD_FILE}?file_name=token123",
    ]
    assert network.calls[0].kwargs["json"]["frequency"] == "15M"
    assert path == str(tmp_path / "DL001_Punjabi_Bagh_DPCC_15Min_2024.csv")
    assert (
        tmp_path / "DL001_Punjabi_Bagh_DPCC_15Min_2024.csv"
    ).read_bytes() == b"a\n1\n"


def test_legacy_client_without_a_repository_file_raises(network, tmp_path, rss_feed):
    rss_feed([])
    network.on(
        "post", FILE_PATH, http_response(json_data={"status": "success", "data": []})
    )

    with pytest.raises(DataNotFoundError, match="DL001"):
        CPCBClient().download_raw_data(
            site_id="DL001",
            station_name="Punjabi Bagh",
            time_period="15Min",
            year="2024",
            output_dir=str(tmp_path),
        )


def test_send_uses_the_ssl_fallback_and_default_timeout(monkeypatch):
    sent = []
    monkeypatch.setattr(
        cpcb_common.http_client,
        "request",
        lambda method, url, **kwargs: sent.append((method, url, kwargs)),
    )

    cpcb_common.send("GET", "https://x.example", timeout=5, retries=0)

    assert sent == [
        ("GET", "https://x.example", {"timeout": 5, "retries": 0, "ssl_fallback": True})
    ]
