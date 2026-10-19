"""Fixtures that several test files share."""

import os

import pytest

from vayuayan.constants import CPCB_CREDENTIAL_ENV

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
def cpcb_credentials(monkeypatch):
    """Set fake CPCB credentials, so the clients use the live directory."""
    for var in CPCB_CREDENTIAL_ENV.values():
        monkeypatch.setenv(var, "x")
