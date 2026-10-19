#' Reshape a CPCB daily sheet to long format
#'
#' @description
#' CPCB daily files have one row per day of the month and one column per
#' month. This turns that sheet into one row per day.
#'
#' @param x Data frame from a CPCB daily file, or the path to a CSV written by
#'   \code{cpcb_download_city_data()} or \code{cpcb_download_station_data()}.
#' @param year Optional year of the sheet. When given, a \code{date} column
#'   is added and impossible dates (31 February) are dropped.
#' @return Data frame with integer columns \code{day} and \code{month},
#'   numeric \code{value}, and \code{date} when \code{year} is given. Days
#'   without a reading are dropped.
#' @examples
#' sheet <- data.frame(Day = 1:2, January = c(180, NA), February = c(150, 140))
#' cpcb_tidy_daily(sheet)
#' cpcb_tidy_daily(sheet, year = 2024)
#' @export
cpcb_tidy_daily <- function(x, year = NULL) {
  if (is.character(x)) {
    x <- utils::read.csv(x, check.names = FALSE)
  }
  months <- match(names(x)[-1], month.name)
  keep <- which(!is.na(months))
  out <- data.frame(
    day = rep(as.integer(x[[1]]), length(keep)),
    month = rep(months[keep], each = nrow(x)),
    value = suppressWarnings(as.numeric(unlist(x[keep + 1], use.names = FALSE)))
  )
  out <- out[!is.na(out$value) & !is.na(out$day), , drop = FALSE]
  if (!is.null(year)) {
    out$date <- as.Date(sprintf("%d-%02d-%02d", as.integer(year), out$month, out$day),
      optional = TRUE
    )
    out <- out[!is.na(out$date), , drop = FALSE]
    out <- out[order(out$date), , drop = FALSE]
  }
  rownames(out) <- NULL
  out
}

#' Reshape raw CPCB station data to long format
#'
#' @description
#' Turn a raw CPCB station file, with a \code{Timestamp} column and one
#' \code{"<name> (<unit>)"} column per pollutant, into one row per time and
#' pollutant.
#'
#' @param raw Data frame as returned by \code{cpcb_download_raw_station_data()}.
#' @param station Optional named list with \code{station_id},
#'   \code{station_name}, \code{city} and \code{state} for every row.
#' @param start_date,end_date Optional first and last dates to keep
#'   (inclusive).
#' @return Data frame with columns \code{station_id}, \code{station_name},
#'   \code{city}, \code{state}, \code{timestamp} (POSIXct, UTC),
#'   \code{pollutant}, \code{unit} and \code{value}, sorted by time and
#'   pollutant. Rows without a time or a numeric value are dropped.
#' @examples
#' raw <- data.frame(
#'   Timestamp = c("2024-01-01 00:00:00", "2024-01-01 00:15:00"),
#'   "PM2.5 (ug/m3)" = c(158, 160), "CO (mg/m3)" = c(1.6, NA),
#'   check.names = FALSE
#' )
#' cpcb_raw_to_long(raw, station = list(station_id = "site_301"))
#' @export
cpcb_raw_to_long <- function(raw, station = NULL, start_date = NULL, end_date = NULL) {
  if (!"Timestamp" %in% names(raw)) {
    stop("Raw CPCB data did not contain a Timestamp column", call. = FALSE)
  }
  ts <- .parse_timestamp(raw$Timestamp)
  keep <- !is.na(ts)
  if (!is.null(start_date)) keep <- keep & ts >= as.POSIXct(as.Date(start_date))
  if (!is.null(end_date)) keep <- keep & ts < as.POSIXct(as.Date(end_date) + 1)
  raw <- raw[keep, , drop = FALSE]
  ts <- ts[keep]

  labels <- setdiff(names(raw), "Timestamp")
  parts <- regmatches(labels, regexec("^\\s*(.*?)\\s*(?:\\((.*?)\\))?\\s*$", labels, perl = TRUE))
  long <- data.frame(
    timestamp = rep(ts, length(labels)),
    pollutant = rep(vapply(parts, `[`, "", 2), each = length(ts)),
    unit = rep(vapply(parts, `[`, "", 3), each = length(ts)),
    value = suppressWarnings(as.numeric(unlist(raw[labels], use.names = FALSE))),
    stringsAsFactors = FALSE
  )
  long <- long[!is.na(long$value), , drop = FALSE]
  long <- long[order(long$timestamp, long$pollutant, method = "radix"), , drop = FALSE]

  n <- nrow(long)
  out <- data.frame(
    station_id = rep(station$station_id %||% "", n),
    station_name = rep(station$station_name %||% "", n),
    city = rep(station$city %||% "", n),
    state = rep(station$state %||% "", n),
    long,
    stringsAsFactors = FALSE
  )
  out[c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value")]
}

#' Daily city-level AQI in long format
#'
#' @description
#' Download (or reuse) the CPCB daily city file for each city and year and
#' return it in long format. CPCB files of past years are cached in
#' \code{vayuayan_cache_dir()}. With \code{cache_dir}, each sheet is also
#' saved as \code{<city>_aqi_<year>.csv} there and read back on later calls.
#'
#' @param city Character vector of city names.
#' @param year Integer year.
#' @param cache_dir Optional directory for CSV copies of the sheets.
#' @return Data frame with columns \code{city}, \code{day}, \code{month} and
#'   \code{value}.
#' @examplesIf interactive()
#' daily <- cpcb_city_daily(c("Delhi", "Mumbai"), 2022)
#' aggregate(value ~ city + month, daily, mean)
#' @export
cpcb_city_daily <- function(city, year,
                            cache_dir = NULL) {
  per_city <- lapply(city, function(name) {
    path <- .cpcb_csv_copy(cache_dir, sprintf("%s_aqi_%s.csv", tolower(name), year))
    if (!file.exists(path)) {
      cpcb_download_city_data(name, year, path)
    }
    cbind(city = name, cpcb_tidy_daily(path))
  })
  do.call(rbind, per_city)
}

#' Daily station-level AQI in long format
#'
#' @description
#' Download (or reuse) the CPCB daily file for each station and year and
#' return them in one long table. CPCB files of past years are cached in
#' \code{vayuayan_cache_dir()}. With \code{cache_dir}, each sheet is also
#' saved as \code{<station_id>_<year>.csv} there. Stations that are not found
#' or have no data for the year are skipped with a warning.
#'
#' @param station_id Character vector of station IDs or names, for example
#'   the \code{value} or \code{label} column of \code{cpcb_get_station_list()}.
#'   Part of a name is enough when it picks one station.
#' @param year Integer year.
#' @param cache_dir Optional directory for CSV copies of the sheets.
#' @return Data frame with columns \code{station_id}, \code{station_name},
#'   \code{day}, \code{month} and \code{value}.
#' @examplesIf interactive()
#' daily <- cpcb_station_daily(c("Anand Vihar, Delhi", "ITO, Delhi"), 2024)
#' @export
cpcb_station_daily <- function(station_id, year,
                               cache_dir = NULL) {
  per_station <- lapply(station_id, function(name) {
    tryCatch(
      {
        station <- .cpcb_require_station(name)
        id <- station$station_id
        path <- .cpcb_csv_copy(cache_dir, sprintf("%s_%s.csv", id, year))
        if (!file.exists(path)) {
          cpcb_download_station_data(id, year, path)
        }
        cbind(station_id = id, station_name = station$station_name, cpcb_tidy_daily(path))
      },
      error = function(e) {
        cli::cli_alert_warning("Skipped {name}: {conditionMessage(e)}")
        NULL
      }
    )
  })
  do.call(rbind, per_station)
}

# per-element parse, so one malformed value does not void the column
.parse_timestamp <- function(x) {
  if (inherits(x, "POSIXct")) {
    return(x)
  }
  x <- as.character(x)
  out <- as.POSIXct(x, tz = "UTC", format = "%Y-%m-%d %H:%M:%OS")
  for (fmt in c("%Y-%m-%dT%H:%M:%OS", "%Y-%m-%d %H:%M", "%Y-%m-%d")) {
    miss <- is.na(out) & !is.na(x)
    if (!any(miss)) break
    out[miss] <- as.POSIXct(x[miss], tz = "UTC", format = fmt)
  }
  out
}

# CSV path in cache_dir, or a session temp file when cache_dir is NULL
.cpcb_csv_copy <- function(cache_dir, name) {
  if (is.null(cache_dir)) {
    return(file.path(tempdir(), name))
  }
  dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
  file.path(cache_dir, name)
}

#' Recent hours of live CPCB data in long format
#'
#' @description
#' Turn the \code{last_hours} series of live station data (one series of
#' \code{date}/\code{val} points per pollutant) into one row per time and
#' pollutant. The CPCB feed has no recent hours, so the result is empty for
#' feed data.
#'
#' @param aqi_data List from \code{cpcb_get_live_aqi_data()}.
#' @param station_id Optional station ID for every row.
#' @return Data frame with columns \code{station_id}, \code{timestamp}
#'   (POSIXct, UTC), \code{pollutant} and \code{value}, sorted by pollutant
#'   and time.
#' @examples
#' cpcb_live_to_long(list(station_id = "site_301", last_hours = list(
#'   list(name = "PM2.5", data = list(list(date = "2024-01-01 10:00:00", val = 80)))
#' )))
#' @export
cpcb_live_to_long <- function(aqi_data, station_id = "") {
  field <- function(points, name) {
    vapply(points, function(p) as.character(p[[name]] %||% NA), "")
  }
  rows <- lapply(aqi_data$last_hours, function(s) {
    data.frame(
      timestamp = field(s$data, "date"),
      pollutant = rep(as.character(s$name %||% NA), length(s$data)),
      value = suppressWarnings(as.numeric(field(s$data, "val")))
    )
  })
  long <- do.call(rbind, c(
    list(data.frame(timestamp = character(), pollutant = character(), value = numeric())),
    rows
  ))
  long$timestamp <- .parse_timestamp(long$timestamp)
  id <- if (nzchar(station_id)) station_id else aqi_data$station_id %||% ""
  long <- data.frame(station_id = rep(id, nrow(long)), long, stringsAsFactors = FALSE)
  long <- long[!is.na(long$timestamp) & !is.na(long$value), , drop = FALSE]
  long <- long[order(long$pollutant, long$timestamp, method = "radix"), , drop = FALSE]
  rownames(long) <- NULL
  long
}

#' Latest pollutant averages of live CPCB data
#'
#' @description
#' The \code{metrics} of live station data as a table with numeric columns.
#'
#' @param aqi_data List from \code{cpcb_get_live_aqi_data()}.
#' @return Data frame with columns \code{pollutant}, \code{avg}, \code{min},
#'   \code{max} (numeric, \code{NA} where CPCB has none) and \code{period},
#'   one row per pollutant.
#' @examples
#' cpcb_live_metrics(list(metrics = data.frame(
#'   name = "PM2.5", avg = "80", min = 60, max = "NA", avgDesc = "Over the last 24 hours"
#' )))
#' @export
cpcb_live_metrics <- function(aqi_data) {
  m <- aqi_data$metrics
  if (!is.data.frame(m) || nrow(m) == 0) {
    return(data.frame(
      pollutant = character(), avg = numeric(), min = numeric(),
      max = numeric(), period = character()
    ))
  }
  num <- function(x) suppressWarnings(as.numeric(x %||% NA))
  data.frame(
    pollutant = as.character(m$name), avg = num(m$avg), min = num(m$min),
    max = num(m$max), period = as.character(m$avgDesc %||% NA),
    stringsAsFactors = FALSE
  )
}
