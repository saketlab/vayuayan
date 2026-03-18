.cpcb_live_coordinate_url <- "http://ip-api.com/json"
.cpcb_live_cookies <- list(ccr_public = "A")

.cpcb_live_make_request <- function(url, headers, data, cookies) {
    hdrs <- if (is.list(headers)) unlist(headers) else headers
    if (!is.null(hdrs) && !is.character(hdrs)) {
        stop("headers must be a named character vector")
    }

    cookie_vec <- NULL
    if (!is.null(cookies)) {
        cookie_vec <- if (is.list(cookies)) {
            unlist(cookies, use.names = TRUE)
        } else {
            cookies
        }
    }

    post_args <- list(url)
    post_args <- c(
        post_args,
        list(httr::add_headers(.headers = hdrs)),
        list(body = data)
    )
    if (!is.null(cookie_vec) && length(cookie_vec) > 0) {
        post_args <- c(post_args, list(httr::set_cookies(.cookies = cookie_vec)))
    }
    post_args <- c(post_args, list(httr::timeout(30)))

    response <- tryCatch(
        {
            do.call(httr::POST, post_args)
        },
        error = function(e) {
            cat("HTTP request error:", e$message, "\n")
            stop(e)
        }
    )

    tryCatch(
        {
            httr::stop_for_status(response)
        },
        error = function(e) {
            status <- tryCatch(httr::status_code(response), error = function(e2) NA)
            resp_text <- tryCatch(
                httr::content(response, as = "text", encoding = "UTF-8"),
                error = function(e2) "<unable to read response body>"
            )
            cat("Request failed with HTTP status:", status, "\n")
            cat("stop_for_status error:", e$message, "\n")
            cat("Response body (preview):\n")
            cat(substr(resp_text, 1, 2000), "\n")
            stop(e)
        }
    )

    decoded_text <- tryCatch(
        {
            httr::content(response, "text", encoding = "UTF-8")
        },
        error = function(e) {
            stop(sprintf("Failed to read response content: %s", e$message))
        }
    )

    decoded_data <- tryCatch(
        {
            rawToChar(jsonlite::base64_dec(decoded_text))
        },
        error = function(e) {
            stop(sprintf("Failed to base64-decode response: %s", e$message))
        }
    )

    parsed <- tryCatch(
        {
            jsonlite::fromJSON(decoded_data)
        },
        error = function(e) {
            stop(sprintf(
                "Failed to parse JSON from decoded response: %s\nPreview:\n%s",
                e$message, substr(decoded_data, 1, 1000)
            ))
        }
    )

    return(parsed)
}

.cpcb_live_clean_pollution_data <- function(data) {
    if (!"chartData" %in% names(data)) {
        return(data)
    }

    cleaned_chart_data <- list()

    for (i in seq_along(data$chartData)) {
        series <- data$chartData[[i]]
        if (length(series) < 2) next

        rows <- series[-1]
        live_data <- lapply(rows, function(row) {
            date_val <- if (!is.null(row[[1]])) {
                as.character(row[[1]])
            } else {
                NA_character_
            }
            raw_val <- row[[2]]

            val <- NA_real_
            if (!is.null(raw_val) && !(is.na(raw_val)) &&
                nzchar(trimws(as.character(raw_val)))) {
                raw_chr <- as.character(raw_val)
                num <- suppressWarnings(as.numeric(raw_chr))
                if (!is.na(num)) {
                    val <- num
                } else {
                    val <- raw_chr
                }
            }

            list(date = date_val, val = val)
        })

        series_name <- paste0("series_", i)
        if (!is.null(data$metrics) && is.data.frame(data$metrics) &&
            nrow(data$metrics) >= i) {
            series_name <- as.character(data$metrics$name[i])
        }

        cleaned_chart_data[[length(cleaned_chart_data) + 1]] <- list(
            name = series_name, data = live_data
        )
    }

    data$last_hours <- cleaned_chart_data
    data$chartData <- NULL

    return(data)
}

#' Get system location via IP geolocation
#'
#' @description
#' Get approximate system location using IP-based geolocation. Returns
#' city-level coordinates based on the machine's public IP address.
#'
#' @return Numeric vector c(lat, lon)
#' @examples
#' \dontrun{
#' loc <- cpcb_get_system_location()
#' cat("Latitude:", loc["lat"], "Longitude:", loc["lon"])
#' }
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
#' Get all air quality monitoring stations in India from CPCB live dashboard.
#'
#' @return List of station data
#' @examples
#' \dontrun{
#' stations <- cpcb_get_all_india()
#' df <- stations_to_dataframe(stations)
#' head(df)
#' }
#' @export
cpcb_get_all_india <- function() {
    station_url <- paste0(.cpcb_base_url, "/aqi_dashboard/aqi_station_all_india")
    body <- .cpcb_encode_base64("{}")

    response <- .cpcb_live_make_request(
        station_url,
        .cpcb_headers,
        body,
        .cpcb_live_cookies
    )

    return(response$stations)
}

#' Find nearest monitoring station
#'
#' @description
#' Find nearest CPCB monitoring station to given coordinates. If no
#' coordinates provided, uses IP-based geolocation automatically.
#' Returns station ID, name, and distance in kilometres.
#'
#' @param coords Optional numeric vector c(lat, lon). If NULL, uses IP location.
#' @return List with station_id, station_name, and distance_km
#' @examples
#' \dontrun{
#' # Auto-detect location
#' nearest <- cpcb_get_nearest_station()
#' cat("Nearest station:", nearest$station_name,
#'     "(", round(nearest$distance_km, 1), "km)")
#'
#' # Provide coordinates manually (Mumbai)
#' nearest <- cpcb_get_nearest_station(coords = c(19.076, 72.877))
#' }
#' @export
cpcb_get_nearest_station <- function(coords = NULL) {
    tryCatch(
        {
            cities <- cpcb_get_all_india()

            if (is.null(coords)) {
                coords <- cpcb_get_system_location()
            }

            user_lat <- as.numeric(coords[1])
            user_lon <- as.numeric(coords[2])

            min_distance <- Inf
            nearest_station <- NULL

            for (i in seq_len(nrow(cities))) {
                stations_df <- cities$stationsInCity[[i]]
                if (!is.data.frame(stations_df) || nrow(stations_df) == 0) next

                for (j in seq_len(nrow(stations_df))) {
                    station_lat <- suppressWarnings(as.numeric(stations_df$latitude[j]))
                    station_lon <- suppressWarnings(as.numeric(stations_df$longitude[j]))
                    if (is.na(station_lat) || is.na(station_lon)) next

                    distance <- geosphere::distHaversine(
                        c(user_lon, user_lat),
                        c(station_lon, station_lat)
                    ) / 1000

                    if (distance < min_distance) {
                        min_distance <- distance
                        nearest_station <- list(
                            station_id = as.character(stations_df$id[j]),
                            station_name = as.character(stations_df$name[j]),
                            distance_km = distance
                        )
                    }
                }
            }

            if (is.null(nearest_station)) {
                stop("No stations found or invalid station data")
            }

            return(nearest_station)
        },
        error = function(e) {
            stop(sprintf("Error finding nearest station: %s", e$message))
        }
    )
}

#' Get live AQI data for a station
#'
#' @description
#' Get live AQI data for a specific station at a specific time.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_103"}).
#' @param date_time Character. Date and time in \code{"YYYY-MM-DDTHH:00:00Z"} format.
#' @return List with live AQI data including pollutant readings
#' @examples
#' \dontrun{
#' aqi <- cpcb_get_live_aqi_data_for_station(
#'   station_id = "site_103",
#'   date_time  = "2024-01-15T10:00:00Z"
#' )
#' }
#' @export
cpcb_get_live_aqi_data_for_station <- function(station_id, date_time) {
    if (is.null(station_id) || is.null(date_time)) {
        stop("Both station_id and date_time must be provided")
    }

    parameters_url <- paste0(
        .cpcb_base_url,
        "/aqi_dashboard/aqi_all_Parameters"
    )

    raw_body <- jsonlite::toJSON(
        list(station_id = station_id, date = date_time),
        auto_unbox = TRUE
    )

    encoded_data <- .cpcb_encode_base64(raw_body)

    return(.cpcb_live_make_request(
        parameters_url,
        .cpcb_headers,
        encoded_data,
        .cpcb_live_cookies
    ))
}

#' Get live AQI data
#'
#' @description
#' Get live AQI data with flexible parameters. Automatically resolves
#' station from coordinates or IP location if not provided.
#'
#' @param station_id Optional character. Station ID. If NULL, nearest station
#'   is found automatically using \code{coords} or IP geolocation.
#' @param coords Optional numeric vector \code{c(lat, lon)}. Used to find
#'   nearest station if \code{station_id} is not provided.
#' @param date Optional character. Date in \code{"YYYY-MM-DD"} format.
#'   Defaults to today.
#' @param hour Optional integer (0--23). Hour of the day. Defaults to
#'   the most recent full hour.
#' @return List with processed live AQI data
#' @examples
#' \dontrun{
#' # Get live AQI at current location and time
#' aqi <- cpcb_get_live_aqi_data()
#'
#' # Get live AQI for a specific station and time
#' aqi <- cpcb_get_live_aqi_data(
#'   station_id = "site_103",
#'   date       = "2024-01-15",
#'   hour       = 10
#' )
#' }
#' @export
cpcb_get_live_aqi_data <- function(station_id = NULL, coords = NULL,
                                   date = NULL, hour = NULL) {
    if (is.null(station_id)) {
        nearest <- cpcb_get_nearest_station(coords)
        station_id <- nearest$station_id
    }

    now <- Sys.time()
    if (is.null(date)) {
        date <- format(now, "%Y-%m-%d")
    }

    if (!is.null(hour)) {
        if (hour < 0 || hour > 23) {
            stop("Hour must be between 0 and 23")
        }
        date_time <- sprintf("%sT%02d:00:00Z", date, hour)
    } else {
        last_hour <- as.POSIXlt(now)
        last_hour$min <- 0
        last_hour$sec <- 0
        date_time <- sprintf("%sT%02d:00:00Z", date, last_hour$hour)
    }

    aqi_data <- cpcb_get_live_aqi_data_for_station(station_id, date_time)
    return(.cpcb_live_clean_pollution_data(aqi_data))
}
