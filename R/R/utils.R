#' Clean station name
#'
#' @description
#' Convert station name to clean underscore-separated format
#'
#' @param station_name Original station name string
#' @return Cleaned station name with underscores
#' @examples
#' clean_station_name("Bandra Kurla Complex, Mumbai - IITM")
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
#' @examples
#' get_aqi_category(150)
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
#' @examples
#' get_aqi_categories(c(42, 180, NA, 450))
#' @export
get_aqi_categories <- function(aqi_values) {
  vapply(aqi_values, get_aqi_category, character(1), USE.NAMES = FALSE)
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
#' @examples
#' # Delhi to Mumbai
#' haversine_distance(28.61, 77.21, 19.08, 72.88)
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
#' @examplesIf interactive()
#' df <- stations_to_dataframe(cpcb_get_all_india())
#' table(df$aqi_category)
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
#' @examplesIf interactive()
#' analyze_station_data(cpcb_get_all_india())
#' @export
analyze_station_data <- function(data) {
  df <- stations_to_dataframe(data)

  analysis <- list(
    total_cities = NROW(data),
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
#' @return \code{NULL}, invisibly. Called for its printed side effect.
#' @examples
#' vayuayan_welcome()
#' @export
vayuayan_welcome <- function() {
  cli::cli_h1("Vayuayan - Air quality data analysis")
  cli::cli_text("Version {utils::packageVersion('vayuayan')}")
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
    "stats <- pm25_get_stats('region.geojson', 2023, 11, region = 'AS')"
  ))
  invisible(NULL)
}

#' Find the nearest stations between two sets of points
#'
#' For every row in \code{from} (e.g. low-cost sensors), find the \code{k}
#' closest rows in \code{to} (e.g. reference stations) by haversine distance.
#' Useful for pairing sensor networks for calibration or cross-validation.
#'
#' @param from Data frame of source points. Must contain \code{lat}/\code{lon}.
#' @param to Data frame of candidate target points. Must contain
#'   \code{lat}/\code{lon}.
#' @param k Integer number of nearest targets to return per source point.
#' @param from_id,to_id Column names identifying each point, carried into the
#'   output as \code{from_id}/\code{to_id}.
#' @return A data frame with one row per (source, nearest target) pair:
#'   \code{from_id}, \code{to_id}, \code{rank} (1 = closest), and
#'   \code{dist_km}.
#' @examples
#' sensors <- data.frame(id = c("a", "b"), lat = c(28.61, 19.08), lon = c(77.21, 72.88))
#' stations <- data.frame(
#'   id = c("delhi", "mumbai", "pune"),
#'   lat = c(28.63, 19.07, 18.52), lon = c(77.22, 72.87, 73.86)
#' )
#' nearest_stations(sensors, stations, k = 2)
#' @export
nearest_stations <- function(from, to, k = 1,
                             from_id = "id", to_id = "id") {
  stopifnot(all(c("lat", "lon") %in% names(from)))
  stopifnot(all(c("lat", "lon") %in% names(to)))
  k <- min(k, nrow(to))

  rows <- lapply(seq_len(nrow(from)), function(i) {
    d <- haversine_distance(from$lat[i], from$lon[i], to$lat, to$lon)
    idx <- order(d)[seq_len(k)]
    data.frame(
      from_id = from[[from_id]][i],
      to_id = to[[to_id]][idx],
      rank = seq_len(k),
      dist_km = d[idx],
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}

#' Summarize station data by city
#'
#' @description
#' One row per city with station counts and the AQI of its live stations.
#'
#' @param data Cities with nested stations, from \code{cpcb_get_all_india()}.
#' @return Data frame with \code{city_name}, \code{city_id}, \code{state_id},
#'   \code{total_stations}, \code{live_stations}, \code{offline_stations},
#'   \code{live_percentage}, \code{avg_aqi}, \code{min_aqi}, \code{max_aqi}
#'   and \code{stations_with_data}.
#' @examplesIf interactive()
#' summary <- stations_to_city_summary(cpcb_get_all_india())
#' head(summary[order(-summary$avg_aqi), ])
#' @export
stations_to_city_summary <- function(data) {
  cities <- if (is.data.frame(data)) {
    lapply(seq_len(nrow(data)), function(i) {
      list(
        cityName = data$cityName[i], cityID = data$cityID[i],
        stateID = data$stateID[i], stationsInCity = data$stationsInCity[[i]]
      )
    })
  } else {
    data
  }
  rows <- lapply(cities, function(city) {
    st <- city$stationsInCity
    live <- if (is.data.frame(st)) !is.na(st$live) & st$live else vapply(st, function(s) isTRUE(s$live), logical(1))
    avg <- if (is.data.frame(st)) st$avg else vapply(st, function(s) as.character(s$avg %||% NA), character(1))
    aqi <- suppressWarnings(as.numeric(avg))[live]
    aqi <- aqi[!is.na(aqi)]
    total <- length(live)
    data.frame(
      city_name = city$cityName %||% "",
      city_id = city$cityID %||% "",
      state_id = city$stateID %||% "",
      total_stations = total,
      live_stations = sum(live),
      offline_stations = total - sum(live),
      live_percentage = if (total > 0) sum(live) / total * 100 else 0,
      avg_aqi = if (length(aqi)) mean(aqi) else NA_real_,
      min_aqi = if (length(aqi)) min(aqi) else NA_real_,
      max_aqi = if (length(aqi)) max(aqi) else NA_real_,
      stations_with_data = length(aqi),
      stringsAsFactors = FALSE
    )
  })
  do.call(rbind, rows)
}
