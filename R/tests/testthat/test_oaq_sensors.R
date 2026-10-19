test_that("oaq_sensors lists every provider by default", {
  asked <- NULL
  local_mocked_bindings(
    oaq_list_providers = function(session) {
      list(providers = data.frame(id = c("cpcb", "airnet")))
    },
    oaq_stations_table = function(session, provider) {
      asked <<- provider
      "table"
    }
  )
  expect_equal(oaq_sensors(list()), "table")
  expect_equal(asked, c("cpcb", "airnet"))
  oaq_sensors(list(), "airnet")
  expect_equal(asked, "airnet")
})

test_that("oaq_city_tally counts only OAQ sensors", {
  sensors <- data.frame(
    id = c("a", "b", "c", "d"), name = c("A", "B", "C", "D"),
    city = c("Bengaluru", "Bengaluru", "Nowhere", "Delhi"),
    lat = c(12.99, 12.95, 21.49, 28.55), lon = c(77.58, 77.60, 83.87, 77.27),
    provider = c("airnet", "airnet", "aurassure", "cpcb")
  )
  tally <- oaq_city_tally(sensors)
  expect_equal(tally$city, c("Bengaluru", "Nowhere"))
  expect_equal(tally$sensors, c(2L, 1L))
  expect_equal(tally$cpcb_stations[2], 0L)
  nearest <- oaq_nearest_cpcb(sensors, k = 3)
  expect_true(all(tapply(nearest$rank, nearest$sensor_id, max) == 3))
  expect_equal(nrow(oaq_city_tally(sensors[sensors$provider == "cpcb", ])), 0)
})

test_that("oaq_daily_means need enough readings", {
  full <- data.frame(date = paste0("t", 1:96), pm25 = 10 + (0:95) %% 2, pm10 = NA)
  short <- data.frame(date = paste0("t", 1:10), pm25 = 50)
  local_mocked_bindings(oaq_get_daily = function(session, provider, sensor_id, year, month, day) {
    if (day == "03") stop("no file")
    list(data = if (day == "01") full else short)
  })
  out <- oaq_daily_means(list(), "airnet", "s1", c("2026-09-01", "2026-09-02", "2026-09-03"))
  expect_equal(as.character(out$date), c("2026-09-01", "2026-09-02"))
  expect_equal(out$pm25[1], 10.5)
  expect_true(is.na(out$pm25[2]))
  expect_equal(out$n_pm25, c(96L, 10L))
  expect_equal(out$n_pm10[1], 0L)
})

test_that("oaq_readings stack days in local time", {
  days <- list(
    "01" = data.frame(
      date = c("2026-09-01T00:00:00+05:30", "2026-09-01T00:15:00+05:30"),
      pm25 = c("12.5", "13"), pm10 = c(NA, 40)
    ),
    "02" = data.frame(date = "bad", pm25 = 1)
  )
  local_mocked_bindings(oaq_get_daily = function(session, provider, sensor_id, year, month, day) {
    if (is.null(days[[day]])) stop("no file")
    list(data = days[[day]])
  })
  out <- oaq_readings(list(), "airnet", "s1", c("2026-09-01", "2026-09-02", "2026-09-03"))
  expect_named(out, c("sensor_id", "timestamp", "pm25", "pm10"))
  expect_equal(format(out$timestamp, "%Y-%m-%d %H:%M:%S"), c("2026-09-01 00:00:00", "2026-09-01 00:15:00"))
  expect_equal(out$pm25, c(12.5, 13))
  expect_true(is.na(out$pm10[1]))
  expect_equal(nrow(oaq_readings(list(), "airnet", "s1", "2026-09-03")), 0)
})

.fake_oaq <- function(env = parent.frame()) {
  readings <- data.frame(
    date = c(sprintf("2026-05-29T%02d:00:00+05:30", 0:22), "2026-05-29T23:45:00+05:30"),
    pm25 = c(rep(10, 23), 300)
  )
  local_mocked_bindings(
    oaq_get_annual = function(session, provider, sensor_id, year) {
      if (year != 2026) stop("no file")
      list(data = data.frame(date = "2026-05-29", pm25 = 300, temp = "31"))
    },
    oaq_get_daily = function(session, provider, sensor_id, year, month, day) {
      if (month != "05" || day != "29") stop("no file")
      list(data = readings)
    },
    .env = env
  )
}

test_that("oaq_daily_records and their check", {
  .fake_oaq()
  records <- oaq_daily_records(list(), "cpcb", "164", c(2025, 2026))
  expect_equal(records$date, as.Date("2026-05-29"))
  expect_equal(records$temp, 31)
  check <- oaq_check_daily_records(list(), "cpcb", "164", c("2026-05-29", "2026-05-30"))
  expect_equal(nrow(check), 1)
  expect_equal(check$n, 24L)
  expect_equal(check$last, 300)
  expect_true(check$record_is_last)
  expect_false(check$record_is_mean)
  expect_equal(check$mean, (23 * 10 + 300) / 24)
})

test_that("oaq_readings of several sensors", {
  .fake_oaq()
  out <- oaq_readings(list(), "cpcb", c("164", "165"), "2026-05-29")
  expect_equal(as.integer(table(out$sensor_id)), c(24L, 24L))
})

test_that("cpcb_raw_readings skips stations without data", {
  local_mocked_bindings(cpcb_download_raw_station_data = function(station_id, year, ...) {
    if (station_id == "site_2") stop("none")
    data.frame(station_id = station_id, pollutant = c("PM2.5", "RH"), value = c(1, 2))
  })
  out <- suppressMessages(cpcb_raw_readings(c("site_1", "site_2"), 2026, "PM2.5"))
  expect_equal(out$station_id, "site_1")
  expect_equal(out$value, 1)
})

test_that("OAQ data requests retry, but not on 4xx", {
  args <- NULL
  local_mocked_bindings(
    RETRY = function(verb, url, ..., times, terminate_on, quiet) {
      args <<- list(times = times, terminate_on = terminate_on)
      structure(list(status_code = 200L), class = "response")
    },
    stop_for_status = function(x, ...) invisible(x),
    content = function(x, ...) '{"data": [1]}',
    .package = "httr"
  )
  expect_equal(.oaq_get("x.json", list(base_url = "https://x", sig_string = "s"))$data, 1L)
  expect_gt(args$times, 1)
  expect_true(all(c(404L, 403L) %in% args$terminate_on))
})

test_that("oaq_fetch_monthly_stations combines providers with different ids and columns", {
  local_mocked_bindings(
    oaq_stations_table = function(session, provider) {
      if (provider == "cpcb") {
        data.frame(id = 1553L, name = "A", lat = 1, lon = 2, city = "X", provider = "cpcb")
      } else {
        data.frame(id = "2CF4", name = "B", lat = 1, lon = 2, city = "X", provider = "airnet")
      }
    },
    oaq_get_monthly = function(session, provider, sensor_id, year, month) {
      if (provider == "cpcb") {
        list(data = data.frame(date = "2026-03-01", pm25 = 10, no2 = 5))
      } else {
        list(data = data.frame(date = "2026-03-01", pm25 = 20))
      }
    }
  )
  out <- oaq_fetch_monthly_stations(list(), c("cpcb", "airnet"), 2026, months = "03")
  expect_equal(sort(out$station_id), c("1553", "2CF4"))
  expect_equal(out$no2[out$station_id == "2CF4"], NA_real_)
})

test_that("oaq_get_city_latest uses lower-case paths", {
  path <- NULL
  local_mocked_bindings(.oaq_get = function(p, session) {
    path <<- p
    list()
  })
  oaq_get_city_latest(list(), "AIRNET", "Bengaluru")
  expect_equal(path, "provider=airnet/live/by_city/bengaluru/map_latest.json")
})
