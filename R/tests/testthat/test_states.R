# The named states of the batch loop, lookups, listings, live readings and daily AQI

alerts <- function(code) capture.output(force(code), type = "message")

data_not_found <- function() {
  tryCatch(.vayuayan_abort("vayuayan_data_not_found", "no file"), error = identity)
}

# stations table of two real directory stations, so report calls resolve exactly
local_two_stations <- function(.env = parent.frame()) {
  local_cpcb(.env = .env)
  testthat::local_mocked_bindings(cpcb_station_table = function(state = NULL, city = NULL) {
    data.frame(
      station_id = c("site_301", "site_5023"), station_name = c("Anand Vihar", "Hapur"),
      city = "C", state = "S", latitude = 28, longitude = 77, stringsAsFactors = FALSE
    )
  }, .env = .env)
}

test_that("each station ends in one named status, with one partial warning", {
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    switch(station_id,
      a = data.frame(station_id = "a", pollutant = "PM2.5", value = 1),
      b = stop(data_not_found()),
      c = .vayuayan_abort("vayuayan_not_found", "Station 'c' not found"),
      d = .vayuayan_abort("vayuayan_ambiguous", "Station 'd' matches 2 stations", candidates = c("x", "y")),
      e = stop("boom")
    )
  })
  msgs <- alerts(out <- cpcb_raw_readings(letters[1:5], 2024))
  expect_equal(attr(out, "station_status"), c(a = "ok", b = "no_data", c = "not_found", d = "ambiguous", e = "error"))
  expect_length(grep("Partial result", msgs), 1)
  expect_true(any(grepl("1 ok, 1 no_data, 1 not_found, 1 ambiguous, 1 error", msgs)))
  expect_true(any(grepl("Skipped d: Station 'd' matches 2 stations", msgs)))
})

test_that("a run that fetches nothing in an outage is a classed error", {
  local_mocked_bindings(cpcb_download_raw_station_data = function(...) stop(connection_error("Timeout was reached")))
  expect_error(cpcb_raw_readings(c("a", "b"), 2024), "CPCB is unavailable", class = "vayuayan_network")

  local_cpcb()
  local_mocked_bindings(cpcb_download_station_data = function(...) stop(connection_error()))
  err <- expect_error(cpcb_station_daily("site_301", 2021), class = "vayuayan_network")
  expect_equal(err$station_status, c(site_301 = "outage"))
})

test_that("a 5xx from the export is an outage and its 500 is no data", {
  local_two_stations()
  local_curl_pool(list(list(status_code = 500L, content = raw(0)), NULL))
  local_http(fake_response(503, ""))
  err <- expect_error(
    cpcb_download_city_report("X", "2026-10-25", "2026-10-26"),
    "CPCB is unavailable",
    class = "vayuayan_network"
  )
  expect_equal(err$station_status, c(site_301 = "no_data", site_5023 = "outage"))
})

test_that("a city with no report and no outage says so, with the statuses", {
  local_two_stations()
  local_curl_pool(rep(list(list(status_code = 500L, content = raw(0))), 2))
  err <- expect_error(
    alerts(cpcb_download_city_report("X", "2026-10-25", "2026-10-26")),
    "no report for city",
    class = "vayuayan_data_not_found"
  )
  expect_equal(unname(err$station_status), c("no_data", "no_data"))
})

test_that("cpcb_station_daily is empty with columns when every station fails with no outage", {
  local_cpcb()
  local_mocked_bindings(cpcb_download_station_data = function(...) stop(data_not_found()))
  msgs <- alerts(out <- cpcb_station_daily("site_301", 2021))
  expect_named(out, c("station_id", "station_name", "day", "month", "value"))
  expect_equal(nrow(out), 0L)
  expect_equal(attr(out, "station_status"), c(site_301 = "no_data"))
  expect_true(any(grepl("Skipped site_301: no file", msgs)))
})

test_that("an ambiguous station carries its candidates and a missing one is not_found", {
  local_cpcb()
  local_no_feed()
  err <- expect_error(.cpcb_require_station("Anand Vihar"), "matches 2 stations", class = "vayuayan_ambiguous")
  expect_length(err$candidates, 2)
  expect_true(all(grepl("Anand Vihar", err$candidates)))
  expect_error(.cpcb_require_station("site_nope"), "not found", class = "vayuayan_not_found")
})

test_that("an exact directory hit needs no feed", {
  local_cpcb()
  http <- local_http()
  expect_equal(.cpcb_resolve_station("site_301")$station_id, "site_301")
  expect_length(http$calls, 0)
})

test_that("directory and feed are searched together", {
  local_mocked_bindings(
    .cpcb_directory_stations = function() {
      data.frame(
        city_code = "C1", station_id = "d1", station_name = "Civil Lines, Pune",
        latitude = 1, longitude = 2, city_name = "Pune", state_name = "MH", state_code = "S1"
      )
    },
    .cpcb_feed_stations = function() {
      data.frame(
        city_code = NA, station_id = "f1", station_name = "Civil Lines, Agra",
        latitude = 1, longitude = 2, city_name = "Agra", state_name = "UP", state_code = NA
      )
    }
  )
  err <- expect_error(.cpcb_resolve_station("Civil Lines"), class = "vayuayan_ambiguous")
  expect_setequal(err$candidates, c("Civil Lines, Pune", "Civil Lines, Agra"))
  expect_equal(.cpcb_resolve_station("Agra")$station_id, "f1")
})

test_that("a city in two states is ambiguous everywhere a city is chosen", {
  local_cpcb()
  local_no_feed()
  http <- local_http()
  err <- expect_error(.cpcb_resolve_city("Aurangabad"), "Bihar; Maharashtra", class = "vayuayan_ambiguous")
  expect_equal(err$candidates, c("Bihar", "Maharashtra"))
  expect_equal(.cpcb_resolve_city("Aurangabad", "Bihar")$state_name, "Bihar")

  expect_error(cpcb_get_station_list("Byrnihat"), class = "vayuayan_ambiguous")
  expect_gt(nrow(cpcb_get_station_list("Byrnihat", "Assam")), 0)
  expect_error(cpcb_get_file_path(city = "Aurangabad"), class = "vayuayan_ambiguous")
  expect_error(cpcb_download_city_data("Aurangabad", 2021, ""), class = "vayuayan_ambiguous")
  expect_error(cpcb_download_hourly_city_data("Aurangabad", 2021), class = "vayuayan_ambiguous")
  expect_error(cpcb_city_daily("Aurangabad", 2021), class = "vayuayan_ambiguous")
  expect_error(.cpcb_resolve_station("Gurdeo", city = "Aurangabad"), class = "vayuayan_ambiguous")
  expect_error(cpcb_download_city_report("Aurangabad", "2026-11-01", "2026-11-02"), class = "vayuayan_ambiguous")
  expect_error(cpcb_raw_readings(year = 2021, city = "Aurangabad"), "Bihar; Maharashtra", class = "vayuayan_ambiguous")
  expect_length(http$calls, 0)

  expect_setequal(cpcb_station_table(city = "Aurangabad")$state, c("Bihar", "Maharashtra"))
})

test_that("a state spelled differently by the feed is not a second state", {
  local_mocked_bindings(cpcb_station_table = function(state = NULL, city = NULL) {
    data.frame(station_id = c("a", "b"), station_name = "X", city = "Srinagar", state = c("Jammu And Kashmir", "Jammu & Kashmir"))
  })
  expect_equal(nrow(.cpcb_city_stations("Srinagar")), 2)
})

test_that("a listing is FILES, NONE or FAILED", {
  outcome <- function(status, body) .cpcb_read_listing(fake_response(status, body))$outcome
  expect_equal(outcome(200, file_listing(filepath = "/a.xlsx", year = "2022")), "FILES")
  expect_equal(outcome(204, ""), "NONE")
  expect_equal(outcome(200, '{"status": "success", "data": []}'), "NONE")
  expect_equal(outcome(200, '{"status": "failed", "data": [{"filepath": "/x"}]}'), "FAILED")
  expect_equal(outcome(200, "<html>maintenance</html>"), "FAILED")
  expect_equal(outcome(503, ""), "FAILED")
  expect_s3_class(.cpcb_read_listing(fake_response(503, ""))$error, "vayuayan_network")
})

test_that("a failed listing raises a network error, not an empty listing", {
  local_cpcb()
  local_http(fake_response(200, '{"status": "failed"}'))
  expect_error(cpcb_get_file_path(city = "Delhi"), "did not answer", class = "vayuayan_network")
  local_http(connection_error())
  expect_error(cpcb_get_file_path(city = "Delhi"), class = "vayuayan_network")
  local_http(fake_response(503, "x"))
  expect_error(cpcb_get_file_path(city = "Delhi"), class = "http_503")
})

test_that("token and download steps raise data_not_found on 404, else network", {
  local_cpcb()
  local_http(fake_response(404, "x"))
  expect_error(.cpcb_download_url("/x.csv"), class = "vayuayan_data_not_found")
  local_http(fake_response(500, "x"), fake_response(500, "x"), fake_response(500, "x"), fake_response(500, "x"))
  expect_error(.cpcb_download_url("/x.csv"), class = "vayuayan_network")

  local_http(token_reply(), fake_response(404, "x"))
  expect_error(.cpcb_download_repository("/x.csv"), class = "vayuayan_data_not_found")
  local_http(token_reply(), fake_response(200, "<html>sorry</html>"))
  expect_error(.cpcb_download_repository("/x.csv"), "no usable file", class = "vayuayan_network")
})

test_that("cached GeoTIFFs are listed with a warning and cleared", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  file.create(file.path(dir, c("a.nc", "b.tif", "keep.txt")))
  msgs <- alerts(listed <- pm25_list_cached_files(dir))
  expect_setequal(basename(listed), c("a.nc", "b.tif"))
  expect_true(any(grepl("coarse Google Earth Engine", msgs)))
  suppressMessages(pm25_clear_cache(dir))
  expect_equal(list.files(dir), "keep.txt")
})

test_that("PM2.5 download failures have a class and keep their cause", {
  dir <- tempfile("vayuayan-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  local_http(fake_response(404, "x"))
  err <- expect_error(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    class = "vayuayan_pm25_download"
  )
  expect_s3_class(err, "http_404")
  local_http(connection_error())
  expect_error(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    class = "vayuayan_pm25_download"
  )
})

test_that("a cached NetCDF must exceed the size limit to be reused", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  file <- "V6GL03.CNNPM25.AS.202311-202311.nc"
  writeBin(raw(.pm25_min_cached_bytes), file.path(dir, file))
  http <- local_http(fake_response(200, raw(4)))
  suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS"))
  expect_length(http$calls, 1)

  writeBin(raw(.pm25_min_cached_bytes + 1), file.path(dir, file))
  http <- local_http()
  suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS"))
  expect_length(http$calls, 0)
})

test_that("pm25_monthly leaves out months that cannot be downloaded", {
  local_mocked_bindings(
    pm25_download_netcdf = function(year, month, ...) {
      if (month == 2) .vayuayan_abort("vayuayan_pm25_download", "no file")
      "x.nc"
    },
    pm25_read_netcdf_bbox = function(...) 7
  )
  msgs <- alerts(out <- pm25_monthly(NULL, 2022, months = 1:3))
  expect_equal(out$month, c(1L, 3L))
  expect_equal(out$pm25, c(7, 7))
  expect_equal(attr(out, "failed_months"), 2L)
  expect_true(any(grepl("No PM2.5 data for 2022-02", msgs)))

  local_mocked_bindings(pm25_download_netcdf = function(...) .vayuayan_abort("vayuayan_pm25_download", "no"))
  suppressMessages(none <- pm25_monthly(NULL, 2022, months = 1))
  expect_equal(nrow(none), 0L)
  expect_equal(attr(none, "failed_months"), 1L)

  local_mocked_bindings(pm25_download_netcdf = function(...) "x.nc")
  all_ok <- pm25_monthly(NULL, 2022, months = 1)
  expect_null(attr(all_ok, "failed_months"))
})

test_that("a live reading names its source and state", {
  local_cpcb()
  local_feed()
  live <- cpcb_get_live_aqi_data_for_station("site_301")
  expect_equal(live$source, "rss")
  expect_equal(live$reading_state, "reading")
  expect_equal(live$as_of, "28-06-2026 18:00:00")

  offline <- cpcb_get_live_aqi_data_for_station("site_feedonly")
  expect_equal(offline$reading_state, "no_reading")
  expect_identical(offline$as_of, NA_character_)
  expect_error(cpcb_get_live_aqi_data_for_station("site_nope"), class = "vayuayan_not_found")
})

test_that("a live station without an AQI is No Reading", {
  cities <- list(list(
    cityName = "C", cityID = "C", stateID = "S",
    stationsInCity = list(
      list(id = "a", name = "A", live = TRUE, avg = "NA"),
      list(id = "b", name = "B", live = TRUE, avg = "50"),
      list(id = "c", name = "C", live = FALSE, avg = "NA")
    )
  ))
  expect_equal(stations_to_dataframe(cities)$status, c("No Reading", "Live", "Offline"))
})

test_that("the automatic pick prefers a current reading; given coordinates keep distance", {
  local_cpcb()
  local_feed()
  near_offline <- c(28.70, 77.10)
  expect_equal(cpcb_get_nearest_station(near_offline)$station_id, "site_feedonly")
  expect_equal(cpcb_get_nearest_station(near_offline, prefer_reading = TRUE)$station_id, "site_301")
  expect_equal(cpcb_get_live_aqi_data(coords = near_offline)$station_id, "site_301")
  expect_equal(cpcb_get_nearest_stations(near_offline, k = 1)$station_id, "site_feedonly")

  local_mocked_bindings(cpcb_get_system_location = function() c(lat = 28.70, lon = 77.10))
  expect_equal(cpcb_get_nearest_station()$station_id, "site_301")
})

test_that("with no current reading anywhere the nearest station is still returned", {
  feed <- data.frame(
    id = c("n", "f"), name = c("N", "F"), latitude = c(1, 5), longitude = c(1, 5),
    live = FALSE, avg = "NA", city = "C", state = "S"
  )
  local_mocked_bindings(.cpcb_rss_stations = function() feed)
  expect_equal(cpcb_get_nearest_station(c(1, 1), prefer_reading = TRUE)$station_id, "n")
})

hours_of <- function(n) as.POSIXct("2024-03-01 00:00:00", tz = "UTC") + 3600 * (seq_len(n) - 1)

daily_status <- function(frames) daily_aqi(do.call(rbind, frames))$aqi_status

test_that("daily_aqi names why a day has no AQI: hours, then PM, then count", {
  full <- hours_of(24)
  three <- long_hours(full, c("PM2.5" = 40, PM10 = 80, NO2 = 30))
  expect_equal(daily_status(list(three)), "ok")
  expect_equal(daily_status(list(three, long_hours(hours_of(5), c(SO2 = 20)))), "ok")
  expect_equal(
    daily_status(list(long_hours(full, c(PM10 = 80, NO2 = 30)), long_hours(hours_of(5), c("PM2.5" = 40)))),
    "too_few_hours"
  )
  expect_equal(daily_status(list(long_hours(full, c(NO2 = 30, SO2 = 20, NH3 = 10)))), "no_pm")
  expect_equal(daily_status(list(long_hours(full, c("PM2.5" = 40, NO2 = 30)))), "too_few_pollutants")
  expect_true("aqi_status" %in% names(.aqi_empty_daily()))
})

test_that("compute_aqi and compute_us_aqi report a status", {
  expect_equal(compute_aqi(c("PM2.5" = 45, PM10 = 80, NO2 = 30))$status, "ok")
  expect_equal(compute_aqi(c(NO2 = 30, SO2 = 20, NH3 = 10))$status, "no_pm")
  expect_equal(compute_aqi(c("PM2.5" = 45, NO2 = 30))$status, "too_few_pollutants")
  expect_equal(compute_us_aqi(c("PM2.5" = 35.4))$status, "ok")
  expect_equal(compute_us_aqi(c(NH3 = 10))$status, "no_sub_index")
  expect_warning(out <- compute_us_aqi(c(O3 = 0.3)), "8-hour O3")
  expect_equal(out$status, "o3_beyond_table")
})

test_that("daily_us_aqi names why a day has no AQI", {
  full <- hours_of(24)
  long <- function(hours, ...) long_of(hours, c(...), station_id = "s")
  expect_equal(daily_us_aqi(long(full, "PM2.5" = 30))$aqi_status, "ok")
  expect_equal(daily_us_aqi(long(hours_of(5), "PM2.5" = 30))$aqi_status, "too_few_hours")
  expect_warning(beyond <- daily_us_aqi(long(full, O3 = 0.3)), "8-hour O3")
  expect_equal(beyond$aqi_status[1], "o3_beyond_table")
})

test_that("only a past year's CSV copy is reused", {
  this_year <- as.integer(format(Sys.Date(), "%Y"))
  path <- tempfile()
  on.exit(unlink(path), add = TRUE)
  expect_false(.cpcb_copy_usable(path, 2021))
  file.create(path)
  expect_true(.cpcb_copy_usable(path, 2021))
  expect_false(.cpcb_copy_usable(path, this_year))
})

test_that("a current-year station copy is fetched again and a past one is not", {
  local_cpcb()
  dir <- tempfile("vayuayan-csv-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  year <- as.integer(format(Sys.Date(), "%Y"))
  utils::write.csv(data.frame(Day = 1, January = 5), file.path(dir, sprintf("site_301_%d.csv", year)), row.names = FALSE)
  http <- local_http(
    fake_response(200, file_listing(filepath = sprintf("/x/%d/site_301.csv", year), year = as.character(year))),
    token_reply(),
    fake_response(200, "Day,January\n1,9\n")
  )
  out <- suppressMessages(cpcb_station_daily("site_301", year, cache_dir = dir))
  expect_length(http$calls, 3)
  expect_equal(out$value, 9)
})

test_that("a city daily copy with a state does not collide with the other state's", {
  local_cpcb()
  dir <- tempfile("vayuayan-csv-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(
    fake_response(200, file_listing(filepath = "/AQI_daily/Aurangabad/2021/a_2021.csv", year = "2021")),
    token_reply(),
    fake_response(200, "Day,January\n1,70\n")
  )
  out <- suppressMessages(cpcb_city_daily("Aurangabad", 2021, cache_dir = dir, state = "Bihar"))
  expect_equal(http$calls[[1]]$body$state, "Bihar")
  expect_equal(out$value, 70)
  expect_equal(list.files(dir), "bihar_aurangabad_aqi_2021.csv")
})

test_that("a CSV copy is written whole or not at all", {
  path <- tempfile(fileext = ".csv")
  on.exit(unlink(path), add = TRUE)
  writeLines("old", path)
  local_mocked_bindings(write.csv = function(x, file, ...) {
    writeLines("partial", file)
    stop("disk full")
  }, .package = "utils")
  expect_error(.cpcb_save(data.frame(a = 1), path), "disk full")
  expect_equal(readLines(path), "old")
  expect_false(file.exists(paste0(path, ".part")))
})

oaq_session_fixture <- list(base_url = "https://data.example/v1", sig_string = "sig=1")

test_that("an expired OAQ session stops the run with a classed error", {
  for (status in c(401L, 403L)) {
    local_http(fake_response(status, "denied"))
    err <- expect_error(
      oaq_readings(oaq_session_fixture, "x", "s1", "2026-01-01"),
      "refused the session",
      class = "vayuayan_auth"
    )
    expect_s3_class(err, paste0("http_", status))
  }
})

test_that("other OAQ failures keep warning and a 404 stays silent", {
  local_http(fake_response(404, "missing"))
  expect_no_warning(out <- oaq_readings(oaq_session_fixture, "x", "s1", "2026-01-01"))
  expect_equal(nrow(out), 0L)
  local_http(fake_response(503, "down"), fake_response(503, "down"), fake_response(503, "down"), fake_response(503, "down"))
  expect_warning(oaq_readings(oaq_session_fixture, "x", "s1", "2026-01-01"), "s1")
})

test_that("daily_aqi accepts empty input with no station_id", {
  empty <- data.frame(timestamp = character(), pollutant = character(), value = numeric())
  out <- daily_aqi(empty)
  expect_equal(nrow(out), 0)
  expect_true("aqi_status" %in% names(out))
})

