"""What the CPCB clients do when an endpoint is gone, broken or down."""

import pytest
import requests

from vayuayan import CPCBHistorical, CPCBLive, cpcb_common
from vayuayan.constants import CPCB_CREDENTIAL_ENV
from vayuayan.exceptions import (
    AuthenticationError,
    DataNotFoundError,
    NetworkError,
    StationNotFoundError,
)

from .cpcb_urls import (
    DASHBOARD_PARAMETERS,
    DASHBOARD_STATIONS,
    DOWNLOAD_FILE,
    DOWNLOAD_LINK,
    FILE_PATH,
    FILES,
    LEGACY_FILE_PATH,
    LEGACY_STATION_LIST,
    OAUTH,
    RSS,
    RSS_FEED,
)
from .fakes import b64_body, http_response

STATION_ARGS = ("site_301", "", "", "Delhi", "2024", "hourly", "stationLevel")
GONE = [
    pytest.param(http_response(status=404), id="404"),
    pytest.param(http_response(status=500), id="500"),
    pytest.param(http_response(status=503), id="503"),
    pytest.param(requests.ConnectionError("down"), id="connection"),
    pytest.param(requests.Timeout("slow"), id="timeout"),
]
GARBAGE = [
    pytest.param(http_response(b"<html>maintenance</html>"), id="html"),
    pytest.param(http_response(b""), id="empty"),
]


@pytest.mark.parametrize("failure", GONE)
def test_file_path_falls_back_to_legacy_when_the_new_route_fails(network, failure):
    network.on("post", FILE_PATH, failure)
    network.on("post", LEGACY_FILE_PATH, http_response(b64_body(FILES)))

    assert CPCBHistorical().get_file_path(*STATION_ARGS) == FILES["data"]
    # The new route is not retried: the legacy route is the retry
    assert network.urls() == [FILE_PATH, LEGACY_FILE_PATH]


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(b"", status=204), id="204-no-body"),
        pytest.param(http_response(json_data={"status": "failed"}), id="failed"),
        pytest.param(http_response(b"{not json"), id="malformed-json"),
        pytest.param(http_response(json_data=[1, 2]), id="json-not-an-object"),
        pytest.param(
            http_response(json_data={"status": "success", "data": "x"}),
            id="data-not-a-list",
        ),
    ],
)
def test_file_path_tries_legacy_when_the_new_route_has_no_usable_answer(network, reply):
    network.on("post", FILE_PATH, reply)
    network.on("post", LEGACY_FILE_PATH, http_response(b64_body(FILES)))

    assert CPCBHistorical().get_file_path(*STATION_ARGS) == FILES["data"]


@pytest.mark.parametrize("failure", GONE)
def test_file_path_raises_network_error_when_no_route_answers(network, failure):
    network.on("post", FILE_PATH, failure)
    network.on("post", LEGACY_FILE_PATH, failure)

    with pytest.raises(NetworkError):
        CPCBHistorical().get_file_path(*STATION_ARGS)


@pytest.mark.parametrize("garbage", GARBAGE)
def test_file_path_raises_network_error_when_both_routes_send_garbage(network, garbage):
    network.on("post", FILE_PATH, http_response(status=500))
    network.on("post", LEGACY_FILE_PATH, garbage)

    with pytest.raises(NetworkError):
        CPCBHistorical().get_file_path(*STATION_ARGS)


def test_file_path_failed_reply_and_a_down_legacy_route_raise(network):
    network.on("post", FILE_PATH, http_response(json_data={"status": "failed"}))
    network.on("post", LEGACY_FILE_PATH, http_response(status=500))

    with pytest.raises(NetworkError):
        CPCBHistorical().get_file_path(*STATION_ARGS)


def test_file_path_empty_204_and_a_down_legacy_route_is_no_files(network):
    network.on("post", FILE_PATH, http_response(b"", status=204))
    network.on("post", LEGACY_FILE_PATH, http_response(status=500))

    assert CPCBHistorical().get_file_path(*STATION_ARGS) == []


def test_file_path_keeps_only_object_entries(network):
    data = {"status": "success", "data": [{"filepath": "/x"}, "junk", 3]}
    network.on("post", FILE_PATH, http_response(json_data=data))

    assert CPCBHistorical().get_file_path(*STATION_ARGS) == [{"filepath": "/x"}]


@pytest.mark.parametrize(
    "failure,attempts,error",
    [
        pytest.param(
            http_response(status=404), 1, DataNotFoundError, id="404-not-retried"
        ),
        pytest.param(http_response(status=500), 4, NetworkError, id="500-retried"),
        pytest.param(
            requests.ConnectionError("down"), 4, NetworkError, id="connection-retried"
        ),
    ],
)
def test_download_link_failure_raises_after_the_retries(
    network, failure, attempts, error
):
    network.on("get", DOWNLOAD_LINK, failure)

    with pytest.raises(error):
        CPCBHistorical(use_cache=False)._download_repository_file("/AQI/2024/x.xlsx")
    assert len(network.calls) == attempts


@pytest.mark.parametrize(
    "failure,error",
    [
        (http_response(status=404), DataNotFoundError),
        (http_response(status=502), NetworkError),
    ],
    ids=["404", "502"],
)
def test_failed_file_download_is_not_cached(network, tmp_path, failure, error):
    network.on("get", DOWNLOAD_LINK, http_response(b"token"))
    network.on("get", DOWNLOAD_FILE, failure)
    client = CPCBHistorical(cache_dir=str(tmp_path))

    with pytest.raises(error):
        client._download_repository_file("/AQI/2020/x.csv")
    assert not list(tmp_path.rglob("*.csv"))


def test_unusable_download_is_not_kept_in_the_cache(network, tmp_path):
    network.on("get", DOWNLOAD_LINK, http_response(b"token"))
    network.on("get", DOWNLOAD_FILE, http_response(b""), http_response(b"Day\n1\n"))
    client = CPCBHistorical(cache_dir=str(tmp_path))

    with pytest.raises(NetworkError, match="no usable file"):
        client._read_repository_csv("/AQI/2020/x.csv")

    assert client._read_repository_csv("/AQI/2020/x.csv")["Day"].tolist() == [1]


@pytest.mark.parametrize(
    "bad_file",
    [b"<html>Service Unavailable</html>", b'{"status":"failed"}', b"", b"  \n"],
    ids=["error-page", "json-error", "empty", "blank"],
)
def test_unusable_cached_file_is_downloaded_again(network, tmp_path, bad_file):
    client = CPCBHistorical(cache_dir=str(tmp_path))
    cached = client._cache_path("/AQI/2020/x.csv")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(bad_file)
    network.on("get", DOWNLOAD_LINK, http_response(b"token"))
    network.on("get", DOWNLOAD_FILE, http_response(b"Day\n1\n"))

    assert client._read_repository_csv("/AQI/2020/x.csv")["Day"].tolist() == [1]
    assert network.urls() == [DOWNLOAD_LINK, f"{DOWNLOAD_FILE}?file_name=token"]
    assert cached.read_bytes() == b"Day\n1\n"


def test_good_cached_file_is_read_without_a_request(network, tmp_path):
    client = CPCBHistorical(cache_dir=str(tmp_path))
    cached = client._cache_path("/AQI/2020/x.csv")
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"Day\n7\n")

    assert client._read_repository_csv("/AQI/2020/x.csv")["Day"].tolist() == [7]
    assert network.calls == []


@pytest.mark.parametrize("failure", GONE)
def test_station_list_falls_back_to_the_rss_feed(network, failure):
    network.on("post", DASHBOARD_STATIONS, failure)
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    cities = CPCBLive().get_all_india()

    assert cities[0]["stationsInCity"][0]["id"] == "site_1"


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(b64_body({"stations": []})), id="no-stations"),
        pytest.param(http_response(b64_body([1])), id="not-an-object"),
        pytest.param(http_response(b"@@not-base64"), id="not-base64"),
        pytest.param(http_response(b""), id="empty"),
    ],
)
def test_station_list_uses_rss_when_the_dashboard_answers_garbage(network, reply):
    network.on("post", DASHBOARD_STATIONS, reply)
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    assert CPCBLive().get_all_india()[0]["cityName"] == "Delhi"


def test_station_list_raises_when_dashboard_and_rss_are_down(network):
    network.on("post", DASHBOARD_STATIONS, http_response(status=500))
    network.on("get", RSS, http_response(status=500))

    with pytest.raises(NetworkError):
        CPCBLive().get_all_india()


def test_station_list_drops_entries_that_are_not_objects(network):
    reply = {"stations": [{"cityName": "A"}, "junk"]}
    network.on("post", DASHBOARD_STATIONS, http_response(b64_body(reply)))

    assert CPCBLive().get_all_india() == [{"cityName": "A"}]


@pytest.mark.parametrize("failure", GONE)
def test_live_parameters_fall_back_to_the_rss_reading(network, failure):
    network.on("post", DASHBOARD_PARAMETERS, failure)
    feed = {
        "country": [
            {
                "stateId": "Delhi",
                "citiesInState": [
                    {
                        "cityId": "Delhi",
                        "stationsInCity": [
                            {
                                "siteId": "site_1",
                                "stationName": "ITO",
                                "lastUpdate": "t",
                                "airQualityIndexValue": "70",
                                "pollutants": [{"indexId": "PM2.5", "avg": "40"}],
                            }
                        ],
                    }
                ],
            }
        ]
    }
    network.on("get", RSS, http_response(json_data=feed))

    data = CPCBLive().get_live_aqi_data_for_station("site_1", "d")

    assert data["station_name"] == "ITO"
    assert data["airQualityIndex"]["value"] == 70.0
    assert data["metrics"][0]["name"] == "PM2.5"


def test_live_parameters_raise_when_dashboard_and_rss_are_down(network):
    network.on("post", DASHBOARD_PARAMETERS, http_response(status=500))
    network.on("get", RSS, requests.ConnectionError("down"))

    with pytest.raises(NetworkError):
        CPCBLive().get_live_aqi_data_for_station("site_1", "d")


def test_live_parameters_raise_when_the_feed_lacks_the_station(network):
    network.on("post", DASHBOARD_PARAMETERS, http_response(status=500))
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    with pytest.raises(StationNotFoundError):
        CPCBLive().get_live_aqi_data_for_station("site_404", "d")


def test_legacy_post_is_not_retried_but_get_is(network):
    network.on("post", DASHBOARD_STATIONS, http_response(status=503))

    with pytest.raises(requests.HTTPError):
        cpcb_common.legacy_post(DASHBOARD_STATIONS, {})

    assert len(network.calls) == 1


def test_broken_certificate_is_resent_without_verification(network):
    network.on(
        "post",
        DASHBOARD_STATIONS,
        requests.exceptions.SSLError("bad cert"),
        http_response(b64_body({"ok": 1})),
    )

    assert cpcb_common.legacy_post(DASHBOARD_STATIONS, {}) == {"ok": 1}
    assert [c.kwargs["verify"] for c in network.calls] == [True, False]


@pytest.mark.parametrize("failure", GONE)
def test_rss_failure_gives_no_cities_and_is_tried_once(network, failure):
    network.on("get", RSS, failure)
    client = CPCBLive()

    assert client._rss_cities() == []
    attempts = len(network.calls)
    assert client._rss_cities() == []
    assert len(network.calls) == attempts


@pytest.mark.parametrize("body", [b"<html>", b"[]", b"null", b'"down"'])
def test_rss_answer_that_is_not_a_feed_gives_no_cities(network, body):
    network.on("get", RSS, http_response(body))

    assert CPCBLive()._rss_cities() == []


def test_complete_list_uses_the_rss_feed_first(network):
    network.on("get", RSS, http_response(json_data=RSS_FEED))

    dropdown = CPCBHistorical().get_complete_list()

    assert dropdown["stations"] == {"Delhi": [{"label": "ITO", "value": "site_1"}]}


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(status=500), id="500"),
        pytest.param(http_response(b"garbage"), id="not-base64"),
        pytest.param(http_response(b64_body([1])), id="not-an-object"),
        pytest.param(http_response(b64_body({"status": "failed"})), id="failed"),
        pytest.param(
            http_response(b64_body({"status": "success", "dropdown": "x"})),
            id="dropdown-not-an-object",
        ),
    ],
)
def test_complete_list_is_empty_when_no_source_answers(network, reply):
    network.on("get", RSS, http_response(status=500))
    network.on("post", LEGACY_STATION_LIST, reply)

    assert CPCBHistorical().get_complete_list() == {}


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(http_response(status=401), id="401"),
        pytest.param(http_response(status=500), id="500"),
        pytest.param(requests.ConnectionError("down"), id="connection"),
        pytest.param(http_response(b"<html>"), id="malformed"),
        pytest.param(http_response(json_data={}), id="no-token"),
        pytest.param(http_response(b"[]"), id="json-not-an-object"),
    ],
)
def test_token_failure_is_an_authentication_error_without_the_url(
    network, monkeypatch, reply
):
    for var in CPCB_CREDENTIAL_ENV.values():
        monkeypatch.setenv(var, "secret-value")
    network.on("post", OAUTH, reply)

    with pytest.raises(AuthenticationError) as error:
        CPCBHistorical()._get_access_token()

    assert "secret-value" not in str(error.value)
    assert OAUTH not in str(error.value)


def test_token_failure_switches_the_directory_to_the_snapshot(
    network, cpcb_credentials
):
    network.on("post", OAUTH, http_response(status=401))
    client = CPCBHistorical()

    assert len(client._new_state_list()) == 36
    assert client._live_directory is False
    # the snapshot answers later calls with no token request
    assert client._new_city_list("ST-10")[0]["city_name"] == "Delhi"
    assert len(network.calls) == 1
