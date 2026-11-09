ip_json <- '{"status": "success", "lat": 28.65, "lon": 77.32}'

test_that("the system location comes from ip-api", {
  http <- local_http(fake_response(200, ip_json))
  loc <- cpcb_get_system_location()
  expect_equal(http$calls[[1]]$method, "GET")
  expect_equal(http$calls[[1]]$url, "http://ip-api.com/json")
  expect_equal(http$calls[[1]]$options$timeout_ms, 30000)
  expect_equal(loc, c(lat = 28.65, lon = 77.32))
})

test_that("a failed location lookup says why", {
  local_http(fake_response(200, '{"status": "fail", "message": "reserved range"}'))
  expect_error(cpcb_get_system_location(), "Geolocation lookup failed: reserved range")

  local_http(fake_response(500, "boom"))
  expect_error(cpcb_get_system_location(), "Error retrieving system location: .*500")

  local_http(connection_error())
  expect_error(cpcb_get_system_location(), "Error retrieving system location: Could not resolve")

  local_http(fake_response(200, "{broken"))
  expect_error(cpcb_get_system_location(), "Error retrieving system location")
})

test_that("cpcb_get_nearest_stations sorts by distance and applies k and radius", {
  local_cpcb()
  local_feed()
  # central Delhi
  near <- cpcb_get_nearest_stations(c(28.6139, 77.2090), k = 2)
  expect_named(near, c(
    "station_id", "station_name", "city", "state", "latitude", "longitude",
    "live", "avg", "distance_km"
  ))
  expect_equal(near$station_id, c("site_301", "site_feedonly"))
  expect_equal(near$city, c("Delhi", "Delhi"))
  expect_equal(near$live, c(TRUE, FALSE))
  # "NA" from CPCB is a missing AQI
  expect_equal(near$avg, c(180, NA))
  expect_type(near$latitude, "double")
  expect_true(near$distance_km[1] < near$distance_km[2])
  expect_equal(rownames(near), c("1", "2"))

  expect_equal(nrow(cpcb_get_nearest_stations(c(28.6139, 77.2090), k = 5)), 3)
  within <- cpcb_get_nearest_stations(c(19.05, 72.84), k = 5, max_distance_km = 50)
  expect_equal(within$station_id, "site_5392")
  expect_equal(nrow(cpcb_get_nearest_stations(c(0, 0), k = 5, max_distance_km = 1)), 0)
})

test_that("stations without coordinates are left out", {
  feed <- data.frame(
    id = c("a", "b"), name = c("A", "B"), latitude = c("bad", "20"), longitude = c("77", "77"),
    live = TRUE, avg = "50", city = "C", state = "S"
  )
  local_mocked_bindings(.cpcb_rss_stations = function() feed)
  expect_equal(cpcb_get_nearest_stations(c(20, 77), k = 5)$station_id, "b")
})

test_that("no coordinates means the IP location is used", {
  local_cpcb()
  http <- local_http(fake_response(200, ip_json), fake_response(200, cpcb_feed_json()))
  near <- cpcb_get_nearest_stations(k = 1)
  expect_equal(http$calls[[1]]$url, "http://ip-api.com/json")
  expect_equal(http$calls[[2]]$url, CPCB_FEED)
  expect_equal(near$station_id, "site_301")
})

test_that("cpcb_get_nearest_station returns the closest as a list", {
  local_cpcb()
  local_feed()
  nearest <- cpcb_get_nearest_station(c(19.05, 72.84))
  expect_named(nearest, c("station_id", "station_name", "distance_km"))
  expect_equal(nearest$station_id, "site_5392")
  expect_lt(nearest$distance_km, 1)
})

test_that("a feed with no usable stations is an error, not a bad list", {
  feed <- data.frame(id = "a", name = "A", latitude = NA, longitude = NA, live = TRUE, avg = "1", city = "C", state = "S")
  local_mocked_bindings(.cpcb_rss_stations = function() feed)
  expect_error(cpcb_get_nearest_station(c(1, 2)), "no stations with coordinates")
})

test_that("the live reading of a station comes from the feed", {
  local_cpcb()
  local_feed()
  out <- cpcb_get_live_aqi_data_for_station("site_301")

  expect_named(out, c(
    "station_id", "station_name", "lastUpdate", "airQualityIndex", "metrics",
    "source", "reading_state", "as_of"
  ))
  expect_equal(out$station_id, "site_301")
  expect_equal(out$station_name, "Anand Vihar, Delhi - DPCC")
  expect_equal(out$lastUpdate, "28-06-2026 18:00:00")
  expect_equal(out$airQualityIndex, 180)
  expect_equal(out$metrics$name, c("PM2.5", "PM10"))
  expect_equal(out$metrics$avg, c("40", "56"))
  expect_equal(out$metrics$min, c("17", "24"))
  expect_equal(out$metrics$max, c("65", "102"))
  expect_equal(out$metrics$avgDesc, rep("28-06-2026 18:00:00", 2))
})

test_that("part of a station name is enough for a live reading", {
  local_cpcb()
  local_feed()
  expect_equal(cpcb_get_live_aqi_data_for_station("Bandra Kurla")$station_id, "site_5392")
})

test_that("an offline station has no metrics and an NA index", {
  local_cpcb()
  local_feed()
  out <- cpcb_get_live_aqi_data_for_station("site_feedonly")
  expect_identical(out$airQualityIndex, NA_real_)
  expect_equal(out$metrics, data.frame())
})

test_that("live readings validate the station", {
  local_cpcb()
  local_feed()
  expect_error(cpcb_get_live_aqi_data_for_station(NULL), "station_id must be provided")
  expect_error(
    cpcb_get_live_aqi_data_for_station("site_nope"),
    "Station site_nope not found in the CPCB live feed"
  )
})

test_that("date arguments are ignored with a warning alert", {
  local_cpcb()
  local_feed()
  expect_message(
    out <- cpcb_get_live_aqi_data_for_station("site_301", date_time = "2024-01-01"),
    "date_time is ignored"
  )
  expect_equal(out$station_id, "site_301")
  expect_message(
    cpcb_get_live_aqi_data("site_301", date = "2024-01-01", hour = 3),
    "date and hour are ignored"
  )
})

test_that("cpcb_get_live_aqi_data finds the nearest station without an ID", {
  local_cpcb()
  local_feed()
  out <- cpcb_get_live_aqi_data(coords = c(19.05, 72.84))
  expect_equal(out$station_id, "site_5392")
  expect_equal(out$airQualityIndex, 95)
})

test_that("live data feeds into metrics and the empty long table", {
  local_cpcb()
  local_feed()
  live <- cpcb_get_live_aqi_data("site_301")
  metrics <- cpcb_live_metrics(live)
  expect_equal(metrics$pollutant, c("PM2.5", "PM10"))
  expect_equal(metrics$avg, c(40, 56))
  expect_equal(metrics$period, rep("28-06-2026 18:00:00", 2))

  long <- cpcb_live_to_long(live)
  expect_equal(nrow(long), 0)
  expect_named(long, c("station_id", "timestamp", "pollutant", "value"))
})
