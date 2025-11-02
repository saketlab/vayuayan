#' CPCBLive R6 Class
#'
#' @description
#' Client for fetching live air quality data from CPCB.
#'
#' @export
CPCBLive <- R6::R6Class(
  "CPCBLive",

  public = list(
    #' @field base_url Base URL for CPCB services
    base_url = "https://airquality.cpcb.gov.in",

    #' @field coordinate_url URL for IP-based geolocation
    coordinate_url = "http://ip-api.com/json",

    #' @field headers HTTP headers for requests
    headers = list(
      "Content-Type" = "application/x-www-form-urlencoded; charset=UTF-8",
      "Accept" = "q=0.8;application/json;q=0.9"
    ),

    #' @description
    #' Initialize the CPCBLive client
    #' @return A new CPCBLive object
    initialize = function() {
      invisible(self)
    },

    #' @description
    #' Get system location using IP-based lookup
    #' @return Numeric vector c(latitude, longitude)
    get_system_location = function() {
      tryCatch({
        response <- httr::GET(self$coordinate_url, httr::timeout(30))
        httr::stop_for_status(response)
        data <- httr::content(response, as = "parsed")

        if (data$status == "success") {
          return(c(lat = data$lat, lon = data$lon))
        } else {
          stop(sprintf("Geolocation lookup failed: %s", data$message))
        }
      }, error = function(e) {
        stop(sprintf("Error retrieving system location: %s", e$message))
      })
    },

    #' @description
    #' Get all air quality monitoring stations in India
    #' @return List of station data
    get_all_india = function() {
      station_url <- paste0(self$base_url, "/aqi_dashboard/aqi_station_all_india")
      body <- "e30="

      response <- private$make_request(
        station_url,
        self$headers,
        body,
        list(ccr_public = "A")
      )

      return(response$stations)
    },

    #' @description
    #' Find nearest monitoring station
    #' @param coords Optional numeric vector c(lat, lon). If NULL, uses IP location
    #' @return List with station_id and station_name
    get_nearest_station = function(coords = NULL) {
      tryCatch({
        cities <- self$get_all_india()

        if (is.null(coords)) {
          coords <- self$get_system_location()
        }

        user_lat <- as.numeric(coords[1])
        user_lon <- as.numeric(coords[2])

        min_distance <- Inf
        nearest_station <- NULL

        # cities is a data.frame with a list-column 'stationsInCity'
        for (i in seq_len(nrow(cities))) {
          stations_df <- cities$stationsInCity[[i]]
          if (!is.data.frame(stations_df) || nrow(stations_df) == 0) next

          for (j in seq_len(nrow(stations_df))) {
            # safe numeric conversion
            station_lat <- suppressWarnings(as.numeric(stations_df$latitude[j]))
            station_lon <- suppressWarnings(as.numeric(stations_df$longitude[j]))
            if (is.na(station_lat) || is.na(station_lon)) next

            # Calculate distance using geosphere package
            distance <- geosphere::distHaversine(
              c(user_lon, user_lat),
              c(station_lon, station_lat)
            ) / 1000  # Convert to km

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
      }, error = function(e) {
        stop(sprintf("Error finding nearest station: %s", e$message))
      })
    },

    #' @description
    #' Get live AQI data for a specific station
    #' @param station_id Station ID
    #' @param date_time Date and time in 'YYYY-MM-DDTHH:00:00Z' format
    #' @return List with live AQI data
    get_live_aqi_data_for_station = function(station_id, date_time) {
      if (is.null(station_id) || is.null(date_time)) {
        stop("Both station_id and date_time must be provided")
      }

      parameters_url <- paste0(
        self$base_url,
        "/aqi_dashboard/aqi_all_Parameters"
      )

      raw_body <- jsonlite::toJSON(
        list(station_id = station_id, date = date_time),
        auto_unbox = TRUE
      )

      encoded_data <- jsonlite::base64_enc(charToRaw(raw_body))

      return(private$make_request(
        parameters_url,
        self$headers,
        encoded_data,
        list(ccr_public = "A")
      ))
    },

    #' @description
    #' Get live AQI data with flexible parameters
    #' @param station_id Optional station ID
    #' @param coords Optional numeric vector c(lat, lon)
    #' @param date Optional date in 'YYYY-MM-DD' format
    #' @param hour Optional hour (0-23)
    #' @return List with processed live AQI data
    get_live_aqi_data = function(station_id = NULL, coords = NULL,
                                 date = NULL, hour = NULL) {
      # Determine station_id
      if (is.null(station_id)) {
        if (!is.null(coords)) {
          nearest <- self$get_nearest_station(coords)
          station_id <- nearest$station_id
        } else {
          system_coords <- self$get_system_location()
          nearest <- self$get_nearest_station(system_coords)
          station_id <- nearest$station_id
        }
      }

      # Determine date and hour
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

      aqi_data <- self$get_live_aqi_data_for_station(station_id, date_time)
      return(private$clean_pollution_data(aqi_data))
    }
  ),

  private = list(
    make_request = function(url, headers, data, cookies) {
      # normalize headers to named character
      hdrs <- if (is.list(headers)) unlist(headers) else headers
      if (!is.null(hdrs) && !is.character(hdrs)) stop("headers must be a named character vector")

      # normalize cookies to named character (or NULL if not provided)
      cookie_vec <- NULL
      if (!is.null(cookies)) {
        cookie_vec <- if (is.list(cookies)) unlist(cookies, use.names = TRUE) else cookies
      }

      # build POST args and call httr::POST, using normalized hdrs and cookie_vec
      post_args <- list(url)
      post_args <- c(post_args,
                     list(httr::add_headers(.headers = hdrs)),
                     list(body = data))
      if (!is.null(cookie_vec) && length(cookie_vec) > 0) {
        post_args <- c(post_args, list(httr::set_cookies(.cookies = cookie_vec)))
      }
      post_args <- c(post_args, list(httr::timeout(30)))
      # return(post_args)
      # perform request and capture failures for debug
      response <- NULL
      response <- tryCatch({
        do.call(httr::POST, post_args)
      }, error = function(e) {
        cat("HTTP request error:", e$message, "\n")
        stop(e)
      })

      # inspect response and fail with debug output if non-2xx
      tryCatch({
        httr::stop_for_status(response)
      }, error = function(e) {
        status <- tryCatch(httr::status_code(response), error = function(e2) NA)
        resp_text <- tryCatch(httr::content(response, as = "text", encoding = "UTF-8"), error = function(e2) "<unable to read response body>")
        cat("Request failed with HTTP status:", status, "\n")
        cat("stop_for_status error:", e$message, "\n")
        cat("Response body (preview):\n")
        cat(substr(resp_text, 1, 2000), "\n")
        stop(e)
      })

      # successful response: return parsed base64-decoded JSON
      decoded_text <- tryCatch({
        httr::content(response, "text", encoding = "UTF-8")
      }, error = function(e) {
        stop(sprintf("Failed to read response content: %s", e$message))
      })

      decoded_data <- tryCatch({
        rawToChar(jsonlite::base64_dec(decoded_text))
      }, error = function(e) {
        stop(sprintf("Failed to base64-decode response: %s", e$message))
      })

      parsed <- tryCatch({
        jsonlite::fromJSON(decoded_data)
      }, error = function(e) {
        stop(sprintf("Failed to parse JSON from decoded response: %s\nPreview:\n%s", e$message, substr(decoded_data, 1, 1000)))
      })

      return(parsed)
    },

    clean_pollution_data = function(data) {
      if (!"chartData" %in% names(data)) {
        return(data)
      }

      cleaned_chart_data <- list()

      for (i in seq_along(data$chartData)) {
        series <- data$chartData[[i]]
        if (length(series) < 2) next

        rows <- series[-1]  # Skip header row
        live_data <- list()
        k <- 0

        for (row in rows) {
          # Each row is typically a length-3 character vector: date, value (or NA), style
          date_val <- if (!is.null(row[[1]])) as.character(row[[1]]) else NA_character_
          raw_val <- row[[2]]

          # Normalize value: try numeric, otherwise keep as character, treat empty/NA as NA
          val <- NA
          if (!is.null(raw_val) && !(is.na(raw_val)) && nzchar(trimws(as.character(raw_val)))) {
            raw_chr <- as.character(raw_val)
            num <- suppressWarnings(as.numeric(raw_chr))
            if (!is.na(num)) {
              val <- num
            } else {
              # keep non-numeric value as character
              val <- raw_chr
            }
          } else {
            val <- NA_real_
          }

          k <- k + 1
          live_data[[k]] <- list(date = date_val, val = val)
        }

        # tidy up live_data length
        if (k > 0) live_data <- live_data[seq_len(k)] else live_data <- list()

        # get series name from metrics (metrics is a data.frame)
        series_name <- paste0("series_", i)
        if (!is.null(data$metrics) && is.data.frame(data$metrics) && nrow(data$metrics) >= i) {
          series_name <- as.character(data$metrics$name[i])
        }

        cleaned_chart_data[[length(cleaned_chart_data) + 1]] <- list(name = series_name, data = live_data)
      }

      data$last_hours <- cleaned_chart_data
      data$chartData <- NULL

      return(data)
    }
  )
)
