"""
Constants for CPCB data fetching.

This module contains URL endpoints, headers, timeouts, and other configuration
constants used throughout the vayuayan package.
"""

from typing import Dict, List

# Base URLs
BASE_URL = "https://airquality.cpcb.gov.in"
RSS_URL = f"{BASE_URL}/caaqms/rss_feed"
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

POST_HEADERS: Dict[str, str] = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": BASE_URL,
}

# Date Parsing Formats
DATE_FORMATS: List[str] = [
    "%B %d, %Y",  # May 27, 2025
    "%b %d, %Y",  # May 27, 2025
    "%d %B %Y",  # 27 May 2025
    "%d %b %Y",  # 27 May 2025
    "%d-%m-%Y",  # 27-05-2025
    "%d/%m/%Y",  # 27/05/2025
    "%m/%d/%Y",  # 05/27/2025
    "%Y-%m-%d",  # 2025-05-27
    "%d-%m-%y",  # 27-05-25
    "%d/%m/%y",  # 27/05/25
    "%d %b %y",  # 27 May 25
    "%b %d %Y",  # May 27 2025
]

# Month Abbreviations Mapping
MONTH_ABBREV: Dict[str, str] = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}

# Full Month Names
MONTHS: List[str] = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# AQI Category Thresholds
AQI_CATEGORIES: Dict[str, Dict[str, int]] = {
    "Good": {"min": 0, "max": 50},
    "Satisfactory": {"min": 51, "max": 100},
    "Moderate": {"min": 101, "max": 200},
    "Poor": {"min": 201, "max": 300},
    "Very Poor": {"min": 301, "max": 400},
    "Severe": {"min": 401, "max": 500},
}

# File Extensions
SUPPORTED_FILE_EXTENSIONS: List[str] = [".csv", ".xlsx", ".xls", ".json"]

# Default File Paths
DEFAULT_DOWNLOAD_DIR: str = "downloads"
DEFAULT_CONFIG_DIR: str = ".vayuayan"
