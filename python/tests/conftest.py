"""Fixtures that several test files share."""

import os
import time

import pytest
import requests

from vayuayan import http_client
from vayuayan.constants import CPCB_CREDENTIAL_ENV

from .fakes import FakeNetwork

# Tk on Windows runners fails when figures are created; tests draw off screen
os.environ.setdefault("MPLBACKEND", "Agg")


@pytest.fixture(autouse=True)
def _no_cpcb_credentials(monkeypatch):
    """Real credentials in the environment would make tests call CPCB."""
    for var in CPCB_CREDENTIAL_ENV.values():
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _private_cache(monkeypatch, tmp_path):
    """Tests must not read or fill the user's download cache."""
    monkeypatch.setenv("VAYUAYAN_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def _small_netcdf_counts_as_cached(request, monkeypatch):
    """Test files are small; tests of the size rule ask for real_size_rule."""
    if "real_size_rule" not in request.fixturenames:
        monkeypatch.setattr("vayuayan.pm25.MIN_CACHED_BYTES", 0)


@pytest.fixture
def real_size_rule():
    """Keep the 1 MiB rule for cached NetCDF files."""


def _feed_down(timeout=30):
    raise requests.ConnectionError("no feed in tests")


@pytest.fixture(autouse=True)
def _no_live_rss_feed(request, monkeypatch):
    """The station catalogue reads the feed; tests must not reach the real one."""
    if "network" not in request.fixturenames:
        monkeypatch.setattr(
            "vayuayan.cpcb_common.fetch_cpcb_rss_station_data", _feed_down
        )


@pytest.fixture
def rss_feed(monkeypatch):
    """Call rss_feed(cities) to make the CPCB RSS feed return those cities."""

    def install(cities):
        monkeypatch.setattr(
            "vayuayan.cpcb_common.fetch_cpcb_rss_station_data",
            lambda timeout=30: cities,
        )

    return install


@pytest.fixture
def network(monkeypatch):
    """A FakeNetwork in place of requests; http_client and its retries stay real."""
    fake = FakeNetwork()
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: fake(method, url, **kwargs),
    )
    monkeypatch.setattr(http_client, "_INSECURE_HOSTS", set())
    monkeypatch.setattr(time, "sleep", fake.sleeps.append)
    return fake


@pytest.fixture
def cpcb_credentials(monkeypatch):
    """Set fake CPCB credentials, so the clients use the live directory."""
    for var in CPCB_CREDENTIAL_ENV.values():
        monkeypatch.setenv(var, "x")
