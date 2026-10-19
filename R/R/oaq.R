.oaq_broker_url <- "https://us-central1-oaqdms.cloudfunctions.net/brokerData"
.oaq_data_base_url <- "https://oaq.notf.in/v1"

#' Establish an OAQ API session
#'
#' @description
#' Performs the OAQ 2-step handshake: calls the Data Broker with your API key
#' and returns the signed-URL parameters needed for all subsequent data
#' requests. Sessions are valid for 24 hours.
#'
#' @param api_key Character. Your OAQ API key. Defaults to
#'   \code{Sys.getenv("OAQ_API_KEY")}.
#' @return Named list with \code{base_url} and \code{sig_string} (the full
#'   query-string to append to every data URL).
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
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

# Signed GET, parsed from JSON. Network errors and 5xx statuses are retried;
# 4xx, such as a missing file, are not.
.oaq_get <- function(path, session) {
  url <- .oaq_url(path, session)

  response <- tryCatch(
    httr::RETRY("GET", url, httr::timeout(30), times = 4, terminate_on = 400:499, quiet = TRUE),
    error = function(e) stop(sprintf("OAQ request failed: %s", e$message))
  )
  httr::stop_for_status(response)

  .oaq_parse(httr::content(response, as = "text", encoding = "UTF-8"))
}

# OAQ sends bare NaN (cpcb 164, 2025-10-19), which jsonlite rejects
.oaq_parse <- function(text) {
  text <- gsub("([:\\[,]\\s*)-?(?:NaN|Infinity)(?=\\s*[,\\]}])", "\\1null", text, perl = TRUE)
  tryCatch(
    jsonlite::fromJSON(text, simplifyVector = TRUE),
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
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' providers <- oaq_list_providers(session)
#' providers$providers$id
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
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' hierarchy <- oaq_get_hierarchy(session, "AURASSURE")
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
#' @param city Character. City name as in the provider hierarchy (any case).
#' @return Parsed list of sensor readings for the city.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' latest <- oaq_get_city_latest(session, "airnet", "Bengaluru")
#' @export
oaq_get_city_latest <- function(session, provider, city) {
  provider <- tolower(provider)
  # OAQ's paths use lower case, while its hierarchy writes "Bengaluru"
  city <- tolower(city)
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
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' stations <- oaq_get_stations_latest(session, "AURASSURE")
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
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' data <- oaq_get_station_24h(session, "airnet", "12036")
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
#' Retrieve daily aggregated air quality data for a sensor and day.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @param month Integer or character. Month (1--12).
#' @param day Integer or character. Day of month (1--31).
#' @return Parsed daily data record.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' daily <- oaq_get_daily(session, "airnet", "12036", 2026, 9, 14)
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
#' Since about March 2026, OAQ's daily values are often the last 15-minute
#' reading of the day, not its mean; use \code{oaq_daily_means()} or \code{readings_mean()} on
#' \code{oaq_readings()} for daily means.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @param month Integer or character. Month (1--12).
#' @return Parsed monthly aggregate record.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' monthly <- oaq_get_monthly(session, "airnet", "12036", 2026, "09")
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
#' Since about March 2026, OAQ's daily values are often the last 15-minute
#' reading of the day, not its mean; use \code{oaq_daily_means()} or \code{readings_mean()} on
#' \code{oaq_readings()} for daily means.
#'
#' @param session List returned by \code{oaq_session()}.
#' @param provider Character. Provider name (e.g. \code{"AURASSURE"}).
#' @param sensor_id Character. Sensor station ID.
#' @param year Integer or character. Year (e.g. \code{2024}).
#' @return Parsed annual aggregate record.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' annual <- oaq_get_annual(session, "airnet", "12036", 2026)
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
#' requested months. Stations that return no data for a month are skipped.
#'
#' Since about March 2026, OAQ's daily values are often the last 15-minute
#' reading of the day, not its mean; use \code{oaq_daily_means()} or \code{readings_mean()} on
#' \code{oaq_readings()} for daily means.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param provider Character vector of provider ids (e.g. \code{"cpcb"},
#'   \code{"airnet"}).
#' @param year Integer year (e.g. \code{2026}).
#' @param months Character vector of zero-padded months (e.g.
#'   \code{c("03", "04")}). Defaults to all twelve months.
#' @param city Optional character vector of city names to keep (matched against
#'   the station list's \code{city} column). \code{NULL} keeps every city.
#' @return A data frame of daily records with \code{provider},
#'   \code{station_id}, \code{date} (class \code{Date}), the pollutant
#'   columns returned by the API as numbers, and \code{lat}/\code{lon}/
#'   \code{name} from the station list.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' blr <- oaq_fetch_monthly_stations(
#'   session, c("cpcb", "airnet"),
#'   year = 2026, months = c("03", "04"), city = "Bengaluru"
#' )
#' @export
oaq_fetch_monthly_stations <- function(session, provider, year,
                                       months = sprintf("%02d", 1:12),
                                       city = NULL) {
  per_provider <- lapply(provider, function(p) {
    .oaq_fetch_monthly(session, p, year, months, city)
  })
  # providers and months can return different columns
  out <- dplyr::bind_rows(per_provider)
  out <- utils::type.convert(out, as.is = TRUE)
  if ("date" %in% names(out)) {
    out$date <- as.Date(out$date)
  }
  out
}

.oaq_fetch_monthly <- function(session, provider, year, months, city) {
  meta <- oaq_stations_table(session, provider)
  if (!is.null(city)) {
    meta <- meta[meta$city %in% city, , drop = FALSE]
  }

  records <- list()
  # ids are text: cpcb ids look numeric, Airnet ids can be alphanumeric
  for (sid in as.character(meta$id)) {
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
    return(NULL)
  }

  out <- dplyr::bind_rows(records)
  meta_cols <- meta[, intersect(
    c("id", "name", "lat", "lon", "city", "provider"), names(meta)
  ), drop = FALSE]
  names(meta_cols)[names(meta_cols) == "id"] <- "station_id"
  meta_cols$station_id <- as.character(meta_cols$station_id)
  merge(out, meta_cols, by = "station_id", all.x = TRUE)
}

#' Latest OAQ readings for one or more providers
#'
#' @description
#' Combine \code{oaq_get_stations_latest()} across providers into one table
#' with numeric columns, dropping stations without coordinates.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param provider Character vector of provider ids.
#' @return Data frame of stations with a \code{provider} column and numeric
#'   \code{lat}, \code{lon} and pollutant columns.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' session <- oaq_session()
#' stations <- oaq_stations_table(session, c("cpcb", "airnet"))
#' @export
oaq_stations_table <- function(session, provider) {
  per_provider <- lapply(provider, function(p) {
    st <- oaq_get_stations_latest(session, p)$stations
    st$provider <- rep(p, NROW(st))
    st
  })
  out <- utils::type.convert(dplyr::bind_rows(per_provider), as.is = TRUE)
  out[!is.na(out$lat) & !is.na(out$lon), , drop = FALSE]
}

#' List OAQ sensors
#'
#' @description
#' Every sensor of the providers, all providers by default. \code{type} is
#' \code{"Reference Station"} for the CPCB stations that OAQ mirrors and
#' \code{"Sensor"} for low-cost sensors.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param provider Optional character vector of provider ids; \code{NULL}
#'   lists every provider of \code{oaq_list_providers()}.
#' @return Data frame as \code{oaq_stations_table()}.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' sensors <- oaq_sensors(oaq_session())
#' table(sensors$provider, sensors$type)
#' @export
oaq_sensors <- function(session, provider = NULL) {
  if (is.null(provider)) {
    provider <- oaq_list_providers(session)$providers$id
  }
  oaq_stations_table(session, provider)
}

#' Nearest CPCB stations of OAQ sensors
#'
#' @description
#' The \code{k} nearest CPCB stations of each sensor, from the bundled CPCB
#' station directory, so the result does not depend on which stations are
#' online.
#'
#' @param sensors Data frame from \code{oaq_sensors()} (\code{id},
#'   \code{name}, \code{city}, \code{lat}, \code{lon}, \code{provider}).
#' @param k Number of CPCB stations per sensor.
#' @return Data frame with \code{provider}, \code{sensor_id},
#'   \code{sensor_name}, \code{city}, \code{rank}, \code{cpcb_station_id},
#'   \code{cpcb_station_name}, \code{cpcb_city} and \code{distance_km},
#'   nearest first for each sensor.
#' @examples
#' sensors <- data.frame(
#'   id = "s1", name = "Kumara Park", city = "Bengaluru",
#'   lat = 12.99, lon = 77.58, provider = "airnet"
#' )
#' oaq_nearest_cpcb(sensors, k = 2)
#' @export
oaq_nearest_cpcb <- function(sensors, k = 1) {
  cpcb <- .cpcb_directory_stations()
  cpcb$lat <- cpcb$latitude
  cpcb$lon <- cpcb$longitude
  pairs <- nearest_stations(sensors, cpcb, k = k, from_id = "id", to_id = "station_id")
  sensor <- sensors[match(pairs$from_id, sensors$id), , drop = FALSE]
  station <- cpcb[match(pairs$to_id, cpcb$station_id), , drop = FALSE]
  data.frame(
    provider = sensor$provider,
    sensor_id = pairs$from_id,
    sensor_name = sensor$name,
    city = sensor$city,
    rank = pairs$rank,
    cpcb_station_id = pairs$to_id,
    cpcb_station_name = station$station_name,
    cpcb_city = station$city_name,
    distance_km = pairs$dist_km,
    stringsAsFactors = FALSE
  )
}

#' Tally of OAQ-only sensors by city
#'
#' @description
#' Count the sensors that are not OAQ's copy of CPCB, by city and provider,
#' next to the CPCB stations of the city.
#'
#' @param sensors Data frame from \code{oaq_sensors()}.
#' @return Data frame with \code{city}, \code{provider}, \code{sensors},
#'   \code{cpcb_stations} (CPCB stations of the city in the station
#'   directory, 0 where CPCB has none) and \code{median_km_to_cpcb} (median
#'   distance of the sensors to their nearest CPCB station), most sensors
#'   first.
#' @examples
#' sensors <- data.frame(
#'   id = c("s1", "s2", "s3"), name = c("A", "B", "C"),
#'   city = c("Bengaluru", "Bengaluru", "Delhi"),
#'   lat = c(12.99, 12.95, 28.61), lon = c(77.58, 77.6, 77.21),
#'   provider = c("airnet", "airnet", "cpcb")
#' )
#' oaq_city_tally(sensors)
#' @export
oaq_city_tally <- function(sensors) {
  own <- sensors[tolower(sensors$provider) != "cpcb", , drop = FALSE]
  if (nrow(own) == 0) {
    return(data.frame(
      city = character(), provider = character(), sensors = integer(),
      cpcb_stations = integer(), median_km_to_cpcb = numeric()
    ))
  }
  nearest <- oaq_nearest_cpcb(own, k = 1)
  groups <- split(nearest, list(nearest$city, nearest$provider), drop = TRUE)
  tally <- do.call(rbind, lapply(groups, function(g) {
    data.frame(
      city = g$city[1], provider = g$provider[1], sensors = nrow(g),
      median_km_to_cpcb = stats::median(g$distance_km), stringsAsFactors = FALSE
    )
  }))
  per_city <- table(tolower(.cpcb_directory_stations()$city_name))
  n <- per_city[tolower(tally$city)]
  tally$cpcb_stations <- as.integer(ifelse(is.na(n), 0L, n))
  tally <- tally[order(-tally$sensors, tally$city, tally$provider, method = "radix"), , drop = FALSE]
  rownames(tally) <- NULL
  tally[c("city", "provider", "sensors", "cpcb_stations", "median_km_to_cpcb")]
}

#' Daily means of an OAQ sensor's 15-minute readings
#'
#' @description
#' OAQ's own daily aggregates (\code{oaq_get_monthly()},
#' \code{oaq_get_annual()}) are often the last reading of the day rather than
#' its mean, so this computes the means from the readings of
#' \code{oaq_get_daily()} instead.
#'
#' @param session List returned by \code{\link{oaq_session}}.
#' @param provider Character. Provider id (e.g. \code{"airnet"}).
#' @param sensor_id Character. Sensor id, or several.
#' @param dates Days, as \code{Date} or \code{"YYYY-MM-DD"}.
#' @param min_readings Fewest readings of a parameter for a daily mean; the
#'   default, 64, is 16 hours, as for the National AQI.
#' @return Data frame with \code{sensor_id}, \code{date} (\code{Date}) and,
#'   for each parameter, its mean and its number of readings
#'   (\code{n_<parameter>}). Means with fewer than \code{min_readings}
#'   readings are \code{NA}. Days that OAQ has no file for are left out.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' oaq_daily_means(oaq_session(), "airnet", "12032", c("2026-09-14", "2026-09-15"))
#' @export
oaq_daily_means <- function(session, provider, sensor_id, dates, min_readings = 64) {
  if (length(sensor_id) > 1) {
    return(dplyr::bind_rows(lapply(sensor_id, function(s) {
      oaq_daily_means(session, provider, s, dates, min_readings)
    })))
  }
  rows <- lapply(as.character(as.Date(dates)), function(day) {
    d <- as.Date(day)
    res <- tryCatch(
      oaq_get_daily(
        session, provider, sensor_id,
        format(d, "%Y"), format(d, "%m"), format(d, "%d")
      ),
      error = function(e) NULL
    )
    readings <- res$data
    if (!is.data.frame(readings) || nrow(readings) == 0) {
      return(NULL)
    }
    row <- list(sensor_id = as.character(sensor_id), date = d)
    for (column in setdiff(names(readings), "date")) {
      values <- suppressWarnings(as.numeric(readings[[column]]))
      values <- values[!is.na(values)]
      row[[paste0("n_", column)]] <- length(values)
      row[[column]] <- if (length(values) >= min_readings) mean(values) else NA_real_
    }
    as.data.frame(row, stringsAsFactors = FALSE)
  })
  out <- dplyr::bind_rows(rows)
  if (nrow(out) == 0) {
    return(data.frame())
  }
  out
}

#' 15-minute readings of an OAQ sensor
#'
#' @description
#' The readings of \code{oaq_get_daily()} for several days, as one table.
#'
#' @inheritParams oaq_daily_means
#' @return Data frame with \code{sensor_id}, \code{timestamp} (POSIXct of the
#'   local wall time, labeled UTC as CPCB data are) and one numeric column
#'   per parameter. Days that OAQ has no file for, and readings without a
#'   valid time, are left out.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' oaq_readings(oaq_session(), "airnet", "12036", c("2026-09-14", "2026-09-15"))
#' @export
oaq_readings <- function(session, provider, sensor_id, dates) {
  if (length(sensor_id) > 1) {
    return(dplyr::bind_rows(lapply(sensor_id, function(s) oaq_readings(session, provider, s, dates))))
  }
  frames <- lapply(as.character(as.Date(dates)), function(day) {
    d <- as.Date(day)
    res <- tryCatch(
      oaq_get_daily(
        session, provider, sensor_id,
        format(d, "%Y"), format(d, "%m"), format(d, "%d")
      ),
      error = function(e) NULL
    )
    rows <- res$data
    if (!is.data.frame(rows) || nrow(rows) == 0 || !"date" %in% names(rows)) {
      return(NULL)
    }
    # "2026-09-15T00:15:00+05:30": keep the local wall time
    timestamp <- as.POSIXct(substr(as.character(rows$date), 1, 19),
      format = "%Y-%m-%dT%H:%M:%S", tz = "UTC"
    )
    values <- lapply(rows[setdiff(names(rows), "date")], function(x) {
      suppressWarnings(as.numeric(x))
    })
    data.frame(
      sensor_id = rep(as.character(sensor_id), nrow(rows)), timestamp = timestamp,
      values, check.names = FALSE, stringsAsFactors = FALSE
    )
  })
  out <- dplyr::bind_rows(frames)
  if (nrow(out) == 0) {
    return(data.frame(sensor_id = character(), timestamp = as.POSIXct(character(), tz = "UTC")))
  }
  out <- out[!is.na(out$timestamp), , drop = FALSE]
  rownames(out) <- NULL
  out
}

#' OAQ's own daily records of a sensor
#'
#' @description
#' The daily values of \code{oaq_get_annual()} for several years. These are
#' OAQ's values, which since about March 2026 are often the last reading of
#' the day rather than its mean; see \code{oaq_check_daily_records()} and
#' \code{oaq_daily_means()}.
#'
#' @inheritParams oaq_daily_means
#' @param years Integer years.
#' @return Data frame with \code{sensor_id}, \code{date} (\code{Date}) and
#'   one numeric column per parameter. Years that OAQ has no file for are
#'   left out.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' oaq_daily_records(oaq_session(), "cpcb", "164", 2026)
#' @export
oaq_daily_records <- function(session, provider, sensor_id, years) {
  if (length(sensor_id) > 1) {
    return(dplyr::bind_rows(lapply(sensor_id, function(s) oaq_daily_records(session, provider, s, years))))
  }
  frames <- lapply(years, function(year) {
    rows <- tryCatch(oaq_get_annual(session, provider, sensor_id, year)$data, error = function(e) NULL)
    if (!is.data.frame(rows) || nrow(rows) == 0 || !"date" %in% names(rows)) {
      return(NULL)
    }
    values <- lapply(rows[setdiff(names(rows), "date")], function(x) suppressWarnings(as.numeric(x)))
    data.frame(
      sensor_id = rep(as.character(sensor_id), nrow(rows)),
      date = as.Date(substr(as.character(rows$date), 1, 10), optional = TRUE),
      values, check.names = FALSE, stringsAsFactors = FALSE
    )
  })
  out <- dplyr::bind_rows(frames)
  if (nrow(out) == 0) {
    return(data.frame(sensor_id = character(), date = as.Date(character())))
  }
  out <- out[!is.na(out$date), , drop = FALSE]
  rownames(out) <- NULL
  out
}

#' Check OAQ's daily records against the 15-minute readings
#'
#' @description
#' Fetches the daily records and the 15-minute readings of the days and calls
#' \code{compare_daily_records()}.
#'
#' @inheritParams oaq_daily_means
#' @param value Parameter to check.
#' @param tolerance Values within it count as equal (0.005: the daily
#'   records have 2 decimals).
#' @return Data frame as \code{compare_daily_records()}. Days without a
#'   record or readings are left out.
#' @examplesIf nzchar(Sys.getenv("OAQ_API_KEY"))
#' oaq_check_daily_records(oaq_session(), "cpcb", "164", c("2026-05-29", "2026-05-30"))
#' @export
oaq_check_daily_records <- function(session, provider, sensor_id, dates, value = "pm25",
                                    tolerance = 0.005) {
  days <- sort(unique(as.Date(dates)))
  records <- oaq_daily_records(session, provider, sensor_id, sort(unique(as.integer(format(days, "%Y")))))
  if (!nrow(records) || !value %in% names(records)) {
    return(.empty_records())
  }
  records <- records[records$date %in% days & !is.na(records[[value]]), , drop = FALSE]
  readings <- oaq_readings(session, provider, sensor_id, records$date)
  if (!nrow(readings) || !value %in% names(readings)) {
    return(.empty_records())
  }
  compare_daily_records(readings, records, value, tolerance)
}
