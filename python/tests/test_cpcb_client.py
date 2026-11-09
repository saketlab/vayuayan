"""The legacy CPCBClient."""

from __future__ import annotations

import pandas as pd
import pytest
import requests

from vayuayan.client import CPCBClient
from vayuayan.cpcb_live import CPCBLive
from vayuayan.exceptions import CPCBError, NetworkError

from .cpcb_urls import LEGACY_DOWNLOAD
from .fakes import http_response

CITIES = [
    {
        "cityName": "Zeta",
        "cityID": "Z",
        "stateID": "S2",
        "stationsInCity": [
            {
                "id": "z_off",
                "name": "Z off",
                "live": False,
                "latitude": 10.0,
                "longitude": 70.0,
                "avg": "",
            },
        ],
    },
    {
        "cityName": "Alpha",
        "cityID": "A",
        "stateID": "S1",
        "stationsInCity": [
            {
                "id": "a_on",
                "name": "A on",
                "live": True,
                "latitude": 20.0,
                "longitude": 75.0,
                "avg": "150",
            },
            {
                "id": None,
                "name": "No id",
                "live": True,
                "latitude": 20.0,
                "longitude": 75.0,
            },
        ],
    },
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(CPCBLive, "get_all_india", lambda self: CITIES)
    return CPCBClient()


def test_list_stations_is_sorted_with_live_cities_first(client):
    stations = client.list_stations()

    assert [city["cityName"] for city in stations] == ["Alpha", "Zeta"]


def test_list_stations_as_dataframe(client):
    df = client.list_stations(as_dataframe=True)

    assert isinstance(df, pd.DataFrame)
    assert df["station_name"].tolist()[0] == "A on"
    assert len(df) == 3


def test_list_stations_propagates_a_source_failure(monkeypatch):
    def down(self):
        raise NetworkError("down")

    monkeypatch.setattr(CPCBLive, "get_all_india", down)

    with pytest.raises(CPCBError):
        CPCBClient().list_stations()


def test_nearest_station(client):
    assert client.get_nearest_station(19.9, 75.0) == "a_on"


def test_nearest_station_with_distance_skips_stations_without_an_id(client):
    station, distance = client.get_nearest_station(20.0, 75.0, return_distance=True)

    assert station == "a_on"
    assert distance == pytest.approx(0.0)


def test_nearest_station_needs_a_station(monkeypatch):
    monkeypatch.setattr(
        CPCBLive,
        "get_all_india",
        lambda self: [{"stationsInCity": [{"name": "no coordinates"}]}],
    )

    with pytest.raises(CPCBError, match="No valid stations"):
        CPCBClient().get_nearest_station(1.0, 2.0)


def test_k_nearest_stations_are_sorted_by_distance(client):
    nearest = client.get_k_nearest_stations(10.0, 70.0, k=2)

    assert nearest[0][0]["id"] == "z_off"
    assert nearest[0][1] == pytest.approx(0.0)
    assert nearest[0][1] < nearest[1][1]
    assert len(nearest) == 2


def test_nearest_station_within_radius(client):
    station, distance = client.get_nearest_station_within_radius(
        20.0, 75.0, max_distance_km=5
    )

    assert station == "a_on"
    assert distance == pytest.approx(0.0)
    assert client.get_nearest_station_within_radius(0.0, 0.0, 5) is None


@pytest.mark.parametrize(
    "url,site,name,period,year,custom,expected",
    [
        ("https://x/a/b.csv?t=1", None, None, None, "2024", None, "b_2024.csv"),
        ("https://x/a/data", None, None, None, "2024", None, "data_2024.csv"),
        ("https://x/a/c_2024.csv", None, None, None, "2024", None, "c_2024.csv"),
        (None, "S1", "Name", "15Min", "2024", None, "S1_Name_15Min_2024.csv"),
        (None, None, None, None, "2024", "my.csv", "my_2024.csv"),
        (None, None, None, None, "2024", "noext", "noext.csv"),
    ],
)
def test_generate_filename(url, site, name, period, year, custom, expected):
    assert (
        CPCBClient()._generate_filename(url, site, name, period, year, custom)
        == expected
    )


def test_filename_of_a_direct_url_without_a_year_is_unchanged():
    name = CPCBClient()._generate_filename(
        "https://x/Delhi_Punjabi_Bagh_2024.csv", None, None, None, "", None
    )

    assert name == "Delhi_Punjabi_Bagh_2024.csv"


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"site_id": "S1"},
        {"site_id": "S1", "station_name": "N", "time_period": "15Min"},
        {"site_id": "S1", "station_name": "N", "time_period": None, "year": "2024"},
    ],
)
def test_download_needs_a_url_or_every_part(kwargs):
    with pytest.raises(CPCBError, match="must be provided"):
        CPCBClient().download_raw_data(**kwargs)


def test_download_saves_the_body(network, tmp_path):
    network.on(
        "get",
        LEGACY_DOWNLOAD,
        http_response(b"a,b\n1,2\n", headers={"content-type": "text/csv"}),
    )

    path = CPCBClient().download_raw_data(
        f"{LEGACY_DOWNLOAD}?file_name=Raw_data/x.csv",
        year="2024",
        output_dir=str(tmp_path / "new"),
    )

    assert path == str(tmp_path / "new" / "x_2024.csv")
    assert (tmp_path / "new" / "x_2024.csv").read_bytes() == b"a,b\n1,2\n"
    assert network.calls[0].kwargs["timeout"] == 60


def test_download_returns_a_dataframe(network, tmp_path):
    network.on(
        "get",
        LEGACY_DOWNLOAD,
        http_response(
            b"a,b\n1,2\n", headers={"content-type": "application/octet-stream"}
        ),
    )

    df = CPCBClient().download_raw_data(
        LEGACY_DOWNLOAD, year="2024", output_dir=str(tmp_path), return_dataframe=True
    )

    assert df.to_dict("records") == [{"a": 1, "b": 2}]


def test_download_of_an_unparsable_body_keeps_the_file_and_returns_none(
    network, tmp_path
):
    network.on(
        "get",
        LEGACY_DOWNLOAD,
        http_response(b"", headers={"content-type": "text/html"}),
    )

    result = CPCBClient().download_raw_data(
        LEGACY_DOWNLOAD,
        year="2024",
        output_dir=str(tmp_path),
        return_dataframe=True,
        verbose=True,
    )

    assert result is None
    assert (tmp_path / "download_file_2024.csv").exists()


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(http_response(status=404), id="404"),
        pytest.param(http_response(status=500), id="500"),
        pytest.param(requests.ConnectionError("down"), id="connection"),
    ],
)
def test_download_failure_is_a_network_error(network, tmp_path, failure):
    network.on("get", LEGACY_DOWNLOAD, failure)

    with pytest.raises(NetworkError):
        CPCBClient().download_raw_data(
            LEGACY_DOWNLOAD, year="2024", output_dir=str(tmp_path)
        )
    assert list(tmp_path.iterdir()) == []


def test_unwritable_output_is_a_cpcb_error(network, tmp_path):
    network.on("get", LEGACY_DOWNLOAD, http_response(b"a\n1\n"))
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("x")

    with pytest.raises(CPCBError, match="Failed to download CSV"):
        CPCBClient().download_raw_data(
            LEGACY_DOWNLOAD, year="2024", output_dir=str(not_a_folder)
        )
