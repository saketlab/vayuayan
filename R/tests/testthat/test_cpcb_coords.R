nominatim <- function(query) {
  paste0("https://nominatim.openstreetmap.org/search?q=", query, "&format=json&limit=1")
}

test_that("stations in the directory need no request", {
  local_cpcb()
  http <- local_http()
  stations <- data.frame(label = "Anand Vihar, Delhi - DPCC", value = "site_301")
  out <- suppressMessages(cpcb_add_coords(stations))

  known <- .cpcb_directory_stations()
  row <- known[known$station_id == "site_301", ]
  expect_equal(out$lat, row$latitude)
  expect_equal(out$lon, row$longitude)
  expect_length(http$calls, 0)
  expect_message(cpcb_add_coords(stations), "Done: 1/1 stations have coordinates")
})

test_that("newer stations get coordinates from the live feed", {
  local_cpcb()
  http <- local_feed()
  stations <- data.frame(label = "Zeta Colony", value = "site_feedonly")
  out <- suppressMessages(cpcb_add_coords(stations))

  expect_equal(http$calls[[1]]$url, CPCB_FEED)
  expect_length(http$calls, 1)
  expect_equal(out$lat, 28.70)
  expect_equal(out$lon, 77.10)
})

test_that("Nominatim is the last resort, one request per missing station", {
  local_cpcb()
  pauses <- 0
  local_mocked_bindings(.nominatim_pause = function() pauses <<- pauses + 1)
  http <- local_feed(
    fake_response(200, '[{"lat": "19.05", "lon": "72.84"}]'),
    fake_response(200, "[]"),
    connection_error("Timeout was reached")
  )
  stations <- data.frame(
    label = c("Bandra, Mumbai - MPCB", "Nowhere Park", "Broken Place - CPCB extra"),
    value = c("site_x1", "site_x2", "site_x3")
  )
  msgs <- character(0)
  out <- withCallingHandlers(
    cpcb_add_coords(stations),
    message = function(m) {
      msgs <<- c(msgs, conditionMessage(m))
      invokeRestart("muffleMessage")
    }
  )

  expect_length(http$calls, 4)
  expect_equal(pauses, 3)
  # the agency suffix is removed before geocoding
  expect_equal(http$calls[[2]]$url, nominatim("Bandra,%20Mumbai"))
  expect_equal(http$calls[[3]]$url, nominatim("Nowhere%20Park"))
  expect_equal(http$calls[[4]]$url, nominatim("Broken%20Place"))
  expect_equal(http$calls[[2]]$options$useragent, "vayuayan-r-package")
  expect_equal(http$calls[[2]]$options$timeout_ms, 10000)

  expect_equal(out$lat, c(19.05, NA, NA))
  expect_equal(out$lon, c(72.84, NA, NA))
  expect_true(any(grepl("3 stations have no CPCB coordinates", msgs)))
  expect_true(any(grepl("NO RESULT for Nowhere Park", msgs)))
  expect_true(any(grepl("FAILED for Broken Place - Timeout was reached", msgs)))
  expect_true(any(grepl("Done: 1/3 stations", msgs)))
})

test_that("a feed outage warns, then falls through to Nominatim", {
  local_cpcb()
  local_mocked_bindings(.nominatim_pause = function() invisible())
  http <- local_http(
    fake_response(500, "down"),
    fake_response(200, '[{"lat": "20.5", "lon": "78.5"}]')
  )
  stations <- data.frame(label = "New Place - DPCC", value = "site_x9")
  expect_warning(
    out <- suppressMessages(cpcb_add_coords(stations)),
    "CPCB live feed unavailable"
  )
  expect_equal(http$calls[[2]]$url, nominatim("New%20Place"))
  expect_equal(out$lat, 20.5)
})

test_that("the Nominatim pause keeps to one request a second", {
  waited <- NULL
  pause <- .nominatim_pause
  environment(pause) <- list2env(
    list(Sys.sleep = function(time) waited <<- time),
    parent = environment(pause)
  )
  pause()
  expect_equal(waited, 1)
})
