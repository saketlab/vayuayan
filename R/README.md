# vayuayanR: Download and analyze air pollution data in R

**vayuayan** is an R package for downloading and analyzing air quality data from multiple sources:

- **WUSTL ACAG Satellite PM2.5**: Satellite-derived PM2.5 estimates at 0.01° (~1 km) resolution, global coverage (1998-2024, product V6.GL.03)
- **CPCB CAAQMS**: Historical and real-time PM2.5, PM10, AQI data from 600+ Central Pollution Control Board monitoring stations (India)
- **OAQ (Open Air Quality)**: Low-cost sensor network data from providers like Airnet (India)

All three sources are accessible through a common R interface with tidy data output.

This is the R port of the Python package [vayuayan](https://github.com/saketlab/vayuayan).

## Etymology

**Vayuayan** (वायुअयन) combines two Sanskrit words:

- **Vayu** (वायु): Wind, air
- **Ayan** (अयन): Path, journey, movement

Together, "Vayuayan" means "the path of wind."

---

## Installation

Install from GitHub using devtools:

```r
# Install devtools
install.packages("devtools")

# Install vayuayan
devtools::install_github("saketlab/vayuayanR")
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

# Add coordinates from CPCB live feed
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

# Get mean PM2.5 statistics for a region from WUSTL ACAG NetCDF.
# region = "AS" downloads the smaller Asia file.
delhi_stats <- pm25_get_stats(
  geojson_file = "delhi_ncr.geojson",
  year         = 2023,
  month        = 11,
  region       = "AS"
)
print(delhi_stats)
# Returns: list(mean, std, min, max, count)

# Get PM2.5 statistics grouped by a column in the GeoJSON
state_stats <- pm25_get_stats(
  geojson_file = "india_districts.geojson",
  year         = 2023,
  month        = 11,
  region       = "AS",
  group_by     = "state_name"
)
print(state_stats)

# Download a NetCDF file manually. Files are cached in
# tools::R_user_dir("vayuayan", "cache") unless cache_dir is given.
pm25_download_netcdf(
  year   = 2023,
  month  = 11,
  region = "AS"
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

# Get stations and add coordinates from CPCB live feed
stations    <- cpcb_get_station_list("Delhi")
stations_sf <- cpcb_add_coords(stations) %>%
  filter(!is.na(lat)) %>%
  sf::st_as_sf(coords = c("lon", "lat"), crs = 4326)

# Plot
ggplot(stations_sf) +
  geom_sf(size = 3, color = "royalblue4", alpha = 0.8) +
  labs(
    title   = "CPCB Monitoring Stations — Delhi",
    caption = "Source: CPCB CAAQMS"
  ) +
  theme_minimal()
```

---



## Contributing

Pull requests and bug reports are welcome.

---

## Disclaimer

This package is not officially affiliated with any government agency or air
quality monitoring network. It is a third-party tool for accessing publicly
available environmental data.
