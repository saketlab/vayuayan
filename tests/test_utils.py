"""Tests for pure utility functions (no network/IO)."""

import numpy as np
import pytest

from vayuayan.utils import (
    clean_station_name,
    get_aqi_category,
    haversine_distance,
    parse_cpcb_rss_station_data,
    sort_station_data,
    station_data_to_dropdown,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "Dr. Karni Singh Shooting Range, Delhi - DPCC",
            "Dr_Karni_Singh_Shooting_Range_Delhi_DPCC",
        ),
        ("ITO, Delhi - DPCC", "ITO_Delhi_DPCC"),
        ("  spaced   out  ", "spaced_out"),
        ("", ""),
        ("!!!", ""),
    ],
)
def test_clean_station_name(raw, expected):
    assert clean_station_name(raw) == expected


def test_clean_station_name_non_string():
    assert clean_station_name(None) == ""  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value,category",
    [
        (0, "Good"),
        (50, "Good"),
        (51, "Satisfactory"),
        (100, "Satisfactory"),
        (200, "Moderate"),
        (300, "Poor"),
        (400, "Very Poor"),
        (401, "Severe"),
        (9999, "Severe"),
    ],
)
def test_get_aqi_category(value, category):
    assert get_aqi_category(value) == category


def test_get_aqi_category_nan():
    assert get_aqi_category(np.nan) == "No Data"


def test_haversine_zero_distance():
    assert haversine_distance(19.07, 72.87, 19.07, 72.87) == pytest.approx(0.0)


def test_haversine_known_distance():
    # Mumbai to Delhi is approximately 1150 km. Permit a large tolerance.
    d = haversine_distance(19.0760, 72.8777, 28.7041, 77.1025)
    assert 1100 < d < 1200


def test_haversine_symmetric():
    a = haversine_distance(0, 0, 10, 10)
    b = haversine_distance(10, 10, 0, 0)
    assert a == pytest.approx(b)


def test_sort_station_data_live_first():
    data = [
        {
            "cityName": "Delhi",
            "stationsInCity": [
                {"name": "B", "live": False},
                {"name": "A", "live": True},
            ],
        }
    ]
    result = sort_station_data(data)
    names = [s["name"] for s in result[0]["stationsInCity"]]
    assert names == ["A", "B"]  # live station first


def test_parse_cpcb_rss_station_data_normalizes_live_feed():
    rss_data = {
        "country": [
            {
                "stateId": "Delhi",
                "citiesInState": [
                    {
                        "cityId": "Delhi",
                        "stationsInCity": [
                            {
                                "stationName": "ITO, Delhi - CPCB",
                                "siteId": "site_123",
                                "latitude": 28.63,
                                "longitude": 77.24,
                                "lastUpdate": "28-06-2026 12:00:00",
                                "pollutants": [
                                    {"indexId": "PM2.5", "avg": "42"},
                                ],
                                # the shape of the live feed in October 2026
                                "airQualityIndexValue": "88",
                                "predominantParameter": "PM2.5",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = parse_cpcb_rss_station_data(rss_data)

    assert result[0]["cityName"] == "Delhi"
    assert result[0]["stateID"] == "Delhi"
    station = result[0]["stationsInCity"][0]
    assert station["id"] == "site_123"
    assert station["name"] == "ITO, Delhi - CPCB"
    assert station["avg"] == "88"
    assert station["airQualityIndex"] == {"value": "88"}
    assert station["live"] is True
    assert station["pollutants"][0]["indexId"] == "PM2.5"


def test_station_data_to_dropdown_groups_by_state_and_city():
    station_data = [
        {
            "cityName": "Delhi",
            "stateID": "Delhi",
            "stationsInCity": [
                {"id": "site_123", "name": "ITO, Delhi - CPCB"},
            ],
        }
    ]

    dropdown = station_data_to_dropdown(station_data)

    assert dropdown["cities"] == {"Delhi": [{"label": "Delhi", "value": "Delhi"}]}
    assert dropdown["stations"] == {
        "Delhi": [{"label": "ITO, Delhi - CPCB", "value": "site_123"}]
    }
