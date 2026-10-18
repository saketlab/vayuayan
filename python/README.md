<p align="center">
  <img src="https://raw.githubusercontent.com/saketlab/vayuayan/main/python/docs/assets/vayuayan.png" alt="Vayuayan Logo" width="200"/>
</p>

# Vayuayan

**Vayuayan** is a Python package that gets air quality data from these sources and analyzes the data:

- **WUSTL ACAG**: [Washington University satellite PM2.5 data](https://sites.wustl.edu/acag/datasets/surface-pm2-5/) (Global)
- **CPCB India**: [Central Pollution Control Board](https://cpcb.nic.in/) monitoring network (India only)

It also computes the Indian National Air Quality Index (NAQI) from pollutant concentrations, with the CPCB breakpoints and rules, and turns CPCB data into tidy (long) tables. Downloaded CPCB files of past years are cached in `~/.cache/vayuayan` (set `VAYUAYAN_CACHE_DIR` to move it).

## Installation

Install from PyPI (recommended):

```bash
pip install vayuayan
```

Install the development version from GitHub:

```bash
pip install "git+https://github.com/saketlab/vayuayan.git#subdirectory=python"
```

Or install from the source code:

```bash
git clone https://github.com/saketlab/vayuayan.git
cd vayuayan/python
pip install -e .
```

## Quick Start

### Command Line Interface

```bash
# List available states/regions for AQI data
vayuayan list_states

# List cities in a state
vayuayan list_cities "Maharashtra"

# List monitoring stations in a city
vayuayan list_stations "Mumbai"

# Download historical city-level AQI data
vayuayan city_data --city "Mumbai" --year 2024 --path "mumbai_aqi_2024.csv"

# Download historical station-level data
vayuayan station_data --station_id "site_5964" --year 2024 --path "station_data_2024.csv"

# Compute the daily National AQI of a station from its raw 15-minute data
vayuayan daily_aqi --station_id "site_301" --year 2024 --path "daily_aqi.csv"

# Get your current location (IP-based)
vayuayan locate_me

# Find nearest monitoring station
vayuayan nearest_station --lat 19.0760 --lon 72.8777

# Get live air quality data
vayuayan live_aqi --station_id "site_5964" --path "live_data.json"

# Analyze PM2.5 satellite data for a region (combines all polygons)
vayuayan pm25 --geojson_path "delhi_ncr.geojson" --year 2023 --month 11

# Analyze PM2.5 data grouped by state
vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name

# Analyze PM2.5 data grouped by multiple columns (state and district)
vayuayan pm25 --geojson_path "india_districts.geojson" --year 2023 --month 11 --group_by state_name,district_name
```

### Python API

```python
from vayuayan import CPCBHistorical, CPCBLive, PM25Client

# Historical data client
historical = CPCBHistorical()
states = historical.get_state_list()
mumbai_stations = historical.get_station_list("Mumbai")

# Live monitoring client
live = CPCBLive()
location = live.get_system_location()
nearest_station = live.get_nearest_station(location)
current_aqi = live.get_live_aqi_data()

# National AQI from concentrations (24-hour averages; 8-hour for CO and O3)
from vayuayan import compute_aqi

compute_aqi({"PM2.5": 45, "PM10": 80, "NO2": 30})  # AQI 80, Satisfactory, PM10

# Daily AQI and tidy rows from raw CPCB data
daily = historical.daily_aqi("site_301", "2024")
rows = historical.download_raw_aqi_data_station_level("site_301", "2024", "", tidy=True)

# Satellite PM2.5 analysis (V6.GL.03 by default)
pm25 = PM25Client()
# Monthly statistics, and state statistics as a GeoDataFrame for a map
monthly = pm25.get_pm25_monthly_stats("delhi_ncr.geojson", 2023)
state_map = pm25.get_pm25_stats(
    "india_districts.geojson", 2023, 11, group_by="state_name", geometry=True
)
# Combined stats for entire region
delhi_stats = pm25.get_pm25_stats("delhi_ncr.geojson", 2023, 11)
# Stats grouped by state
state_stats = pm25.get_pm25_stats(
    "india_districts.geojson", 2023, 11, group_by="state_name"
)
# Stats grouped by multiple columns (state and district)
district_stats = pm25.get_pm25_stats(
    "india_districts.geojson", 2023, 11, group_by="state_name,district_name"
)
```


## Contributing

We accept contributions. To contribute, open a pull request.

## Disclaimer

This package has no official relation to a government agency or to an air quality monitoring network. It is a third-party tool for public environmental data. Users must make sure that the data is accurate. Users must also give the correct attribution.

## Etymology

**Vayuayan** (वायुअयन) combines two Sanskrit words:
- **Vayu** (वायु): Wind, air 
- **Ayan** (अयन): Path, journey, movement

Thus, "Vayuayan" means "the path of wind". The name refers to the movement of air quality data across space and time.
