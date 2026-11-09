test_that("a city listing is a JSON POST with CPCB's canonical names", {
  local_cpcb()
  http <- local_http(fake_response(200, file_listing(filepath = "/a.xlsx", year = "2022")))
  files <- cpcb_get_file_path(city = "delhi", frequency = "daily", data_type = "cityLevel")

  call <- http$calls[[1]]
  expect_equal(call$method, "POST")
  expect_equal(call$url, paste0(CPCB_REPO, "file-path"))
  expect_equal(call$encode, "json")
  expect_equal(call$headers[["Accept"]], "application/json")
  expect_equal(call$options$timeout_ms, 30000)
  expect_equal(call$body, list(
    station_id = "", station_name = "", state = "Delhi", city = "Delhi",
    year = "", frequency = "1D", dataType = "cityLevel"
  ))
  expect_equal(files, list(list(filepath = "/a.xlsx", year = "2022")))
})

test_that("an unknown city is sent as the caller wrote it", {
  local_cpcb()
  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path(state = "Nowhere", city = "Atlantis", year = 2024, frequency = "monthly")

  expect_equal(http$calls[[1]]$body, list(
    station_id = "", station_name = "", state = "Nowhere", city = "Atlantis",
    year = "2024", frequency = "1M", dataType = "cityLevel"
  ))
})

test_that("a known city drops any station fields the caller set", {
  local_cpcb()
  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path(station_id = "x", station_name = "y", city = "mumbai")
  body <- http$calls[[1]]$body
  expect_equal(body$station_id, "")
  expect_equal(body$station_name, "")
  expect_equal(body$state, "Maharashtra")
  expect_equal(body$city, "Mumbai")
})

test_that("a station listing sends the resolved station", {
  local_cpcb()
  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path(station_id = "site_5392", year = 2024, frequency = "hourly", data_type = "stationLevel")

  expect_equal(http$calls[[1]]$body, list(
    station_id = "site_5392", station_name = "Bandra Kurla Complex, Mumbai - IITM",
    state = "Maharashtra", city = "Mumbai", year = "2024", frequency = "1H",
    dataType = "stationLevel"
  ))
})

test_that("a raw listing uses the 15-minute code and the station from its name", {
  local_cpcb()
  local_no_feed()
  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path(
    station_name = "Anand Vihar, Delhi - DPCC", year = 2023,
    frequency = "15_minute", data_type = "raw"
  )
  expect_equal(http$calls[[1]]$body, list(
    station_id = "site_301", station_name = "Anand Vihar, Delhi - DPCC",
    state = "Delhi", city = "Delhi", year = "2023", frequency = "15M", dataType = "raw"
  ))
})

test_that("a station lookup failure still sends what the caller gave", {
  local_cpcb()
  http <- local_feed(fake_response(204, ""))
  cpcb_get_file_path(station_id = "site_nope", city = "X", data_type = "stationLevel")
  # first the feed lookup, then the listing itself
  expect_equal(http$calls[[1]]$url, CPCB_FEED)
  expect_equal(http$calls[[2]]$body$station_id, "site_nope")
  expect_equal(http$calls[[2]]$body$city, "X")
})

test_that("any other data type is sent without a lookup", {
  local_cpcb()
  http <- local_http(fake_response(204, ""))
  cpcb_get_file_path(station_id = "abc", state = "S", city = "C", data_type = "custom")
  expect_length(http$calls, 1)
  expect_equal(http$calls[[1]]$body$station_id, "abc")
  expect_equal(http$calls[[1]]$body$dataType, "custom")
})

test_that("each file comes back with the fields CPCB sent", {
  local_cpcb()
  body <- file_listing(filepath = c("/a.xlsx", "/b.xlsx"), year = c("2021", "2022"), month = c(NA, "May"))
  local_http(fake_response(200, body))
  files <- cpcb_get_file_path(city = "Delhi")
  expect_length(files, 2)
  expect_equal(files[[2]]$filepath, "/b.xlsx")
  expect_equal(files[[2]]$month, "May")
  expect_equal(files[[1]]$year, "2021")
})

test_that("no match in any of CPCB's forms is an empty listing", {
  local_cpcb()
  no_match <- list(
    list(204L, ""),
    list(200L, ""),
    list(200L, '{"status": "success", "data": []}'),
    list(200L, '{"status": "success"}'),
    list(200L, '{"status": "success", "data": null}')
  )
  for (case in no_match) {
    local_http(fake_response(case[[1]], case[[2]]))
    expect_equal(cpcb_get_file_path(city = "Delhi"), list(), info = case[[2]])
  }
})

test_that("a failing listing raises an error", {
  local_cpcb()
  for (status in c(400L, 404L, 500L, 503L)) {
    local_http(fake_response(status, "error"))
    expect_error(cpcb_get_file_path(city = "Delhi"), class = paste0("http_", status))
  }
  local_http(connection_error())
  expect_error(cpcb_get_file_path(city = "Delhi"), "Could not resolve")

  local_http(fake_response(200, "<html>maintenance</html>"))
  expect_error(cpcb_get_file_path(city = "Delhi"))
})

test_that("a TLS failure on the listing retries unverified", {
  local_cpcb()
  http <- local_http(
    connection_error("SSL: certificate verify failed"),
    fake_response(200, file_listing(filepath = "/a.xlsx", year = "2022"))
  )
  files <- suppressMessages(cpcb_get_file_path(city = "Delhi"))
  expect_length(files, 1)
  expect_equal(http$calls[[1]]$method, "POST")
  expect_null(http$calls[[1]]$ssl_verifypeer)
  expect_equal(http$calls[[2]]$ssl_verifypeer, 0L)
})
