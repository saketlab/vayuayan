#' Clean Station Name
#'
#' @description
#' Convert station name to clean underscore-separated format
#'
#' @param station_name Original station name string
#' @return Cleaned station name with underscores
#' @export
clean_station_name <- function(station_name) {
  if (is.null(station_name) || !is.character(station_name) || nchar(station_name) == 0) {
    return("")
  }
  
  cleaned <- trimws(station_name)
  
  # Handle "City - Organization" pattern
  cleaned <- gsub("\\s*-\\s*", " ", cleaned)
  
  # Remove commas and replace with space
  cleaned <- gsub(",\\s*", " ", cleaned)
  
  # Remove dots but keep the text
  cleaned <- gsub("\\.", "", cleaned)
  
  # Remove other punctuation and special characters
  cleaned <- gsub("[^\\w\\s]", " ", cleaned, perl = TRUE)
  
  # Replace multiple whitespace with single space
  cleaned <- gsub("\\s+", " ", cleaned)
  
  # Replace spaces with underscores
  cleaned <- gsub(" ", "_", cleaned)
  
  # Remove multiple consecutive underscores
  cleaned <- gsub("_+", "_", cleaned)
  
  # Remove leading and trailing underscores
  cleaned <- gsub("^_+|_+$", "", cleaned)
  
  return(cleaned)
}

#' Get AQI Category
#'
#' @description
#' Convert AQI numeric value to category
#'
#' @param aqi_value Numeric AQI value
#' @return AQI category string
#' @export
get_aqi_category <- function(aqi_value) {
  if (is.na(aqi_value)) {
    return("No Data")
  } else if (aqi_value <= 50) {
    return("Good")
  } else if (aqi_value <= 100) {
    return("Satisfactory")
  } else if (aqi_value <= 200) {
    return("Moderate")
  } else if (aqi_value <= 300) {
    return("Poor")
  } else if (aqi_value <= 400) {
    return("Very Poor")
  } else {
    return("Severe")
  }
}

#' Vectorized AQI Category
#'
#' @description
#' Convert vector of AQI values to categories
#'
#' @param aqi_values Numeric vector of AQI values
#' @return Character vector of AQI categories
#' @export
get_aqi_categories <- function(aqi_values) {
  sapply(aqi_values, get_aqi_category)
}

#' Calculate Haversine Distance
#'
#' @description
#' Calculate great circle distance between two points
#'
#' @param lat1 Latitude of first point
#' @param lon1 Longitude of first point
#' @param lat2 Latitude of second point
#' @param lon2 Longitude of second point
#' @return Distance in kilometers
#' @export
haversine_distance <- function(lat1, lon1, lat2, lon2) {
  # Convert to radians
  lat1_rad <- lat1 * pi / 180
  lon1_rad <- lon1 * pi / 180
  lat2_rad <- lat2 * pi / 180
  lon2_rad <- lon2 * pi / 180
  
  # Haversine formula
  dlat <- lat2_rad - lat1_rad
  dlon <- lon2_rad - lon1_rad
  
  a <- sin(dlat / 2)^2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)^2
  c <- 2 * asin(sqrt(a))
  
  # Earth's radius in kilometers
  return(c * 6371)
}

#' Convert Station Data to DataFrame
#'
#' @description
#' Convert nested station data to a flat data frame
#'
#' @param data List of cities with nested stations
#' @return Data frame with station information
#' @export
stations_to_dataframe <- function(data) {
  rows <- list()
  
  for (city in data) {
    city_name <- city$cityName %||% ""
    city_id <- city$cityID %||% ""
    state_id <- city$stateID %||% ""
    
    for (station in city$stationsInCity) {
      rows[[length(rows) + 1]] <- data.frame(
        city_name = city_name,
        city_id = city_id,
        state_id = state_id,
        station_id = station$id %||% "",
        station_name = station$name %||% "",
        longitude = as.numeric(station$longitude %||% NA),
        latitude = as.numeric(station$latitude %||% NA),
        live = station$live %||% FALSE,
        avg_aqi = as.numeric(station$avg %||% NA),
        stringsAsFactors = FALSE
      )
    }
  }
  
  dplyr::bind_rows(rows)
}

#' Null Default Operator
#'
#' @description
#' Return default value if x is NULL
#'
#' @param x Value to check
#' @param y Default value
#' @return x if not NULL, else y
#' @keywords internal
`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

#' Analyze Station Data
#'
#' @description
#' Comprehensive analysis of station data
#'
#' @param data List of cities with nested stations
#' @return List with analysis results
#' @export
analyze_station_data <- function(data) {
  df <- stations_to_dataframe(data)
  
  analysis <- list(
    total_cities = length(data),
    total_stations = nrow(df),
    live_stations = sum(df$live, na.rm = TRUE),
    offline_stations = sum(!df$live, na.rm = TRUE),
    states = length(unique(df$state_id)),
    unique_states = sort(unique(df$state_id)),
    stations_with_aqi_data = sum(!is.na(df$avg_aqi)),
    avg_aqi_overall = mean(df$avg_aqi, na.rm = TRUE),
    min_aqi = min(df$avg_aqi, na.rm = TRUE),
    max_aqi = max(df$avg_aqi, na.rm = TRUE)
  )
  
  # Add AQI category distribution
  df$aqi_category <- get_aqi_categories(df$avg_aqi)
  analysis$aqi_categories <- table(df$aqi_category)
  
  return(analysis)
}

#' Print Vayuayan Welcome Message
#'
#' @description
#' Display package information and usage
#'
#' @export
vayuayan_welcome <- function() {
  cli::cli_h1("Vayuayan - Air Quality Data Analysis")
  cli::cli_text("Version 0.1.3")
  cli::cli_text("")
  cli::cli_h2("Available Clients:")
  cli::cli_ul(c(
    "CPCBHistorical - Historical AQI data from CPCB",
    "CPCBLive - Real-time AQI monitoring",
    "PM25Client - Satellite PM2.5 data processing"
  ))
  cli::cli_text("")
  cli::cli_h2("Quick Start:")
  cli::cli_code("historical <- CPCBHistorical$new()")
  cli::cli_code("states <- historical$get_state_list()")
  cli::cli_code("")
  cli::cli_code("live <- CPCBLive$new()")
  cli::cli_code("location <- live$get_system_location()")
  cli::cli_code("")
  cli::cli_code("pm25 <- PM25Client$new()")
  cli::cli_code("stats <- pm25$get_pm25_stats('region.geojson', 2023, 11)")
}
