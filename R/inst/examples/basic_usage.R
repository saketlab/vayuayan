# Basic Usage Examples for vayuayan R Package
# This script demonstrates the core functionality

library(vayuayan)
library(dplyr)
library(ggplot2)

# ============================================================================
# 1. HISTORICAL AQI DATA
# ============================================================================

cat("\n=== Historical AQI Data Examples ===\n\n")

# Get list of all states
cat("Fetching state list...\n")
states <- cpcb_get_state_list()
cat("Available states:", length(states), "\n")
print(head(states, 10))

# Get cities in a specific state
cat("\nFetching cities in Maharashtra...\n")
cities_mh <- cpcb_get_city_list("Maharashtra")
cat("Cities in Maharashtra:", length(cities_mh), "\n")
print(head(cities_mh, 10))

# Get monitoring stations in a city
cat("\nFetching stations in Mumbai...\n")
stations_mumbai <- cpcb_get_station_list("Mumbai")
cat("Stations in Mumbai:", nrow(stations_mumbai), "\n")
print(head(stations_mumbai))

# Download city-level AQI data (commented out to avoid actual download)
# cpcb_download_city_data(
#   city = "Mumbai",
#   year = 2024,
#   save_location = "data/mumbai_aqi_2024.csv"
# )

# Download station-level AQI data (commented out to avoid actual download)
# if (nrow(stations_mumbai) > 0) {
#   station_id <- stations_mumbai$station_id[1]
#   cpcb_download_station_data(
#     station_id = station_id,
#     year = 2024,
#     save_location = "data/station_data_2024.csv"
#   )
# }


# ============================================================================
# 2. LIVE AQI MONITORING
# ============================================================================

cat("\n\n=== Live AQI Monitoring Examples ===\n\n")

# Get current location using IP geolocation
cat("Getting current location...\n")
tryCatch(
  {
    location <- cpcb_get_system_location()
    cat("Current location (lat, lon):", location, "\n")

    # Find nearest monitoring station
    cat("\nFinding nearest station...\n")
    nearest <- cpcb_get_nearest_station(location)
    cat("Nearest station:\n")
    cat("  ID:", nearest$station_id, "\n")
    cat("  Name:", nearest$station_name, "\n")
    cat("  Distance:", round(nearest$distance_km, 2), "km\n")

    # Get live AQI data for nearest station
    cat("\nFetching live AQI data...\n")
    aqi_data <- cpcb_get_live_aqi_data(station_id = nearest$station_id)

    if (!is.null(aqi_data$metrics) && length(aqi_data$metrics) > 0) {
      cat("Live AQI metrics:\n")
      for (metric in aqi_data$metrics) {
        cat(sprintf(
          "  %s: Avg=%s, Min=%s, Max=%s\n",
          metric$name, metric$avg, metric$min, metric$max
        ))
      }
    } else {
      cat("No live data available (station may be offline)\n")
    }
  },
  error = function(e) {
    cat("Error:", e$message, "\n")
  }
)


# ============================================================================
# 3. ALL INDIA STATION DATA ANALYSIS
# ============================================================================

cat("\n\n=== All India Station Data Analysis ===\n\n")

tryCatch(
  {
    # Get all stations across India
    cat("Fetching all India station data...\n")
    all_stations <- cpcb_get_all_india()

    # Convert to tidy dataframe
    df <- stations_to_dataframe(all_stations)

    cat("Total stations:", nrow(df), "\n")
    cat("Live stations:", sum(df$live, na.rm = TRUE), "\n")
    cat("Offline stations:", sum(!df$live, na.rm = TRUE), "\n")

    # State-wise summary
    cat("\nState-wise station summary:\n")
    state_summary <- df %>%
      group_by(state_id) %>%
      summarise(
        total_stations = n(),
        live_stations = sum(live, na.rm = TRUE),
        offline_stations = sum(!live, na.rm = TRUE),
        avg_aqi = mean(avg_aqi, na.rm = TRUE),
        .groups = "drop"
      ) %>%
      arrange(desc(live_stations)) %>%
      head(10)

    print(state_summary)

    # AQI category distribution
    cat("\nAQI Category Distribution:\n")
    df_with_aqi <- df %>%
      filter(!is.na(avg_aqi)) %>%
      mutate(aqi_category = get_aqi_categories(avg_aqi))

    category_counts <- table(df_with_aqi$aqi_category)
    print(category_counts)

    # Comprehensive analysis
    cat("\nComprehensive Station Analysis:\n")
    analysis <- analyze_station_data(all_stations)
    print(str(analysis))
  },
  error = function(e) {
    cat("Error:", e$message, "\n")
  }
)


# ============================================================================
# 4. PM2.5 SATELLITE DATA (Example - requires GeoJSON file)
# ============================================================================

cat("\n\n=== PM2.5 Satellite Data Examples ===\n\n")

cat("Note: PM2.5 analysis requires GeoJSON files with polygon boundaries\n")

# Example usage (commented out - requires GeoJSON file)
# cat("\nExample: Analyzing PM2.5 for Delhi NCR...\n")
# if (file.exists("data/delhi_ncr.geojson")) {
#   delhi_stats <- pm25_get_stats(
#     geojson_file = "data/delhi_ncr.geojson",
#     year = 2023,
#     month = 11
#   )
#   cat("Delhi NCR PM2.5 Statistics:\n")
#   print(delhi_stats)
# } else {
#   cat("GeoJSON file not found. Skipping PM2.5 analysis.\n")
# }

# Example with grouping (commented out)
# if (file.exists("data/india_states.geojson")) {
#   state_stats <- pm25_get_stats(
#     geojson_file = "data/india_states.geojson",
#     year = 2023,
#     month = 11,
#     group_by = "state_name"
#   )
#   cat("\nState-wise PM2.5 Statistics:\n")
#   print(head(state_stats, 10))
# }

# List cached NetCDF files
cat("\nListing cached NetCDF files:\n")
cached_files <- pm25_list_cached_files()

if (length(cached_files) == 0) {
  cat("No cached files found.\n")
  cat("NetCDF files will be automatically downloaded when analyzing PM2.5 data.\n")
}

# Clear cache (commented out to preserve downloads)
# cat("\nClearing cache...\n")
# pm25_clear_cache()


# ============================================================================
# 5. GEOSPATIAL ANALYSIS (if sf is available)
# ============================================================================

cat("\n\n=== Geospatial Analysis Example ===\n\n")

if (requireNamespace("sf", quietly = TRUE)) {
  tryCatch(
    {
      all_stations <- cpcb_get_all_india()
      df <- stations_to_dataframe(all_stations)

      # Filter live stations with valid coordinates
      live_stations <- df %>%
        filter(live == TRUE, !is.na(longitude), !is.na(latitude))

      cat("Creating spatial object with", nrow(live_stations), "live stations...\n")

      # Convert to sf object
      stations_sf <- sf::st_as_sf(
        live_stations,
        coords = c("longitude", "latitude"),
        crs = 4326
      )

      cat("Spatial object created successfully\n")
      cat("CRS:", sf::st_crs(stations_sf)$input, "\n")

      # Find stations within a bounding box (example: Maharashtra region)
      mh_bbox <- sf::st_bbox(c(xmin = 72.5, ymin = 15.5, xmax = 80.5, ymax = 22.5),
        crs = 4326
      )
      mh_stations <- sf::st_crop(stations_sf, mh_bbox)

      cat("Stations in Maharashtra region:", nrow(mh_stations), "\n")
    },
    error = function(e) {
      cat("Error in geospatial analysis:", e$message, "\n")
    }
  )
} else {
  cat("sf package not available. Skipping geospatial analysis.\n")
  cat("Install with: install.packages('sf')\n")
}


# ============================================================================
# SUMMARY
# ============================================================================

cat("\n\n=== Summary ===\n\n")
cat("This script demonstrated:\n")
cat("1. Fetching historical AQI data (states, cities, stations)\n")
cat("2. Live AQI monitoring and geolocation\n")
cat("3. All India station data analysis\n")
cat("4. PM2.5 satellite data processing\n")
cat("5. Geospatial analysis of monitoring stations\n")
cat("\nFor more information, see: ?vayuayan or vayuayan_welcome()\n")
