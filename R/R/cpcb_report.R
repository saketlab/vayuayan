# Request key and label of the raw station file; the report heading is the label's name in capitals
.cpcb_report_pollutants <- data.frame(
  key = c("PM25", "PM10", "NO", "NO2", "NOx", "NH3", "SO2", "CO", "Ozone"),
  label = c(
    "PM2.5 (\u00b5g/m\u00b3)", "PM10 (\u00b5g/m\u00b3)", "NO (\u00b5g/m\u00b3)",
    "NO2 (\u00b5g/m\u00b3)", "NOx (ppb)", "NH3 (\u00b5g/m\u00b3)",
    "SO2 (\u00b5g/m\u00b3)", "CO (mg/m\u00b3)", "Ozone (\u00b5g/m\u00b3)"
  ),
  stringsAsFactors = FALSE
)

.cpcb_report_periods <- c(
  "15_minute" = "15M", "15m" = "15M", "30_minute" = "30M", "30m" = "30M",
  hourly = "1H", "1_hour" = "1H", "1h" = "1H", "4_hour" = "4H", "4h" = "4H",
  "8_hour" = "8H", "8h" = "8H", daily = "24H", "24_hours" = "24H", "24h" = "24H", "1d" = "24H"
)

.cpcb_report_call_id <- "get-real-time-report-excel"

.cpcb_report_url <- function() paste0(.cpcb_base_url, "/cpcb-common-report/api/excel/export")
.cpcb_report_accept <- "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
.cpcb_report_connections <- 6

# The current time of the request; mocked so the request body can be pinned
.cpcb_now <- function() Sys.time()

.cpcb_report_plain <- function(x) toupper(gsub("[^[:alnum:]]", "", x))

.cpcb_report_headings <- function() toupper(.aqi_split_label(.cpcb_report_pollutants$label))

.cpcb_report_key <- function(name) {
  wanted <- .cpcb_report_plain(name)
  if (wanted == "O3") wanted <- "OZONE"
  keys <- .cpcb_report_pollutants$key
  hit <- which(.cpcb_report_plain(keys) == wanted)
  if (length(hit) == 0) {
    stop(sprintf(
      "'%s' is not a pollutant of the CPCB report: %s", name, paste(.cpcb_report_headings(), collapse = ", ")
    ), call. = FALSE)
  }
  keys[hit]
}

.cpcb_report_time <- function(x, arg) {
  parsed <- .parse_timestamp(x)
  if (length(parsed) != 1 || is.na(parsed)) {
    stop(sprintf("'%s' is not a date or time", arg), call. = FALSE)
  }
  format(parsed, "%Y-%m-%d %H:%M:%S")
}

.cpcb_report_payload <- function(station, start, end, frequency, pollutants) {
  period <- .cpcb_report_periods[tolower(frequency)]
  if (length(period) != 1 || is.na(period)) {
    stop(sprintf(
      "'%s' is not a report frequency: %s", frequency,
      paste(names(.cpcb_report_periods), collapse = ", ")
    ), call. = FALSE)
  }
  names_wanted <- pollutants %||% .cpcb_report_pollutants$key
  if (length(names_wanted) == 0) {
    stop("pollutants is empty", call. = FALSE)
  }
  keys <- unique(vapply(names_wanted, .cpcb_report_key, "", USE.NAMES = FALSE))
  parameters <- paste(keys, collapse = ",")
  now <- .cpcb_now()
  list(
    reportDate = format(now, "%d-%m-%Y"),
    reportTime = format(now, "%H:%M:%S"),
    stationId = station$station_id,
    state = station$state,
    city = station$city,
    station = station$station_name,
    parameters = parameters,
    columns = paste0("from_time,to_time,", parameters),
    avgPeriod = unname(period),
    fromDate = .cpcb_report_time(start, "start"),
    toDate = .cpcb_report_time(end, "end"),
    callid = .cpcb_report_call_id,
    templateId = .cpcb_report_call_id,
    callIdArguments = "stationId,fromDate,toDate,avgPeriod,parameters"
  )
}

# The readings of an export file, with the columns of the raw station file
.cpcb_parse_report <- function(body) {
  if (length(body) < 2 || !identical(body[1:2], charToRaw("PK"))) {
    .vayuayan_abort("vayuayan_parse", "CPCB sent no usable report")
  }
  path <- tempfile(fileext = ".xlsx")
  on.exit(unlink(path), add = TRUE)
  writeBin(body, path)
  sheet <- tryCatch(
    as.data.frame(readxl::read_excel(path, col_names = FALSE, col_types = "text", .name_repair = "minimal")),
    error = function(e) .vayuayan_abort("vayuayan_parse", "CPCB sent no usable report")
  )
  first <- trimws(as.character(sheet[[1]]))
  header <- which(first == "From Date")[1]
  if (is.na(header)) {
    .vayuayan_abort("vayuayan_parse", "CPCB sent a report without a data table")
  }
  rows <- if (header < nrow(sheet)) (header + 1):nrow(sheet) else integer(0)
  times <- as.POSIXct(first[rows], tz = "UTC", format = "%d-%m-%Y %H:%M")
  # the footer rows after the data have no date in this column
  ended <- which(is.na(times))
  n <- if (length(ended)) ended[1] - 1L else length(times)
  times <- times[seq_len(n)]
  rows <- rows[seq_len(n)]

  table <- data.frame(
    Timestamp = format(times, "%Y-%m-%d %H:%M:%S"), stringsAsFactors = FALSE, check.names = FALSE
  )
  headings <- toupper(.aqi_split_label(as.character(unlist(sheet[header, , drop = FALSE]))))
  hit <- match(headings, .cpcb_report_headings())
  for (i in which(!is.na(hit))) {
    table[[.cpcb_report_pollutants$label[hit[i]]]] <- .to_numeric(sheet[[i]][rows])
  }
  if (sum(!is.na(unlist(table[-1]))) == 0) {
    .vayuayan_abort("vayuayan_data_not_found", "CPCB has no readings for this report")
  }
  table
}

#' Station data from CPCB's report export
#'
#' @description
#' Download a station's readings for any period from CPCB's report export,
#' which needs no login. The result has the columns of the raw station file,
#' so \code{cpcb_raw_to_long()} and \code{tidy = TRUE} work the same way.
#' Reports are never cached.
#'
#' CPCB includes the periods that end at or before \code{end}: a whole day
#' needs \code{end} at the next day's 00:00. The export holds recent readings
#' only; an older period comes back blank, which is reported as no data. Use
#' \code{cpcb_download_raw_station_data()} for past years.
#'
#' @param station_id Character. Station ID (e.g. \code{"site_301"}) or name. Part of a
#'   name is enough when it picks one station.
#' @param start,end First and last time: text, \code{Date} or \code{POSIXct},
#'   in Indian Standard Time. A date alone means its 00:00.
#' @param frequency Character. \code{"15_minute"} (default), \code{"30_minute"},
#'   \code{"hourly"}, \code{"4_hour"}, \code{"8_hour"} or \code{"daily"}, or
#'   CPCB's codes 15M, 30M, 1H, 4H, 8H and 24H.
#' @param pollutants Optional character vector of pollutants such as
#'   \code{c("PM2.5", "NOx", "Ozone")}; defaults to all nine of the report.
#' @param save_location Character. CSV path to save the result to; \code{""}
#'   saves nothing.
#' @param tidy Logical. If \code{TRUE}, return (and save) long rows from
#'   \code{cpcb_raw_to_long()} instead of the wide table.
#' @param city,state Optional city and state that narrow an ambiguous station
#'   name. State applies only together with city.
#' @return Data frame with \code{Timestamp} (the start of each period) and one
#'   \code{"<name> (<unit>)"} column per pollutant, or long rows when
#'   \code{tidy = TRUE}.
#' @examplesIf interactive()
#' cpcb_download_station_report("Anand Vihar, Delhi", "2026-11-01", "2026-11-02", pollutants = "PM2.5")
#' @export
cpcb_download_station_report <- function(station_id, start, end, frequency = "15_minute",
                                         pollutants = NULL, save_location = "", tidy = FALSE,
                                         city = NULL, state = NULL) {
  station <- .cpcb_require_station(station_id, city, state)
  payload <- .cpcb_report_payload(station, start, end, frequency, pollutants)
  # 500 means CPCB cannot build this report, so a retry cannot help
  res <- .cpcb_request(
    "POST", .cpcb_report_url(),
    body = .cpcb_report_json(payload), encode = "raw",
    httr::add_headers(`Content-Type` = "application/json", Accept = .cpcb_report_accept),
    httr::timeout(60), terminate_on = 400:599, times = 4
  )
  if (httr::status_code(res) == 500) {
    .vayuayan_abort("vayuayan_data_not_found", "CPCB could not build this report")
  }
  httr::stop_for_status(res)
  df <- .cpcb_parse_report(httr::content(res, as = "raw"))
  if (tidy) {
    df <- cpcb_raw_to_long(df, station)
  }
  .cpcb_save(df, save_location)
}

#' Report export of every station of a city
#'
#' @description
#' \code{cpcb_download_station_report()} for each station of a city, as one
#' table, with the requests sent in parallel. A station that gets no report
#' is skipped with a warning, and an outage stops the run, keeping the
#' stations already fetched. If nothing was fetched in an outage, the function
#' stops with an error of class \code{vayuayan_network}.
#'
#' @param city Character. City name or code.
#' @param start,end,frequency,pollutants,tidy As in
#'   \code{cpcb_download_station_report()}.
#' @param state Optional state name or code, needed for a city name used in
#'   more than one state.
#' @param save_location Path to save the CSV. If empty, no file is saved.
#' @return The table of \code{cpcb_download_station_report()} for each station.
#'   The wide table starts with \code{station_id} and \code{station_name}.
#'   Attribute \code{station_status} gives each station's outcome, as in
#'   \code{cpcb_raw_readings()}.
#' @examplesIf interactive()
#' delhi <- cpcb_download_city_report("Delhi", "2026-11-08", "2026-11-09",
#'   frequency = "hourly", pollutants = "PM2.5"
#' )
#' @export
cpcb_download_city_report <- function(city, start, end, frequency = "15_minute",
                                      pollutants = NULL, state = NULL,
                                      save_location = "", tidy = FALSE) {
  stations <- .cpcb_city_stations(city, state)
  rows <- lapply(seq_len(nrow(stations)), function(i) as.list(stations[i, ]))
  payloads <- lapply(rows, .cpcb_report_payload, start = start, end = end, frequency = frequency, pollutants = pollutants)
  replies <- .cpcb_report_pool(payloads)

  # stations the pool answered go first, so an outage on the rest cannot lose them
  answered <- vapply(replies, function(r) isTRUE(r$status_code %in% c(200, 500)), TRUE)
  run <- .cpcb_each_station(
    stations$station_id,
    function(id) {
      i <- match(id, stations$station_id)
      status <- replies[[i]]$status_code
      # 500 means CPCB cannot build this report, so a retry cannot help
      if (isTRUE(status == 500)) {
        .vayuayan_abort("vayuayan_data_not_found", "CPCB could not build this report")
      }
      if (!isTRUE(status == 200)) {
        return(cpcb_download_station_report(id, start, end, frequency, pollutants, tidy = tidy))
      }
      df <- .cpcb_parse_report(replies[[i]]$content)
      if (tidy) cpcb_raw_to_long(df, rows[[i]]) else df
    },
    stations$station_name,
    visit = c(which(answered), which(!answered))
  )
  .cpcb_check_available(run)
  frames <- run$frames
  if (!tidy) {
    frames <- Map(function(df, id, name) {
      if (!is.null(df)) cbind(station_id = id, station_name = name, df)
    }, frames, stations$station_id, stations$station_name)
  }
  out <- dplyr::bind_rows(frames)
  if (nrow(out) == 0) {
    .vayuayan_abort(
      "vayuayan_data_not_found",
      sprintf("CPCB has no report for city '%s'", city),
      station_status = run$status
    )
  }
  .cpcb_save(.cpcb_with_status(out, run), save_location)
}

.cpcb_report_json <- function(payload) as.character(jsonlite::toJSON(payload, auto_unbox = TRUE))

# One reply per payload in order, NULL for a transfer that failed
.cpcb_report_pool <- function(payloads) {
  n_con <- .cpcb_report_connections
  pool <- curl::new_pool(total_con = n_con, host_con = n_con, multiplex = FALSE)
  replies <- vector("list", length(payloads))
  insecure <- isTRUE(.cpcb_cache$insecure)
  # libcurl counts the time a request waits for a free connection
  timeout <- 60 * ceiling(length(payloads) / n_con)
  for (i in seq_along(payloads)) {
    local({
      slot <- i
      handle <- curl::new_handle(url = .cpcb_report_url())
      curl::handle_setopt(
        handle,
        copypostfields = .cpcb_report_json(payloads[[slot]]),
        timeout = timeout,
        ssl_verifypeer = if (insecure) 0L else 1L,
        ssl_verifyhost = if (insecure) 0L else 2L
      )
      curl::handle_setheaders(handle, "Content-Type" = "application/json", Accept = .cpcb_report_accept)
      curl::multi_add(
        handle,
        done = function(reply) replies[[slot]] <<- reply,
        fail = function(message) invisible(),
        pool = pool
      )
    })
  }
  curl::multi_run(pool = pool)
  replies
}
