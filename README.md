<p align="center">
  <img src="docs/assets/vayuayan.png" alt="Vayuayan Logo" width="200"/>
</p>

# Vayuayan

**Vayuayan** is a comprehensive Python package for fetching and analysing air quality data from multiple sources worldwide:

- **WUSTL ACAG**: [Washington University satellite PM2.5 data](https://sites.wustl.edu/acag/datasets/surface-pm2-5/) (Global)
- **CPCB India**: Central Pollution Control Board](https://cpcb.nic.in/) monitoring network (India only)

## Installation

```bash
pip install git+https://github.com/saketkc/vayuayan.git
```

Or install from source:

```bash
git clone https://github.com/saketkc/vayuayan.git
cd vayuayan
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

# Satellite PM2.5 analysis
pm25 = PM25Client()
# Combined stats for entire region
delhi_stats = pm25.get_pm25_stats("delhi_ncr.geojson", 2023, 11)
# Stats grouped by state
state_stats = pm25.get_pm25_stats("india_districts.geojson", 2023, 11, group_by="state_name")
# Stats grouped by multiple columns (state and district)
district_stats = pm25.get_pm25_stats("india_districts.geojson", 2023, 11, group_by="state_name,district_name")
```

## Contributing

Contributions are welcome! Please feel free to submit a pull request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Disclaimer

This package is not officially affiliated with any government agency or air quality monitoring network. It's a third-party tool for accessing publicly available environmental data. Users are responsible for verifying data accuracy and following proper attribution guidelines.

## Etymology

**Vayuayan** (वायुअयन) combines two Sanskrit words:
- **Vayu** (वायु): Wind, air 
- **Ayan** (अयन): Path, journey, movement

Together, "Vayuayan" means "the path of wind" - representing the journey and movement of air quality data across space and time.
