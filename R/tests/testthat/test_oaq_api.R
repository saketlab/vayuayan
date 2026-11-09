session <- list(base_url = "https://data.example/v1", sig_string = "Expires=1&Signature=abc")

url_for <- function(path) paste0("https://data.example/v1/", path, "?Expires=1&Signature=abc")

test_that("the OAQ session handshake calls the broker with the key", {
  http <- local_http(fake_response(200, '{"baseUrl": "https://cdn.example/v1/", "signature": "sig=1"}'))
  s <- oaq_session("KEY123")

  expect_equal(http$calls[[1]]$method, "GET")
  expect_equal(
    http$calls[[1]]$url,
    "https://us-central1-oaqdms.cloudfunctions.net/brokerData?action=api_session&token=KEY123"
  )
  expect_equal(http$calls[[1]]$options$timeout_ms, 30000)
  expect_equal(s, list(base_url = "https://cdn.example/v1", sig_string = "sig=1"))
})

test_that("the OAQ session defaults the base URL and accepts Signature", {
  local_http(fake_response(200, '{"Signature": "S"}'))
  expect_equal(oaq_session("k"), list(base_url = "https://oaq.notf.in/v1", sig_string = "S"))
})

test_that("the OAQ session reports what went wrong", {
  old <- Sys.getenv("OAQ_API_KEY", unset = NA)
  Sys.unsetenv("OAQ_API_KEY")
  on.exit(if (!is.na(old)) Sys.setenv(OAQ_API_KEY = old), add = TRUE)
  expect_error(oaq_session(), "OAQ API key not found")

  local_http(connection_error())
  expect_error(oaq_session("k"), "OAQ handshake request failed: Could not resolve")

  local_http(fake_response(401, "denied"))
  expect_error(oaq_session("k"), class = "http_401")

  local_http(fake_response(200, '{"status": "error"}'))
  expect_error(oaq_session("k"), "missing signature")
})

test_that("each OAQ endpoint requests its signed path", {
  cases <- list(
    list(function() oaq_list_providers(session), "meta/providers.json"),
    list(function() oaq_get_hierarchy(session, "AURASSURE"), "provider=aurassure/meta/hierarchy.json"),
    list(function() oaq_get_stations_latest(session, "CPCB"), "provider=cpcb/live/global/all_stations_latest.json"),
    list(function() oaq_get_station_24h(session, "AIRNET", "12036"), "provider=airnet/live/sensors/12036/last24h.json"),
    list(function() oaq_get_daily(session, "AIRNET", "12036", "2026", "9", 4), "provider=airnet/history/daily/12036/2026/09/04.json"),
    list(function() oaq_get_monthly(session, "AIRNET", "12036", 2026, "09"), "provider=airnet/history/aggregates/12036/monthly_2026_09.json"),
    list(function() oaq_get_annual(session, "AIRNET", "12036", 2026), "provider=airnet/history/aggregates/12036/annual_2026.json"),
    list(function() oaq_get_city_latest(session, "AIRNET", "Bengaluru"), "provider=airnet/live/by_city/bengaluru/map_latest.json")
  )
  for (case in cases) {
    http <- local_http(fake_response(200, '{"data": [{"pm25": 12}]}'))
    got <- case[[1]]()
    expect_equal(http$calls[[1]]$method, "GET", info = case[[2]])
    expect_equal(http$calls[[1]]$url, url_for(case[[2]]), info = case[[2]])
    expect_equal(got$data$pm25, 12L, info = case[[2]])
  }
})

test_that("OAQ requests fail with a reason", {
  local_http(fake_response(404, "missing"))
  expect_error(oaq_get_annual(session, "x", "1", 2026), class = "http_404")
  local_http(fake_response(503, "busy"))
  expect_error(oaq_get_annual(session, "x", "1", 2026), class = "http_503")
  local_http(connection_error())
  expect_error(oaq_get_annual(session, "x", "1", 2026), "OAQ request failed: Could not resolve")
  local_http(fake_response(200, "<html>"))
  expect_error(oaq_get_annual(session, "x", "1", 2026), "Failed to parse OAQ response")
})

test_that("oaq_stations_table combines providers and drops stations with no place", {
  bodies <- list(
    cpcb = '{"stations": [{"id": "1", "lat": "12.5", "lon": "77.5", "pm25": "9"}, {"id": "2", "lat": "NA", "lon": "77.5", "pm25": "9"}]}',
    airnet = '{"stations": [{"id": "2CF", "lat": "13.0", "lon": "78.0"}]}'
  )
  http <- local_http(fake_response(200, bodies$cpcb), fake_response(200, bodies$airnet))
  out <- oaq_stations_table(session, c("cpcb", "airnet"))

  expect_equal(http$calls[[1]]$url, url_for("provider=cpcb/live/global/all_stations_latest.json"))
  expect_equal(http$calls[[2]]$url, url_for("provider=airnet/live/global/all_stations_latest.json"))
  expect_equal(out$id, c("1", "2CF"))
  expect_equal(out$provider, c("cpcb", "airnet"))
  expect_type(out$lat, "double")
})

test_that("oaq_fetch_monthly_stations filters cities and skips empty months", {
  table <- data.frame(id = c(1, 2), name = c("A", "B"), lat = 1, lon = 2, city = c("X", "Y"))
  asked <- character(0)
  local_mocked_bindings(
    oaq_stations_table = function(session, provider) table,
    oaq_get_monthly = function(session, provider, sensor_id, year, month) {
      asked <<- c(asked, paste(sensor_id, month))
      if (month == "01") stop(http_404_error())
      if (month == "02") return(list(data = data.frame()))
      list(data = data.frame(date = "2026-03-01", pm25 = 10))
    }
  )
  out <- oaq_fetch_monthly_stations(list(), "cpcb", 2026, months = c("01", "02", "03"), city = "X")

  expect_equal(asked, c("1 01", "1 02", "1 03"))
  expect_equal(out$station_id, 1L)
  expect_equal(out$date, as.Date("2026-03-01"))
  expect_equal(out$name, "A")
})

test_that("oaq_fetch_monthly_stations is empty when no station has data", {
  local_mocked_bindings(
    oaq_stations_table = function(session, provider) data.frame(id = "1", lat = 1, lon = 2, city = "X"),
    oaq_get_monthly = function(...) stop(http_404_error())
  )
  out <- oaq_fetch_monthly_stations(list(), "cpcb", 2026, months = "01")
  expect_equal(nrow(out), 0)
  expect_false("date" %in% names(out))
})

test_that("oaq_daily_means covers several sensors and all-missing days", {
  day <- data.frame(date = paste0("t", 1:2), pm25 = c(10, 20))
  local_mocked_bindings(oaq_get_daily = function(session, provider, sensor_id, year, month, day_of) {
    if (sensor_id == "none") stop(http_404_error())
    list(data = day)
  })
  both <- oaq_daily_means(list(), "x", c("a", "b"), "2026-09-01", min_readings = 2)
  expect_equal(both$sensor_id, c("a", "b"))
  expect_equal(both$pm25, c(15, 15))
  expect_equal(oaq_daily_means(list(), "x", "none", "2026-09-01"), data.frame())
})

test_that("oaq_daily_records covers several sensors and years without files", {
  local_mocked_bindings(oaq_get_annual = function(session, provider, sensor_id, year) {
    if (sensor_id == "none") stop(http_404_error())
    list(data = data.frame(date = c("2026-05-29T00:00:00", "garbage"), pm25 = c("5", "6")))
  })
  both <- oaq_daily_records(list(), "x", c("a", "b"), 2026)
  expect_equal(both$sensor_id, c("a", "b"))
  expect_equal(both$date, as.Date(c("2026-05-29", "2026-05-29")))
  expect_equal(both$pm25, c(5, 5))

  none <- oaq_daily_records(list(), "x", "none", 2026)
  expect_equal(nrow(none), 0)
  expect_named(none, c("sensor_id", "date"))
  expect_s3_class(none$date, "Date")
})

test_that("oaq_check_daily_records is empty without records or readings", {
  empty <- .empty_records()
  expect_equal(nrow(empty), 0)
  expect_true("record_is_last_4_mean" %in% names(empty))

  local_mocked_bindings(
    oaq_daily_records = function(session, provider, sensor_id, years) {
      data.frame(sensor_id = character(), date = as.Date(character()))
    }
  )
  expect_equal(oaq_check_daily_records(list(), "x", "s", "2026-01-01"), empty)

  local_mocked_bindings(
    oaq_daily_records = function(session, provider, sensor_id, years) {
      data.frame(sensor_id = sensor_id, date = as.Date("2026-01-01"), pm25 = 5)
    },
    oaq_readings = function(session, provider, sensor_id, dates) data.frame()
  )
  expect_equal(oaq_check_daily_records(list(), "x", "s", "2026-01-01"), empty)
})

test_that("compare_daily_records is empty when a side has no usable rows", {
  readings <- data.frame(sensor_id = "s", timestamp = as.POSIXct("2026-01-01", tz = "UTC"), pm25 = NA_real_)
  records <- data.frame(sensor_id = "s", date = as.Date("2026-01-01"), pm25 = 10)
  expect_equal(compare_daily_records(readings, records), .empty_records())
})

test_that("oaq_audit_daily_records stops at today in India and can be empty", {
  today <- as.Date(format(Sys.time(), tz = "Asia/Kolkata", "%Y-%m-%d"))
  seen <- NULL
  local_mocked_bindings(
    oaq_daily_records = function(session, provider, sensor_id, years) {
      data.frame(sensor_id = sensor_id, date = c(today - 1, today))
    },
    oaq_check_daily_records = function(session, provider, sensor_id, dates, value, tolerance) {
      seen <<- dates
      .empty_records()
    }
  )
  out <- oaq_audit_daily_records(list(), data.frame(provider = "cpcb", sensor_id = "1"), 2026)
  expect_equal(seen, today - 1)
  expect_equal(nrow(out), 0)
  expect_true("provider" %in% names(out))
})
