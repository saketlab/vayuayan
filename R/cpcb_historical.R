.cpcb_base_url <- "https://airquality.cpcb.gov.in"

#' Fetch complete station and city list from CPCB
#'
#' @description
#' List every state, city and station in the CPCB station directory bundled
#' with the package. Needs no internet connection.
#'
#' @return List with \code{cities} (named by state; data frames of
#'   \code{label}/\code{value}) and \code{stations} (named by city; data
#'   frames of station \code{label} and ID \code{value}).
#' @examples
#' all_data <- cpcb_get_complete_list()
#' names(all_data)
#' @export
cpcb_get_complete_list <- function() {
  cities <- do.call(rbind, .cpcb_directory()$cities)
  stations <- .cpcb_directory_stations()
  list(
    cities = lapply(split(cities$city_name, cities$state_name), .cpcb_dropdown),
    stations = lapply(
      split(stations, stations$city_name),
      function(st) .cpcb_dropdown(st$station_name, st$station_id)
    )
  )
}

#' Get list of states with AQI data
#'
#' @description
#' Get the states in the CPCB station directory bundled with the package.
#' Needs no internet connection.
#'
#' @return Character vector of state names
#' @examples
#' states <- cpcb_get_state_list()
#' head(states)
#' @export
cpcb_get_state_list <- function() {
  sort(.cpcb_directory()$states$state_name)
}

#' Get list of cities in a state
#'
#' @description
#' Get the cities of a state from the bundled CPCB station directory.
#' Matching is case-insensitive and also accepts CPCB state codes.
#'
#' @param state Character. State name (e.g. \code{"Maharashtra"}, \code{"Delhi"}).
#' @return Character vector of city names
#' @examples
#' cities <- cpcb_get_city_list("Maharashtra")
#' head(cities)
#' @export
cpcb_get_city_list <- function(state) {
  state_entry <- .cpcb_resolve_state(state)
  if (is.null(state_entry)) {
    return(character(0))
  }
  cities <- .cpcb_directory()$cities[[state_entry$state_code]]
  sort(as.character(cities$city_name))
}

#' Get station list for a city
#'
#' @description
#' Get the monitoring stations of a city from the bundled CPCB station
#' directory.
#'
#' @param city Character. City name (e.g. \code{"Delhi"}, \code{"Mumbai"}).
#' @return Data frame with columns \code{label} (station name) and
#'   \code{value} (station ID)
#' @examples
#' stations <- cpcb_get_station_list("Delhi")
#' head(stations)
#' @export
cpcb_get_station_list <- function(city) {
  city_entry <- .cpcb_resolve_city(city)
  st <- if (!is.null(city_entry)) .cpcb_directory()$stations[[city_entry$city_code]]
  if (!is.data.frame(st)) {
    return(.cpcb_dropdown(character(0)))
  }
  .cpcb_dropdown(st$station_name, st$station_id)
}

#' Add coordinates to station list
#'
#' @description
#' Add lat/lon coordinates to a station data frame. Coordinates come from the
#' bundled CPCB station directory, then from the CPCB live feed for stations
#' newer than the directory, then from Nominatim geocoding of the station
#' name as a last resort.
#'
#' @param stations Data frame from \code{cpcb_get_station_list()}
#' @return Same data frame with \code{lat} and \code{lon} columns added
#' @examplesIf interactive()
#' stations <- cpcb_get_station_list("Mumbai")
#' stations_with_coords <- cpcb_add_coords(stations)
#' head(stations_with_coords)
#' @export
cpcb_add_coords <- function(stations) {
  known <- .cpcb_directory_stations()
  idx <- match(stations$value, known$station_id)
  stations$lat <- known$latitude[idx]
  stations$lon <- known$longitude[idx]

  if (anyNA(stations$lat)) {
    feed <- tryCatch(.cpcb_rss_stations(), error = function(e) {
      warning("CPCB live feed unavailable: ", conditionMessage(e), call. = FALSE)
      NULL
    })
    missing <- which(is.na(stations$lat))
    idx <- match(stations$value[missing], feed$id)
    stations$lat[missing] <- suppressWarnings(as.numeric(feed$latitude[idx]))
    stations$lon[missing] <- suppressWarnings(as.numeric(feed$longitude[idx]))
  }

  # Nominatim fallback for any remaining NAs.
  # Stations absent from the live feed (e.g. temporarily offline) are
  # geocoded via OpenStreetMap as a best-effort fallback
  missing_idx <- which(is.na(stations$lat))

  if (length(missing_idx) > 0) {
    message(
      length(missing_idx),
      " stations have no CPCB coordinates -- trying Nominatim fallback..."
    )

    for (i in missing_idx) {
      label <- stations$label[i]

      # Strip agency suffix for cleaner query: "Bandra, Mumbai - MPCB" -> "Bandra, Mumbai"
      query <- gsub(
        "\\s*-\\s*(DPCC|CPCB|IMD|IITM|MPCB|BMC|APPCB|TSPCB|KSPCB).*$",
        "", label
      )

      Sys.sleep(1) # Nominatim rate limit: 1 request/second
      tryCatch(
        {
          url <- utils::URLencode(paste0(
            "https://nominatim.openstreetmap.org/search?q=",
            query,
            "&format=json&limit=1"
          ))
          resp <- httr::GET(
            url,
            httr::user_agent("vayuayan-r-package"),
            httr::timeout(10)
          )
          result <- httr::content(resp, as = "parsed")

          if (length(result) > 0) {
            stations$lat[i] <- as.numeric(result[[1]]$lat)
            stations$lon[i] <- as.numeric(result[[1]]$lon)
            message(
              "  Nominatim: ", query, " -> ",
              result[[1]]$lat, ", ", result[[1]]$lon
            )
          } else {
            message("  Nominatim: NO RESULT for ", query)
          }
        },
        error = function(e) {
          message("  Nominatim: FAILED for ", query, " - ", e$message)
        }
      )
    }
  }

  n_final <- sum(!is.na(stations$lat))
  message("Done: ", n_final, "/", nrow(stations), " stations have coordinates")

  return(stations)
}

#' Get file path for CPCB data download
#'
#' @description
#' Get file path for downloading data from CPCB. Used internally by
#' \code{cpcb_download_city_data()} and \code{cpcb_download_station_data()}.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_103"}).
#' @param station_name Character. Station name.
#' @param state Character. State name.
#' @param city Character. City name.
#' @param year Integer or character. Year for data (e.g. \code{2022}).
#' @param frequency Character. Data frequency: \code{"daily"},
#'   \code{"hourly"}, \code{"monthly"} or \code{"15_minute"}.
#' @param data_type Character. Type of data: \code{"cityLevel"},
#'   \code{"stationLevel"} or \code{"raw"}.
#' @return List of file entries, each with \code{filePath}, \code{year} and
#'   \code{month} (\code{NA} when CPCB gives none).
#' @examplesIf interactive()
#' paths <- cpcb_get_file_path(
#'   city = "Delhi", frequency = "daily",
#'   data_type = "cityLevel"
#' )
#' str(paths[[1]])
#' @export
cpcb_get_file_path <- function(station_id = "",
                               station_name = "",
                               state = "",
                               city = "",
                               year = "",
                               frequency = "daily",
                               data_type = "cityLevel") {
  payload <- list(
    station_id = station_id,
    station_name = station_name,
    state = state,
    city = city,
    year = as.character(year),
    frequency = .cpcb_normalize_frequency(frequency),
    dataType = data_type
  )

  # endpoint matches CPCB's exact state/city/station names
  if (data_type == "cityLevel") {
    city_entry <- .cpcb_resolve_city(city, state)
    if (!is.null(city_entry)) {
      payload$station_id <- ""
      payload$station_name <- ""
      payload$state <- city_entry$state_name
      payload$city <- city_entry$city_name
    }
  } else if (data_type %in% c("stationLevel", "raw")) {
    station <- .cpcb_resolve_station(station_id, station_name)
    if (!is.null(station)) {
      payload[names(station)] <- station
    }
  }

  response <- httr::POST(
    .cpcb_new_api("file-path"),
    body = payload,
    encode = "json",
    httr::accept_json(),
    httr::timeout(30)
  )
  httr::stop_for_status(response)

  # CPCB answers 204 with an empty body on no match
  text <- httr::content(response, as = "text", encoding = "UTF-8")
  if (is.na(text) || !nzchar(text)) {
    return(list())
  }
  parsed_response <- jsonlite::fromJSON(text)

  df <- parsed_response$data
  if (!identical(parsed_response$status, "success") ||
    !is.data.frame(df) || nrow(df) == 0) {
    return(list())
  }
  years <- suppressWarnings(as.integer(.cpcb_col(df, "year")))
  months <- as.character(.cpcb_col(df, "month"))
  lapply(seq_len(nrow(df)), function(i) {
    list(filePath = as.character(df$filepath[i]), year = years[i], month = months[i])
  })
}

#' Download city-level AQI data
#'
#' @description
#' Download daily PM2.5 AQI data for a city from the CPCB data repository
#' for a given year. Data is saved as a CSV file with one row per day and
#' one column per month.
#'
#' @param city Character. City name (e.g. \code{"Delhi"}, \code{"Mumbai"}).
#' @param year Integer. Year for data (e.g. \code{2022}).
#' @param save_location Character. Full file path to save the downloaded CSV.
#' @return Data frame preview (first 6 rows) of the downloaded data.
#'   The full data is saved to \code{save_location}.
#' @examplesIf interactive()
#' cpcb_download_city_data(
#'   city          = "Delhi",
#'   year          = 2022,
#'   save_location = tempfile(fileext = ".csv")
#' )
#' @export
cpcb_download_city_data <- function(city, year, save_location) {
  data_files <- cpcb_get_file_path(
    city = city,
    frequency = "daily",
    data_type = "cityLevel"
  )
  .cpcb_save_year(data_files, year, save_location, paste("city", city))
}

#' Download station-level AQI data
#'
#' @description
#' Download daily PM2.5 AQI data for a single CPCB monitoring station for
#' a given year. Data is saved as a CSV file with one row per day and one
#' column per month.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param year Integer. Year for data (e.g. \code{2022}).
#' @param save_location Character. Full file path to save the downloaded CSV.
#' @return Data frame preview (first 6 rows) of the downloaded data.
#'   The full data is saved to \code{save_location}.
#' @examplesIf interactive()
#' cpcb_download_station_data(
#'   station_id    = "Bandra Kurla Complex, Mumbai - MPCB",
#'   year          = 2022,
#'   save_location = tempfile(fileext = ".csv")
#' )
#' @export
cpcb_download_station_data <- function(station_id, year, save_location) {
  station <- .cpcb_require_station(station_id)

  data_files <- cpcb_get_file_path(
    station_id = station$station_id,
    station_name = station$station_name,
    state = station$state,
    city = station$city,
    frequency = "daily",
    data_type = "stationLevel"
  )

  .cpcb_save_year(data_files, year, save_location, paste("station", station$station_name))
}
