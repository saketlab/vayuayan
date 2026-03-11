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

#' Add coordinates to station list
#'
#' @description
#' Add lat/lon coordinates to a station data frame by querying the CPCB
#' live coordinates API (\code{iit_rss_feed_with_coordinates}). This is the
#' same source used by the Python vayuayan package and returns authoritative
#' coordinates directly from CPCB - no geocoding, no rate limiting, no NAs
#' for oddly-named stations.
#'
#' Falls back to Nominatim geocoding for any stations not found in the CPCB
#' response (e.g. offline stations absent from the live feed).
#'
#' @param stations Data frame from \code{cpcb_get_station_list()}
#' @return Same data frame with \code{lat} and \code{lon} columns added
#' @export
cpcb_add_coords <- function(stations) {

    # -- Step 1: fetch all-India station coordinates from CPCB API --------------
    coords_url <- paste0(.cpcb_base_url, "/caaqms/iit_rss_feed_with_coordinates")

    message("Fetching station coordinates from CPCB API...")

    api_coords <- tryCatch({
        response <- httr::GET(
            coords_url,
            httr::user_agent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            ),
            httr::timeout(30)
        )
        httr::stop_for_status(response)

        data <- httr::content(response, as = "parsed", type = "application/json")

        # Flatten nested country -> state -> city -> station structure
        do.call(rbind, lapply(data$country, function(state) {
            do.call(rbind, lapply(state$citiesInState, function(city) {
                do.call(rbind, lapply(city$stationsInCity, function(station) {
                    data.frame(
                        value = as.character(station$siteId),
                        lat   = suppressWarnings(as.numeric(station$latitude)),
                        lon   = suppressWarnings(as.numeric(station$longitude)),
                        stringsAsFactors = FALSE
                    )
                }))
            }))
        }))
    }, error = function(e) {
        warning("CPCB coordinates API failed: ", e$message,
                ". Falling back to Nominatim for all stations.")
        NULL
    })

    # -- Step 2: join API coordinates to station list by site ID ----------------
    if (!is.null(api_coords)) {
        stations <- merge(
            stations, api_coords,
            by = "value", all.x = TRUE
        )
        n_matched <- sum(!is.na(stations$lat))
        message(n_matched, "/", nrow(stations),
                " stations matched from CPCB coordinates API")
    } else {
        stations$lat <- NA_real_
        stations$lon <- NA_real_
    }

    # -- Step 3: Nominatim fallback for any remaining NAs -----------------------
    # Stations absent from the live feed (e.g. temporarily offline) are
    # geocoded via OpenStreetMap as a best-effort fallback
    missing_idx <- which(is.na(stations$lat))

    if (length(missing_idx) > 0) {
        message(length(missing_idx),
                " stations not found in API - trying Nominatim fallback...")

        for (i in missing_idx) {
            label <- stations$label[i]

            # Strip agency suffix for cleaner query: "Bandra, Mumbai - MPCB" -> "Bandra, Mumbai"
            query <- gsub("\\s*-\\s*(DPCC|CPCB|IMD|IITM|MPCB|BMC|APPCB|TSPCB|KSPCB).*$",
                          "", label)

            Sys.sleep(1)  # Nominatim rate limit: 1 request/second
            tryCatch({
                url <- utils::URLencode(paste0(
                    "https://nominatim.openstreetmap.org/search?q=",
                    query,
                    "&format=json&limit=1"
                ))
                resp   <- httr::GET(url,
                                    httr::user_agent("vayuayan-r-package"),
                                    httr::timeout(10))
                result <- httr::content(resp, as = "parsed")

                if (length(result) > 0) {
                    stations$lat[i] <- as.numeric(result[[1]]$lat)
                    stations$lon[i] <- as.numeric(result[[1]]$lon)
                    message("  Nominatim: ", query, " -> ",
                            result[[1]]$lat, ", ", result[[1]]$lon)
                } else {
                    message("  Nominatim: NO RESULT for ", query)
                }
            }, error = function(e) {
                message("  Nominatim: FAILED for ", query, " - ", e$message)
            })
        }
    }

    n_final <- sum(!is.na(stations$lat))
    message("Done: ", n_final, "/", nrow(stations), " stations have coordinates")

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
