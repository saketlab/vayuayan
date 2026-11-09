"""Station tables, the CPCB RSS fetcher and the request helpers of utils."""

from __future__ import annotations

import logging
import math

import pandas as pd
import pytest
import requests

from vayuayan import utils
from vayuayan.exceptions import DataProcessingError, NetworkError

from .cpcb_urls import RSS
from .fakes import b64_body, http_response

URL = "https://x.example/api"
CITIES = [
    {
        "cityName": "Delhi",
        "cityID": "DL",
        "stateID": "Delhi",
        "stationsInCity": [
            {"id": "a", "name": "A", "live": True, "avg": "120",
             "latitude": "28.6", "longitude": "77.2"},
            {"id": "b", "name": "B", "live": True, "avg": 40,
             "latitude": 28.7, "longitude": 77.1},
            {"id": "c", "name": "C", "live": False, "avg": "",
             "latitude": None, "longitude": None},
        ],
    },
    {"cityName": "Empty", "cityID": "E", "stateID": "Goa", "stationsInCity": []},
    {
        "cityName": "Mumbai",
        "cityID": "MB",
        "stateID": "Maharashtra",
        "stationsInCity": [
            {"id": "m", "name": "M", "live": False, "avg": "450",
             "latitude": "bad", "longitude": 72.8},
        ],
    },
]  # fmt: skip


def test_rss_fetch_parses_the_feed(network):
    feed = {
        "country": [
            {
                "stateId": "Goa",
                "citiesInState": [
                    {
                        "cityId": "Panaji",
                        "stationsInCity": [{"siteId": "s", "stationName": "P"}],
                    }
                ],
            }
        ]
    }
    network.on("get", RSS, http_response(json_data=feed))

    cities = utils.fetch_cpcb_rss_station_data(timeout=7)

    assert cities[0]["cityName"] == "Panaji"
    assert cities[0]["stateID"] == "Goa"
    assert network.urls() == [RSS]
    assert network.calls[0].kwargs["timeout"] == 7


def test_rss_fetch_failures(network):
    network.on("get", RSS, http_response(status=500))
    with pytest.raises(NetworkError):
        utils.fetch_cpcb_rss_station_data()

    network.on("get", RSS, http_response(b"<html>"))
    with pytest.raises(ValueError):
        utils.fetch_cpcb_rss_station_data()


def test_rss_parsing_of_older_feeds_and_of_stations_without_an_id():
    feed = {
        "country": [
            {
                "stateId": "Goa",
                "citiesInState": [
                    {
                        "cityId": "Panaji",
                        "stationsInCity": [
                            {"stationName": "Old", "airQualityIndex": {"Value": 77}},
                            {"stationName": "Blank"},
                        ],
                    }
                ],
            }
        ]
    }

    stations = utils.parse_cpcb_rss_station_data(feed)[0]["stationsInCity"]

    by_name = {s["name"]: s for s in stations}
    assert by_name["Old"]["id"] == "Old"  # the name stands in for a missing id
    assert by_name["Old"]["avg"] == 77
    assert by_name["Old"]["live"] is False
    assert by_name["Blank"]["avg"] == ""
    assert by_name["Blank"]["airQualityIndex"] == {}


def test_sort_station_data_handles_cities_without_a_station_list():
    data = [{"cityName": "B"}, {"cityName": "A", "stationsInCity": []}]

    assert [c["cityName"] for c in utils.sort_station_data(data)] == ["A", "B"]


def test_dropdown_skips_unnamed_cities_and_incomplete_stations():
    data = [
        {"cityName": "", "stateID": "X", "stationsInCity": [{"id": "1", "name": "n"}]},
        {
            "cityName": "B",
            "stateID": "X",
            "stationsInCity": [{"id": "", "name": "no id"}, {"id": "2", "name": "z"}],
        },
        {"cityName": "A", "stateID": "X", "stationsInCity": []},
        {"cityName": "A", "stateID": "X", "stationsInCity": []},
    ]

    dropdown = utils.station_data_to_dropdown(data)

    assert dropdown["cities"] == {
        "X": [{"label": "A", "value": "A"}, {"label": "B", "value": "B"}]
    }
    assert dropdown["stations"]["B"] == [{"label": "z", "value": "2"}]


def test_iter_station_coords_skips_stations_without_valid_coordinates():
    assert [
        (station["id"], lat, lon)
        for station, lat, lon in utils.iter_station_coords(CITIES)
    ] == [("a", 28.6, 77.2), ("b", 28.7, 77.1)]


def test_station_with_nan_coordinates_is_skipped():
    cities = [
        {
            "stationsInCity": [
                {"id": "nan", "latitude": "NaN", "longitude": "NaN"},
                {"id": "ok", "latitude": 1.0, "longitude": 2.0},
            ]
        }
    ]

    assert [s["id"] for s, _, _ in utils.iter_station_coords(cities)] == ["ok"]


def test_station_distances():
    distances = utils.station_distances(CITIES, "28.6", "77.2")

    assert [station["id"] for station, _ in distances] == ["a", "b"]
    assert distances[0][1] == pytest.approx(0.0)
    assert distances[1][1] > 0


@pytest.mark.parametrize(
    "value,expected", [("12.5", 12.5), (3, 3.0), ("NA", -1.0), ("", -1.0), (None, -1.0)]
)
def test_safe_float_conversion(value, expected):
    assert utils._safe_float_conversion(value, default=-1.0) == expected


def test_safe_float_conversion_defaults_to_nan():
    assert math.isnan(utils._safe_float_conversion(object()))


def test_stations_to_dataframe():
    df = utils.stations_to_dataframe(CITIES)

    assert df["station_id"].tolist() == ["a", "b", "c", "m"]
    assert df["status"].tolist() == ["Live", "Live", "Offline", "Offline"]
    assert df["aqi_category"].tolist() == [
        "Moderate",
        "Good",
        "No Data",
        "Severe",
    ]
    assert df.loc[0, "latitude"] == 28.6
    assert math.isnan(df.loc[3, "latitude"])
    assert df.loc[3, "city_id"] == "MB"


def test_city_summary_averages_live_stations_only():
    summary = utils.stations_to_city_summary(CITIES).set_index("city_name")

    delhi = summary.loc["Delhi"]
    assert (delhi["total_stations"], delhi["live_stations"]) == (3, 2)
    assert delhi["offline_stations"] == 1
    assert delhi["live_percentage"] == pytest.approx(200 / 3)
    assert (delhi["avg_aqi"], delhi["min_aqi"], delhi["max_aqi"]) == (80, 40, 120)
    assert delhi["stations_with_data"] == 2

    empty = summary.loc["Empty"]
    assert (empty["total_stations"], empty["live_percentage"]) == (0, 0)
    assert math.isnan(empty["avg_aqi"])
    # An offline station's value does not count
    assert math.isnan(summary.loc["Mumbai", "avg_aqi"])


def test_coordinates_table_skips_stations_without_valid_coordinates():
    df = utils.stations_to_coordinates_dataframe(CITIES)

    assert df["station_id"].tolist() == ["a", "b"]
    assert df.loc[0, "state_id"] == "Delhi"
    assert df.loc[0, "aqi_category"] == "Moderate"
    assert df.loc[1, "status"] == "Live"


@pytest.mark.parametrize(
    "method,column",
    [
        ("stations", "station_id"),
        ("city_summary", "total_stations"),
        ("coordinates", "latitude"),
    ],
)
def test_convert_station_data(method, column):
    df = utils.convert_station_data_to_dataframe(CITIES, method)

    assert isinstance(df, pd.DataFrame)
    assert column in df.columns


def test_convert_station_data_rejects_an_unknown_method():
    with pytest.raises(ValueError, match="Method must be"):
        utils.convert_station_data_to_dataframe(CITIES, "nope")


def _cities_with_coordinate(bad):
    return [
        {
            "cityName": "X",
            "stateID": "S",
            "stationsInCity": [
                {"id": "bad-lat", "latitude": bad, "longitude": 77.0},
                {"id": "bad-lon", "latitude": 28.0, "longitude": bad},
                {"id": "ok", "latitude": 28.0, "longitude": 77.0},
            ],
        }
    ]


NOT_FINITE = ["inf", "-Infinity", "nan", math.inf, math.nan]


@pytest.mark.parametrize("bad", NOT_FINITE)
def test_coordinates_dataframe_skips_coordinates_that_are_not_finite(bad):
    df = utils.stations_to_coordinates_dataframe(_cities_with_coordinate(bad))

    assert df["station_id"].tolist() == ["ok"]


@pytest.mark.parametrize("bad", NOT_FINITE)
def test_iter_station_coords_skips_coordinates_that_are_not_finite(bad):
    rows = utils.iter_station_coords(_cities_with_coordinate(bad))

    assert [s["id"] for s, _, _ in rows] == ["ok"]


def test_stations_to_dataframe_of_no_cities_has_every_column():
    assert list(utils.stations_to_dataframe([]).columns) == [
        "city_name",
        "city_id",
        "state_id",
        "station_id",
        "station_name",
        "longitude",
        "latitude",
        "live",
        "avg_aqi",
        "status",
        "aqi_category",
    ]


def test_analyze_station_data():
    result = utils.analyze_station_data(CITIES)

    assert (result["total_cities"], result["total_stations"]) == (3, 4)
    assert (result["live_stations"], result["offline_stations"]) == (2, 2)
    assert result["states"] == 2  # Goa has no stations, so no row
    assert result["unique_states"] == ["Delhi", "Maharashtra"]
    assert result["stations_with_aqi_data"] == 3
    assert (result["min_aqi"], result["max_aqi"]) == (40, 450)
    assert result["avg_aqi_overall"] == pytest.approx(610 / 3)
    assert result["aqi_categories"] == {
        "Moderate": 1,
        "Good": 1,
        "No Data": 1,
        "Severe": 1,
    }
    assert result["stations_per_city"]["max"] == 3


def test_analyze_station_data_of_no_stations():
    assert utils.analyze_station_data([])["total_stations"] == 0


@pytest.mark.parametrize(
    "verbose,level", [(True, logging.INFO), (False, logging.DEBUG)]
)
def test_log_if_verbose(caplog, verbose, level):
    with caplog.at_level(logging.DEBUG, logger="vayuayan.utils"):
        utils._log_if_verbose("note", verbose)

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [(level, "note")]


def test_safe_get_sends_the_default_headers(network):
    network.on("get", URL, http_response(b"ok"))

    response = utils.safe_get(URL, timeout=5)

    assert response.content == b"ok"
    assert "User-Agent" in network.calls[0].kwargs["headers"]
    assert network.calls[0].kwargs["timeout"] == 5


def test_safe_get_can_skip_certificate_checks(network):
    network.on("get", URL, http_response(b"ok"))

    utils.safe_get(URL, verify_ssl=False)

    assert network.calls[0].kwargs["verify"] is False


@pytest.mark.parametrize(
    "failure,attempts,reason",
    [
        (http_response(status=404), 1, "404"),
        (http_response(status=503), 3, "503"),
        (requests.ConnectionError("down"), 3, "ConnectionError"),
    ],
)
def test_safe_get_failure(network, failure, attempts, reason):
    network.on("get", URL, failure)

    with pytest.raises(NetworkError, match=reason):
        utils.safe_get(URL, max_retries=2)
    assert len(network.calls) == attempts


def test_safe_post_decodes_the_base64_reply(network):
    network.on("post", URL, http_response(b64_body({"ok": True})))

    reply = utils.safe_post(URL, {"h": "1"}, "payload", cookies={"c": "1"})

    assert reply == {"ok": True}
    call = network.calls[0]
    assert (call.kwargs["data"], call.kwargs["cookies"]) == ("payload", {"c": "1"})


def test_safe_post_retries_with_its_backoff(network):
    network.on("post", URL, http_response(status=500), http_response(b64_body({})))

    assert utils.safe_post(URL, {"h": "1"}, "", max_retries=1, backoff_factor=0.5) == {}
    assert network.sleeps == [0.5]


def test_safe_post_failure_is_a_network_error(network):
    network.on("post", URL, http_response(status=404))

    with pytest.raises(NetworkError, match="404"):
        utils.safe_post(URL, {"h": "1"}, "")


@pytest.mark.parametrize("body", [b"", b"not base64!", b"bm90IGpzb24="])
def test_safe_post_garbage_is_a_processing_error(network, body):
    network.on("post", URL, http_response(body))

    with pytest.raises(DataProcessingError):
        utils.safe_post(URL, {"h": "1"}, "")


@pytest.mark.parametrize(
    "url,headers,cookies,message",
    [
        ("", {"h": "1"}, None, "URL"),
        (None, {"h": "1"}, None, "URL"),
        (URL, {}, None, "Headers"),
        (URL, "h", None, "Headers"),
        (URL, {"h": "1"}, "c", "Cookies"),
    ],
)
def test_safe_post_validates_its_arguments(url, headers, cookies, message):
    with pytest.raises(ValueError, match=message):
        utils.safe_post(url, headers, "", cookies=cookies)


def test_decode_b64_json_response():
    assert utils.decode_b64_json_response(http_response(b64_body([1, 2]))) == [1, 2]

    with pytest.raises(ValueError, match="empty"):
        utils.decode_b64_json_response(http_response(b""))
    with pytest.raises(ValueError):
        utils.decode_b64_json_response(http_response(b"bm90IGpzb24="))  # not JSON


def test_url_encode_round_trips():
    assert utils.decode_b64_json_response(
        http_response(utils.url_encode({"a": 1}).encode())
    ) == {"a": 1}


def test_nearest_stations_needs_coordinates():
    with_coords = pd.DataFrame({"id": ["a"], "lat": [1.0], "lon": [2.0]})

    with pytest.raises(ValueError, match="lat and lon"):
        utils.nearest_stations(pd.DataFrame({"id": ["a"]}), with_coords)


def test_rss_station_with_na_last_update_is_not_live():
    feed = {
        "country": [
            {
                "stateId": "Tripura",
                "citiesInState": [
                    {
                        "cityId": "Agartala",
                        "stationsInCity": [
                            {
                                "siteId": "site_1",
                                "stationName": "A",
                                "lastUpdate": "NA",
                                "airQualityIndexValue": "NA",
                            },
                            {
                                "siteId": "site_2",
                                "stationName": "B",
                                "lastUpdate": "09-11-2026 09:00:00",
                            },
                        ],
                    }
                ],
            }
        ]
    }

    stations = utils.parse_cpcb_rss_station_data(feed)[0]["stationsInCity"]
    by_id = {s["id"]: s for s in stations}

    assert by_id["site_1"]["live"] is False
    assert by_id["site_1"]["lastUpdate"] == ""
    assert by_id["site_2"]["live"] is True
