# CPCB's report export: the exact request, the Excel parsing and the failures.

report_url <- "https://airquality.cpcb.gov.in/cpcb-common-report/api/excel/export"
report_now <- as.POSIXct("2026-11-09 10:03:37", tz = "UTC")
all_keys <- "PM25,PM10,NO,NO2,NOx,NH3,SO2,CO,Ozone"
all_labels <- c(
  "PM2.5 (µg/m³)", "PM10 (µg/m³)", "NO (µg/m³)",
  "NO2 (µg/m³)", "NOx (ppb)", "NH3 (µg/m³)",
  "SO2 (µg/m³)", "CO (mg/m³)", "Ozone (µg/m³)"
)
headings <- c("From Date", "To Date", "PM2.5", "PM10", "NO", "NO2", "NOX", "NH3", "SO2", "CO", "OZONE")

# The real export of site_301 for 2026-10-25
xlsx_bytes <- function() {
  path <- test_path("fixtures", "station_report.xlsx")
  readBin(path, "raw", file.size(path))
}
xlsx_response <- function() fake_response(200, xlsx_bytes())

# A sheet read_excel would return: header rows, then the rows given
mock_sheet <- function(rows, .env = parent.frame()) {
  sheet <- as.data.frame(
    rbind(
      c("CENTRAL POLLUTION CONTROL BOARD", rep(NA, 10)),
      c("State", NA, "Delhi", rep(NA, 8)),
      headings,
      do.call(rbind, rows)
    ),
    stringsAsFactors = FALSE
  )
  testthat::local_mocked_bindings(read_excel = function(...) sheet, .package = "readxl", .env = .env)
}

local_report <- function(..., .env = parent.frame()) {
  local_cpcb(.env = .env)
  testthat::local_mocked_bindings(.cpcb_now = function() report_now, .env = .env)
  local_http(..., .env = .env)
}

test_that("the report request has the exact URL, method, headers and body", {
  log <- local_report(xlsx_response())
  cpcb_download_station_report("site_301", "2026-11-01 00:00:00", "2026-11-01 06:00:00")

  expect_length(log$calls, 1L)
  call <- log$calls[[1]]
  expect_equal(call$method, "POST")
  expect_equal(call$url, report_url)
  expect_equal(call$encode, "raw")
  expect_equal(call$headers[["Content-Type"]], "application/json")
  expect_equal(
    call$headers[["Accept"]],
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
  )
  expect_false("Authorization" %in% names(call$headers))
  expect_equal(jsonlite::fromJSON(call$body), list(
    reportDate = "09-11-2026",
    reportTime = "10:03:37",
    stationId = "site_301",
    state = "Delhi",
    city = "Delhi",
    station = "Anand Vihar, Delhi - DPCC",
    parameters = all_keys,
    columns = paste0("from_time,to_time,", all_keys),
    avgPeriod = "15M",
    fromDate = "2026-11-01 00:00:00",
    toDate = "2026-11-01 06:00:00",
    callid = "get-real-time-report-excel",
    templateId = "get-real-time-report-excel",
    callIdArguments = "stationId,fromDate,toDate,avgPeriod,parameters"
  ))
})

test_that("a real export has the raw file's columns and values", {
  local_report(xlsx_response())
  df <- cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26")
  expect_named(df, c("Timestamp", all_labels))
  expect_equal(nrow(df), 96L)
  expect_equal(df$Timestamp[1], "2026-10-25 00:00:00")
  expect_equal(df$Timestamp[96], "2026-10-25 23:45:00")
  expect_equal(
    unlist(df[1, -1], use.names = FALSE),
    c(35, 172, 4.4, 14.5, 11.3, 23.2, 16.6, 0.23, 22)
  )
  # blank cells are missing, as the 00:15 NO of this day
  expect_true(is.na(df[["NO (µg/m³)"]][2]))
})

test_that("report rows stop at the footer, and blank cells are missing", {
  mock_sheet(list(
    c("01-11-2025 00:00", "01-11-2025 00:15", rep(NA, 9)),
    c("01-11-2025 00:15", "01-11-2025 00:30", 146, 309, 165.2, 103, 189.1, 0.1, 61.8, NA, 19),
    c("Average", rep(NA, 10)),
    c("01-11-2025 00:45", "01-11-2025 01:00", 1, 1, 1, 1, 1, 1, 1, 1, 1)
  ))
  local_report(fake_response(200, as.raw(c(0x50, 0x4b, 1, 2))))
  df <- cpcb_download_station_report("site_301", "2025-11-01", "2025-11-02")
  expect_equal(df$Timestamp, c("2025-11-01 00:00:00", "2025-11-01 00:15:00"))
  expect_equal(df[["PM2.5 (µg/m³)"]], c(NA, 146))
  expect_equal(df[["CO (mg/m³)"]], c(NA_real_, NA_real_))
})

test_that("tidy = TRUE gives the rows of cpcb_raw_to_long, and save_location writes", {
  local_report(xlsx_response(), xlsx_response())
  path <- tempfile(fileext = ".csv")
  long <- suppressMessages(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26", tidy = TRUE, save_location = path))
  expect_named(long, c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value"))
  expect_true(file.exists(path))
  expect_equal(unique(long$station_id), "site_301")
  expect_equal(unique(long$unit[long$pollutant == "CO"]), "mg/m³")
  expect_equal(unique(long$unit[long$pollutant == "NOx"]), "ppb")
  wide <- cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26")
  expect_equal(long, cpcb_raw_to_long(wide, list(
    station_id = "site_301", station_name = "Anand Vihar, Delhi - DPCC", city = "Delhi", state = "Delhi"
  )))
})

test_that("frequency names map to CPCB's codes and unknown ones fail", {
  cases <- c(
    "15_minute" = "15M", "30_minute" = "30M", hourly = "1H", "4_hour" = "4H",
    "8_hour" = "8H", daily = "24H", "1H" = "1H", "24H" = "24H", "1d" = "24H"
  )
  for (name in names(cases)) {
    log <- local_report(xlsx_response())
    cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26", frequency = name)
    expect_equal(jsonlite::fromJSON(log$calls[[1]]$body)$avgPeriod, unname(cases[[name]]), info = name)
  }
  local_report()
  expect_error(cpcb_download_station_report("site_301", "a", "b", frequency = "weekly"), "report frequency")
})

test_that("pollutants pick request keys, drop duplicates and reject others", {
  log <- local_report(xlsx_response())
  df <- cpcb_download_station_report(
    "site_301", "2026-10-25", "2026-10-26",
    pollutants = c("PM2.5", "nox", "O3", "Ozone")
  )
  body <- jsonlite::fromJSON(log$calls[[1]]$body)
  expect_equal(body$parameters, "PM25,NOx,Ozone")
  expect_equal(body$columns, "from_time,to_time,PM25,NOx,Ozone")
  # the table has what CPCB sent; the fixture holds all nine
  expect_named(df, c("Timestamp", all_labels))
  local_report()
  expect_error(cpcb_download_station_report("site_301", "a", "b", pollutants = "Benzene"), "not a pollutant")
  expect_error(cpcb_download_station_report("site_301", "a", "b", pollutants = character(0)), "pollutants is empty")
})

test_that("dates and times of several kinds are formatted for the request", {
  log <- local_report(xlsx_response(), xlsx_response())
  cpcb_download_station_report("site_301", as.Date("2026-10-25"), as.POSIXct("2026-10-26 06:30:00", tz = "UTC"))
  body <- jsonlite::fromJSON(log$calls[[1]]$body)
  expect_equal(c(body$fromDate, body$toDate), c("2026-10-25 00:00:00", "2026-10-26 06:30:00"))

  cpcb_download_station_report("site_301", "2026-10-25 06:30", "2026-10-26")
  body <- jsonlite::fromJSON(log$calls[[2]]$body)
  expect_equal(c(body$fromDate, body$toDate), c("2026-10-25 06:30:00", "2026-10-26 00:00:00"))

  local_report()
  expect_error(cpcb_download_station_report("site_301", "not a date", "2026-10-26"), "'start' is not a date")
  expect_error(cpcb_download_station_report("site_301", "2026-10-26", NA), "'end' is not a date")
})

test_that("a station that is not found stops as elsewhere", {
  local_cpcb()
  local_http(connection_error())
  expect_error(cpcb_download_station_report("nosuch", "2026-10-25", "2026-10-26"), "Station 'nosuch' not found")
})

test_that("failures from CPCB stop with a clear message", {
  local_report(fake_response(500, "Excel generation failed"))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "could not build this report")

  local_report(fake_response(503, ""))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"))

  local_report(connection_error())
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "Could not resolve host")
})

test_that("an unusable body or no readings stops", {
  local_report(fake_response(200, "<html>sorry</html>"))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "no usable report")

  local_report(fake_response(200, as.raw(c(0x50, 0x4b, 1, 2))))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "no usable report")

  local_report(fake_response(200, raw(0)))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "no usable report")
})

test_that("a sheet without the table or without readings stops", {
  testthat::local_mocked_bindings(
    read_excel = function(...) data.frame(a = c("CENTRAL POLLUTION", "State"), b = c(NA, NA)),
    .package = "readxl"
  )
  local_report(fake_response(200, as.raw(c(0x50, 0x4b, 1, 2))))
  expect_error(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "without a data table")

  # an old period comes back with every reading blank
  mock_sheet(list(c("15-03-2024 00:00", "15-03-2024 00:15", rep(NA, 9))))
  local_report(fake_response(200, as.raw(c(0x50, 0x4b, 1, 2))))
  expect_error(cpcb_download_station_report("site_301", "2024-03-15", "2024-03-16"), "no readings")

  # nothing after the header row
  testthat::local_mocked_bindings(
    read_excel = function(...) as.data.frame(rbind(headings), stringsAsFactors = FALSE),
    .package = "readxl"
  )
  local_report(fake_response(200, as.raw(c(0x50, 0x4b, 1, 2))))
  expect_error(cpcb_download_station_report("site_301", "2024-03-15", "2024-03-16"), "no readings")
})

test_that("a report with only some pollutants keeps those columns", {
  sheet <- as.data.frame(rbind(
    c("From Date", "To Date", "NO2", "PM2.5"),
    c("01-11-2026 00:00", "01-11-2026 00:15", "10", "20")
  ), stringsAsFactors = FALSE)
  local_mocked_bindings(read_excel = function(path, ...) sheet, .package = "readxl")
  out <- .cpcb_parse_report(charToRaw("PK"))
  expect_setequal(names(out), c("Timestamp", "NO2 (µg/m³)", "PM2.5 (µg/m³)"))
  expect_equal(out[["NO2 (µg/m³)"]], 10)
  expect_equal(out[["PM2.5 (µg/m³)"]], 20)
})

test_that("reports are never cached", {
  cache <- local_cpcb()
  local_http(xlsx_response())
  testthat::local_mocked_bindings(.cpcb_now = function() report_now)
  cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26")
  expect_false(dir.exists(cache))
})

test_that("the request time is the current time", {
  expect_s3_class(.cpcb_now(), "POSIXct")
  expect_lt(abs(as.numeric(difftime(.cpcb_now(), Sys.time(), units = "secs"))), 60)
})

test_that("an SSL failure is retried without verification", {
  log <- local_report(connection_error("SSL certificate problem"), xlsx_response())
  expect_message(cpcb_download_station_report("site_301", "2026-10-25", "2026-10-26"), "SSL verification failed")
  expect_length(log$calls, 2L)
  expect_equal(log$calls[[2]]$ssl_verifypeer, 0L)
})

test_that("cpcb_station_table lists stations with coordinates and filters", {
  local_cpcb()
  local_feed()
  delhi <- cpcb_station_table(city = "delhi")
  expect_named(delhi, c("station_id", "station_name", "city", "state", "latitude", "longitude"))
  expect_true("site_301" %in% delhi$station_id)
  expect_true(all(delhi$city == "Delhi"))
  expect_type(delhi$latitude, "double")
  expect_false(is.unsorted(delhi$station_name))
  expect_gt(nrow(cpcb_station_table()), nrow(delhi))
  expect_equal(nrow(cpcb_station_table(state = "Delhi")), nrow(delhi))
  expect_equal(nrow(cpcb_station_table(city = "Delhi", state = "Kerala")), 0)
  expect_equal(nrow(cpcb_station_table(city = "nowhere")), 0)
})

test_that("a city report joins its stations and skips those with no report", {
  local_cpcb()
  local_feed()
  local_curl_pool()
  asked <- character()
  out_file <- tempfile(fileext = ".csv")
  on.exit(unlink(out_file), add = TRUE)
  local_mocked_bindings(cpcb_download_station_report = function(station_id, ...) {
    asked <<- c(asked, station_id)
    if (station_id == "site_301") stop("no report")
    data.frame(Timestamp = "2026-11-08 00:00:00", `PM2.5 (µg/m³)` = 50, check.names = FALSE)
  })
  out <- suppressMessages(cpcb_download_city_report(
    "Delhi", "2026-11-08", "2026-11-09", save_location = out_file
  ))
  expect_equal(names(out)[1:3], c("station_id", "station_name", "Timestamp"))
  expect_setequal(asked, cpcb_station_table(city = "Delhi")$station_id)
  expect_false("site_301" %in% out$station_id)
  expect_equal(nrow(out), length(asked) - 1)
  expect_equal(nrow(utils::read.csv(out_file)), nrow(out))
})

test_that("a city report stops on an unknown city or when nothing comes back", {
  local_cpcb()
  local_feed()
  local_curl_pool()
  expect_error(cpcb_download_city_report("nowhere", "2026-11-08", "2026-11-09"), "not found")
  local_mocked_bindings(cpcb_download_station_report = function(...) stop("down"))
  expect_error(
    suppressMessages(cpcb_download_city_report("Delhi", "2026-11-08", "2026-11-09")),
    "no report"
  )
})

test_that("a tidy city report adds no columns", {
  local_cpcb()
  local_feed()
  local_curl_pool()
  seen <- NULL
  local_mocked_bindings(cpcb_download_station_report = function(station_id, ..., tidy = FALSE) {
    seen <<- tidy
    data.frame(station_id = station_id, value = 1)
  })
  out <- suppressMessages(cpcb_download_city_report("Delhi", "2026-11-08", "2026-11-09", tidy = TRUE))
  expect_true(seen)
  expect_named(out, c("station_id", "value"))
})

# Three stations, so a run can stop part way
local_three_stations <- function(.env = parent.frame()) {
  local_report(.env = .env)
  testthat::local_mocked_bindings(cpcb_station_table = function(state = NULL, city = NULL) {
    data.frame(
      station_id = c("site_1", "site_2", "site_3"), station_name = c("One", "Two", "Three"),
      city = "Delhi", state = "Delhi", latitude = 28, longitude = 77, stringsAsFactors = FALSE
    )
  }, .env = .env)
}

pool_ok <- function() list(status_code = 200L, content = xlsx_bytes())

# cpcb_download_station_report replaced; returns the log of the stations asked
local_sequential <- function(fail = character(), error = simpleError("no report"), .env = parent.frame()) {
  log <- new.env(parent = emptyenv())
  log$asked <- character()
  testthat::local_mocked_bindings(cpcb_download_station_report = function(station_id, ...) {
    log$asked <- c(log$asked, station_id)
    if (station_id %in% fail) stop(error)
    data.frame(Timestamp = "2026-10-25 00:00:00", `PM2.5 (µg/m³)` = 1, check.names = FALSE)
  }, .env = .env)
  log
}

report_messages <- function(code) capture.output(force(code), type = "message")

test_that("a city report posts in parallel on a pool of 6 connections", {
  local_three_stations()
  seq_log <- local_sequential()
  pool <- local_curl_pool(list(pool_ok(), pool_ok(), pool_ok()))
  out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26", pollutants = "PM2.5")

  expect_equal(pool$pools[[1]]$total_con, 6)
  expect_equal(pool$pools[[1]]$host_con, 6)
  expect_length(pool$added, 3)
  expect_length(seq_log$asked, 0)
  handle <- pool$handles[[2]]
  expect_equal(handle$url, report_url)
  expect_equal(handle$headers[["Content-Type"]], "application/json")
  expect_equal(handle$headers$Accept, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
  expect_equal(handle$options$ssl_verifypeer, 1L)
  expect_equal(handle$options$ssl_verifyhost, 2L)
  body <- jsonlite::fromJSON(handle$options$copypostfields)
  expect_equal(body$stationId, "site_2")
  expect_equal(body$station, "Two")
  expect_equal(body$parameters, "PM25")
  expect_equal(names(out)[1:3], c("station_id", "station_name", "Timestamp"))
  expect_equal(unique(out$station_id), c("site_1", "site_2", "site_3"))
  expect_equal(nrow(out), 288)
})

test_that("the pool sends unverified after an SSL failure, as the prefetch does", {
  local_three_stations()
  local_sequential()
  .cpcb_cache$insecure <- TRUE
  pool <- local_curl_pool(list(pool_ok(), pool_ok(), pool_ok()))
  cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26")
  expect_equal(pool$handles[[1]]$options$ssl_verifypeer, 0L)
  expect_equal(pool$handles[[1]]$options$ssl_verifyhost, 0L)
})

test_that("the timeout covers the wait for a free connection", {
  local_cpcb()
  pool <- local_curl_pool()
  .cpcb_report_pool(rep(list(list(stationId = "a")), 13))
  expect_equal(pool$handles[[1]]$options$timeout, 180)
})

test_that("HTTP 500 skips a station without a second request", {
  local_three_stations()
  seq_log <- local_sequential()
  local_curl_pool(list(list(status_code = 500L, content = raw(0)), pool_ok(), pool_ok()))
  msgs <- report_messages(out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26"))
  expect_length(seq_log$asked, 0)
  expect_equal(unique(out$station_id), c("site_2", "site_3"))
  expect_true(any(grepl("Skipped One: CPCB could not build", msgs)))
})

test_that("a failed transfer goes through the sequential download, once", {
  local_three_stations()
  seq_log <- local_sequential()
  local_curl_pool(list(NULL, list(status_code = 503L, content = raw(0)), pool_ok()))
  out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26")
  expect_equal(seq_log$asked, c("site_1", "site_2"))
  expect_equal(unique(out$station_id), c("site_1", "site_2", "site_3"))
})

test_that("a 200 that does not parse is an error, without a second request", {
  local_three_stations()
  seq_log <- local_sequential()
  local_curl_pool(list(pool_ok(), pool_ok(), list(status_code = 200L, content = charToRaw("<html>"))))
  msgs <- report_messages(out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26"))
  expect_length(seq_log$asked, 0)
  expect_equal(attr(out, "station_status"), c(site_1 = "ok", site_2 = "ok", site_3 = "error"))
  expect_true(any(grepl("Skipped Three: CPCB sent no usable report", msgs)))
})

test_that("an outage stops the sequential stage and returns what the pool got", {
  local_three_stations()
  seq_log <- local_sequential(fail = c("site_2", "site_3"), error = connection_error("Timeout was reached"))
  local_curl_pool(list(pool_ok(), NULL, NULL))
  msgs <- report_messages(out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26"))
  expect_equal(seq_log$asked, "site_2")
  expect_equal(unique(out$station_id), "site_1")
  expect_length(grep("outage stopped the run", msgs), 1)
  expect_equal(attr(out, "station_status"), c(site_1 = "ok", site_2 = "outage", site_3 = "not_attempted"))
})

test_that("an outage with no report at all is still an error", {
  local_three_stations()
  local_sequential(fail = c("site_1", "site_2", "site_3"), error = connection_error())
  local_curl_pool()
  err <- expect_error(
    suppressMessages(cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26")),
    "CPCB is unavailable",
    class = "vayuayan_network"
  )
  expect_equal(err$station_status, c(site_1 = "outage", site_2 = "not_attempted", site_3 = "not_attempted"))
})

test_that("tidy rows of the pool carry the station", {
  local_three_stations()
  local_sequential()
  local_curl_pool(list(pool_ok(), pool_ok(), pool_ok()))
  out <- cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26", tidy = TRUE)
  expect_named(out, c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value"))
  expect_equal(unique(out$station_name), c("One", "Two", "Three"))
  expect_equal(unique(out$city), "Delhi")
})

test_that("a bad frequency stops before any request", {
  local_three_stations()
  pool <- local_curl_pool()
  expect_error(cpcb_download_city_report("Delhi", "2026-10-25", "2026-10-26", frequency = "weekly"), "report frequency")
  expect_length(pool$added, 0)
})

test_that("the real pool passes handles to curl", {
  local_cpcb()
  added <- list()
  testthat::local_mocked_bindings(
    multi_add = function(handle, done, fail, pool) {
      added[[length(added) + 1]] <<- list(handle = handle, done = done, fail = fail, pool = pool)
      invisible(handle)
    },
    multi_run = function(pool) {
      added[[1]]$done(list(status_code = 200L, content = raw(0)))
      added[[2]]$fail("Timeout was reached")
      invisible(NULL)
    },
    .package = "curl"
  )
  replies <- .cpcb_report_pool(list(list(a = 1), list(a = 2)))
  expect_s3_class(added[[1]]$pool, "curl_multi")
  expect_s3_class(added[[1]]$handle, "curl_handle")
  expect_equal(replies[[1]]$status_code, 200L)
  expect_null(replies[[2]])
})
