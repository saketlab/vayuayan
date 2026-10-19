test_that("get_state_list returns character vector", {
  skip_on_cran()
  skip_if_offline()

  states <- cpcb_get_state_list()

  expect_type(states, "character")
  expect_gt(length(states), 0)
  expect_true(all(!is.na(states)))
})

test_that("get_city_list returns cities for valid state", {
  skip_on_cran()
  skip_if_offline()

  cities <- cpcb_get_city_list("Maharashtra")

  expect_type(cities, "character")
  expect_gt(length(cities), 0)
})

test_that("get_city_list returns empty for invalid state", {
  skip_on_cran()
  skip_if_offline()

  cities <- cpcb_get_city_list("InvalidState123")

  expect_type(cities, "character")
  expect_equal(length(cities), 0)
})

test_that("get_station_list returns data frame for valid city", {
  skip_on_cran()
  skip_if_offline()

  stations <- cpcb_get_station_list("Mumbai")

  expect_s3_class(stations, "data.frame")
})

test_that("get_complete_list returns list with expected structure", {
  skip_on_cran()
  skip_if_offline()

  complete_list <- cpcb_get_complete_list()

  expect_type(complete_list, "list")
  expect_true("cities" %in% names(complete_list))
  expect_true("stations" %in% names(complete_list))
})

cpcb_test_that("download functions require valid parameters", {
  # Test city data download with invalid city
  expect_error(
    cpcb_download_city_data("InvalidCity123", "2024", tempfile()),
    "not found"
  )

  # Test station data download with invalid station
  expect_error(
    cpcb_download_station_data("invalid_station", "2024", tempfile()),
    "not found"
  )
})

cpcb_test_that("city data downloads from the CPCB repository", {
  out <- tempfile(fileext = ".csv")
  suppressMessages(cpcb_download_city_data("Mumbai", 2022, out))
  df <- utils::read.csv(out)

  expect_equal(nrow(df), 31)
  expect_true(all(c("Day", "January", "December") %in% names(df)))
  unlink(out)
})

cpcb_test_that("station file paths resolve for a directory station", {
  paths <- cpcb_get_file_path(
    station_id = "site_5392",
    frequency = "daily",
    data_type = "stationLevel"
  )
  expect_gt(length(paths), 0)
  expect_true(all(c("filepath", "year") %in% names(paths[[1]])))
})

cpcb_test_that("live feed returns stations with coordinates and readings", {
  cities <- cpcb_get_all_india()
  df <- stations_to_dataframe(cities)

  expect_gt(nrow(df), 100)
  expect_true(any(!is.na(df$avg_aqi)))

  nearest <- cpcb_get_nearest_station(c(19.076, 72.877))
  expect_lt(nearest$distance_km, 20)

  live <- suppressMessages(cpcb_get_live_aqi_data(station_id = nearest$station_id))
  expect_true(is.data.frame(live$metrics))
})
