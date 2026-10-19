"""
Vayuayan (वायुअयन) is Sanskrit for "path of the wind". This package downloads
and examines air quality data.

CPCBHistorical and CPCBLive read data from the CPCB monitoring stations in
India. OAQClient reads data from OAQ low-cost sensors. PM25Client reads WUSTL
ACAG satellite PM2.5 data. compute_aqi and daily_aqi calculate the CPCB
National AQI. compute_us_aqi calculates the US EPA AQI. The sensor_* functions
compare sensor data with the US EPA targets for PM2.5 sensors.

Usage:
    >>> from vayuayan import CPCBHistorical
    >>> states = CPCBHistorical().get_state_list()
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
from .plot_theme import set_theme
from .pm25 import PM25Client
from .sensor_plots import plot_sensor_vs_reference
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
from .us_aqi import (
    US_AQI_CATEGORIES,
    US_AQI_COLORS,
    US_AQI_COLORS_ASSIST,
    US_POLLUTANTS,
    compute_us_aqi,
    us_aqi_category,
    us_aqi_color,
    us_pollutant_name,
    us_sub_index,
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
    "plot_sensor_vs_reference",
    "set_theme",
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
    # US EPA AQI
    "compute_us_aqi",
    "us_sub_index",
    "us_pollutant_name",
    "us_aqi_category",
    "us_aqi_color",
    "US_AQI_CATEGORIES",
    "US_AQI_COLORS",
    "US_AQI_COLORS_ASSIST",
    "US_POLLUTANTS",
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
