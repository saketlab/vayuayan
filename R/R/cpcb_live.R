.cpcb_live_coordinate_url <- "http://ip-api.com/json"

#' Get system location via IP geolocation
#'
#' @description
#' Get approximate system location using IP-based geolocation. Returns
#' city-level coordinates based on the machine's public IP address.
#'
#' @return Numeric vector c(lat, lon)
#' @examplesIf interactive()
#' loc <- cpcb_get_system_location()
#' cat("Latitude:", loc["lat"], "Longitude:", loc["lon"])
#' @export
cpcb_get_system_location <- function() {
  tryCatch(
    {
      response <- httr::GET(.cpcb_live_coordinate_url, httr::timeout(30))
      httr::stop_for_status(response)
      data <- httr::content(response, as = "parsed")

      if (data$status == "success") {
        return(c(lat = data$lat, lon = data$lon))
      } else {
        stop(sprintf("Geolocation lookup failed: %s", data$message))
      }
    },
    error = function(e) {
      stop(sprintf("Error retrieving system location: %s", e$message))
    }
  )
}

#' Get all India monitoring stations
#'
#' @description
#' Get all air quality monitoring stations in India with their latest
#' readings, from the public CPCB station feed.
#'
#' @return Data frame of cities (\code{cityName}, \code{cityID},
#'   \code{stateID}) with a \code{stationsInCity} list-column of station data
#'   frames (\code{id}, \code{name}, \code{latitude}, \code{longitude},
#'   \code{live}, \code{avg}, \code{lastUpdate}, \code{pollutants}).
#' @examplesIf interactive()
#' stations <- cpcb_get_all_india()
#' df <- stations_to_dataframe(stations)
#' head(df)
#' @export
cpcb_get_all_india <- function() {
  .cpcb_rss_cities()
}

#' Find nearest monitoring station
#'
#' @description
#' Find the CPCB monitoring station nearest to given coordinates, or to the
#' IP-based location when none are given.
#'
#' @param coords Optional numeric vector c(lat, lon). If NULL, uses IP location.
#' @return List with station_id, station_name, and distance_km
#' @examplesIf interactive()
#' # Auto-detect location
#' nearest <- cpcb_get_nearest_station()
#' cat(
#'   "Nearest station:", nearest$station_name,
#'   "(", round(nearest$distance_km, 1), "km)"
#' )
#'
#' # Provide coordinates manually (Mumbai)
#' nearest <- cpcb_get_nearest_station(coords = c(19.076, 72.877))
#' @export
cpcb_get_nearest_station <- function(coords = NULL) {
  nearest <- cpcb_get_nearest_stations(coords, k = 1)
  if (nrow(nearest) == 0) {
    stop("Error finding nearest station: no stations with coordinates", call. = FALSE)
  }
  list(
    station_id = nearest$station_id,
    station_name = nearest$station_name,
    distance_km = nearest$distance_km
  )
}

#' Find the nearest monitoring stations
#'
#' @description
#' The \code{k} CPCB stations in the live feed nearest to a location,
#' optionally within a radius.
#'
#' @param coords Optional numeric vector c(lat, lon). If NULL, uses IP location.
#' @param k Integer. Number of stations to return.
#' @param max_distance_km Numeric. Only stations within this distance.
#' @return Data frame sorted by distance with \code{station_id},
#'   \code{station_name}, \code{city}, \code{state}, \code{latitude},
#'   \code{longitude}, \code{live}, \code{avg} and \code{distance_km}. It
#'   has no rows when no station is in range.
#' @examplesIf interactive()
#' # 5 nearest stations to central Delhi
#' cpcb_get_nearest_stations(c(28.6139, 77.2090), k = 5)
#'
#' # nearest station within 10 km, if any
#' cpcb_get_nearest_stations(c(28.6139, 77.2090), k = 1, max_distance_km = 10)
#' @export
cpcb_get_nearest_stations <- function(coords = NULL, k = 5, max_distance_km = Inf) {
  if (is.null(coords)) {
    coords <- cpcb_get_system_location()
  }
  stations <- .cpcb_rss_stations()
  stations$latitude <- suppressWarnings(as.numeric(stations$latitude))
  stations$longitude <- suppressWarnings(as.numeric(stations$longitude))
  stations$distance_km <- haversine_distance(
    as.numeric(coords[1]), as.numeric(coords[2]),
    stations$latitude, stations$longitude
  )
  stations <- stations[!is.na(stations$distance_km) &
    stations$distance_km <= max_distance_km, , drop = FALSE]
  stations <- utils::head(stations[order(stations$distance_km), , drop = FALSE], k)
  out <- data.frame(
    station_id = as.character(stations$id),
    station_name = as.character(stations$name),
    city = stations$city,
    state = stations$state,
    latitude = stations$latitude,
    longitude = stations$longitude,
    live = stations$live,
    avg = suppressWarnings(as.numeric(stations$avg)),
    distance_km = stations$distance_km,
    stringsAsFactors = FALSE
  )
  rownames(out) <- NULL
  out
}

#' Get live AQI data for a station
#'
#' @description
#' Get the latest AQI reading for a station from the public CPCB station
#' feed.
#'
#' The feed holds only the latest hour, so \code{date_time} is ignored.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param date_time Ignored; the feed holds only the latest reading.
#' @return List with \code{station_id}, \code{station_name},
#'   \code{lastUpdate}, \code{airQualityIndex} and a \code{metrics} data
#'   frame of pollutant readings (\code{name}, \code{avg}, \code{min},
#'   \code{max}, \code{avgDesc}).
#' @examplesIf interactive()
#' aqi <- cpcb_get_live_aqi_data_for_station(station_id = "site_103")
#' @export
cpcb_get_live_aqi_data_for_station <- function(station_id, date_time = NULL) {
  if (is.null(station_id)) {
    stop("station_id must be provided")
  }
  if (!is.null(date_time)) {
    cli::cli_alert_warning(
      "CPCB only publishes the latest reading; date_time is ignored."
    )
  }

  st <- .cpcb_find_station(.cpcb_rss_stations(), station_id, "id", "name")
  if (is.null(st)) {
    stop(sprintf("Station %s not found in the CPCB live feed", station_id),
      call. = FALSE
    )
  }

  pollutants <- st$pollutants[[1]]
  metrics <- if (is.data.frame(pollutants) && nrow(pollutants) > 0) {
    data.frame(
      name = pollutants$indexId,
      avg = pollutants$avg,
      min = pollutants$min,
      max = pollutants$max,
      avgDesc = st$lastUpdate,
      stringsAsFactors = FALSE
    )
  } else {
    data.frame()
  }
  list(
    station_id = st$id,
    station_name = st$name,
    lastUpdate = st$lastUpdate,
    airQualityIndex = st$avg,
    metrics = metrics
  )
}

#' Get live AQI data
#'
#' @description
#' Get live AQI data of a station. Without \code{station_id}, the station
#' nearest to \code{coords} or to the IP-based location is used.
#'
#' @param station_id Optional character. Station ID or name. If NULL, nearest station
#'   is found automatically using \code{coords} or IP geolocation.
#' @param coords Optional numeric vector \code{c(lat, lon)}. Used to find
#'   nearest station if \code{station_id} is not provided.
#' @param date,hour Ignored; the feed holds only the latest reading.
#' @return List as returned by \code{cpcb_get_live_aqi_data_for_station()}.
#' @examplesIf interactive()
#' # Get live AQI at the current location
#' aqi <- cpcb_get_live_aqi_data()
#'
#' # Get live AQI for a specific station
#' aqi <- cpcb_get_live_aqi_data(station_id = "site_103")
#' @export
cpcb_get_live_aqi_data <- function(station_id = NULL, coords = NULL,
                                   date = NULL, hour = NULL) {
  if (is.null(station_id)) {
    station_id <- cpcb_get_nearest_station(coords)$station_id
  }
  if (!is.null(date) || !is.null(hour)) {
    cli::cli_alert_warning(
      "CPCB only publishes the latest reading; date and hour are ignored."
    )
  }
  cpcb_get_live_aqi_data_for_station(station_id)
}
