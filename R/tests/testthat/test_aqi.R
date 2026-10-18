# Expected values come from the Python package (vayuayan.aqi) on the same
# inputs; see fixtures/daily_aqi_python.csv.

test_that("sub-indices match the Python package", {
  cases <- data.frame(
    pollutant = c("PM2.5", "PM2.5", "PM2.5", "PM2.5", "PM10", "O3", "CO", "CO", "Pb", "Pb", "Ozone"),
    concentration = c(30, 30.5, 45, 1000, 430, 900, 1.05, 10, 0.5, 0.50001, 120),
    expected = c(50, 50.5, 74.65517, 500, 400, 428.86667, 50.5, 200, 50, 51.00098, 129.07463)
  )
  got <- mapply(aqi_sub_index, cases$pollutant, cases$concentration)
  expect_equal(unname(got), cases$expected, tolerance = 1e-6)
  expect_true(is.na(aqi_sub_index("PM10", NA)))
  expect_error(aqi_sub_index("Benzene", 1), "not a NAQI pollutant")
})

test_that("pollutant labels resolve to NAQI names", {
  expect_equal(
    aqi_pollutant_name(c("PM2.5 (ug/m3)", "pm25", "Ozone", "CO (mg/m3)", "lead", "Benzene")),
    c("PM2.5", "PM2.5", "O3", "CO", "Pb", NA)
  )
})

test_that("compute_aqi follows the CPCB sufficiency rule", {
  r <- compute_aqi(c("PM2.5" = 45, PM10 = 80, NO2 = 30))
  expect_equal(r$aqi, 80L)
  expect_equal(r$category, "Satisfactory")
  expect_equal(r$dominant_pollutant, "PM10")

  expect_true(is.na(compute_aqi(c("PM2.5" = 45, NO2 = 30))$aqi))
  expect_true(is.na(compute_aqi(c(NO2 = 30, SO2 = 10, CO = 2))$aqi))

  r <- compute_aqi(list("PM10 (ug/m3)" = 300, Ozone = 250, "CO (mg/m3)" = 12, Benzene = 5))
  expect_equal(r$aqi, 309L)
  expect_equal(r$dominant_pollutant, "O3")
})

test_that("daily_aqi matches the Python package", {
  long <- utils::read.csv(test_path("fixtures", "daily_aqi_input.csv"), fileEncoding = "UTF-8")
  expected <- utils::read.csv(
    test_path("fixtures", "daily_aqi_python.csv"),
    na.strings = c("", "NA", "<NA>"), check.names = FALSE
  )
  for (end in c(24, 16)) {
    want <- expected[expected$day_ends_at == end, -1]
    got <- daily_aqi(long, day_ends_at = end)

    expect_equal(nrow(got), nrow(want))
    expect_equal(as.character(got$date), want$date)
    expect_equal(got$aqi, want$aqi)
    expect_equal(got$category, want$category)
    expect_equal(got$dominant_pollutant, want$dominant_pollutant)
    expect_equal(got$n_pollutants, want$n_pollutants)
    sub_cols <- grep("_sub_index$", names(want), value = TRUE)
    expect_equal(sort(names(got)[grepl("_sub_index$", names(got))]), sort(sub_cols))
    for (col in sub_cols) {
      expect_equal(got[[col]], want[[col]], tolerance = 1e-6, info = paste(end, col))
    }
  }
})

test_that("cpcb_raw_to_long splits labels into pollutant and unit", {
  raw <- data.frame(
    Timestamp = c("2024-01-01 00:00:00", "2024-01-01 00:15:00", "bad"),
    "PM2.5 (ug/m3)" = c(158, 160, 1),
    "CO (mg/m3)" = c(1.6, NA, 1),
    check.names = FALSE
  )
  long <- cpcb_raw_to_long(raw, station = list(station_id = "site_301", city = "Delhi"))

  expect_named(long, c(
    "station_id", "station_name", "city", "state",
    "timestamp", "pollutant", "unit", "value"
  ))
  expect_equal(nrow(long), 3)
  expect_equal(long$pollutant, c("CO", "PM2.5", "PM2.5"))
  expect_equal(long$unit, c("mg/m3", "ug/m3", "ug/m3"))
  expect_equal(unique(long$station_id), "site_301")
  expect_equal(nrow(cpcb_raw_to_long(raw, end_date = "2023-12-31")), 0)
})

test_that("cpcb_tidy_daily adds dates and drops impossible days", {
  sheet <- data.frame(Day = c(28, 30), January = c(1, 2), February = c(3, 4))
  out <- cpcb_tidy_daily(sheet, year = 2024)
  expect_equal(as.character(out$date), c("2024-01-28", "2024-01-30", "2024-02-28"))
})
