test_that("clean_station_name removes special characters", {
  expect_equal(
    clean_station_name("Dr. Karni Singh Shooting Range, Delhi - DPCC"),
    "Dr_Karni_Singh_Shooting_Range_Delhi_DPCC"
  )
  
  expect_equal(
    clean_station_name("ITO, Delhi - DPCC"),
    "ITO_Delhi_DPCC"
  )
  
  expect_equal(
    clean_station_name("Station  with    spaces"),
    "Station_with_spaces"
  )
})

test_that("clean_station_name handles edge cases", {
  expect_equal(clean_station_name(""), "")
  expect_equal(clean_station_name(NULL), "")
  expect_equal(clean_station_name("   "), "")
  expect_equal(clean_station_name("___test___"), "test")
})

test_that("get_aqi_category returns correct categories", {
  expect_equal(get_aqi_category(25), "Good")
  expect_equal(get_aqi_category(50), "Good")
  expect_equal(get_aqi_category(75), "Satisfactory")
  expect_equal(get_aqi_category(100), "Satisfactory")
  expect_equal(get_aqi_category(150), "Moderate")
  expect_equal(get_aqi_category(200), "Moderate")
  expect_equal(get_aqi_category(250), "Poor")
  expect_equal(get_aqi_category(300), "Poor")
  expect_equal(get_aqi_category(350), "Very Poor")
  expect_equal(get_aqi_category(400), "Very Poor")
  expect_equal(get_aqi_category(450), "Severe")
  expect_equal(get_aqi_category(500), "Severe")
  expect_equal(get_aqi_category(NA), "No Data")
})

test_that("get_aqi_categories works with vectors", {
  aqi_values <- c(25, 75, 150, 250, 350, 450, NA)
  categories <- get_aqi_categories(aqi_values)
  
  expect_equal(length(categories), length(aqi_values))
  expect_equal(categories[1], "Good")
  expect_equal(categories[2], "Satisfactory")
  expect_equal(categories[3], "Moderate")
  expect_equal(categories[4], "Poor")
  expect_equal(categories[5], "Very Poor")
  expect_equal(categories[6], "Severe")
  expect_equal(categories[7], "No Data")
})

test_that("haversine_distance calculates correctly", {
  # Mumbai to Delhi (approximately 1150 km)
  mumbai <- c(19.0760, 72.8777)
  delhi <- c(28.7041, 77.1025)
  
  distance <- haversine_distance(
    mumbai[1], mumbai[2],
    delhi[1], delhi[2]
  )
  
  expect_type(distance, "double")
  expect_gt(distance, 1100)
  expect_lt(distance, 1200)
})

test_that("haversine_distance handles same point", {
  distance <- haversine_distance(19.0760, 72.8777, 19.0760, 72.8777)
  expect_equal(distance, 0)
})

test_that("haversine_distance is symmetric", {
  dist1 <- haversine_distance(19.0760, 72.8777, 28.7041, 77.1025)
  dist2 <- haversine_distance(28.7041, 77.1025, 19.0760, 72.8777)
  
  expect_equal(dist1, dist2)
})

test_that("null default operator works", {
  expect_equal(NULL %||% "default", "default")
  expect_equal("value" %||% "default", "value")
  expect_equal(0 %||% "default", 0)
  expect_equal(FALSE %||% "default", FALSE)
})

test_that("stations_to_dataframe converts correctly", {
  mock_data <- list(
    list(
      cityName = "Mumbai",
      cityID = "MUM01",
      stateID = "MH",
      stationsInCity = list(
        list(
          id = "station1",
          name = "Station 1",
          latitude = "19.0760",
          longitude = "72.8777",
          live = TRUE,
          avg = "50"
        ),
        list(
          id = "station2",
          name = "Station 2",
          latitude = "19.1",
          longitude = "72.9",
          live = FALSE,
          avg = NULL
        )
      )
    )
  )
  
  df <- stations_to_dataframe(mock_data)
  
  expect_s3_class(df, "data.frame")
  expect_equal(nrow(df), 2)
  expect_true("city_name" %in% names(df))
  expect_true("station_id" %in% names(df))
  expect_true("latitude" %in% names(df))
  expect_true("longitude" %in% names(df))
  expect_equal(df$city_name[1], "Mumbai")
  expect_equal(df$live[1], TRUE)
  expect_equal(df$live[2], FALSE)
})

test_that("analyze_station_data computes statistics", {
  mock_data <- list(
    list(
      cityName = "City1",
      cityID = "C1",
      stateID = "S1",
      stationsInCity = list(
        list(id = "s1", name = "Station 1", latitude = "19", longitude = "72", 
             live = TRUE, avg = "50"),
        list(id = "s2", name = "Station 2", latitude = "19.1", longitude = "72.1", 
             live = FALSE, avg = "100")
      )
    )
  )
  
  analysis <- analyze_station_data(mock_data)
  
  expect_type(analysis, "list")
  expect_equal(analysis$total_cities, 1)
  expect_equal(analysis$total_stations, 2)
  expect_equal(analysis$live_stations, 1)
  expect_equal(analysis$offline_stations, 1)
  expect_equal(analysis$stations_with_aqi_data, 2)
  expect_equal(analysis$avg_aqi_overall, 75)
})
