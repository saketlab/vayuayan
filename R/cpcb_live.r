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
        
        for (city_data in cities) {
          for (station in city_data$stationsInCity) {
            tryCatch({
              station_lat <- as.numeric(station$latitude)
              station_lon <- as.numeric(station$longitude)
              
              # Calculate distance using geosphere package
              distance <- geosphere::distHaversine(
                c(user_lon, user_lat),
                c(station_lon, station_lat)
              ) / 1000  # Convert to km
              
              if (distance < min_distance) {
                min_distance <- distance
                nearest_station <- list(
                  station_id = station$id,
                  station_name = station$name,
                  distance_km = distance
                )
              }
            }, error = function(e) {
              # Skip stations with invalid coordinates
            })
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
      response <- httr::POST(
        url,
        httr::add_headers(.headers = headers),
        body = data,
        httr::set_cookies(.cookies = cookies),
        httr::timeout(30)
      )
      
      httr::stop_for_status(response)
      
      decoded_data <- rawToChar(jsonlite::base64_dec(httr::content(response, "text")))
      return(jsonlite::fromJSON(decoded_data))
    },
    
    clean_pollution_data = function(data) {
      if (!"chartData" %in% names(data)) {
        return(data)
      }
      
      cleaned_chart_data <- list()
      
      for (i in seq_along(data$chartData)) {
        series <- data$chartData[[i]]
        
        if (length(series) < 2) next
        
        rows <- series[-1]  # Skip header
        live_data <- list()
        
        for (row in rows) {
          if (length(row) >= 2 && !is.null(row[[1]]) && !is.null(row[[2]])) {
            live_data <- c(live_data, list(list(date = row[[1]], val = row[[2]])))
          }
        }
        
        if (i <= length(data$metrics)) {
          series_name <- data$metrics[[i]]$name
          cleaned_chart_data <- c(
            cleaned_chart_data,
            list(list(name = series_name, data = live_data))
          )
        }
      }
      
      data$last_hours <- cleaned_chart_data
      data$chartData <- NULL
      
      return(data)
    }
  )
)
