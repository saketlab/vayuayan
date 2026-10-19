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
#' @return Data frame of observations.
#' @examplesIf interactive()
#' raw <- cpcb_download_raw_station_data("site_301", 2024, tidy = TRUE)
#' @export
cpcb_download_raw_station_data <- function(station_id, year, save_location = "",
                                           frequency = "15_minute", tidy = FALSE) {
  station <- .cpcb_require_station(station_id)
  files <- cpcb_get_file_path(
    station_id = station$station_id,
    station_name = station$station_name,
    state = station$state,
    city = station$city,
    year = year,
    frequency = frequency,
    data_type = "raw"
  )
  if (length(files) == 0) {
    stop(sprintf("Raw data not found for station %s in year %s", station$station_name, year),
      call. = FALSE
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
#' @param city Character. City name.
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
cpcb_download_hourly_city_data <- function(city, year, save_location = "", month = NULL) {
  files <- cpcb_get_file_path(
    city = city, year = year, frequency = "hourly", data_type = "cityLevel"
  )
  .cpcb_save(.cpcb_combine_months(files, year, month), save_location)
}

#' @rdname cpcb_download_hourly
#' @export
cpcb_download_hourly_station_data <- function(station_id, year, save_location = "",
                                              month = NULL) {
  station <- .cpcb_require_station(station_id)
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
#' NAQI with \code{daily_aqi()}.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station (e.g. \code{"Anand Vihar, Delhi"}).
#' @param year Integer year.
#' @param day_ends_at Hour at which each day's 24 hours end; 16 matches CPCB's
#'   4 PM bulletin.
#' @return Data frame as returned by \code{daily_aqi()}, limited to dates in
#'   \code{year}.
#' @examplesIf interactive()
#' anand_vihar <- cpcb_station_daily_aqi("Anand Vihar, Delhi", 2024, day_ends_at = 16)
#' @export
cpcb_station_daily_aqi <- function(station_id, year, day_ends_at = 24) {
  long <- cpcb_download_raw_station_data(station_id, year, tidy = TRUE)
  daily <- daily_aqi(long, day_ends_at = day_ends_at)
  # a window ending on 1 January of the next year is not in this year
  daily[format(daily$date, "%Y") == as.character(year), , drop = FALSE]
}

.cpcb_combine_months <- function(files, year, month = NULL) {
  selected <- if (!is.null(month)) {
    Filter(function(e) {
      isTRUE(tolower(e[["month"]] %||% "") == tolower(month)) ||
        grepl(tolower(month), tolower(e[["filepath"]]), fixed = TRUE)
    }, files)
  } else {
    in_year <- Filter(function(e) identical(as.character(e[["year"]]), as.character(year)), files)
    if (length(in_year)) in_year else files
  }
  if (length(selected) == 0) {
    stop(sprintf(
      "Data not found for year %s%s", year,
      if (is.null(month)) "" else paste(" and month", month)
    ), call. = FALSE)
  }
  frames <- lapply(selected, function(e) {
    month_name <- e[["month"]]
    if (is.null(month_name) || is.na(month_name)) month_name <- month %||% NA_character_
    entry_year <- suppressWarnings(as.integer(e[["year"]] %||% NA))
    df <- .cpcb_read_repository(e[["filepath"]])
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
    utils::write.csv(df, save_location, row.names = FALSE)
    cli::cli_alert_success("Saved to {save_location}")
  }
  df
}

#' Raw 15-minute data of several stations
#'
#' @description
#' \code{cpcb_download_raw_station_data(tidy = TRUE)} for several stations,
#' as one long table. Stations without a raw file for the year are skipped
#' with a warning.
#'
#' @param station_id Character vector of station IDs or names.
#' @param year Integer year.
#' @param pollutants Optional pollutant names to keep, such as
#'   \code{c("PM2.5", "RH")}.
#' @return Data frame as \code{cpcb_raw_to_long()}.
#' @examplesIf interactive()
#' raw <- cpcb_raw_readings(c("site_1554", "site_162"), 2025, "PM2.5")
#' @export
cpcb_raw_readings <- function(station_id, year, pollutants = NULL) {
  frames <- lapply(station_id, function(id) {
    long <- tryCatch(
      cpcb_download_raw_station_data(id, year, tidy = TRUE),
      error = function(e) {
        cli::cli_alert_warning("Skipped {id}: {conditionMessage(e)}")
        NULL
      }
    )
    if (!is.null(long) && !is.null(pollutants)) long <- long[long$pollutant %in% pollutants, , drop = FALSE]
    long
  })
  out <- dplyr::bind_rows(frames)
  if (nrow(out) == 0) {
    return(cpcb_raw_to_long(data.frame(Timestamp = character())))
  }
  out
}
