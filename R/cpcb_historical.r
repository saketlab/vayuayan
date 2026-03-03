.cpcb_base_url <- "https://airquality.cpcb.gov.in"

.cpcb_headers <- c(
  "Content-Type" = "application/x-www-form-urlencoded; charset=UTF-8",
  "Accept" = "q=0.8;application/json;q=0.9"
)

.cpcb_encode_base64 <- function(data) {
  jsonlite::base64_enc(charToRaw(data))
}

.cpcb_decode_base64 <- function(data) {
  rawToChar(jsonlite::base64_dec(data))
}

#' Fetch complete station and city list from CPCB
#'
#' @description
#' Fetch the complete list of all India stations and cities from CPCB.
#'
#' @return List containing station and city data
#' @export
cpcb_get_complete_list <- function() {
  endpoint <- paste0(.cpcb_base_url, "/dataRepository/all_india_stationlist")
  form_body <- .cpcb_encode_base64("{}")

  response <- httr::POST(
    endpoint,
    body = form_body,
    encode = "form",
    httr::timeout(30)
  )

  httr::stop_for_status(response)
  decoded_response <- .cpcb_decode_base64(httr::content(response, "text"))
  parsed_response <- jsonlite::fromJSON(decoded_response)

  if (parsed_response$status == "success") {
    return(parsed_response$dropdown)
  }

  return(list())
}

#' Get list of states with AQI data
#'
#' @description
#' Get list of states available for AQI data from CPCB.
#'
#' @return Character vector of state names
#' @export
cpcb_get_state_list <- function() {
  tryCatch(
    {
      complete_list <- cpcb_get_complete_list()
      states <- names(complete_list$cities)
      return(sort(states))
    },
    error = function(e) {
      warning("Failed to fetch state list: ", e$message)
      return(character(0))
    }
  )
}

#' Get list of cities in a state
#'
#' @description
#' Get list of cities in a given state from CPCB.
#'
#' @param state State name
#' @return Character vector of city names
#' @export
cpcb_get_city_list <- function(state) {
  tryCatch(
    {
      complete_list <- cpcb_get_complete_list()
      if (state %in% names(complete_list$cities)) {
        cities <- complete_list$cities[[state]]$value
        return(sort(cities))
      }
      return(character(0))
    },
    error = function(e) {
      warning("Failed to fetch city list: ", e$message)
      return(character(0))
    }
  )
}

#' Get station list for a city
#'
#' @description
#' Get station list available in given city from CPCB.
#'
#' @param city City name
#' @return Data frame of station information
#' @export
cpcb_get_station_list <- function(city) {
  tryCatch(
    {
      complete_list <- cpcb_get_complete_list()
      if (city %in% names(complete_list$stations)) {
        stations <- complete_list$stations[[city]]
        return(stations)
      }
      return(data.frame())
    },
    error = function(e) {
      warning("Failed to fetch station list: ", e$message)
      return(data.frame())
    }
  )
}

.cpcb_abbreviations <- c(
  "DU" = "Delhi University",
  "NSIT" = "Netaji Subhas Institute of Technology",
  "IHBAS" = "Institute of Human Behaviour and Allied Sciences",
  "IGI" = "Indira Gandhi International Airport",
  "ITO" = "Income Tax Office",
  "JLN" = "Jawaharlal Nehru",
  "RK Puram" = "R.K. Puram",
  "DTU" = "Delhi Technological University",
  "CRRI" = "Central Road Research Institute"
)

.cpcb_colocated_coords <- list(
  "site_109" = c(lat = 28.5918, lon = 77.2273),
  "site_5395" = c(lat = 28.5947, lon = 77.2250),
  "site_1563" = c(lat = 28.6396, lon = 77.1463),
  "site_107" = c(lat = 28.6356, lon = 77.1462)
)

#' Clean station label for geocoding
#'
#' @description
#' Clean a CPCB station label for Nominatim geocoding by stripping agency
#' suffixes and expanding known abbreviations.
#'
#' @param label Station label string
#' @return Cleaned query string suitable for geocoding
#' @keywords internal
.cpcb_clean_geocoding_query <- function(label) {
  query <- gsub("\\s*-\\s*(DPCC|CPCB|IMD|IITM).*$", "", label)

  for (abbr in names(.cpcb_abbreviations)) {
    pattern <- paste0("\\b", abbr, "\\b")
    query <- gsub(pattern, .cpcb_abbreviations[abbr], query)
  }

  query
}

#' Add coordinates to station list
#'
#' @description
#' Add lat/lon coordinates to a station list via OpenStreetMap geocoding.
#' Handles co-located stations (same name, different agencies) by using
#' differentiated coordinates, and expands known abbreviations for better
#' geocoding accuracy.
#'
#' @param stations Data frame from cpcb_get_station_list()
#' @return Same data frame with lat and lon columns added
#' @export
cpcb_add_coords <- function(stations) {
  queries <- vapply(
    stations$label,
    .cpcb_clean_geocoding_query,
    character(1),
    USE.NAMES = FALSE
  )

  message(
    "Geocoding ",
    nrow(stations),
    " stations via OpenStreetMap (~",
    nrow(stations),
    " seconds)..."
  )

  coords <- lapply(seq_along(queries), function(i) {
    station_id <- as.character(stations$value[i])
    if (station_id %in% names(.cpcb_colocated_coords)) {
      coords_val <- .cpcb_colocated_coords[[station_id]]
      message(
        "  ", i, "/", nrow(stations), ": ", queries[i],
        " -> co-located fix (", coords_val[1], ", ", coords_val[2], ")"
      )
      return(data.frame(lat = coords_val[1], lon = coords_val[2]))
    }

    Sys.sleep(1)
    tryCatch(
      {
        url <- utils::URLencode(
          paste0(
            "https://nominatim.openstreetmap.org/search?q=",
            queries[i],
            "&format=json&limit=1"
          )
        )
        response <- httr::GET(
          url,
          httr::user_agent("vayuayan-r-package"),
          httr::timeout(10)
        )
        result <- httr::content(response, as = "parsed")

        if (length(result) > 0) {
          message(
            "  ", i, "/", nrow(stations), ": ", queries[i],
            " -> ", result[[1]]$lat, ", ", result[[1]]$lon
          )
          data.frame(
            lat = as.numeric(result[[1]]$lat),
            lon = as.numeric(result[[1]]$lon)
          )
        } else {
          message(
            "  ", i, "/", nrow(stations), ": NO RESULT for ", queries[i]
          )
          data.frame(lat = NA_real_, lon = NA_real_)
        }
      },
      error = function(e) {
        message("  ", i, "/", nrow(stations), ": FAILED - ", e$message)
        data.frame(lat = NA_real_, lon = NA_real_)
      }
    )
  })

  coords_df <- do.call(rbind, coords)
  stations$lat <- coords_df$lat
  stations$lon <- coords_df$lon

  n_success <- sum(!is.na(stations$lat))
  message("Done: ", n_success, "/", nrow(stations), " stations geocoded")

  return(stations)
}

#' Get file path for CPCB data download
#'
#' @description
#' Get file path for downloading data from CPCB.
#'
#' @param station_id Station ID
#' @param station_name Station name
#' @param state State name
#' @param city City name
#' @param year Year for data
#' @param frequency Data frequency ('hourly' or 'daily')
#' @param data_type Type of data ('cityLevel' or 'stationLevel')
#' @return List of file path information
#' @export
cpcb_get_file_path <- function(
  station_id = "",
  station_name = "",
  state = "",
  city = "",
  year = "",
  frequency = "daily",
  data_type = "cityLevel"
) {
  payload <- list(
    station_id = station_id,
    station_name = station_name,
    state = state,
    city = city,
    year = year,
    frequency = frequency,
    dataType = data_type
  )

  payload_str <- jsonlite::toJSON(payload, auto_unbox = TRUE)
  encoded_payload <- .cpcb_encode_base64(payload_str)

  endpoint <- paste0(.cpcb_base_url, "/dataRepository/file_Path")

  response <- httr::POST(
    endpoint,
    body = encoded_payload,
    httr::add_headers(.headers = .cpcb_headers),
    httr::timeout(30)
  )

  httr::stop_for_status(response)
  decoded_response <- .cpcb_decode_base64(httr::content(response, "text"))
  parsed_response <- jsonlite::fromJSON(decoded_response)

  if (parsed_response$status == "success") {
    df <- parsed_response$data
    if (is.data.frame(df) && nrow(df) > 0) {
      result <- lapply(seq_len(nrow(df)), function(i) {
        list(
          filePath = as.character(df$filepath[i]),
          year = as.integer(df$year[i])
        )
      })
      return(result)
    }
    return(list())
  }

  return(list())
}

#' Download city-level AQI data
#'
#' @description
#' Download past year AQI data for a city from CPCB.
#'
#' @param city City name
#' @param year Year for data
#' @param save_location Path to save downloaded data
#' @return Data frame preview of downloaded data
#' @export
cpcb_download_city_data <- function(city, year, save_location) {
  data_files <- cpcb_get_file_path(
    city = city,
    frequency = "daily",
    data_type = "cityLevel"
  )
  for (entry in data_files) {
    if (entry$year == year) {
      cat(entry$year, "\n")
      cat(entry$filePath, "\n")
      base_path <- paste0(
        .cpcb_base_url,
        "/dataRepository/download_file?file_name="
      )
      file_url <- paste0(base_path, entry$filePath)
      tmp <- tempfile(fileext = ".xlsx")
      res <- httr::GET(
        file_url,
        httr::write_disk(tmp, overwrite = TRUE),
        httr::timeout(60)
      )
      httr::stop_for_status(res)
      df <- readxl::read_excel(tmp, n_max = 31)
      unlink(tmp)

      utils::write.csv(df, file = save_location, row.names = FALSE)
      cat("File Saved to mentioned location", "\n")
      return(head(df))
    }
  }

  stop(sprintf("Data not found for city %s in year %s", city, year))
}

#' Download station-level AQI data
#'
#' @description
#' Download past year AQI data for a station from CPCB.
#'
#' @param station_id Station ID
#' @param year Year for data
#' @param save_location Path to save downloaded data
#' @return Data frame preview of downloaded data
#' @export
cpcb_download_station_data <- function(station_id, year, save_location) {
  complete_list <- cpcb_get_complete_list()

  station_name <- NULL
  for (city in names(complete_list$stations)) {
    df <- complete_list$stations[[city]]
    idx <- which(df$value == station_id)
    if (length(idx) > 0) {
      station_name <- as.character(df$label[idx[1]])
      break
    }
  }

  if (is.null(station_name)) {
    stop(sprintf("Station ID %s not found", station_id))
  }

  data_files <- cpcb_get_file_path(
    station_id = station_id,
    station_name = station_name,
    frequency = "daily",
    data_type = "stationLevel"
  )

  for (entry in data_files) {
    if (entry$year == year) {
      base_path <- paste0(
        .cpcb_base_url,
        "/dataRepository/download_file?file_name="
      )
      file_url <- paste0(base_path, entry$filePath)
      tmp <- tempfile(fileext = ".xlsx")
      res <- httr::GET(
        file_url,
        httr::write_disk(tmp, overwrite = TRUE),
        httr::timeout(60)
      )
      httr::stop_for_status(res)
      df <- readxl::read_excel(tmp, n_max = 31)
      unlink(tmp)

      utils::write.csv(df, file = save_location, row.names = FALSE)
      cat("File Saved to mentioned location", "\n")
      return(head(df))
    }
  }

  stop(sprintf(
    "Data not found for station %s in year %s",
    station_id,
    year
  ))
}
