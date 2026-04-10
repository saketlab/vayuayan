#' Clean station name
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

  cleaned <- gsub("\\s*-\\s*", " ", cleaned)
  cleaned <- gsub(",\\s*", " ", cleaned)
  cleaned <- gsub("\\.", "", cleaned)
  cleaned <- gsub("[^\\w\\s]", " ", cleaned, perl = TRUE)
  cleaned <- gsub("\\s+", " ", cleaned)
  cleaned <- gsub(" ", "_", cleaned)
  cleaned <- gsub("_+", "_", cleaned)
  cleaned <- gsub("^_+|_+$", "", cleaned)

  return(cleaned)
}

#' Get AQI category
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

#' Vectorized AQI category
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

#' Calculate haversine distance
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
  lat1_rad <- lat1 * pi / 180
  lon1_rad <- lon1 * pi / 180
  lat2_rad <- lat2 * pi / 180
  lon2_rad <- lon2 * pi / 180

  dlat <- lat2_rad - lat1_rad
  dlon <- lon2_rad - lon1_rad

  a <- sin(dlat / 2)^2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)^2
  c <- 2 * asin(sqrt(a))

  return(c * 6371)
}

#' Convert station data to data frame
#'
#' @description
#' Convert nested station data to a flat data frame with geographic
#' information, AQI values, and categories. This is the primary way to
#' get station coordinates (latitude/longitude) from live CPCB data.
#'
#' @param data List of cities with nested stations (from cpcb_get_all_india())
#' @return Data frame with columns: station_id, station_name, city_name,
#'   city_id, state_id, longitude, latitude, live, avg_aqi, status,
#'   aqi_category
#' @export
stations_to_dataframe <- function(data) {
  rows <- list()

  .extract_stations <- function(stations, city_name, city_id, state_id) {
    if (is.data.frame(stations)) {
      for (i in seq_len(nrow(stations))) {
        lon <- suppressWarnings(as.numeric(stations$longitude[i]))
        lat <- suppressWarnings(as.numeric(stations$latitude[i]))
        if (is.na(lon) || is.na(lat)) next

        is_live <- stations$live[i] %||% FALSE
        avg_aqi <- suppressWarnings(as.numeric(stations$avg[i]))

        rows[[length(rows) + 1]] <<- data.frame(
          station_id = as.character(stations$id[i] %||% ""),
          station_name = as.character(stations$name[i] %||% ""),
          city_name = city_name,
          city_id = city_id,
          state_id = state_id,
          longitude = lon,
          latitude = lat,
          live = is_live,
          avg_aqi = avg_aqi,
          status = if (isTRUE(is_live)) "Live" else "Offline",
          aqi_category = get_aqi_category(avg_aqi),
          stringsAsFactors = FALSE
        )
      }
    } else if (is.list(stations)) {
      for (station in stations) {
        lon <- suppressWarnings(as.numeric(station$longitude %||% NA))
        lat <- suppressWarnings(as.numeric(station$latitude %||% NA))
        if (is.na(lon) || is.na(lat)) next

        is_live <- station$live %||% FALSE
        avg_aqi <- suppressWarnings(as.numeric(station$avg %||% NA))

        rows[[length(rows) + 1]] <<- data.frame(
          station_id = as.character(station$id %||% ""),
          station_name = as.character(station$name %||% ""),
          city_name = city_name,
          city_id = city_id,
          state_id = state_id,
          longitude = lon,
          latitude = lat,
          live = is_live,
          avg_aqi = avg_aqi,
          status = if (isTRUE(is_live)) "Live" else "Offline",
          aqi_category = get_aqi_category(avg_aqi),
          stringsAsFactors = FALSE
        )
      }
    }
  }

  if (is.data.frame(data)) {
    for (i in seq_len(nrow(data))) {
      city_name <- data$cityName[i] %||% ""
      city_id <- data$cityID[i] %||% ""
      state_id <- data$stateID[i] %||% ""
      stations <- data$stationsInCity[[i]]
      if (is.null(stations)) next
      .extract_stations(stations, city_name, city_id, state_id)
    }
  } else {
    for (city in data) {
      city_name <- city$cityName %||% ""
      city_id <- city$cityID %||% ""
      state_id <- city$stateID %||% ""
      stations <- city$stationsInCity
      if (is.null(stations)) next
      .extract_stations(stations, city_name, city_id, state_id)
    }
  }

  dplyr::bind_rows(rows)
}

`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

#' Analyze station data
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

  df$aqi_category <- get_aqi_categories(df$avg_aqi)
  analysis$aqi_categories <- table(df$aqi_category)

  return(analysis)
}

#' Print vayuayan welcome message
#'
#' @description
#' Display package information and usage
#'
#' @export
vayuayan_welcome <- function() {
  cli::cli_h1("Vayuayan - Air quality data analysis")
  cli::cli_text("Version 0.1.3")
  cli::cli_text(" ")
  cli::cli_h2("Available functions:")
  cli::cli_ul(c(
    "cpcb_get_state_list(), cpcb_get_city_list() - Historical AQI data from CPCB",
    "cpcb_get_live_aqi_data(), cpcb_get_nearest_station() - Real-time AQI monitoring",
    "pm25_get_stats(), pm25_download_netcdf() - Satellite PM2.5 data processing",
    "oaq_session(), oaq_get_stations_latest() - OAQ open air quality platform"
  ))
  cli::cli_text(" ")
  cli::cli_h2("Quick start:")
  cli::cli_code(c(
    "states <- cpcb_get_state_list()",
    "cities <- cpcb_get_city_list('Maharashtra')",
    " ",
    "location <- cpcb_get_system_location()",
    "aqi <- cpcb_get_live_aqi_data()",
    " ",
    "stats <- pm25_get_stats('region.geojson', 2023, 11)"
  ))
}
