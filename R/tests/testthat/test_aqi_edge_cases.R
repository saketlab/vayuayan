# Unit labels, invalid concentrations and boundaries of the NAQI and US AQI.

day_hours <- function(n = 24, tz = "UTC", start = "2024-01-01 00:00:00") {
  seq(as.POSIXct(start, tz = tz), by = "hour", length.out = n)
}

test_that("NAQI converts a mass unit in the label", {
  expect_equal(aqi_sub_index("CO (µg/m³)", 1000), 50)
  expect_equal(aqi_sub_index("CO (ug/m3)", 1000), 50)
  expect_equal(aqi_sub_index("PM2.5 (mg/m3)", 0.030), 50)

  res <- compute_aqi(c("PM2.5 (ug/m3)" = 30, "PM10 (ug/m3)" = 50, "CO (ug/m3)" = 1000))
  expect_equal(res$aqi, 50L)
  expect_equal(res$category, "Good")
  expect_equal(unname(res$sub_indices["CO"]), 50)
})

test_that("daily_aqi takes the unit from the label without a unit column", {
  long <- long_of(day_hours(), c("PM2.5 (ug/m3)" = 30, "PM10 (ug/m3)" = 50, "CO (ug/m3)" = 1000))
  out <- daily_aqi(long)
  expect_equal(out$CO_sub_index, 50)
  expect_equal(out$aqi, 50L)
})

test_that("a NAQI pollutant in ppb or ppm is missing, with one warning", {
  expect_warning(s <- aqi_sub_index("O3 (ppb)", 40), "ppb or ppm")
  expect_true(is.na(s))

  warned <- 0L
  res <- withCallingHandlers(
    compute_aqi(c("PM2.5" = 30, PM10 = 50, "NO2 (ppb)" = 20, "SO2 (ppm)" = 1)),
    warning = function(w) {
      warned <<- warned + 1L
      invokeRestart("muffleWarning")
    }
  )
  expect_equal(warned, 1L)
  expect_true(is.na(res$aqi))
  expect_setequal(names(res$sub_indices), c("PM2.5", "PM10"))
})

test_that("daily_aqi drops ppb gases from the unit column, with one warning", {
  long <- long_of(day_hours(), c("PM2.5" = 30, PM10 = 50, NO2 = 40))
  long$unit <- rep(c("ug/m3", "ug/m3", "ppb"), each = 24)
  expect_warning(out <- daily_aqi(long), "NO2")
  expect_false("NO2_sub_index" %in% names(out))
  expect_true(is.na(out$aqi))
})

test_that("negative concentrations are invalid", {
  expect_true(is.na(aqi_sub_index("PM2.5", -10)))
  expect_true(is.na(aqi_sub_index("CO", -0.5)))
  expect_equal(aqi_pollutant_category("PM2.5", -999), "No Data")

  res <- compute_aqi(c("PM2.5" = -999, NO2 = 20, SO2 = 20))
  expect_true(is.na(res$aqi))
  expect_false("PM2.5" %in% names(res$sub_indices))

  out <- daily_aqi(long_of(day_hours(), c("PM2.5" = -999, NO2 = 40, SO2 = 40)))
  expect_true(nrow(out) == 0 || is.na(out$aqi[1]))
})

test_that("daily_aqi removes negative readings before the hourly mean", {
  hours <- rep(day_hours(), each = 4) + rep(c(0, 900, 1800, 2700), 24)
  value <- rep(c(-999, 30, 30, 30), 24)
  long <- data.frame(
    timestamp = rep(hours, 3),
    pollutant = rep(c("PM2.5", "PM10", "NO2"), each = 96),
    value = c(value, rep(50, 96), rep(40, 96))
  )
  expect_equal(daily_aqi(long)$`PM2.5_sub_index`, 50)
})

test_that("Inf counts as missing in the NAQI and US AQI", {
  res <- compute_aqi(c("PM2.5" = Inf, PM10 = 50, NO2 = 40))
  expect_true(is.na(res$aqi))
  expect_true(is.na(res$dominant_pollutant))
  expect_true(is.na(aqi_sub_index("PM2.5", Inf)))
  expect_true(is.na(us_aqi_sub_index("PM2.5", Inf)))
  expect_true(is.na(compute_us_aqi(c("PM2.5" = Inf))$aqi))

  long <- long_of(day_hours(), c("PM2.5" = Inf, PM10 = 50, NO2 = 40))
  expect_true(is.na(daily_aqi(long)$aqi))
})

test_that("US SO2 from 305 ppb is 200 unless a 24-hour value reaches the upper bands", {
  res <- compute_us_aqi(c(SO2 = -1, SO2_24h = 10))
  expect_true(is.na(res$aqi))
  expect_false("SO2" %in% names(res$sub_indices))

  expect_equal(compute_us_aqi(c(SO2 = 305, SO2_24h = 10))$aqi, 200L)
  # the EPA's AQS code table gives 200 for 1-hour SO2 from 305 ppb without a 24-hour value
  expect_equal(compute_us_aqi(c(SO2 = 305, SO2_24h = -1))$aqi, 200L)
  expect_equal(compute_us_aqi(c(SO2 = 305))$aqi, 200L)
  expect_equal(compute_us_aqi(c(SO2 = 400, SO2_24h = 305))$dominant_pollutant, "SO2_24h")
  # 304.9 truncates to 304, inside the 1-hour table, so its own sub-index applies
  expect_equal(compute_us_aqi(c(SO2 = 304.9, SO2_24h = 10))$sub_indices[["SO2"]], us_aqi_sub_index("SO2", 304))
  expect_lt(compute_us_aqi(c(SO2 = 250, SO2_24h = 10))$aqi, 200L)
})

test_that("US AQI rejects negatives before truncating, and keeps float tolerance", {
  expect_true(is.na(us_aqi_sub_index("PM10", -5e-10)))
  expect_true(is.na(us_aqi_sub_index("PM2.5", -5e-11)))
  # a value this close to a breakpoint is float noise from a conversion
  expect_equal(us_aqi_sub_index("PM10", 55 - 5e-10), 51)
})

test_that("US AQI converts ppb and ppm labels to the unit of the table", {
  expect_equal(us_aqi_sub_index("O3 (ppb)", 54), 50)
  expect_equal(us_aqi_sub_index("SO2 (ppm)", 0.035), 50)
  expect_equal(us_aqi_sub_index("CO (ppb)", 4400), 50)
  expect_equal(us_aqi_sub_index("NO2 (ppm)", 0.053), 50)
  expect_equal(us_aqi_sub_index("O3 (ppm)", 0.054), 50)
})

test_that("daily_aqi with no sufficient day returns NA rows", {
  out <- daily_aqi(long_of(day_hours(10), c("PM2.5" = 45, PM10 = 80, NO2 = 30)))
  expect_equal(nrow(out), 1L)
  expect_true(is.na(out$aqi))
  expect_true(is.na(out$dominant_pollutant))
  expect_true(is.na(out$category))
})

test_that("the 8-hour window minimum follows min_hours below 6", {
  long <- long_of(day_hours(4), c("PM2.5" = 30, PM10 = 50, O3 = 50))
  out <- daily_aqi(long, min_hours = 4)
  expect_equal(out$O3_sub_index, 50)
  expect_equal(out$aqi, 50L)
  # above 6 the window minimum stays 6: 5 hours is too few at the default
  expect_true(is.na(daily_aqi(long_of(day_hours(5), c(O3 = 50)))$O3_sub_index))
  expect_equal(daily_aqi(long_of(day_hours(5), c(O3 = 50)), min_hours = 5)$O3_sub_index, 50)
})

test_that("the unit is the last parenthesised group", {
  expect_equal(.aqi_split_label("CO (8hr) (ug/m3)", part = 2), "ug/m3")
  expect_equal(.aqi_split_label("CO (8hr) (ug/m3)", part = 1), "CO (8hr)")
  expect_equal(aqi_pollutant_name("CO (8hr) (ug/m3)"), "CO")
  expect_equal(aqi_sub_index("CO (8hr) (ug/m3)", 1000), 50)

  raw <- data.frame(
    Timestamp = "2024-01-01 00:00:00", "CO (8hr) (ug/m3)" = 1000, check.names = FALSE
  )
  out <- cpcb_raw_to_long(raw)
  expect_equal(out$pollutant, "CO (8hr)")
  expect_equal(out$unit, "ug/m3")
})

test_that("US AQI ties do not depend on the input order", {
  r1 <- compute_us_aqi(c(O3 = 0.054, "PM2.5" = 9.0))
  r2 <- compute_us_aqi(c("PM2.5" = 9.0, O3 = 0.054))
  expect_equal(r1$dominant_pollutant, "PM2.5")
  expect_equal(r1$dominant_pollutant, r2$dominant_pollutant)
  expect_equal(compute_us_aqi(c(SO2 = 305, SO2_24h = 20, NO2 = 649))$dominant_pollutant, "SO2")
})

test_that("every NAQI breakpoint gives its band", {
  tops <- unname(.aqi_categories)
  for (name in names(.aqi_pollutants)) {
    upper <- .aqi_pollutants[[name]]$tops
    bp <- cbind(c(0, utils::head(upper, -1)), upper)
    for (k in seq_len(nrow(bp))) {
      low <- if (k == 1) 0 else tops[k - 1]
      expect_equal(aqi_sub_index(name, bp[k, 1]), low, tolerance = 1e-6, info = paste(name, k))
      expect_equal(aqi_sub_index(name, bp[k, 2]), tops[k], tolerance = 1e-6, info = paste(name, k))
      expect_equal(
        aqi_sub_index(name, (bp[k, 1] + bp[k, 2]) / 2), (low + tops[k]) / 2,
        tolerance = 1e-5, info = paste(name, "mid", k)
      )
    }
  }
})

test_that("a blank unit cell falls back to the unit in the label", {
  long <- long_of(day_hours(), c("PM2.5" = 30, PM10 = 50, "CO (ug/m3)" = 1000))
  long$unit <- rep(c("ug/m3", NA, " "), each = 24)
  out <- daily_aqi(long)
  expect_equal(out$CO_sub_index, 50)
  expect_equal(out$aqi, 50L)
})

test_that("every US AQI breakpoint gives its band, and truncates", {
  for (name in names(.us_aqi_pollutants)) {
    p <- .us_aqi_pollutants[[name]]
    bands <- matrix(p$bands, ncol = 4, byrow = TRUE)
    step <- 10^(-p$decimals)
    for (k in seq_len(nrow(bands))) {
      expect_equal(us_aqi_sub_index(name, bands[k, 1]), bands[k, 3], tolerance = 1e-6, info = paste(name, k))
      expect_equal(us_aqi_sub_index(name, bands[k, 2]), bands[k, 4], tolerance = 1e-6, info = paste(name, k))
      expect_equal(
        us_aqi_sub_index(name, bands[k, 2] + 0.4 * step), bands[k, 4],
        tolerance = 1e-6, info = paste(name, "trunc", k)
      )
    }
  }
})
