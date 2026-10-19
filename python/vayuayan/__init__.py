"""
Vayuayan: air quality data for India.

Vayuayan (वायुअयन) is Sanskrit for "path of the wind". This Python package gets
air quality data from many sources and analyzes the data.

Main Classes:
    - CPCBClient: Legacy client for CPCB web services
    - CPCBHistorical: Client for historical air quality data
    - CPCBLive: Client for live air quality data
    - PM25Client: Client for satellite PM2.5 data

National AQI and tidy data:
    - compute_aqi, sub_index: CPCB National AQI from concentrations
    - daily_aqi: daily AQI of stations from tidy (long) data
    - cpcb_raw_to_long: raw CPCB station data to tidy rows (TIDY_COLUMNS)

Usage:
    >>> from vayuayan import CPCBHistorical, CPCBLive
    >>> historical = CPCBHistorical()
    >>> states = historical.get_state_list()
    >>> live = CPCBLive()
    >>> location = live.get_system_location()
"""

__version__ = "0.3.0"
__author__ = "Saket Choudhary"
__email__ = "saketc@iitb.ac.in"
__description__ = (
    "Vayuayan - Comprehensive Python package for fetching and analyzing "
    "air quality data from multiple sources including CPCB India"
)
__url__ = "https://github.com/saketlab/vayuayan"

# Client classes
from .aqi import (
    HEALTH_IMPACTS,
    WHO_PM25_GUIDELINES,
    AQIResult,
    compute_aqi,
    daily_aqi,
    health_impact,
    pollutant_category,
    pollutant_name,
    sub_index,
)
from .client import CPCBClient

# Configuration functions
from .constants import get_cache_dir, get_config_dir, get_gee_project_file
from .cpcb_historical import CPCBHistorical
from .cpcb_live import CPCBLive

# Exceptions
from .exceptions import (
    AuthenticationError,
    CityNotFoundError,
    ConfigurationError,
    CPCBError,
    DataNotFoundError,
    DataParsingError,
    DataProcessingError,
    InvalidDataError,
    NetworkError,
    RateLimitError,
    StationNotFoundError,
)
from .gee import setup_earth_engine
from .geo import india_boundary
from .oaq import OAQClient, oaq_city_tally, oaq_nearest_cpcb
from .oaq_plots import (
    plot_daily_record_day,
    plot_daily_record_difference,
    plot_daily_record_scatter,
    plot_daily_record_series,
    plot_daily_record_share,
    plot_daily_record_timeline,
)
from .oaq_records import compare_daily_records, daily_record_summary
from .pm25 import PM25Client
from .sensor_qa import (
    EPA_PM25_TARGETS,
    collocated_precision,
    peer_ratio,
    ratio_by_humidity,
    readings_mean,
    sensor_accuracy,
    sensor_completeness,
    sensor_plausibility,
)
from .tidy import (
    TIDY_COLUMNS,
    cpcb_raw_to_long,
    cpcb_tidy_daily,
    daily_aqi_workbook_to_long,
    live_metrics,
    live_to_long,
)

# Utility functions for users
from .utils import (
    analyze_station_data,
    clean_station_name,
    convert_station_data_to_dataframe,
    get_aqi_categories,
    get_aqi_category,
    haversine_distance,
    nearest_stations,
    stations_to_city_summary,
    stations_to_dataframe,
)

# Names that "from vayuayan import *" exports
__all__ = [
    # Client classes
    "CPCBClient",
    "CPCBHistorical",
    "CPCBLive",
    "PM25Client",
    "OAQClient",
    "oaq_nearest_cpcb",
    "oaq_city_tally",
    "compare_daily_records",
    "daily_record_summary",
    "plot_daily_record_day",
    "plot_daily_record_timeline",
    "plot_daily_record_scatter",
    "plot_daily_record_share",
    "plot_daily_record_series",
    "plot_daily_record_difference",
    # National AQI and tidy data
    "AQIResult",
    "compute_aqi",
    "sub_index",
    "pollutant_name",
    "daily_aqi",
    "health_impact",
    "pollutant_category",
    "HEALTH_IMPACTS",
    "WHO_PM25_GUIDELINES",
    "TIDY_COLUMNS",
    "live_to_long",
    "live_metrics",
    "cpcb_raw_to_long",
    "daily_aqi_workbook_to_long",
    "cpcb_tidy_daily",
    "india_boundary",
    # Sensor quality
    "EPA_PM25_TARGETS",
    "readings_mean",
    "sensor_completeness",
    "sensor_plausibility",
    "collocated_precision",
    "peer_ratio",
    "sensor_accuracy",
    "ratio_by_humidity",
    # Setup functions
    "setup_earth_engine",
    "get_config_dir",
    "get_cache_dir",
    "get_gee_project_file",
    # Exceptions
    "CPCBError",
    "NetworkError",
    "DataNotFoundError",
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
    "get_aqi_categories",
    "nearest_stations",
    "stations_to_city_summary",
    "haversine_distance",
]
