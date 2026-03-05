# vayuayan: Air Quality Data Analysis for India

**vayuayan** is an R package for fetching and analysing air quality data from multiple sources:

- **WUSTL ACAG**: Washington University satellite PM2.5 data (Global)
- **CPCB India**: Central Pollution Control Board monitoring network (India only)

This is the R port of the Python package [vayuayan](https://github.com/saketlab/vayuayan).

## Etymology

**Vayuayan** (वायुअयन) combines two Sanskrit words:

- **Vayu** (वायु): Wind, air
- **Ayan** (अयन): Path, journey, movement

Together, "Vayuayan" means "the path of wind" — representing the journey and movement of air quality data across space and time.

---

## Installation

Install from GitHub using devtools:

```r
# Install devtools 
install.packages("devtools")

# Install vayuayan
devtools::install_github("saketkc/vayuayanR")
```

---

## Quick Start

### CPCB Historical AQI Data

```r
library(vayuayan)

# Get list of available states
states <- cpcb_get_state_list()
print(states)

# Get cities in a state
cities <- cpcb_get_city_list("Maharashtra")
print(cities)

# Get stations in a city
stations <- cpcb_get_station_list("Mumbai")
print(stations)

# Add coordinates to station list via OpenStreetMap geocoding
stations <- cpcb_add_coords(stations)
print(stations[, c("label", "lat", "lon")])

# Download city-level daily PM2.5 data
cpcb_download_city_data(
  city          = "Mumbai",
  year          = 2022,
  save_location = "mumbai_aqi_2022.csv"
)

# Download per-station daily PM2.5 data
cpcb_download_station_data(
  station_id    = "site_5964",
  year          = 2022,
  save_location = "station_data_2022.csv"
)
```

### PM2.5 Satellite Data Analysis

```r
library(vayuayan)

# Get mean PM2.5 statistics for a region from WUSTL ACAG NetCDF
delhi_stats <- pm25_get_stats(
  geojson_file = "delhi_ncr.geojson",
  year         = 2022,
  month        = 11
)
print(delhi_stats)
# Returns: list(mean, std, min, max, count)

# Get PM2.5 statistics grouped by a column in the GeoJSON
state_stats <- pm25_get_stats(
  geojson_file = "india_districts.geojson",
  year         = 2022,
  month        = 11,
  group_by     = "state_name"
)
print(state_stats)

# Download a NetCDF file manually
pm25_download_netcdf(
  year      = 2022,
  month     = 11,
  cache_dir = "pm25_data"
)
```

---

## Data Analysis with tidyverse

```r
library(vayuayan)
library(tidyverse)

# Download and reshape city-level data
cpcb_download_city_data("Delhi", 2022, "delhi_aqi_2022.csv")

delhi_monthly <- read.csv("delhi_aqi_2022.csv") %>%
  pivot_longer(cols = -Day, names_to = "Month_Name", values_to = "pm25") %>%
  mutate(month = match(Month_Name, month.name)) %>%
  filter(!is.na(pm25)) %>%
  group_by(month) %>%
  summarise(mean_pm25 = mean(pm25, na.rm = TRUE), .groups = "drop")

# Plot seasonal trend
ggplot(delhi_monthly, aes(x = month, y = mean_pm25)) +
  geom_line(linewidth = 1, color = "#d77027") +
  geom_point(size = 2.5, color = "#d77027") +
  scale_x_continuous(breaks = 1:12, labels = month.abb) +
  labs(
    title = "Delhi 2022: Monthly Mean PM2.5",
    y     = expression(paste("PM2.5 (", mu, "g/m"^3, ")")),
    x     = NULL
  ) +
  theme_minimal()
```

---

## Mapping Station Locations

```r
library(vayuayan)
library(sf)
library(ggplot2)

# Get stations and geocode them
stations    <- cpcb_get_station_list("Delhi")
stations_sf <- cpcb_add_coords(stations) %>%
  filter(!is.na(lat)) %>%
  sf::st_as_sf(coords = c("lon", "lat"), crs = 4326)

# Plot
ggplot(stations_sf) +
  geom_sf(size = 3, color = "royalblue4", alpha = 0.8) +
  labs(
    title = "CPCB Monitoring Stations — Delhi",
    caption = "Source: CPCB CAAQMS"
  ) +
  theme_minimal()
```

---

## API Reference

### CPCB Functions

| Function | Description |
|----------|-------------|
| `cpcb_get_state_list()` | Get all available states |
| `cpcb_get_city_list(state)` | Get cities in a state |
| `cpcb_get_station_list(city)` | Get stations in a city as a data frame |
| `cpcb_get_complete_list()` | Get all states, cities, and stations |
| `cpcb_add_coords(station_df)` | Geocode stations via OpenStreetMap Nominatim |
| `cpcb_download_city_data(city, year, save_location)` | Download city-level daily PM2.5 |
| `cpcb_download_station_data(station_id, year, save_location)` | Download per-station daily PM2.5 |

### PM2.5 Satellite Functions

| Function | Description |
|----------|-------------|
| `pm25_get_stats(geojson_file, year, month, cache_dir, group_by)` | Extract mean PM2.5 stats for a region |
| `pm25_download_netcdf(year, month, cache_dir)` | Download WUSTL ACAG NetCDF file |

### Utility Functions

| Function | Description |
|----------|-------------|
| `get_aqi_category(value)` | Get AQI category label for a single value |
| `get_aqi_categories(values)` | Vectorised AQI category labels |
| `clean_station_name(name)` | Sanitise station name for use as filename |
| `haversine_distance(lat1, lon1, lat2, lon2)` | Distance between two coordinates (km) |
| `stations_to_dataframe(data)` | Convert raw station list to tidy data frame |


---

## Contributing

Contributions are welcome! Please feel free to submit a pull request.

---

## Disclaimer

This package is not officially affiliated with any government agency or air
quality monitoring network. It is a third-party tool for accessing publicly
available environmental data. Users are responsible for verifying data accuracy
and following proper attribution guidelines.

---

## Citation

If you use this package in your research, please cite:

```
Choudhary, S., & Prajapat, M. K. (2025). vayuayan: Air Quality Data Analysis
for India. R package version 0.1.3. https://github.com/saketkc/vayuayanR
```
