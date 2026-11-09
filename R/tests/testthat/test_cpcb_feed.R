test_that("the live feed is a plain GET of the coordinates feed", {
  local_cpcb()
  http <- local_feed()
  cities <- cpcb_get_all_india()

  call <- http$calls[[1]]
  expect_equal(call$method, "GET")
  expect_equal(call$url, CPCB_FEED)
  expect_null(call$query)
  expect_match(call$options$useragent, "Mozilla/5.0", fixed = TRUE)
  expect_equal(call$options$timeout_ms, 30000)
  expect_named(cities, c("cityName", "cityID", "stateID", "stationsInCity"))
})

test_that("the feed retries like every other CPCB GET, but not on 4xx", {
  local_cpcb()
  http <- local_feed()
  .cpcb_rss_cities()
  expect_equal(http$calls[[1]]$args$times, 4)
  expect_equal(http$calls[[1]]$args$terminate_on, 400:499)
})

test_that("the feed is flattened to cities with stations, empty ones dropped", {
  local_cpcb()
  local_feed()
  cities <- .cpcb_rss_cities()

  # sorted by share of live stations: Mumbai 100%, Delhi 50%
  expect_equal(cities$cityName, c("Mumbai", "Delhi"))
  expect_equal(cities$cityID, cities$cityName)
  expect_equal(cities$stateID, c("Maharashtra", "Delhi"))

  delhi <- cities$stationsInCity[[2]]
  expect_named(delhi, c("id", "name", "latitude", "longitude", "live", "avg", "lastUpdate", "pollutants"))
  # the live station sorts first
  expect_equal(delhi$id, c("site_301", "site_feedonly"))
  expect_equal(delhi$live, c(TRUE, FALSE))
  expect_equal(delhi$avg, c("180", "NA"))
  expect_equal(delhi$pollutants[[1]]$indexId, c("PM2.5", "PM10"))
})

test_that(".cpcb_rss_stations adds the city and state of each station", {
  local_cpcb()
  local_feed()
  st <- .cpcb_rss_stations()
  expect_equal(st$id, c("site_5392", "site_301", "site_feedonly"))
  expect_equal(st$city, c("Mumbai", "Delhi", "Delhi"))
  expect_equal(st$state, c("Maharashtra", "Delhi", "Delhi"))
})

test_that("the feed is fetched once within the TTL and again after it", {
  local_cpcb()
  http <- local_feed(fake_response(200, cpcb_feed_json()))

  first <- .cpcb_rss_cities()
  expect_equal(.cpcb_rss_cities(), first)
  expect_length(http$calls, 1)

  .cpcb_cache$rss$time <- Sys.time() - 60 * (.cpcb_rss_ttl_mins + 1)
  .cpcb_rss_cities()
  expect_length(http$calls, 2)
})

test_that("a failing feed raises an error and is not cached", {
  local_cpcb()
  cases <- list(
    list(reply = fake_response(404, "gone"), class = "http_404"),
    list(reply = fake_response(502, "bad gateway"), class = "http_502")
  )
  for (case in cases) {
    local_http(case$reply)
    expect_error(.cpcb_rss_cities(), class = case$class)
    expect_null(.cpcb_cache$rss)
  }

  local_http(connection_error())
  expect_error(.cpcb_rss_cities(), "Could not resolve")

  local_http(fake_response(200, "{not json"))
  expect_error(.cpcb_rss_cities())
  expect_null(.cpcb_cache$rss)

  local_http(fake_response(200, ""))
  expect_error(.cpcb_rss_cities())
  expect_null(.cpcb_cache$rss)
})

test_that("a feed TLS failure retries unverified for the session", {
  local_cpcb()
  http <- local_http(
    connection_error("SSL peer certificate was not OK"),
    fake_response(200, cpcb_feed_json())
  )
  cities <- suppressMessages(.cpcb_rss_cities())
  expect_equal(nrow(cities), 2)
  expect_null(http$calls[[1]]$ssl_verifypeer)
  expect_equal(http$calls[[2]]$ssl_verifypeer, 0L)
})

test_that("a feed without states yields no cities", {
  local_cpcb()
  local_http(fake_response(200, '{"country": []}'))
  expect_null(.cpcb_rss_cities())
})

test_that("a feed without states means no nearby stations", {
  local_cpcb()
  local_http(fake_response(200, '{"country": []}'))
  near <- cpcb_get_nearest_stations(c(28.6, 77.2))
  expect_equal(nrow(near), 0)
  expect_true("station_id" %in% names(near))
})

test_that(".cpcb_rss_station_frame fills fields CPCB left out", {
  out <- .cpcb_rss_station_frame(data.frame(siteId = "site_1"))
  expect_equal(out$id, "site_1")
  expect_true(is.na(out$name))
  expect_false(out$live)
  expect_equal(out$lastUpdate, "")
  expect_null(out$pollutants[[1]])

  live <- .cpcb_rss_station_frame(data.frame(
    siteId = c("a", "b"), lastUpdate = c("today", NA)
  ))
  expect_equal(live$live, c(TRUE, FALSE))
})

test_that(".cpcb_sort_cities leaves no cities alone and breaks ties by name", {
  expect_null(.cpcb_sort_cities(NULL))
  empty <- data.frame(cityName = character())
  expect_equal(nrow(.cpcb_sort_cities(empty)), 0)

  st <- function(live, name) data.frame(live = live, name = name, id = name)
  cities <- data.frame(cityName = c("beta", "Alpha", "Gamma"))
  cities$stationsInCity <- list(st(TRUE, "x"), st(TRUE, "y"), st(c(FALSE, TRUE), c("a", "z")))
  out <- .cpcb_sort_cities(cities)

  expect_equal(out$cityName, c("Alpha", "beta", "Gamma"))
  expect_equal(out$stationsInCity[[3]]$name, c("z", "a"))
  expect_equal(rownames(out), c("1", "2", "3"))
})
