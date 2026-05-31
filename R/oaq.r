.oaq_broker_url <- "https://us-central1-oaqdms.cloudfunctions.net/brokerData"
.oaq_data_base_url <- "https://oaq.notf.in/v1"

#' Establish an OAQ API session
#'
#' @description
#' Performs the OAQ 2-step handshake: calls the Data Broker with your API key
#' and returns the signed-URL parameters needed for all subsequent data
#' requests. Sessions are valid for 24 hours.
#'
#' The API key is read from the \code{OAQ_API_KEY} environment variable if
#' \code{api_key} is not supplied.
#'
#' @param api_key Character. Your OAQ API key. Defaults to
#'   \code{Sys.getenv("OAQ_API_KEY")}.
#' @return Named list with \code{base_url} and \code{sig_string} (the full
#'   query-string to append to every data URL).
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' }
#' @export
oaq_session <- function(api_key = Sys.getenv("OAQ_API_KEY")) {
  if (!nzchar(api_key)) {
    stop("OAQ API key not found. Pass api_key or set OAQ_API_KEY env var.")
  }

  url <- paste0(.oaq_broker_url, "?action=api_session&token=", api_key)

  response <- tryCatch(
    httr::GET(url, httr::timeout(30)),
    error = function(e) stop(sprintf("OAQ handshake request failed: %s", e$message))
  )
  httr::stop_for_status(response)

  data <- httr::content(response, as = "parsed", type = "application/json")

  base_url <- data[["baseUrl"]] %||% .oaq_data_base_url
  sig_string <- data[["signature"]] %||% data[["Signature"]]

  if (is.null(sig_string)) {
    stop(sprintf(
      "Unexpected OAQ broker response (missing signature).\nResponse: %s",
      jsonlite::toJSON(data, auto_unbox = TRUE)
    ))
  }

  list(
    base_url   = sub("/$", "", base_url),
    sig_string = sig_string
  )
}

# Build a signed OAQ data URL.
# path: object path relative to base_url (no leading slash).
.oaq_url <- function(path, session) {
  paste0(session$base_url, "/", path, "?", session$sig_string)
}

# Execute a signed GET request and parse JSON response.
.oaq_get <- function(path, session) {
  url <- .oaq_url(path, session)

  response <- tryCatch(
    httr::GET(url, httr::timeout(30)),
    error = function(e) stop(sprintf("OAQ request failed: %s", e$message))
  )
  httr::stop_for_status(response)

  tryCatch(
    jsonlite::fromJSON(
      httr::content(response, as = "text", encoding = "UTF-8"),
      simplifyVector = TRUE
    ),
    error = function(e) stop(sprintf("Failed to parse OAQ response: %s", e$message))
  )
}

#' List all OAQ data providers
#'
#' @description
#' Retrieve the list of all available data providers on the OAQ platform,
#' including their IDs, display names, and data attribution.
#'
#' @param session List returned by \code{oaq_session()}.
#' @return List with a \code{providers} element containing id, name, and
#'   attribution for each provider.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' providers <- oaq_list_providers(session)
#' sapply(providers$providers, `[[`, "id")
#' }
#' @export
oaq_list_providers <- function(session) {
  .oaq_get("meta/providers.json", session)
}

#' Get provider geographic hierarchy
#'
#' @description
#' Get the Country > City > Sensor geographical tree for a data provider.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @return Parsed hierarchy list.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' hierarchy <- oaq_get_hierarchy(session, "AURASSURE")
#' }
#' @export
oaq_get_hierarchy <- function(session, provider) {
  provider <- tolower(provider)
  .oaq_get(paste0("provider=", provider, "/meta/hierarchy.json"), session)
}

#' Get latest AQI for a city
#'
#' @description
#' Get the latest air quality map readings for all sensors in a city.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param city Character. City name as it appears in the provider hierarchy.
#' @return Parsed list of sensor readings for the city.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' latest <- oaq_get_city_latest(session, "AURASSURE", "Bengaluru")
#' }
#' @export
oaq_get_city_latest <- function(session, provider, city) {
  provider <- tolower(provider)
  .oaq_get(
    paste0("provider=", provider, "/live/by_city/", city, "/map_latest.json"),
    session
  )
}

#' Get latest readings from all stations
#'
#' @description
#' Get the latest sensor readings from all monitoring stations under a provider.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @return Parsed list of station-level latest readings.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' stations <- oaq_get_stations_latest(session, "AURASSURE")
#' }
#' @export
oaq_get_stations_latest <- function(session, provider) {
  provider <- tolower(provider)
  .oaq_get(
    paste0("provider=", provider, "/live/global/all_stations_latest.json"),
    session
  )
}

#' Get last 24 hours of data for a sensor
#'
#' @description
#' Retrieve the last 24 hours of readings for a specific sensor station.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @return Parsed list of hourly readings.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' data <- oaq_get_station_24h(session, "AURASSURE", "sensor_001")
#' }
#' @export
oaq_get_station_24h <- function(session, provider, sensor_id) {
  provider <- tolower(provider)
  .oaq_get(
    paste0("provider=", provider, "/live/sensors/", sensor_id, "/last24h.json"),
    session
  )
}

#' Get daily historical data for a sensor
#'
#' @description
#' Retrieve daily aggregated air quality data for a specific sensor, date.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @param month Integer or character. Month (1--12).
#' @param day Integer or character. Day of month (1--31).
#' @return Parsed daily data record.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' daily <- oaq_get_daily(session, "AURASSURE", "sensor_001", 2024, 1, 15)
#' }
#' @export
oaq_get_daily <- function(session, provider, sensor_id, year, month, day) {
  provider <- tolower(provider)
  .oaq_get(
    sprintf(
      "provider=%s/history/daily/%s/%d/%02d/%02d.json",
      provider, sensor_id, as.integer(year),
      as.integer(month), as.integer(day)
    ),
    session
  )
}

#' Get monthly aggregated data for a sensor
#'
#' @description
#' Retrieve monthly aggregated air quality data for a specific sensor and month.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @param month Integer or character. Month (1--12).
#' @return Parsed monthly aggregate record.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' monthly <- oaq_get_monthly(session, "AURASSURE", "sensor_001", 2024, 1)
#' }
#' @export
oaq_get_monthly <- function(session, provider, sensor_id, year, month) {
  provider <- tolower(provider)
  .oaq_get(
    paste0(
      "provider=", provider,
      "/history/aggregates/", sensor_id,
      "/monthly_", year, "_", month, ".json"
    ),
    session
  )
}

#' Get annual aggregated data for a sensor
#'
#' @description
#' Retrieve annual aggregated air quality data for a specific sensor and year.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @return Parsed annual aggregate record.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' annual <- oaq_get_annual(session, "AURASSURE", "sensor_001", 2024)
#' }
#' @export
oaq_get_annual <- function(session, provider, sensor_id, year) {
  provider <- tolower(provider)
  .oaq_get(
    paste0(
      "provider=", provider,
      "/history/aggregates/", sensor_id,
      "/annual_", year, ".json"
    ),
    session
  )
}

#' Fetch monthly station data for a provider across one or more months
#'
#' Pulls the station list for \code{provider}, optionally restricts it to one
#' or more cities, then fetches monthly aggregates for every station across the
#' requested months. Returns a single tidy data frame with station metadata
#' (id, name, lat, lon) joined to each daily record. Stations that return no
#' data for a month are skipped.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param provider Character provider id (e.g. \code{"cpcb"}, \code{"airnet"}).
#' @param year Integer year (e.g. \code{2026}).
#' @param months Character vector of zero-padded months (e.g.
#'   \code{c("03", "04")}). Defaults to all twelve months.
#' @param city Optional character vector of city names to keep (matched against
#'   the station list's \code{city} column). \code{NULL} keeps every city.
#' @return A data frame of daily records with \code{station_id}, \code{date},
#'   the pollutant columns returned by the API, and \code{lat}/\code{lon}/
#'   \code{name} from the station list.
#' @examples
#' \dontrun{
#' session <- oaq_session()
#' blr <- oaq_fetch_monthly_stations(
#'   session, "airnet",
#'   year = 2026, months = c("03", "04"), city = "Bengaluru"
#' )
#' }
#' @export
oaq_fetch_monthly_stations <- function(session, provider, year,
                                       months = sprintf("%02d", 1:12),
                                       city = NULL) {
  live <- oaq_get_stations_latest(session, provider)
  meta <- live$stations
  if (!is.null(city)) {
    meta <- meta[meta$city %in% city, , drop = FALSE]
  }
  meta$lat <- as.numeric(meta$lat)
  meta$lon <- as.numeric(meta$lon)

  records <- list()
  for (sid in meta$id) {
    for (m in months) {
      res <- tryCatch(
        oaq_get_monthly(session, provider, sid, year, m),
        error = function(e) NULL
      )
      if (is.null(res$data) || nrow(res$data) == 0) next
      df <- res$data
      df$station_id <- sid
      records[[length(records) + 1]] <- df
    }
  }
  if (length(records) == 0) {
    return(meta[0, ])
  }

  out <- do.call(rbind, records)
  meta_cols <- meta[, intersect(
    c("id", "name", "lat", "lon", "city"), names(meta)
  ), drop = FALSE]
  names(meta_cols)[names(meta_cols) == "id"] <- "station_id"
  merge(out, meta_cols, by = "station_id", all.x = TRUE)
}
