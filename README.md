# vayuayan: Air Quality Data Analysis for India

**vayuayan** is an R package for fetching and analyzing air quality data from multiple sources:

- **WUSTL ACAG**: Washington University satellite PM2.5 data (Global)
- **CPCB India**: Central Pollution Control Board monitoring network (India only)

This is the R port of the Python package [vayuayan](https://github.com/saketlab/vayuayan).

## Installation

Install from GitHub using devtools:

```r
# Install devtools if you haven't already
install.packages("devtools")

# Install vayuayan
devtools::install_github("saketlab/vayuayan-r")
```

## Quick Start

### Historical AQI Data

```r
library(vayuayan)

# Create historical data client
historical <- CPCBHistorical$new()

# Get list of states
states <- historical$get_state_list()
print(states)

# Get cities in Maharashtra
cities <- historical$get_city_list("Maharashtra")
print(cities)

# Get stations in Mumbai
stations <- historical$get_station_list("Mumbai")
print(stations)

# Download city-level data
historical$download_city_data(
  city = "Mumbai",
  year = 2024,
  save_location = "mumbai_aqi_2024.csv"
)

# Download station-level data
historical$download_station_data(
  station_id = "site_5964",
  year = 2024,
  save_location = "station_data_2024.csv"
)
```

### Live AQI Monitoring

```r
# Create live monitoring client
live <- CPCBLive$new()

# Get your current location (IP-based)
location <- live$get_system_location()
print(location)

# Find nearest monitoring station
nearest <- live$get_nearest_station()
print(nearest)

# Get live AQI data for nearest station
aqi_data <- live$get_live_aqi_data()
print(aqi_data$metrics)

# Get live AQI for specific coordinates
aqi_data <- live$get_live_aqi_data(
  coords = c(19.0760, 72.8777)  # Mumbai coordinates
)

# Get live AQI for specific station and time
aqi_data <- live$get_live_aqi_data(
  station_id = "site_5964",
  date = "2024-02-25",
  hour = 10
)
```

### PM2.5 Satellite Data Analysis

```r
# Create PM2.5 client
pm25 <- PM25Client$new(cache_dir = "pm25_cache")

# Get PM2.5 statistics for a region (combines all polygons)
delhi_stats <- pm25$get_pm25_stats(
  geojson_file = "delhi_ncr.geojson",
  year = 2023,
  month = 11
)
print(delhi_stats)

# Get PM2.5 statistics grouped by state
state_stats <- pm25$get_pm25_stats(
  geojson_file = "india_districts.geojson",
  year = 2023,
  month = 11,
  group_by = "state_name"
)
print(state_stats)

# Get PM2.5 statistics grouped by multiple columns
district_stats <- pm25$get_pm25_stats(
  geojson_file = "india_districts.geojson",
  year = 2023,
  month = 11,
  group_by = "state_name,district_name"
)
print(district_stats)

# List cached NetCDF files
pm25$list_cached_files()

# Clear cache
pm25$clear_cache()
```

## Data Analysis with tidyverse

The package integrates well with tidyverse workflows:

```r
library(vayuayan)
library(dplyr)
library(ggplot2)

# Get all station data
live <- CPCBLive$new()
stations_data <- live$get_all_india()

# Convert to tidy dataframe
df <- stations_to_dataframe(stations_data)

# Analyze live stations by state
state_summary <- df %>%
  group_by(state_id) %>%
  summarise(
    total_stations = n(),
    live_stations = sum(live),
    avg_aqi = mean(avg_aqi, na.rm = TRUE),
    .groups = "drop"
  ) %>%
  arrange(desc(live_stations))

print(state_summary)

# Plot AQI distribution
df %>%
  filter(!is.na(avg_aqi)) %>%
  mutate(aqi_category = get_aqi_categories(avg_aqi)) %>%
  ggplot(aes(x = avg_aqi, fill = aqi_category)) +
  geom_histogram(bins = 30) +
  labs(
    title = "Distribution of AQI Values",
    x = "AQI",
    y = "Count",
    fill = "Category"
  ) +
  theme_minimal()
```

## Mapping Air Quality Stations

```r
library(vayuayan)
library(sf)
library(ggplot2)

# Get station data with coordinates
live <- CPCBLive$new()
stations_data <- live$get_all_india()
df <- stations_to_dataframe(stations_data)

# Filter live stations with valid coordinates
live_stations <- df %>%
  filter(live == TRUE, !is.na(longitude), !is.na(latitude)) %>%
  mutate(aqi_category = get_aqi_categories(avg_aqi))

# Convert to sf object
stations_sf <- st_as_sf(
  live_stations,
  coords = c("longitude", "latitude"),
  crs = 4326
)

# Plot stations on map
ggplot(stations_sf) +
  geom_sf(aes(color = aqi_category), size = 2, alpha = 0.6) +
  scale_color_manual(
    values = c(
      "Good" = "green",
      "Satisfactory" = "lightgreen",
      "Moderate" = "yellow",
      "Poor" = "orange",
      "Very Poor" = "red",
      "Severe" = "darkred"
    )
  ) +
  labs(
    title = "Live Air Quality Monitoring Stations in India",
    color = "AQI Category"
  ) +
  theme_minimal()
```

## API Reference

### CPCBHistorical

- `new()` - Initialize historical data client
- `get_state_list()` - Get available states
- `get_city_list(state)` - Get cities in a state
- `get_station_list(city)` - Get stations in a city
- `download_city_data(city, year, save_location)` - Download city-level data
- `download_station_data(station_id, year, save_location)` - Download station-level data

### CPCBLive

- `new()` - Initialize live monitoring client
- `get_system_location()` - Get IP-based location
- `get_all_india()` - Get all stations in India
- `get_nearest_station(coords = NULL)` - Find nearest station
- `get_live_aqi_data(station_id = NULL, coords = NULL, date = NULL, hour = NULL)` - Get live AQI data

### PM25Client

- `new(cache_dir = "pm25_data")` - Initialize PM2.5 client
- `download_netcdf_if_needed(year, month = NULL, force_download = FALSE)` - Download NetCDF data
- `get_pm25_stats(geojson_file, year, month = NULL, group_by = NULL)` - Compute PM2.5 statistics
- `list_cached_files()` - List cached NetCDF files
- `clear_cache()` - Clear all cached files

## Contributing

Contributions are welcome! Please feel free to submit a pull request.

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This package is not officially affiliated with any government agency or air quality monitoring network. It's a third-party tool for accessing publicly available environmental data. Users are responsible for verifying data accuracy and following proper attribution guidelines.

## Etymology

**Vayuayan** (वायुअयन) combines two Sanskrit words:
- **Vayu** (वायु): Wind, air
- **Ayan** (अयन): Path, journey, movement

Together, "Vayuayan" means "the path of wind" - representing the journey and movement of air quality data across space and time.

## Citation

If you use this package in your research, please cite:

```
Choudhary, S., & Prajapat, M. K. (2025). vayuayan: Air Quality Data Analysis for India. 
R package version 0.1.3. https://github.com/saketlab/vayuayan-r
```
