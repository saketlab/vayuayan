"""
Constants of the vayuayan package.

The constants are URL endpoints, headers, timeouts, and other configuration
values.
"""

import os
import platform
from pathlib import Path
from typing import Dict, Optional, Tuple

# Base URLs
BASE_URL = "https://airquality.cpcb.gov.in"
RSS_URL_WITH_COORDINATES = f"{BASE_URL}/caaqms/iit_rss_feed_with_coordinates"

# API Endpoints
DOWNLOAD_URL = f"{BASE_URL}/dataRepository/download_file?file_name=Raw_data"
ALL_STATION_URL = f"{BASE_URL}/aqi_dashboard/aqi_station_all_india"
ALL_PARAMETERS_URL = f"{BASE_URL}/aqi_dashboard/aqi_all_Parameters"

# Request Configuration
DEFAULT_TIMEOUT: int = 10
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_BACKOFF_FACTOR: float = 1.0

# HTTP Headers
DEFAULT_HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}

# Headers and cookie of the old base64 form endpoints (dataRepository, dashboard)
LEGACY_FORM_HEADERS: Dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "q=0.8;application/json;q=0.9",
}
PUBLIC_COOKIES: Dict[str, str] = {"ccr_public": "A"}

# WUSTL ACAG satellite PM2.5 archive (anonymous S3 over HTTPS)
SATPM_BASE_URL = "https://satpmdata.s3.amazonaws.com/"

# The same form headers with a Referer instead of Accept; unused, kept for code
# that imports it
POST_HEADERS: Dict[str, str] = {
    "Content-Type": LEGACY_FORM_HEADERS["Content-Type"],
    "Referer": BASE_URL,
}

# AQI Category Thresholds
AQI_CATEGORIES: Dict[str, Dict[str, int]] = {
    "Good": {"min": 0, "max": 50},
    "Satisfactory": {"min": 51, "max": 100},
    "Moderate": {"min": 101, "max": 200},
    "Poor": {"min": 201, "max": 300},
    "Very Poor": {"min": 301, "max": 400},
    "Severe": {"min": 401, "max": 500},
}

# Default File Paths
DEFAULT_DOWNLOAD_DIR: str = "downloads"


def _user_dir(xdg_var: str, default: str, windows_parts: Tuple[str, ...]) -> Path:
    """The vayuayan folder in a per-user base directory of the platform."""
    home = Path.home()
    if platform.system() == "Windows":
        return home.joinpath("AppData", "Local", "vayuayan", *windows_parts)
    return Path(os.environ.get(xdg_var, home / default)) / "vayuayan"


def get_config_dir() -> Path:
    """Get the standard configuration directory of vayuayan.

    Returns:
        Path: Platform-specific config directory
            - Linux/macOS: ~/.config/vayuayan
            - Windows: ~/AppData/Local/vayuayan
    """
    config_dir = _user_dir("XDG_CONFIG_HOME", ".config", ())
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_cache_dir() -> Path:
    """Get the cache directory of vayuayan (not created here).

    Returns:
        Path: $VAYUAYAN_CACHE_DIR if it is set, else
            - Linux/macOS: $XDG_CACHE_HOME/vayuayan or ~/.cache/vayuayan
            - Windows: ~/AppData/Local/vayuayan/cache
    """
    if os.environ.get("VAYUAYAN_CACHE_DIR"):
        return Path(os.environ["VAYUAYAN_CACHE_DIR"])
    return _user_dir("XDG_CACHE_HOME", ".cache", ("cache",))


def get_gee_project_file() -> Path:
    """Get the path to the GEE project configuration file."""
    return get_config_dir() / "gee_project"


CPCB_CREDENTIAL_ENV = {
    "username": "CPCB_USERNAME",
    "password": "CPCB_PASSWORD",
    "client_id": "CPCB_CLIENT_ID",
    "client_secret": "CPCB_CLIENT_SECRET",
}


def get_cpcb_credentials() -> Optional[Dict[str, str]]:
    """Return CPCB OAuth credentials from the environment, or None if any is unset."""
    creds = {key: os.environ.get(var, "") for key, var in CPCB_CREDENTIAL_ENV.items()}
    return creds if all(creds.values()) else None
