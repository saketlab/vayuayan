test_that("CPCBHistorical initializes correctly", {
  client <- CPCBHistorical$new()
  
  expect_s3_class(client, "CPCBHistorical")
  expect_equal(client$base_url, "https://airquality.cpcb.gov.in")
  expect_type(client$headers, "list")
})

test_that("get_state_list returns character vector", {
  skip_on_cran()
  skip_if_offline()
  
  client <- CPCBHistorical$new()
  states <- client$get_state_list()
  
  expect_type(states, "character")
  expect_gt(length(states), 0)
  expect_true(all(!is.na(states)))
})

test_that("get_city_list returns cities for valid state", {
  skip_on_cran()
  skip_if_offline()
  
  client <- CPCBHistorical$new()
  cities <- client$get_city_list("Maharashtra")
  
  expect_type(cities, "character")
  expect_gt(length(cities), 0)
})

test_that("get_city_list returns empty for invalid state", {
  skip_on_cran()
  skip_if_offline()
  
  client <- CPCBHistorical$new()
  cities <- client$get_city_list("InvalidState123")
  
  expect_type(cities, "character")
  expect_equal(length(cities), 0)
})

test_that("get_station_list returns data frame for valid city", {
  skip_on_cran()
  skip_if_offline()
  
  client <- CPCBHistorical$new()
  stations <- client$get_station_list("Mumbai")
  
  expect_s3_class(stations, "data.frame")
  expect_true("station_id" %in% names(stations))
  expect_true("station_name" %in% names(stations))
})

test_that("get_complete_list returns list with expected structure", {
  skip_on_cran()
  skip_if_offline()
  
  client <- CPCBHistorical$new()
  complete_list <- client$get_complete_list()
  
  expect_type(complete_list, "list")
  expect_true("cities" %in% names(complete_list))
  expect_true("stations" %in% names(complete_list))
})

test_that("base64 encoding and decoding works correctly", {
  client <- CPCBHistorical$new()
  
  # Access private method for testing
  encode_base64 <- client$.__enclos_env__$private$encode_base64
  decode_base64 <- client$.__enclos_env__$private$decode_base64
  
  test_string <- "Hello, World!"
  encoded <- encode_base64(test_string)
  decoded <- decode_base64(encoded)
  
  expect_type(encoded, "character")
  expect_equal(decoded, test_string)
})

test_that("download functions require valid parameters", {
  skip_on_cran()
  
  client <- CPCBHistorical$new()
  
  # Test city data download with invalid city
  expect_error(
    client$download_city_data("InvalidCity123", "2024", tempfile()),
    "not found"
  )
  
  # Test station data download with invalid station
  expect_error(
    client$download_station_data("invalid_station", "2024", tempfile()),
    "not found"
  )
})
