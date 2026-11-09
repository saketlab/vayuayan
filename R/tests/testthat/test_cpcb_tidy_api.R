test_that("cpcb_tidy_daily with a year adds dates and drops impossible ones", {
  sheet <- data.frame(Day = c(30, 31), January = c(5, 6), February = c(7, 8))
  out <- cpcb_tidy_daily(sheet, year = 2024)
  expect_equal(out$date, as.Date(c("2024-01-30", "2024-01-31")))
  expect_equal(out$value, c(5, 6))
})

test_that(".parse_timestamp reads each CPCB format and leaves the rest NA", {
  stamp <- as.POSIXct("2024-01-01 10:00:00", tz = "UTC")
  expect_identical(.parse_timestamp(stamp), stamp)
  got <- .parse_timestamp(c(
    "2024-01-01 10:00:00", "2024-01-01T10:00:00", "2024-01-01 10:00",
    "2024-01-01", "not a time", NA
  ))
  expect_equal(format(got[1:3], "%Y-%m-%d %H:%M"), rep("2024-01-01 10:00", 3))
  expect_equal(format(got[4], "%Y-%m-%d"), "2024-01-01")
  expect_true(all(is.na(got[5:6])))
})

raw_table <- data.frame(
  Timestamp = c("2024-01-01 00:00:00", "2024-01-02 00:00:00", "2024-01-03 00:00:00", "bad"),
  "PM2.5 (ug/m3)" = c(10, 20, 30, 40),
  "RH" = c("1", "x", "3", "4"),
  check.names = FALSE
)

test_that("cpcb_raw_to_long splits labels, drops bad rows and adds the station", {
  out <- cpcb_raw_to_long(raw_table, station = list(station_id = "site_1", city = "Delhi"))
  expect_named(out, c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value"))
  expect_equal(out$pollutant, c("PM2.5", "RH", "PM2.5", "PM2.5", "RH"))
  expect_equal(out$unit, c("ug/m3", "", "ug/m3", "ug/m3", ""))
  expect_equal(out$value, c(10, 1, 20, 30, 3))
  expect_equal(unique(out$station_id), "site_1")
  expect_equal(unique(out$city), "Delhi")
  expect_equal(unique(out$state), "")
})

test_that("cpcb_raw_to_long keeps the dates asked for, inclusive", {
  from <- cpcb_raw_to_long(raw_table, start_date = "2024-01-02")
  expect_equal(unique(format(from$timestamp, "%d")), c("02", "03"))
  to <- cpcb_raw_to_long(raw_table, end_date = "2024-01-02")
  expect_equal(unique(format(to$timestamp, "%d")), c("01", "02"))
})

test_that("cpcb_raw_to_long needs a Timestamp column", {
  expect_error(cpcb_raw_to_long(data.frame(a = 1)), "did not contain a Timestamp column")
})

test_that("cpcb_live_metrics is empty without metrics", {
  empty <- cpcb_live_metrics(list(metrics = data.frame()))
  expect_equal(nrow(empty), 0)
  expect_named(empty, c("pollutant", "avg", "min", "max", "period"))
  expect_equal(nrow(cpcb_live_metrics(list())), 0)
})

test_that(".cpcb_csv_copy uses the session temp directory by default", {
  expect_equal(.cpcb_csv_copy(NULL, "x.csv"), file.path(tempdir(), "x.csv"))
  dir <- tempfile("vayuayan-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  expect_equal(.cpcb_csv_copy(dir, "y.csv"), file.path(dir, "y.csv"))
  expect_true(dir.exists(dir))
})

sheet_json <- function(city, years) {
  file_path_json(data.frame(
    filepath = sprintf("/AQI_daily/city_level/%s/%d/%s_%d.csv", city, years, city, years),
    year = as.character(years),
    stringsAsFactors = FALSE
  ))
}

test_that("cpcb_city_daily lists once, prefetches, then reads the cache", {
  local_cpcb()
  dir <- tempfile("vayuayan-csv-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(
    fake_response(200, sheet_json("pune", 2021:2022)),
    token_reply("tok1"),
    token_reply("tok2")
  )
  dl <- local_multi_download(c(200L, 200L))

  out <- suppressMessages(cpcb_city_daily("Pune", 2021:2022, cache_dir = dir))

  # no request is left after the batch download: the sheets come from the cache
  expect_length(http$calls, 3)
  expect_equal(http$calls[[1]]$url, paste0(CPCB_REPO, "file-path"))
  expect_equal(http$calls[[1]]$body$year, "")
  expect_length(dl$urls, 2)
  expect_equal(out$city, c("Pune", "Pune"))
  expect_equal(out$value, c(10L, 10L))
  expect_equal(out$date, as.Date(c("2021-01-01", "2022-01-01")))
  expect_setequal(list.files(dir), c("pune_aqi_2021.csv", "pune_aqi_2022.csv"))
})

test_that("cpcb_city_daily without cache_dir uses a session temp copy", {
  local_cpcb()
  http <- local_http(
    fake_response(200, sheet_json("testcityx", 2021)),
    token_reply(),
    fake_response(200, "Day,March\n2,70\n")
  )
  copy <- file.path(tempdir(), "testcityx_aqi_2021.csv")
  on.exit(unlink(copy), add = TRUE)
  out <- suppressMessages(cpcb_city_daily("testcityx", 2021))

  expect_equal(out$date, as.Date("2021-03-02"))
  expect_equal(out$value, 70L)
  expect_true(file.exists(copy))
})

test_that("cpcb_city_daily fails on a year CPCB does not have", {
  local_cpcb()
  local_http(fake_response(200, sheet_json("pune", 2021)))
  expect_error(cpcb_city_daily("Pune", 2020), "Data not found for city Pune in year 2020")
})

test_that("cpcb_station_daily downloads, then tidies each station", {
  local_cpcb()
  local_no_feed()
  dir <- tempfile("vayuayan-csv-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(
    fake_response(200, file_path_json(data.frame(
      filepath = "/AQI_daily/station/site_301/2021/s_2021.csv", year = "2021"
    ))),
    token_reply(),
    fake_response(200, "Day,January\n1,180\n")
  )
  out <- suppressMessages(cpcb_station_daily("Anand Vihar, Delhi", 2021, cache_dir = dir))

  expect_equal(http$calls[[1]]$body$station_id, "site_301")
  expect_equal(out$station_id, "site_301")
  expect_equal(out$station_name, "Anand Vihar, Delhi - DPCC")
  expect_equal(out$value, 180)
  expect_true(file.exists(file.path(dir, "site_301_2021.csv")))
})

test_that("cpcb_station_daily skips stations it cannot get", {
  local_cpcb()
  dir <- tempfile("vayuayan-csv-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(
    fake_response(500, "down"),
    fake_response(200, cpcb_feed_json()),
    fake_response(200, file_path_json(data.frame(filepath = "/AQI_daily/s/2021/s_2021.csv", year = "2021"))),
    token_reply(),
    fake_response(200, "Day,January\n1,99\n")
  )
  # "site_nope" fails the feed lookup; "site_feedonly" succeeds from the next one
  msgs <- capture.output(
    out <- cpcb_station_daily(c("site_nope", "site_feedonly"), 2021, cache_dir = dir),
    type = "message"
  )
  expect_equal(out$station_id, "site_feedonly")
  expect_true(any(grepl("Skipped site_nope", msgs)))
  expect_length(http$calls, 5)
})
