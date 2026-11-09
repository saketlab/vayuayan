# The station catalogue, narrowing by city and state, and the batch functions.

messages_of <- function(code) capture.output(force(code), type = "message")

test_that("the catalogue adds feed-only stations with the feed's coordinates", {
  local_cpcb()
  local_feed()
  delhi <- cpcb_station_table(city = "Delhi")
  row <- delhi[delhi$station_id == "site_feedonly", ]
  expect_equal(nrow(row), 1)
  expect_equal(row$station_name, "Zeta Colony, Delhi - DPCC")
  expect_equal(c(row$latitude, row$longitude), c(28.70, 77.10))
  expect_equal(c(row$city, row$state), c("Delhi", "Delhi"))
  expect_named(delhi, c("station_id", "station_name", "city", "state", "latitude", "longitude"))
  expect_equal(order(delhi$state, delhi$city, delhi$station_name, method = "radix"), seq_len(nrow(delhi)))
})

test_that("a station in both sources comes from the directory", {
  local_cpcb()
  local_feed()
  st <- .cpcb_station_catalogue()
  expect_equal(sum(st$station_id == "site_301"), 1)
  known <- .cpcb_directory_stations()
  expect_equal(st$latitude[st$station_id == "site_301"], known$latitude[known$station_id == "site_301"])
  expect_equal(nrow(st), nrow(known) + 1)
})

test_that("state and city filters reach feed-only stations, by name and by code", {
  local_cpcb()
  local_feed()
  codes <- .cpcb_resolve_city("Delhi")
  for (table in list(
    cpcb_station_table(state = "delhi"),
    cpcb_station_table(state = codes$state_code),
    cpcb_station_table(city = codes$city_code),
    cpcb_station_table(state = "Delhi", city = "Delhi")
  )) {
    expect_true("site_feedonly" %in% table$station_id)
  }
  expect_false("site_feedonly" %in% cpcb_station_table(state = "Kerala")$station_id)
  expect_false("site_feedonly" %in% cpcb_station_table(city = "Mumbai")$station_id)
})

test_that("a feed station with no directory city still filters by name", {
  local_cpcb()
  local_mocked_bindings(.cpcb_rss_stations = function() {
    data.frame(
      id = c("site_new", NA, "", "site_noname", "site_new"),
      name = c("New Place", "No ID", "Blank ID", NA, "Repeat"),
      latitude = c("10.5", "1", "1", "1", "1"), longitude = c("70.5", "1", "1", "1", "1"),
      city = "Newtown", state = "Delhi", stringsAsFactors = FALSE
    )
  })
  st <- cpcb_station_table(city = "newtown")
  expect_equal(st$station_id, "site_new")
  expect_equal(st$station_name, "New Place")
  expect_equal(st$latitude, 10.5)
  codes <- .cpcb_resolve_state("Delhi")
  expect_equal(nrow(cpcb_station_table(state = codes$state_code, city = "Newtown")), 1)
})

test_that("the table uses the directory alone when the feed is down, at info level", {
  local_cpcb()
  local_http(connection_error())
  msgs <- messages_of(table <- cpcb_station_table(city = "Delhi"))
  expect_true(any(grepl("feed unavailable", msgs)))
  expect_false(any(grepl("Could not resolve", msgs) & grepl("Skipped", msgs)))
  known <- .cpcb_directory_stations()
  expect_setequal(table$station_id, known$station_id[known$city_name == "Delhi"])
  expect_false("site_feedonly" %in% table$station_id)
})

test_that("an empty feed leaves the directory alone", {
  local_cpcb()
  local_http(fake_response(200, '{"country": []}'))
  expect_equal(nrow(.cpcb_feed_stations()), 0)
  expect_equal(nrow(.cpcb_station_catalogue()), nrow(.cpcb_directory_stations()))
})

test_that("a city narrows an ambiguous station name", {
  local_cpcb()
  local_no_feed()
  http <- local_http()
  expect_equal(.cpcb_resolve_station("Anand Vihar", city = "Delhi")$station_id, "site_301")
  expect_equal(.cpcb_resolve_station("Anand Vihar", city = "Hapur")$station_id, "site_5023")
  expect_equal(.cpcb_resolve_station("anand vihar", city = "delhi", state = "delhi")$station_id, "site_301")
  expect_equal(.cpcb_require_station("Anand Vihar", "Delhi")$station_name, "Anand Vihar, Delhi - DPCC")
  expect_length(http$calls, 0)
})

test_that("a state narrows the city, and alone it does not narrow, as in Python", {
  local_cpcb()
  local_feed()
  expect_null(.cpcb_resolve_station("Anand Vihar", city = "Delhi", state = "Kerala"))
  expect_error(.cpcb_resolve_station("Anand Vihar", state = "Delhi"), "matches 2 stations")
})

test_that("a city also narrows the feed search", {
  local_cpcb()
  local_feed()
  expect_equal(.cpcb_resolve_station("Zeta Colony", city = "Delhi")$station_id, "site_feedonly")
  expect_null(.cpcb_resolve_station("Zeta Colony", city = "Mumbai"))
  expect_error(.cpcb_require_station("Zeta Colony", "Mumbai"), "not found")
})

test_that("single-station functions pass city and state to the resolver", {
  local_cpcb()
  local_no_feed()
  listing <- function() {
    fake_response(200, file_listing(filepath = "/x/site_301_2023.csv", year = "2023"))
  }
  raw_body <- "Timestamp,PM2.5 (ug/m3)\n2023-01-01 00:00:00,158\n"

  http <- local_http(listing(), token_reply(), fake_response(200, raw_body))
  cpcb_download_raw_station_data("Anand Vihar", 2023, city = "Delhi")
  expect_equal(http$calls[[1]]$body$station_id, "site_301")

  http <- local_http(listing(), token_reply(), fake_response(200, "Day,January\n1,10\n"))
  path <- tempfile(fileext = ".csv")
  on.exit(unlink(path), add = TRUE)
  suppressMessages(cpcb_download_station_data("Anand Vihar", 2023, path, city = "Delhi"))
  expect_equal(http$calls[[1]]$body$station_id, "site_301")

  http <- local_http(
    fake_response(200, file_listing(filepath = "/x/site_301_January.csv", year = "2023", month = "January")),
    token_reply(),
    fake_response(200, "Hour,AQI\n1,10\n")
  )
  cpcb_download_hourly_station_data("Anand Vihar", 2023, city = "Delhi", state = "Delhi")
  expect_equal(http$calls[[1]]$body$station_id, "site_301")

  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path("Anand Vihar", city = "Delhi", frequency = "daily", data_type = "stationLevel")
  expect_equal(http$calls[[1]]$body$station_id, "site_301")
})

test_that("the station report and the daily AQI accept city and state", {
  local_cpcb()
  local_no_feed()
  asked <- NULL
  local_mocked_bindings(
    cpcb_download_raw_station_data = function(station_id, year, ...) {
      asked <<- station_id
      long_hours(as.POSIXct("2023-06-01 00:00:00", tz = "UTC") + 3600 * 0:23, c("PM2.5" = 30))
    }
  )
  cpcb_station_daily_aqi("Anand Vihar", 2023, city = "Delhi", state = "Delhi")
  expect_equal(asked, "site_301")
  cpcb_station_daily_aqi("site_5023", 2023)
  expect_equal(asked, "site_5023")

  http <- local_http(fake_response(500, "no"))
  expect_error(
    cpcb_download_station_report("Anand Vihar", "2026-10-25", "2026-10-26", city = "Delhi"),
    "could not build"
  )
  expect_equal(jsonlite::fromJSON(http$calls[[1]]$body)$stationId, "site_301")
})

test_that("batch functions need stations or a city, and know the city", {
  local_cpcb()
  local_feed()
  expect_error(cpcb_raw_readings(year = 2025), "station_id or city")
  expect_error(cpcb_raw_readings(year = 2025, state = "Delhi"), "station_id or city")
  expect_error(cpcb_station_daily(year = 2025), "station_id or city")
  expect_error(cpcb_raw_readings(year = 2025, city = "nowhere"), "City 'nowhere' not found")
  expect_error(cpcb_station_daily(year = 2025, city = "nowhere"), "City 'nowhere' not found")
})

test_that("a city expands to all its stations, feed-only stations included", {
  local_cpcb()
  local_feed()
  asked <- character()
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    asked <<- c(asked, station_id)
    data.frame(station_id = station_id, pollutant = c("PM2.5", "RH"), value = c(1, 2))
  })
  out <- cpcb_raw_readings(year = 2025, pollutants = "PM2.5", city = "Delhi")
  expect_setequal(asked, cpcb_station_table(city = "Delhi")$station_id)
  expect_true("site_feedonly" %in% out$station_id)
  expect_true(all(out$pollutant == "PM2.5"))
})

test_that("given stations are narrowed by the city in a batch", {
  local_cpcb()
  local_no_feed()
  asked <- character()
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    asked <<- c(asked, station_id)
    data.frame(station_id = station_id, pollutant = "PM2.5", value = 1)
  })
  cpcb_raw_readings("Anand Vihar", 2025, city = "Delhi")
  expect_equal(asked, "site_301")
})

test_that("cpcb_station_daily expands a city and keeps positional calls", {
  local_cpcb()
  local_feed()
  dir <- tempfile("vayuayan-csv-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  table <- cpcb_station_table(city = "Delhi")
  sheet <- data.frame(Day = 1, January = 5)
  for (id in table$station_id) {
    utils::write.csv(sheet, file.path(dir, sprintf("%s_2022.csv", id)), row.names = FALSE)
  }
  out <- cpcb_station_daily(year = 2022, cache_dir = dir, city = "Delhi")
  expect_setequal(out$station_id, table$station_id)
  one <- cpcb_station_daily("site_301", 2022, dir)
  expect_equal(one$station_id, "site_301")
  narrowed <- cpcb_station_daily("Anand Vihar", 2022, dir, city = "Delhi")
  expect_equal(narrowed$station_id, "site_301")
})

test_that("the first network failure stops the loop with one warning", {
  asked <- character()
  fetch <- function(id) {
    asked <<- c(asked, id)
    if (id == "b") stop(connection_error("Timeout was reached"))
    id
  }
  msgs <- messages_of(out <- .cpcb_each_station(c("a", "b", "c", "d"), fetch, c("A", "B", "C", "D")))
  expect_equal(asked, c("a", "b"))
  expect_equal(out$frames, list("a", NULL, NULL, NULL))
  expect_equal(out$status, c(a = "ok", b = "outage", c = "not_attempted", d = "not_attempted"))
  expect_length(grep("outage stopped the run", msgs), 1)
  expect_true(any(grepl("at B", msgs) & grepl("2 not_attempted", msgs)))
  expect_false(any(grepl("Skipped", msgs)))
})

test_that("a failure that is not a network failure skips only that station", {
  fetch <- function(id) if (id == "b") stop("no report") else id
  msgs <- messages_of(out <- .cpcb_each_station(c("a", "b", "c"), fetch))
  expect_equal(out$frames, list("a", NULL, "c"))
  expect_equal(out$status, c(a = "ok", b = "error", c = "ok"))
  expect_true(any(grepl("Skipped b: no report", msgs)))
  expect_length(grep("Partial result: 2 ok, 1 error", msgs), 1)
  expect_false(any(grepl("outage", msgs)))
})

test_that("a network failure on the last station is an outage too", {
  fetch <- function(id) if (id == "b") stop(connection_error()) else id
  msgs <- messages_of(out <- .cpcb_each_station(c("a", "b"), fetch))
  expect_equal(out$frames, list("a", NULL))
  expect_equal(out$status, c(a = "ok", b = "outage"))
  expect_false(any(grepl("Skipped b", msgs)))
  expect_length(grep("outage stopped the run at b", msgs), 1)
})

test_that("a NULL result leaves the slot empty and the list its length", {
  expect_equal(suppressMessages(.cpcb_each_station(c("a", "b"), function(id) NULL))$frames, list(NULL, NULL))
})

test_that("cpcb_raw_readings keeps what it fetched before an outage", {
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    if (station_id == "site_2") stop(connection_error())
    data.frame(station_id = station_id, pollutant = "PM2.5", value = 1)
  })
  msgs <- messages_of(out <- cpcb_raw_readings(c("site_1", "site_2", "site_3"), 2026))
  expect_equal(out$station_id, "site_1")
  expect_length(grep("outage stopped the run", msgs), 1)
})
