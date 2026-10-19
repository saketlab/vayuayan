# hand-computed EPA-454/B-24-002 values; test_parity.R only compares R with Python

test_that("US AQI sub-indices match the EPA tables", {
  expect_equal(us_aqi_sub_index("PM2.5", c(9.0, 9.05, 9.1, 35.4)), c(50, 50, 51, 100))
  expect_equal(us_aqi_sub_index("PM2.5", 12.0), 49 / 26.3 * 2.9 + 51)
  expect_equal(us_aqi_sub_index("PM10", 155), 101)
  expect_equal(us_aqi_sub_index("O3", 0.078), 125.5)
  expect_equal(us_aqi_sub_index("O3_1h", 0.21), 99 / 0.199 * 0.005 + 201)
  expect_equal(us_aqi_sub_index("SO2_24h", 400), 99 / 299 * 95 + 201)
  expect_equal(us_aqi_sub_index("O3 (ug/m3)", 100), 50 / 0.054 * 0.050)
  expect_equal(us_aqi_sub_index("CO (mg/m3)", 5), 50 / 4.4 * 4.3)
})

test_that("above the highest breakpoint the 301-500 slope continues", {
  expect_equal(us_aqi_sub_index("PM2.5", 400), 199 / 99.9 * 174.5 + 301)
  expect_equal(us_aqi_sub_index("CO", 600), 199 / 19.9 * 569.5 + 301)
  expect_equal(us_aqi_sub_index("NO2", 3000), 199 / 799 * 1750 + 301)
  expect_equal(compute_us_aqi(c("PM2.5" = 400))$aqi, 649L)
  expect_equal(us_aqi_category(c(300, 301, 650)), c("Very Unhealthy", "Hazardous", "Hazardous"))
})

test_that("values outside a partial table have no sub-index", {
  expect_true(all(is.na(us_aqi_sub_index("O3", 0.21))))
  expect_true(is.na(us_aqi_sub_index("O3_1h", 0.1)))
  expect_true(is.na(us_aqi_sub_index("SO2", 400)))
  expect_true(is.na(us_aqi_sub_index("SO2_24h", 300)))
})

test_that("compute_us_aqi follows the EPA rules", {
  r <- compute_us_aqi(list("PM2.5" = 35.4, O3 = 0.060, Benzene = 3, NO2 = NA))
  expect_equal(r[c("aqi", "category", "dominant_pollutant")], list(aqi = 100L, category = "Moderate", dominant_pollutant = "PM2.5"))
  expect_equal(compute_us_aqi(c(O3 = 0.078))$aqi, 126L) # half up
  expect_equal(compute_us_aqi(c(O3 = 0.21, O3_1h = 0.21))$dominant_pollutant, "O3_1h")
  so2 <- compute_us_aqi(c(SO2 = 305, SO2_24h = 304))
  expect_equal(c(so2$aqi, so2$sub_indices[["SO2"]]), c(200, 200))
  expect_true(is.na(compute_us_aqi(c(Benzene = 3))$aqi))
  expect_error(us_aqi_sub_index("NH3", 10), "not a US AQI pollutant")
})

test_that("US AQI colors match EPA Tables 2 and 3", {
  expect_equal(us_aqi_color(c(120, 650, NA)), c("#FF7E00", "#7E0023", NA))
  expect_equal(us_aqi_color(120, color_vision_assist = TRUE), "#FF8205")
})
