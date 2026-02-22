#' CPCBHistorical R6 Class
#'
#' @description
#' Client for fetching historical Air Quality Index (AQI) data from CPCB.
#'
#' @export
CPCBHistorical <- R6::R6Class(
  "CPCBHistorical",

  public = list(
    #' @field base_url Base URL for CPCB services
    base_url = "https://airquality.cpcb.gov.in",

    #' @field headers HTTP headers for requests
    headers = list(
      "Content-Type" = "application/x-www-form-urlencoded; charset=UTF-8",
      "Accept" = "q=0.8;application/json;q=0.9"
    ),

    #' @description
    #' Initialize the CPCBHistorical client
    #' @return A new CPCBHistorical object
    initialize = function() {
      invisible(self)
    },

    #' @description
    #' Fetch the complete list of all India stations and cities
    #' @return List containing station and city data
    get_complete_list = function() {
      endpoint <- paste0(self$base_url, "/dataRepository/all_india_stationlist")
      form_body <- private$encode_base64("{}")

      response <- httr::POST(
        endpoint,
        body = form_body,
        encode = "form",
        httr::timeout(30)
      )

      httr::stop_for_status(response)
      decoded_response <- private$decode_base64(httr::content(response, "text"))
      parsed_response <- jsonlite::fromJSON(decoded_response)

      if (parsed_response$status == "success") {
        return(parsed_response$dropdown)
      }

      return(list())
    },

    #' @description
    #' Get list of states available for AQI data
    #' @return Character vector of state names
    get_state_list = function() {
      tryCatch(
        {
          complete_list <- self$get_complete_list()
          states <- names(complete_list$cities)
          return(sort(states))
        },
        error = function(e) {
          warning("Failed to fetch state list: ", e$message)
          return(character(0))
        }
      )
    },

    #' @description
    #' Get list of cities in a given state
    #' @param state State name
    #' @return Character vector of city names
    get_city_list = function(state) {
      tryCatch(
        {
          complete_list <- self$get_complete_list()
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
    },

    #' @description
    #' Get station list available in given city
    #' @param city City name
    #' @return Data frame of station information
    get_station_list = function(city) {
      tryCatch(
        {
          complete_list <- self$get_complete_list()
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
    },

    #' @description
    #' Add lat/lon coordinates to a station list via OpenStreetMap geocoding
    #' @param stations Data frame from get_station_list()
    #' @return Same data frame with lat and lon columns added
    add_coords = function(stations) {
      # Fallback for stations Nominatim can't resolve (abbreviations, campuses)
      # Coords are approximate (±200-500m), sourced manually via Google Maps
      fallback_coords <- list(
        "North Campus, DU, Delhi" = c(28.6900, 77.2130),
        "NSIT Dwarka, Delhi" = c(28.6090, 77.0330),
        "IHBAS, Dilshad Garden, Delhi" = c(28.6810, 77.3020)
      )
      # Strip agency suffix: "Anand Vihar, Delhi - DPCC" → "Anand Vihar, Delhi"
      # Nominatim doesn't recognise DPCC/CPCB/IMD/IITM as place names
      queries <- gsub("\\s*-\\s*(DPCC|CPCB|IMD|IITM).*$", "", stations$label)

      message(
        "Geocoding ",
        nrow(stations),
        " stations via OpenStreetMap (~",
        nrow(stations),
        " seconds)..."
      )

      coords <- lapply(seq_along(queries), function(i) {
        Sys.sleep(1) # Nominatim rate limit: max 1 req/sec, required by usage policy
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
                "  ",
                i,
                "/",
                nrow(stations),
                ": ",
                queries[i],
                " -> ",
                result[[1]]$lat,
                ", ",
                result[[1]]$lon
              )
              data.frame(
                lat = as.numeric(result[[1]]$lat),
                lon = as.numeric(result[[1]]$lon)
              )
            } else if (queries[i] %in% names(fallback_coords)) {
              # Nominatim failed — use fallback
              coords_val <- fallback_coords[[queries[i]]]
              message(
                "  ",
                i,
                "/",
                nrow(stations),
                ": ",
                queries[i],
                " -> fallback (",
                coords_val[1],
                ", ",
                coords_val[2],
                ")"
              )
              data.frame(lat = coords_val[1], lon = coords_val[2])
            } else {
              message(
                "  ",
                i,
                "/",
                nrow(stations),
                ": NO RESULT for ",
                queries[i]
              )
              data.frame(lat = NA_real_, lon = NA_real_)
            }
          },
          error = function(e) {
            # Also try fallback on error
            if (queries[i] %in% names(fallback_coords)) {
              coords_val <- fallback_coords[[queries[i]]]
              message(
                "  ",
                i,
                "/",
                nrow(stations),
                ": ",
                queries[i],
                " -> fallback after error"
              )
              data.frame(lat = coords_val[1], lon = coords_val[2])
            } else {
              message("  ", i, "/", nrow(stations), ": FAILED - ", e$message)
              data.frame(lat = NA_real_, lon = NA_real_)
            }
          }
        )
      })

      coords_df <- do.call(rbind, coords)
      stations$lat <- coords_df$lat
      stations$lon <- coords_df$lon

      n_success <- sum(!is.na(stations$lat))
      message("Done: ", n_success, "/", nrow(stations), " stations geocoded")

      return(stations)
    },

    #' @description
    #' Get file path for downloading data
    #' @param station_id Station ID
    #' @param station_name Station name
    #' @param state State name
    #' @param city City name
    #' @param year Year for data
    #' @param frequency Data frequency ('hourly' or 'daily')
    #' @param data_type Type of data ('cityLevel' or 'stationLevel')
    #' @return List of file path information
    get_file_path = function(
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
      encoded_payload <- private$encode_base64(payload_str)

      endpoint <- paste0(self$base_url, "/dataRepository/file_Path")

      response <- httr::POST(
        endpoint,
        body = encoded_payload,
        httr::add_headers(.headers = unlist(self$headers)),
        httr::timeout(30)
      )

      httr::stop_for_status(response)
      decoded_response <- private$decode_base64(httr::content(response, "text"))
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
    },

    #' @description
    #' Download past year AQI data for a city
    #' @param city City name
    #' @param year Year for data
    #' @param save_location Path to save downloaded data
    #' @return Data frame preview of downloaded data
    download_city_data = function(city, year, save_location) {
      data_files <- self$get_file_path(
        city = city,
        frequency = "daily",
        data_type = "cityLevel"
      )
      for (entry in data_files) {
        if (entry$year == year) {
          cat(entry$year, '\n')
          cat(entry$filePath, '\n')
          base_path <- paste0(
            self$base_url,
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
          df <- readxl::read_excel(tmp)
          unlink(tmp)
          df <- df[1:min(31, nrow(df)), ] # Limit to 31 rows

          utils::write.csv(df, file = save_location, row.names = FALSE)
          cat('File Saved to mentioned location', '\n')
          return(head(df))
        }
      }

      stop(sprintf("Data not found for city %s in year %s", city, year))
    },

    #' @description
    #' Download past year AQI data for a station
    #' @param station_id Station ID
    #' @param year Year for data
    #' @param save_location Path to save downloaded data
    #' @return Data frame preview of downloaded data
    download_station_data = function(station_id, year, save_location) {
      complete_list <- self$get_complete_list()

      # Find station name
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

      data_files <- self$get_file_path(
        station_id = station_id,
        station_name = station_name,
        frequency = "daily",
        data_type = "stationLevel"
      )

      for (entry in data_files) {
        if (entry$year == year) {
          base_path <- paste0(
            self$base_url,
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
          df <- readxl::read_excel(tmp)
          unlink(tmp)
          df <- df[1:min(31, nrow(df)), ] # Limit to 31 rows

          utils::write.csv(df, file = save_location, row.names = FALSE)
          cat('File Saved to mentioned location', '\n')
          return(head(df))
        }
      }

      stop(sprintf(
        "Data not found for station %s in year %s",
        station_id,
        year
      ))
    }
  ),

  private = list(
    encode_base64 = function(data) {
      jsonlite::base64_enc(charToRaw(data))
    },

    decode_base64 = function(data) {
      rawToChar(jsonlite::base64_dec(data))
    }
  )
)
