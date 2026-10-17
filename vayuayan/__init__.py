"""
Vayuayan: air quality data for India.

Vayuayan (वायुअयन) is Sanskrit for "path of the wind". This Python package gets
air quality data from many sources and analyzes the data.

Main Classes:
    - CPCBClient: Legacy client for CPCB web services
    - CPCBHistorical: Client for historical air quality data
    - CPCBLive: Client for live air quality data
    - PM25Client: Client for satellite PM2.5 data

Usage:
    >>> from vayuayan import CPCBHistorical, CPCBLive
    >>> historical = CPCBHistorical()
    >>> states = historical.get_state_list()
    >>> live = CPCBLive()
    >>> location = live.get_system_location()
"""

__version__ = "0.1.5"
__author__ = "Saket Choudhary"
__email__ = "saketc@iitb.ac.in"
__description__ = (
    "Vayuayan - Comprehensive Python package for fetching and analyzing "
    "air quality data from multiple sources including CPCB India"
)
__url__ = "https://github.com/saketlab/vayuayan"

# Client classes
from .air_quality_client import CPCBHistorical, CPCBLive, PM25Client, setup_earth_engine
from .client import CPCBClient

# Configuration functions
from .constants import get_config_dir, get_gee_project_file

# Exceptions
from .exceptions import (
    AuthenticationError,
    CityNotFoundError,
    ConfigurationError,
    CPCBError,
    DataParsingError,
    DataProcessingError,
    InvalidDataError,
    NetworkError,
    RateLimitError,
    StationNotFoundError,
)

# Utility functions for users
from .utils import (
    analyze_station_data,
    clean_station_name,
    convert_station_data_to_dataframe,
    get_aqi_category,
    haversine_distance,
    stations_to_dataframe,
)

# Names that "from vayuayan import *" exports
__all__ = [
    # Client classes
    "CPCBClient",
    "CPCBHistorical",
    "CPCBLive",
    "PM25Client",
    # Setup functions
    "setup_earth_engine",
    "get_config_dir",
    "get_gee_project_file",
    # Exceptions
    "CPCBError",
    "NetworkError",
    "DataParsingError",
    "DataProcessingError",
    "CityNotFoundError",
    "StationNotFoundError",
    "InvalidDataError",
    "AuthenticationError",
    "RateLimitError",
    "ConfigurationError",
    # Utility functions
    "clean_station_name",
    "stations_to_dataframe",
    "convert_station_data_to_dataframe",
    "analyze_station_data",
    "get_aqi_category",
    "haversine_distance",
]


def get_version() -> str:
    """Get the package version.

    Returns:
        Package version string.
    """
    return __version__


def get_package_info() -> dict:
    """Get the package information.

    Returns:
        Dictionary with the package metadata.
    """
    return {
        "name": "vayuayan",
        "version": __version__,
        "author": __author__,
        "email": __email__,
        "description": __description__,
        "url": __url__,
        "classes": [
            "CPCBClient - Low-level client for air quality web services",
            "CPCBHistorical - Historical air quality data analysis",
            "CPCBLive - Real-time air quality monitoring",
            "PM25Client - Satellite PM2.5 data processing and analysis",
        ],
        "key_features": [
            "Multi-source air quality data fetching",
            "Historical and real-time AQI monitoring",
            "Satellite PM2.5 data analysis with GeoJSON",
            "Geospatial station location services",
            "Automated data caching and processing",
            "Comprehensive CLI and Python API",
        ],
    }
