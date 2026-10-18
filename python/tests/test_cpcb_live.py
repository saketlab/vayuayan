"""Tests for CPCB live API fallback behavior."""

from vayuayan import CPCBLive

from .fakes import raise_connection_error

RSS_STATIONS = [
    {
        "cityName": "Agartala",
        "cityID": "Agartala",
        "stateID": "Tripura",
        "stationsInCity": [
            {
                "id": "site_5587",
                "name": "Bardowali, Agartala - Tripura SPCB",
                "latitude": 23.83,
                "longitude": 91.27,
                "live": True,
                "avg": "56",
                "lastUpdate": "28-06-2026 18:00:00",
                "airQualityIndex": {"value": "56"},
                "pollutants": [
                    {"indexId": "PM2.5", "avg": "40", "min": "17", "max": "65"},
                    {"indexId": "PM10", "avg": "56", "min": "24", "max": "102"},
                ],
            }
        ],
    }
]


def test_get_all_india_falls_back_to_rss(monkeypatch, rss_feed):
    client = CPCBLive()
    monkeypatch.setattr(client, "_make_request", raise_connection_error)
    rss_feed(RSS_STATIONS)

    assert client.get_all_india() == RSS_STATIONS


def test_get_live_aqi_data_for_station_falls_back_to_rss_metrics(monkeypatch, rss_feed):
    client = CPCBLive()
    monkeypatch.setattr(client, "_make_request", raise_connection_error)
    rss_feed(RSS_STATIONS)

    data = client.get_live_aqi_data_for_station("site_5587", "2026-06-28T12:00:00Z")

    assert data["station_id"] == "site_5587"
    assert data["station_name"] == "Bardowali, Agartala - Tripura SPCB"
    assert data["metrics"] == [
        {
            "name": "PM2.5",
            "avg": "40",
            "min": "17",
            "max": "65",
            "avgDesc": "28-06-2026 18:00:00",
        },
        {
            "name": "PM10",
            "avg": "56",
            "min": "24",
            "max": "102",
            "avgDesc": "28-06-2026 18:00:00",
        },
    ]
