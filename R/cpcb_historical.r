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
      tryCatch({
        complete_list <- self$get_complete_list()
        states <- names(complete_list$cities)
        return(sort(states))
      }, error = function(e) {
        warning("Failed to fetch state list: ", e$message)
        return(character(0))
      })
    },
    
    #' @description
    #' Get list of cities in a given state
    #' @param state State name
    #' @return Character vector of city names
    get_city_list = function(state) {
      tryCatch({
        complete_list <- self$get_complete_list()
        if (state %in% names(complete_list$cities)) {
          cities <- sapply(complete_list$cities[[state]], function(x) x$value)
          return(sort(cities))
        }
        return(character(0))
      }, error = function(e) {
        warning("Failed to fetch city list: ", e$message)
        return(character(0))
      })
    },
    
    #' @description
    #' Get station list available in given city
    #' @param city City name
    #' @return Data frame of station information
    get_station_list = function(city) {
      tryCatch({
        complete_list <- self$get_complete_list()
        if (city %in% names(complete_list$stations)) {
          stations <- complete_list$stations[[city]]
          df <- do.call(rbind, lapply(stations, function(s) {
            data.frame(
              station_id = s$value,
              station_name = s$label,
              stringsAsFactors = FALSE
            )
          }))
          return(df[order(df$station_name), ])
        }
        return(data.frame())
      }, error = function(e) {
        warning("Failed to fetch station list: ", e$message)
        return(data.frame())
      })
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
    get_file_path = function(station_id = "", station_name = "", state = "", 
                            city = "", year = "", frequency = "daily", 
                            data_type = "cityLevel") {
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
        httr::add_headers(.headers = self$headers),
        httr::timeout(30)
      )
      
      httr::stop_for_status(response)
      decoded_response <- private$decode_base64(httr::content(response, "text"))
      parsed_response <- jsonlite::fromJSON(decoded_response)
      
      if (parsed_response$status == "success") {
        return(parsed_response$data)
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
          base_path <- paste0(
            self$base_url, 
            "/dataRepository/download_file?file_name="
          )
          file_url <- paste0(base_path, entry$filepath)
          
          df <- readxl::read_excel(file_url)
          df <- df[1:min(31, nrow(df)), ]  # Limit to 31 rows
          
          readr::write_csv(df, save_location)
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
      for (city_stations in complete_list$stations) {
        for (station in city_stations) {
          if (station$value == station_id) {
            station_name <- station$label
            break
          }
        }
        if (!is.null(station_name)) break
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
          file_url <- paste0(base_path, entry$filepath)
          
          df <- readxl::read_excel(file_url)
          df <- df[1:min(31, nrow(df)), ]
          
          readr::write_csv(df, save_location)
          return(head(df))
        }
      }
      
      stop(sprintf("Data not found for station %s in year %s", station_id, year))
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
