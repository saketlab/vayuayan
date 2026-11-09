# Daily US AQI from raw readings, and the standard option of the station helper.

eq <- function(c, c_lo, c_hi, i_lo, i_hi) (i_hi - i_lo) / (c_hi - c_lo) * (c - c_lo) + i_lo

# named list of hourly value vectors, NA leaves the hour out
long_us <- function(values, start = "2024-01-01 00:00:00", station = "s1", unit = NULL) {
  hours <- as.POSIXct(start, tz = "UTC") + 3600 * (seq_along(values[[1]]) - 1)
  frames <- lapply(names(values), function(label) {
    keep <- !is.na(values[[label]])
    data.frame(
      station_id = station, timestamp = hours[keep], pollutant = label,
      value = values[[label]][keep], stringsAsFactors = FALSE
    )
  })
  out <- do.call(rbind, frames)
  if (!is.null(unit)) out$unit <- unit
  out
}

test_that("PM uses the 24-hour mean and needs 18 hours", {
  out <- daily_us_aqi(long_us(list("PM2.5" = rep(20, 18))))
  expect_equal(out$`PM2.5_sub_index`, eq(20, 9.1, 35.4, 51, 100))
  expect_equal(out$aqi, 71L)
  expect_equal(out$category, "Moderate")
  expect_equal(out$dominant_pollutant, "PM2.5")
  expect_equal(out$n_pollutants, 1)

  short <- daily_us_aqi(long_us(list("PM2.5" = rep(20, 17))))
  expect_true(is.na(short$aqi))
  expect_true(is.na(short$category))
  expect_true(is.na(short$dominant_pollutant))
  expect_equal(short$n_pollutants, 0)
})

test_that("min_hours adjusts the 18", {
  long <- long_us(list("PM2.5" = rep(20, 10)))
  expect_equal(daily_us_aqi(long, min_hours = 10)$aqi, 71L)
  expect_true(is.na(daily_us_aqi(long, min_hours = 11)$aqi))
})

test_that("15-minute readings become hourly means first", {
  stamps <- as.POSIXct("2024-01-01 00:00:00", tz = "UTC") + 900 * (0:95)
  long <- data.frame(
    station_id = "s1", timestamp = stamps, pollutant = "PM2.5 (µg/m³)",
    # negatives are left out before the hourly mean, as in daily_aqi
    value = ifelse(seq_along(stamps) %% 4 == 1, -999, 20)
  )
  expect_equal(daily_us_aqi(long)$`PM2.5_sub_index`, eq(20, 9.1, 35.4, 51, 100))
})

test_that("8-hour O3 converts units and uses the highest window", {
  # 100 ug/m3 = 100 * 24.45 / 48 / 1000 = 0.0509 ppm, truncated to 0.050
  series <- c(rep(20, 8), rep(100, 8), rep(20, 8))
  out <- daily_us_aqi(long_us(list(O3 = series), unit = "µg/m³"))
  expect_equal(out$O3_sub_index, eq(0.050, 0.0, 0.054, 0, 50))
})

test_that("an 8-hour day needs 18 of its 24 windows", {
  # the 18th window from the end needs hours 1-6; from hour 2 there are only 17
  ok <- daily_us_aqi(long_us(list(CO = c(NA, rep(1, 23)))))
  expect_false(is.na(ok$CO_sub_index))
  short <- daily_us_aqi(long_us(list(CO = c(NA, NA, rep(1, 22)))))
  expect_true(is.na(short$CO_sub_index))
})

test_that("an 8-hour window needs six hours", {
  # hours 0-4 and 8-23: only the windows ending at hours 13-23 hold 6 hours
  long <- long_us(list(CO = c(rep(1, 5), rep(NA, 3), rep(1, 16))))
  expect_true(is.na(daily_us_aqi(long)$CO_sub_index))
  expect_false(is.na(daily_us_aqi(long, min_hours = 11)$CO_sub_index))
  expect_true(is.na(daily_us_aqi(long, min_hours = 12)$CO_sub_index))
})

test_that("a missing hour still ends a window", {
  # hours 5-11 are high, 12 is missing: only the window ending at 12 is all high
  out <- daily_us_aqi(long_us(list(CO = c(rep(0.1, 5), rep(8, 7), NA, rep(0.1, 11)))))
  expect_equal(out$CO_sub_index, eq(8, 4.5, 9.4, 51, 100))
})

test_that("NO2 uses the highest hour and needs 18 hours", {
  out <- daily_us_aqi(long_us(list(NO2 = c(rep(40, 20), 120, rep(40, 3))), unit = "ppb"))
  expect_equal(out$NO2_sub_index, eq(120, 101, 360, 101, 150))
  expect_true(is.na(daily_us_aqi(long_us(list(NO2 = rep(120, 17))))$aqi))
})

test_that("SO2 uses the 1-hour table below 305 ppb and the 24-hour mean above", {
  low <- daily_us_aqi(long_us(list(SO2 = c(rep(50, 23), 100)), unit = "ppb"))
  expect_equal(low$SO2_sub_index, eq(100, 76, 185, 101, 150))

  spike <- daily_us_aqi(long_us(list(SO2 = c(rep(10, 23), 400)), unit = "ppb"))
  expect_equal(spike$SO2_sub_index, 200)
  expect_equal(spike$dominant_pollutant, "SO2")

  high <- daily_us_aqi(long_us(list(SO2 = rep(400, 24)), unit = "ppb"))
  expect_equal(high$SO2_sub_index, eq(400, 305, 604, 201, 300))
  expect_equal(high$dominant_pollutant, "SO2")
})

test_that("the AQI needs no minimum number of pollutants", {
  out <- daily_us_aqi(long_us(list(PM10 = rep(100, 24))))
  # 49 / 99 * 45 + 51 = 73.27
  expect_equal(out$aqi, 73L)
  expect_equal(names(out)[ncol(out)], "PM10_sub_index")
})

test_that("pollutants convert and come in table order; others are left out", {
  long <- rbind(
    long_us(list(NO2 = rep(100, 24)), unit = "ppb"),
    long_us(list("PM2.5" = rep(12, 24)), unit = "µg/m³"),
    long_us(list(CO = rep(1000, 24)), unit = "µg/m³"),
    long_us(list(NH3 = rep(50, 24)), unit = "µg/m³")
  )
  out <- daily_us_aqi(long)
  expect_equal(
    names(out)[grepl("_sub_index$", names(out))],
    c("PM2.5_sub_index", "CO_sub_index", "NO2_sub_index")
  )
  # 1 mg/m3 CO = 1 * 24.45 / 28.01 = 0.873 ppm, truncated to 0.8
  expect_equal(out$CO_sub_index, eq(0.8, 0.0, 4.4, 0, 50))
})

test_that("a blank unit means the unit of the US table", {
  out <- daily_us_aqi(long_us(list(O3 = rep(0.060, 24)), unit = ""))
  expect_equal(out$O3_sub_index, eq(0.060, 0.055, 0.070, 51, 100))
})

test_that("day_ends_at moves the window and must be an hour", {
  long <- long_us(list("PM2.5" = rep(20, 24)), start = "2024-01-01 16:00:00")
  # calendar days hold 8 and 16 hours, both below 18
  expect_true(all(is.na(daily_us_aqi(long)$aqi)))
  bulletin <- daily_us_aqi(long, day_ends_at = 16)
  expect_equal(as.character(bulletin$date), "2024-01-02")
  expect_equal(bulletin$aqi, 71L)
  expect_error(daily_us_aqi(long, day_ends_at = 25), "day_ends_at")
})

test_that("a gap of whole days makes no rows", {
  long <- rbind(
    long_us(list(CO = rep(1, 24))),
    long_us(list(CO = rep(1, 24)), start = "2024-01-05 00:00:00")
  )
  expect_equal(as.character(daily_us_aqi(long)$date), c("2024-01-01", "2024-01-05"))
})

test_that("several stations are kept apart", {
  long <- rbind(
    long_us(list("PM2.5" = rep(20, 24)), station = "b"),
    long_us(list("PM2.5" = rep(100, 24)), station = "a")
  )
  out <- daily_us_aqi(long)
  expect_equal(out$station_id, c("a", "b"))
  expect_equal(out$aqi, c(compute_us_aqi(c("PM2.5" = 100))$aqi, 71L))
})

test_that("without US pollutants the result is empty", {
  out <- daily_us_aqi(long_us(list(NH3 = rep(50, 24))))
  expect_equal(nrow(out), 0L)
  expect_named(out, c("station_id", "date", "aqi", "category", "dominant_pollutant", "n_pollutants", "aqi_status"))
})

test_that("8-hour O3 above the table gives no AQI, with one warning", {
  long <- rbind(
    long_us(list(O3 = rep(0.25, 48)), unit = "ppm"),
    long_us(list("PM2.5" = rep(20, 48)), unit = "µg/m³")
  )
  expect_warning(out <- daily_us_aqi(long), "2 day")
  expect_true(all(is.na(out$aqi)))
  expect_true(all(is.na(out$category)))
  expect_equal(out$`PM2.5_sub_index`[1], eq(20, 9.1, 35.4, 51, 100))
  expect_true(is.na(out$O3_sub_index[1]))
})

test_that("the station helper accepts standard, and rejects others", {
  long <- rbind(
    long_us(list("PM2.5" = rep(45, 24)), unit = "µg/m³"),
    long_us(list(PM10 = rep(80, 24)), unit = "µg/m³"),
    long_us(list(NO2 = rep(30, 24)), unit = "µg/m³")
  )
  local_mocked_bindings(cpcb_download_raw_station_data = function(...) long)

  india <- cpcb_station_daily_aqi("s1", 2024)
  us <- cpcb_station_daily_aqi("s1", 2024, standard = "us")
  expect_equal(india$category, "Satisfactory")
  expect_equal(india$aqi, 80L)
  expect_equal(us$aqi, 124L)
  expect_equal(us$category, "Unhealthy for Sensitive Groups")
  expect_error(cpcb_station_daily_aqi("s1", 2024, standard = "uk"), "india")
})
