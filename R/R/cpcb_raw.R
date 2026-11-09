#' Download raw CPCB station data
#'
#' @description
#' Download a station's raw CPCB file for a year, for example 15-minute
#' observations of every pollutant and weather variable.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param year Integer year.
#' @param save_location Character. CSV path to save the result to; \code{""}
#'   saves nothing.
#' @param frequency Character. Raw interval: \code{"15_minute"} (default),
#'   \code{"hourly"} or \code{"daily"}.
#' @param tidy Logical. If \code{TRUE}, return (and save) long rows from
#'   \code{cpcb_raw_to_long()} instead of CPCB's wide table.
#' @param city,state Optional city and state that narrow an ambiguous station
#'   name. State applies only together with city.
#' @return Data frame of observations.
#' @examplesIf interactive()
#' raw <- cpcb_download_raw_station_data("site_301", 2024, tidy = TRUE)
#' @export
cpcb_download_raw_station_data <- function(station_id, year, save_location = "",
                                           frequency = "15_minute", tidy = FALSE,
                                           city = NULL, state = NULL) {
  station <- .cpcb_require_station(station_id, city, state)
  files <- cpcb_get_file_path(
    station_id = station$station_id,
    station_name = station$station_name,
    state = station$state,
    city = station$city,
    year = year,
    frequency = frequency,
    data_type = "raw"
  )
  files <- Filter(function(e) .cpcb_entry_in_year(e, year), files)
  if (length(files) == 0) {
    .vayuayan_abort(
      "vayuayan_data_not_found",
      sprintf("Raw data not found for station %s in year %s", station$station_name, year)
    )
  }
  df <- .cpcb_read_repository(files[[1]][["filepath"]])
  if (tidy) {
    df <- cpcb_raw_to_long(df, station)
  }
  .cpcb_save(df, save_location)
}

#' Download hourly AQI data
#'
#' @description
#' Download CPCB's hourly AQI workbooks for a city or a station and combine
#' the months of a year.
#'
#' @param city Character. City name. For
#'   \code{cpcb_download_hourly_station_data()}, an optional city that narrows
#'   an ambiguous station name.
#' @param state Optional state that narrows \code{city}, needed for a city name
#'   used in more than one state.
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param year Integer year.
#' @param save_location Character. CSV path to save the result to; \code{""}
#'   saves nothing.
#' @param month Optional month name (e.g. \code{"January"}). If \code{NULL},
#'   all months of the year are combined.
#' @return Data frame of hourly AQI with \code{Year} and \code{Month} columns.
#' @examplesIf interactive()
#' delhi_jan <- cpcb_download_hourly_city_data("Delhi", 2024, month = "January")
#' @name cpcb_download_hourly
NULL

#' @rdname cpcb_download_hourly
#' @export
cpcb_download_hourly_city_data <- function(city, year, save_location = "", month = NULL, state = "") {
  files <- cpcb_get_file_path(
    city = city, state = state, year = year, frequency = "hourly", data_type = "cityLevel"
  )
  .cpcb_save(.cpcb_combine_months(files, year, month), save_location)
}

#' @rdname cpcb_download_hourly
#' @export
cpcb_download_hourly_station_data <- function(station_id, year, save_location = "",
                                              month = NULL, city = NULL, state = NULL) {
  station <- .cpcb_require_station(station_id, city, state)
  files <- cpcb_get_file_path(
    station_id = station$station_id,
    station_name = station$station_name,
    state = station$state,
    city = station$city,
    year = year, frequency = "hourly", data_type = "stationLevel"
  )
  .cpcb_save(.cpcb_combine_months(files, year, month), save_location)
}

#' Daily National AQI of a station from its raw data
#'
#' @description
#' Download a station's raw 15-minute data for a year and compute its daily
#' AQI with \code{daily_aqi()} (NAQI) or \code{daily_us_aqi()} (US EPA). With
#' \code{day_ends_at} before 24, the window
#' of 1 January starts on 31 December, so the previous year's file is read
#' too; if it is missing, 1 January uses the current year's hours only.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param year Integer year.
#' @param day_ends_at Hour at which each day's 24 hours end; 16 matches CPCB's
#'   4 PM bulletin.
#' @param standard \code{"india"} for the NAQI or \code{"us"} for the US EPA AQI.
#' @param city,state Optional city and state that narrow an ambiguous station
#'   name. State applies only together with city.
#' @return Data frame as returned by \code{daily_aqi()} or
#'   \code{daily_us_aqi()}, limited to dates in \code{year}.
#' @examplesIf interactive()
#' anand_vihar <- cpcb_station_daily_aqi("Anand Vihar, Delhi", 2024, day_ends_at = 16)
#' @export
cpcb_station_daily_aqi <- function(station_id, year, day_ends_at = 24, standard = "india",
                                   city = NULL, state = NULL) {
  if (length(standard) != 1 || !standard %in% c("india", "us")) {
    stop("standard must be 'india' or 'us'", call. = FALSE)
  }
  station_id <- .cpcb_station_id(station_id, city, state)
  long <- cpcb_download_raw_station_data(station_id, year, tidy = TRUE)
  if (day_ends_at < 24) {
    long <- dplyr::bind_rows(.cpcb_last_day_of_year(station_id, as.integer(year) - 1L), long)
  }
  daily <- if (standard == "us") {
    daily_us_aqi(long, day_ends_at = day_ends_at)
  } else {
    daily_aqi(long, day_ends_at = day_ends_at)
  }
  # a window ending on 1 January of the next year is not in this year
  daily[format(daily$date, "%Y") == as.character(year), , drop = FALSE]
}

# 31 December of a year, or NULL when its file cannot be read
.cpcb_last_day_of_year <- function(station_id, year) {
  long <- tryCatch(
    cpcb_download_raw_station_data(station_id, year, tidy = TRUE),
    error = function(e) {
      cli::cli_alert_warning("No data for 31 December {year}: {conditionMessage(e)}")
      NULL
    }
  )
  if (is.null(long)) {
    return(NULL)
  }
  long[.local_date(long$timestamp) == as.Date(sprintf("%d-12-31", year)), , drop = FALSE]
}

# entries that name another year are never used; "n/a" is no year
.cpcb_entry_in_year <- function(entry, year) {
  entry_year <- trimws(as.character(entry[["year"]] %||% ""))
  length(entry_year) != 1 || is.na(entry_year) || !grepl("^[0-9]{4}$", entry_year) ||
    entry_year == as.character(year)
}

# station names can contain a month, so the path is only matched word by word
.cpcb_entry_has_month <- function(entry, month) {
  month <- tolower(month)
  entry_month <- tolower(as.character(entry[["month"]] %||% ""))
  if (!is.na(entry_month) && nzchar(entry_month)) {
    return(startsWith(entry_month, month))
  }
  month %in% strsplit(tolower(entry[["filepath"]]), "[^a-z]+")[[1]]
}

.cpcb_combine_months <- function(files, year, month = NULL) {
  files <- Filter(function(e) !is.null(e[["filepath"]]) && .cpcb_entry_in_year(e, year), files)
  selected <- if (!is.null(month)) {
    Filter(function(e) .cpcb_entry_has_month(e, month), files)
  } else {
    files
  }
  if (length(selected) == 0) {
    .vayuayan_abort("vayuayan_data_not_found", sprintf(
      "Data not found for year %s%s", year,
      if (is.null(month)) "" else paste(" and month", month)
    ))
  }
  frames <- lapply(selected, function(e) {
    month_name <- e[["month"]]
    if (is.null(month_name) || is.na(month_name)) month_name <- month %||% NA_character_
    entry_year <- suppressWarnings(as.integer(e[["year"]] %||% NA))
    df <- .cpcb_read_repository(e[["filepath"]])
    if (nrow(df) == 0) {
      return(NULL)
    }
    # CPCB writes missing hours as text, which makes the whole column character
    chr <- vapply(df, is.character, logical(1))
    df[chr] <- utils::type.convert(df[chr], as.is = TRUE)
    cbind(
      Year = if (length(entry_year) == 1 && !is.na(entry_year)) entry_year else as.integer(year),
      Month = month_name, df
    )
  })
  dplyr::bind_rows(frames)
}

.cpcb_save <- function(df, save_location) {
  if (nzchar(save_location)) {
    # an interrupted write must not leave a truncated copy that later reads as complete
    partial <- paste0(save_location, ".part")
    on.exit(unlink(partial), add = TRUE)
    utils::write.csv(df, partial, row.names = FALSE)
    if (!file.rename(partial, save_location)) stop("Could not write ", save_location, call. = FALSE)
    cli::cli_alert_success("Saved to {save_location}")
  }
  df
}

# The ID of a name narrowed by city or state, so later lookups cannot be ambiguous
.cpcb_station_id <- function(station, city, state) {
  if (is.null(city) && is.null(state)) {
    return(station)
  }
  .cpcb_require_station(station, city, state)$station_id
}

.cpcb_city_stations <- function(city, state = NULL) {
  stations <- cpcb_station_table(state, city)
  if (nrow(stations) == 0) {
    .vayuayan_abort("vayuayan_not_found", sprintf("City '%s' not found", city))
  }
  if (is.null(state) || !nzchar(state)) {
    # the feed can spell a directory state differently, which is not a second state
    key <- gsub("[^a-z]", "", gsub("&", "and", tolower(stations$state), fixed = TRUE))
    states <- stations$state[!duplicated(key)]
    if (length(states) > 1) .cpcb_abort_ambiguous_city(city, states)
  }
  stations
}

# The stations a batch function was given, or every station of its city
.cpcb_batch_ids <- function(station_id, city, state) {
  if (length(station_id) > 0) {
    return(station_id)
  }
  if (is.null(city) || !nzchar(city)) {
    stop("Give station_id or city", call. = FALSE)
  }
  .cpcb_city_stations(city, state)$station_id
}

.cpcb_is_outage <- function(e) inherits(e, c("curl_error", "http_500"))

.cpcb_station_status <- function(e) {
  if (inherits(e, "vayuayan_ambiguous")) {
    return("ambiguous")
  }
  if (inherits(e, "vayuayan_not_found")) {
    return("not_found")
  }
  if (.cpcb_is_outage(e)) {
    return("outage")
  }
  if (inherits(e, c("vayuayan_data_not_found", "http_404"))) {
    return("no_data")
  }
  "error"
}

# frames stay in the order of ids whatever visit is, so callers can pair them with their stations
.cpcb_each_station <- function(ids, fetch, labels = ids, visit = seq_along(ids)) {
  frames <- vector("list", length(ids))
  status <- stats::setNames(rep("not_attempted", length(ids)), ids)
  outage <- NULL
  for (i in visit) {
    result <- tryCatch(fetch(ids[i]), error = identity)
    if (!inherits(result, "error")) {
      status[i] <- if (is.null(result)) "no_data" else "ok"
      if (!is.null(result)) frames[[i]] <- result
      next
    }
    status[i] <- .cpcb_station_status(result)
    if (status[i] == "outage") {
      outage <- list(station = labels[i], reason = conditionMessage(result))
      break
    }
    cli::cli_alert_warning("Skipped {labels[i]}: {conditionMessage(result)}")
  }
  run <- list(frames = frames, status = status, outage = outage)
  .cpcb_warn_partial(run)
  run
}

.cpcb_status_counts <- function(status) {
  counts <- table(factor(status, c("ok", "no_data", "not_found", "ambiguous", "outage", "not_attempted", "error")))
  counts <- counts[counts > 0]
  paste(sprintf("%d %s", as.integer(counts), names(counts)), collapse = ", ")
}

# Nothing fetched in an outage is raised by the caller, so it needs no warning here
.cpcb_warn_partial <- function(run) {
  fetched <- any(run$status == "ok")
  if (all(run$status == "ok") || (!fetched && !is.null(run$outage))) {
    return(invisible())
  }
  counts <- .cpcb_status_counts(run$status)
  if (is.null(run$outage)) {
    cli::cli_alert_warning("Partial result: {counts}")
  } else {
    cli::cli_alert_warning("CPCB outage stopped the run at {run$outage$station}: {run$outage$reason} ({counts})")
  }
}

# An outage with nothing fetched must not look like a station with no data
.cpcb_check_available <- function(run) {
  if (is.null(run$outage) || any(run$status == "ok")) {
    return(invisible())
  }
  .vayuayan_abort(
    "vayuayan_network",
    sprintf("CPCB is unavailable: %s (%s)", run$outage$reason, .cpcb_status_counts(run$status)),
    station_status = run$status
  )
}

.cpcb_with_status <- function(out, run) {
  attr(out, "station_status") <- run$status
  out
}

#' Raw 15-minute data of several stations
#'
#' @description
#' \code{cpcb_download_raw_station_data(tidy = TRUE)} for several stations or
#' every station of a city, as one long table. Stations without a raw file
#' for the year are skipped with a warning, and an outage stops the run,
#' keeping the stations already fetched. If nothing was fetched in an outage,
#' the function stops with an error of class \code{vayuayan_network}.
#'
#' @param station_id Character vector of station IDs or names, or \code{NULL}
#'   with \code{city}.
#' @param year Integer year.
#' @param pollutants Optional pollutant names to keep, such as
#'   \code{c("PM2.5", "RH")}.
#' @param city Optional city: all its stations when \code{station_id} is
#'   \code{NULL}, otherwise it narrows ambiguous names.
#' @param state Optional state, for cities that share a name.
#' @return Data frame as \code{cpcb_raw_to_long()}, with attribute
#'   \code{station_status}: a named character vector giving each station's
#'   outcome, one of \code{"ok"}, \code{"no_data"}, \code{"not_found"},
#'   \code{"ambiguous"}, \code{"outage"}, \code{"not_attempted"} or
#'   \code{"error"}.
#' @examplesIf interactive()
#' raw <- cpcb_raw_readings(c("site_1554", "site_162"), 2025, "PM2.5")
#' delhi <- cpcb_raw_readings(year = 2025, pollutants = "PM2.5", city = "Delhi")
#' @export
cpcb_raw_readings <- function(station_id = NULL, year, pollutants = NULL, city = NULL, state = NULL) {
  ids <- .cpcb_batch_ids(station_id, city, state)
  run <- .cpcb_each_station(ids, function(id) {
    long <- cpcb_download_raw_station_data(.cpcb_station_id(id, city, state), year, tidy = TRUE)
    if (!is.null(pollutants)) long <- long[long$pollutant %in% pollutants, , drop = FALSE]
    long
  })
  .cpcb_check_available(run)
  out <- dplyr::bind_rows(run$frames)
  if (nrow(out) == 0) {
    out <- cpcb_raw_to_long(data.frame(Timestamp = character()))
  }
  .cpcb_with_status(out, run)
}
