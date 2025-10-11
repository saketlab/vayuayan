"""
Vayuayan - Comprehensive Air Quality Data Analysis Package.

Vayuayan (वायुअयन) meaning "path of the wind" in Sanskrit, is a comprehensive
Python package for fetching and analyzing air quality data from multiple sources.

Main Classes:
    - CPCBClient: Low-level client for CPCB web services
    - CPCBHistorical: Historical air quality data client
    - CPCBLive: Live air quality monitoring client
    - PM25Client: Satellite PM2.5 data processing client

Usage:
    >>> from vayuayan import CPCBHistorical, CPCBLive
    >>> historical = CPCBHistorical()
    >>> states = historical.get_state_list()
    >>> live = CPCBLive()
    >>> location = live.get_system_location()
"""

__version__ = "0.1.0"
__author__ = "Saket Choudhary"
__email__ = "saketc@iitb.ac.in"
__description__ = "Vayuayan - Comprehensive Python package for fetching and analyzing air quality data from multiple sources including CPCB India"
__url__ = "https://github.com/saketkc/vayuayan"

# Import main client classes
from .air_quality_client import CPCBHistorical, CPCBLive, PM25Client
from .client import CPCBClient

# Import exceptions for convenience
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

# Import utility functions that might be useful for users
from .utils import (
    analyze_station_data,
    clean_station_name,
    convert_station_data_to_dataframe,
    get_aqi_category,
    haversine_distance,
    stations_to_dataframe,
)

# Define what gets exported when using "from vayuayan import *"
__all__ = [
    # Main client classes
    "CPCBClient",
    "CPCBHistorical",
    "CPCBLive",
    "PM25Client",
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
    """Get comprehensive package information.

    Returns:
        Dictionary containing package metadata.
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
