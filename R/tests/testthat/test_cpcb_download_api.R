daily_sheet <- "Day,January\n1,180\n2,190\n"

test_that("cpcb_download_city_data lists, gets a token, then the year's file", {
  dir <- local_cpcb()
  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  path <- "/AQI_daily/city_level/delhi/2022/delhi_2022.csv"
  http <- local_http(
    fake_response(200, file_listing(filepath = c("/AQI_daily/city_level/delhi/2021/delhi_2021.csv", path), year = c("2021", "2022"))),
    token_reply("tok%3D"),
    fake_response(200, daily_sheet)
  )
  preview <- suppressMessages(cpcb_download_city_data("delhi", 2022, out))

  expect_equal(http$calls[[1]]$url, paste0(CPCB_REPO, "file-path"))
  expect_equal(http$calls[[1]]$body$year, "")
  expect_equal(http$calls[[1]]$body$frequency, "1D")
  expect_equal(http$calls[[2]]$query, list(file_name = path))
  expect_equal(http$calls[[3]]$url, paste0(CPCB_REPO, "download-excel-fileEnc?file_name=tok%3D"))
  expect_equal(preview$January, c(180L, 190L))
  expect_equal(utils::read.csv(out)$January, c(180L, 190L))
  # past-year files are cached
  expect_true(file.exists(file.path(dir, .cpcb_cache_name(path))))
})

test_that("cpcb_download_city_data reports a year or city CPCB does not have", {
  local_cpcb()
  local_http(fake_response(204, ""))
  expect_error(cpcb_download_city_data("Atlantis", 2022, tempfile()), "Data not found for city Atlantis in year 2022")
  local_http(fake_response(200, file_listing(filepath = "/a_2021.csv", year = "2021")))
  expect_error(cpcb_download_city_data("Delhi", 2022, tempfile()), "Data not found")
})

test_that("cpcb_download_station_data sends the resolved station", {
  local_cpcb()
  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  http <- local_http(
    fake_response(200, file_listing(filepath = "/AQI_daily/station/site_301/2022/s_2022.csv", year = "2022")),
    token_reply(),
    fake_response(200, daily_sheet)
  )
  preview <- suppressMessages(cpcb_download_station_data("site_301", 2022, out))

  body <- http$calls[[1]]$body
  expect_equal(body$station_id, "site_301")
  expect_equal(body$station_name, "Anand Vihar, Delhi - DPCC")
  expect_equal(body$dataType, "stationLevel")
  expect_equal(body$state, "Delhi")
  expect_equal(preview$January, c(180L, 190L))
})

test_that("each station download needs a known station", {
  downloads <- list(
    function() cpcb_download_station_data("site_nope", 2022, tempfile()),
    function() cpcb_download_raw_station_data("site_nope", 2023),
    function() cpcb_download_hourly_station_data("site_nope", 2025)
  )
  for (download in downloads) {
    local_cpcb()
    local_feed()
    expect_error(download(), "Station 'site_nope' not found")
  }
})

raw_csv <- paste0(
  "Timestamp,PM2.5 (ug/m3),CO (mg/m3)\n",
  "2023-01-01 00:00:00,158,1.6\n",
  "2023-01-01 00:15:00,160,\n"
)

test_that("cpcb_download_raw_station_data fetches the station's raw file", {
  local_cpcb()
  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  http <- local_http(
    fake_response(200, file_listing(filepath = "/Raw_data/15Min/2023/site_301_15Min.csv")),
    token_reply(),
    fake_response(200, raw_csv)
  )
  df <- suppressMessages(cpcb_download_raw_station_data("site_301", 2023, out))

  body <- http$calls[[1]]$body
  expect_equal(body$station_id, "site_301")
  expect_equal(body$year, "2023")
  expect_equal(body$frequency, "15M")
  expect_equal(body$dataType, "raw")
  expect_equal(http$calls[[2]]$query, list(file_name = "/Raw_data/15Min/2023/site_301_15Min.csv"))
  expect_equal(df$`PM2.5 (ug/m3)`, c(158L, 160L))
  expect_true(file.exists(out))
})

test_that("cpcb_download_raw_station_data can return long rows at another interval", {
  local_cpcb()
  http <- local_http(
    fake_response(200, file_listing(filepath = "/Raw_data/1H/2023/site_301.csv")),
    token_reply(),
    fake_response(200, raw_csv)
  )
  long <- cpcb_download_raw_station_data("site_301", 2023, frequency = "hourly", tidy = TRUE)

  expect_equal(http$calls[[1]]$body$frequency, "1H")
  expect_equal(long$pollutant, c("CO", "PM2.5", "PM2.5"))
  expect_equal(long$station_id, rep("site_301", 3))
  expect_equal(long$city, rep("Delhi", 3))
})

test_that("cpcb_download_raw_station_data reports a station with no raw file", {
  local_cpcb()
  local_http(fake_response(204, ""))
  expect_error(
    cpcb_download_raw_station_data("site_301", 2023),
    "Raw data not found for station Anand Vihar, Delhi - DPCC in year 2023"
  )
})

hourly_csv <- function(value) sprintf("Day,00:00:00\n1,%s\n", value)

test_that("cpcb_download_hourly_city_data combines the months of the listing", {
  local_cpcb()
  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  http <- local_http(
    fake_response(200, file_listing(
      filepath = c("/AQI_hourly/delhi/January/delhi_January.csv", "/AQI_hourly/delhi/February/delhi_February.csv"),
      month = c("January", "February")
    )),
    token_reply("tokA"),
    fake_response(200, hourly_csv(101)),
    token_reply("tokB"),
    fake_response(200, hourly_csv(202))
  )
  df <- suppressMessages(cpcb_download_hourly_city_data("Delhi", 2025, out))

  body <- http$calls[[1]]$body
  expect_equal(body$frequency, "1H")
  expect_equal(body$dataType, "cityLevel")
  expect_equal(body$year, "2025")
  expect_equal(body$city, "Delhi")
  expect_length(http$calls, 5)
  expect_equal(df$Month, c("January", "February"))
  expect_equal(df$Year, c(2025L, 2025L))
  expect_equal(df[["00:00:00"]], c(101L, 202L))
  expect_equal(nrow(utils::read.csv(out)), 2)
})

test_that("cpcb_download_hourly_station_data sends the station and filters a month", {
  local_cpcb()
  http <- local_http(
    fake_response(200, file_listing(
      filepath = c("/AQI_hourly/2025/January/a.csv", "/AQI_hourly/2025/February/a.csv"),
      month = c("January", "February")
    )),
    token_reply(),
    fake_response(200, hourly_csv(202))
  )
  df <- cpcb_download_hourly_station_data("site_301", 2025, month = "february")

  body <- http$calls[[1]]$body
  expect_equal(body$station_id, "site_301")
  expect_equal(body$dataType, "stationLevel")
  expect_equal(body$frequency, "1H")
  expect_equal(http$calls[[2]]$query$file_name, "/AQI_hourly/2025/February/a.csv")
  expect_equal(df$Month, "February")
  expect_length(http$calls, 3)
})

mock_months <- function(reader = function(filepath, n_max = Inf) data.frame(Day = 1, v = 1), env = parent.frame()) {
  local_mocked_bindings(.cpcb_read_repository = reader, .env = env)
}

test_that("the year field picks the files; another year's files are never used", {
  seen <- character(0)
  mock_months(function(filepath, n_max = Inf) {
    seen <<- c(seen, filepath)
    data.frame(Day = 1, v = 1)
  })
  files <- list(
    list(filepath = "/2024.csv", year = "2024", month = "January"),
    list(filepath = "/2025.csv", year = "2025", month = "January")
  )
  df <- .cpcb_combine_months(files, 2025)
  expect_equal(seen, "/2025.csv")
  expect_equal(df$Year, 2025L)

  seen <- character(0)
  expect_error(.cpcb_combine_months(files, 2030), "Data not found for year 2030")
  expect_equal(seen, character(0))
})

test_that("a month is found by CPCB's field or its file path", {
  mock_months()
  files <- list(
    list(filepath = "/a/February/x.csv", month = NA_character_),
    list(filepath = "/a/x.csv", month = "MARCH")
  )
  expect_equal(.cpcb_combine_months(files, 2025, "february")$Month, "february")
  expect_equal(.cpcb_combine_months(files, 2025, "March")$Month, "MARCH")
  expect_error(
    .cpcb_combine_months(files, 2025, "June"),
    "Data not found for year 2025 and month June"
  )
  expect_error(.cpcb_combine_months(list(), 2025), "Data not found for year 2025$")
})

test_that("a month name is not matched inside a station's name", {
  mock_months()
  files <- list(
    list(filepath = "/AQI_hourly/2025/January/Mayaganj_Bhagalpur_BSPCB_January_2025.xlsx", month = "January"),
    list(filepath = "/AQI_hourly/2025/May/Mayaganj_Bhagalpur_BSPCB_May_2025.xlsx", month = "May")
  )
  df <- .cpcb_combine_months(files, 2025, "May")
  expect_equal(df$Month, "May")
})

test_that("rows get the year and month, from the entry or the request", {
  mock_months()
  no_month <- list(list(filepath = "/x.csv"))
  df <- .cpcb_combine_months(no_month, "2025")
  expect_equal(df$Year, 2025L)
  expect_true(is.na(df$Month))

  entry_year <- list(list(filepath = "/x.csv", year = "2019", month = "May"))
  expect_equal(.cpcb_combine_months(entry_year, 2019, "May")$Year, 2019L)
  expect_equal(.cpcb_combine_months(list(list(filepath = "/x.csv", year = "n/a")), 2024)$Year, 2024L)
})

test_that("a month's workbook with no rows does not lose the other months", {
  mock_months(function(filepath, n_max = Inf) {
    if (grepl("Jan", filepath)) data.frame(Day = integer()) else data.frame(Day = 1)
  })
  files <- list(
    list(filepath = "/Jan.csv", month = "January"),
    list(filepath = "/Feb.csv", month = "February")
  )
  df <- .cpcb_combine_months(files, 2025)
  expect_equal(df$Month, "February")
})

test_that("text in an hourly column does not make it character", {
  mock_months(function(filepath, n_max = Inf) {
    data.frame(Day = c("1", "2"), `00:00:00` = c("NA", "81"), check.names = FALSE)
  })
  df <- .cpcb_combine_months(list(list(filepath = "/x.csv")), 2025)
  expect_type(df$`00:00:00`, "integer")
  expect_equal(df$`00:00:00`, c(NA, 81L))
  expect_equal(df$Day, 1:2)
})

test_that(".cpcb_save writes only when given a path", {
  df <- data.frame(a = 1:2)
  expect_identical(.cpcb_save(df, ""), df)

  out <- tempfile(fileext = ".csv")
  on.exit(unlink(out), add = TRUE)
  expect_identical(suppressMessages(.cpcb_save(df, out)), df)
  expect_equal(utils::read.csv(out), df)
})

test_that("cpcb_station_daily_aqi drops windows ending in the next year", {
  hours <- seq(as.POSIXct("2024-12-30 16:00:00", tz = "UTC"), by = "hour", length.out = 48)
  long <- data.frame(
    station_id = "site_301",
    timestamp = rep(hours, 3),
    pollutant = rep(c("PM2.5", "PM10", "NO2"), each = 48),
    unit = "ug/m3",
    value = rep(c(45, 80, 30), each = 48)
  )
  asked <- NULL
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    asked <<- list(station_id = station_id, year = year, args = list(...))
    long
  })

  out <- cpcb_station_daily_aqi("site_301", 2024, day_ends_at = 16)
  expect_equal(asked$args, list(tidy = TRUE))
  expect_equal(out$date, as.Date("2024-12-31"))
  # every sub-index is computed, and PM10's 80 ug/m3 is the highest (AQI 80)
  expect_equal(out$aqi, 80)
  expect_equal(out$n_pollutants, 3L)
})

test_that("cpcb_raw_readings keeps all pollutants or returns an empty long table", {
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, tidy) {
    if (station_id == "bad") stop("no file")
    expect_true(tidy)
    data.frame(station_id = station_id, pollutant = c("PM2.5", "RH"), value = c(1, 2))
  })
  expect_equal(nrow(cpcb_raw_readings("site_1", 2026)), 2)
  empty <- suppressMessages(cpcb_raw_readings("bad", 2026))
  expect_equal(nrow(empty), 0)
  expect_named(empty, c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value"))
})
