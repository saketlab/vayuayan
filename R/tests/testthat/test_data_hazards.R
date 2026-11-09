# Time zones, duplicates, odd sheets, sensor edge cases and failed downloads.

ist_hours <- function(n) {
  seq(as.POSIXct("2024-01-01 00:00:00", tz = "Asia/Kolkata"), by = "hour", length.out = n)
}

ist_readings <- function() {
  ts <- seq(as.POSIXct("2026-01-01 00:00:00", tz = "Asia/Kolkata"), by = "15 mins", length.out = 80)
  data.frame(sensor_id = "s1", timestamp = ts, pm25 = 25)
}

test_that("24:00 is the next day's midnight", {
  expect_equal(
    .parse_timestamp(c("2024-01-01 24:00:00", "2024-01-01 24:00")),
    rep(as.POSIXct("2024-01-02 00:00:00", tz = "UTC"), 2)
  )
})

test_that("calendar days use the timestamps' own time zone", {
  hours <- ist_hours(20)
  long <- data.frame(
    timestamp = rep(hours, 3),
    pollutant = rep(c("PM2.5", "PM10", "NO2"), each = 20),
    value = rep(c(30, 50, 40), each = 20)
  )
  out <- daily_aqi(long)
  expect_equal(out$date, as.Date("2024-01-01"))
  expect_equal(out$aqi, 50L)

  readings <- ist_readings()
  expect_equal(nrow(readings_mean(readings, by = "day")), 1L)
  expect_equal(sensor_completeness(readings, "2026-01-01", "2026-01-01")$valid_days, 1L)

  hourly <- readings_mean(readings, by = "hour")
  expect_equal(format(hourly$hour[1], "%H:%M"), "00:00")
  expect_equal(attr(hourly$hour, "tzone"), "Asia/Kolkata")
})

test_that("compare_daily_records and cpcb_raw_to_long use the local day", {
  readings <- ist_readings()
  records <- data.frame(sensor_id = "s1", date = as.Date("2026-01-01"), pm25 = 25)
  out <- compare_daily_records(readings, records)
  expect_equal(nrow(out), 1L)
  expect_equal(out$n, 80L)

  raw <- data.frame(Timestamp = ist_hours(4), "PM2.5 (ug/m3)" = 1:4, check.names = FALSE)
  long <- cpcb_raw_to_long(raw, start_date = "2024-01-01", end_date = "2024-01-01")
  expect_equal(nrow(long), 4L)
})

test_that("duplicate timestamps are averaged before anything counts them", {
  ts <- seq(as.POSIXct("2026-01-01 00:00:00", tz = "UTC"), by = "15 mins", length.out = 96)
  twice <- data.frame(sensor_id = "s1", timestamp = rep(ts, 2), pm25 = 25)
  expect_lte(sensor_completeness(twice, "2026-01-01", "2026-01-01")$readings_pct, 100)

  instant <- data.frame(
    sensor_id = "s1", timestamp = rep(as.POSIXct("2026-01-01", tz = "UTC"), 72), pm25 = 25
  )
  expect_equal(nrow(readings_mean(instant, by = "day")), 0L)
  expect_equal(sensor_completeness(instant, "2026-01-01", "2026-01-01")$valid_days, 0L)

  rep_means <- data.frame(
    sensor_id = "s1", timestamp = ts[c(1, 1, 1, 2, 3)], pm25 = c(100, 100, 100, 20, 60)
  )
  expect_equal(readings_mean(rep_means, by = "hour", min_readings = 3)$pm25, 60)
  # a stuck run is counted over distinct times
  stuck <- data.frame(sensor_id = "s1", timestamp = rep(ts[1], 8), pm25 = 7)
  expect_equal(sensor_plausibility(stuck)$readings, 1L)
  expect_equal(sensor_plausibility(stuck)$stuck_pct, 0)
})

test_that("daily_aqi averages a duplicated timestamp once", {
  hours <- seq(as.POSIXct("2024-01-01 00:00:00", tz = "UTC"), by = "hour", length.out = 24)
  long <- long_hours(hours, c("PM2.5" = 30, PM10 = 50, NO2 = 40))
  extra <- long[long$pollutant == "PM2.5" & long$timestamp == hours[1], ]
  extra$value <- 30
  half <- extra
  half$value <- 60
  half$timestamp <- hours[1] + 900
  # hour 1 averages 30 (duplicated) and 60 to 45, not 30, 30, 60 to 40
  out <- daily_aqi(rbind(long, extra, extra, half), min_hours = 16)
  expect_equal(out$`PM2.5_sub_index`, aqi_sub_index("PM2.5", (45 + 30 * 23) / 24))
})

test_that("compare_daily_records counts distinct times", {
  ts <- as.POSIXct("2026-03-10", tz = "UTC") + c(0, 0, 900)
  readings <- data.frame(sensor_id = "s1", timestamp = ts, pm25 = c(10, 30, 40))
  records <- data.frame(sensor_id = "s1", date = as.Date("2026-03-10"), pm25 = 30)
  out <- compare_daily_records(readings, records)
  expect_equal(out$n, 2L)
  expect_equal(out$mean, 30)
})

test_that("Inf in raw data and sensor data counts as missing", {
  raw <- data.frame(
    Timestamp = "2024-01-01 00:00:00",
    "PM2.5 (ug/m3)" = "Inf", "PM10 (ug/m3)" = "-Inf", check.names = FALSE
  )
  expect_equal(nrow(cpcb_raw_to_long(raw)), 0L)

  sheet <- data.frame(Day = 1:2, January = c("Inf", "10"))
  expect_equal(cpcb_tidy_daily(sheet)$value, 10)

  readings <- data.frame(
    sensor_id = "s1",
    timestamp = as.POSIXct("2026-01-01", tz = "UTC") + 900 * 0:3,
    pm25 = c(1, Inf, -Inf, 3)
  )
  out <- readings_mean(readings, by = "hour", min_readings = 2)
  expect_equal(out$pm25, 2)
  expect_equal(out$n, 2L)
  expect_equal(sensor_plausibility(readings)$readings, 2L)

  expect_equal(
    cpcb_live_to_long(list(last_hours = list(list(
      name = "PM2.5", data = list(
        list(date = "2024-01-01 10:00:00", val = "Inf"),
        list(date = "2024-01-01 11:00:00", val = 5)
      )
    ))))$value,
    5
  )
  metrics <- list(metrics = data.frame(name = "PM2.5", avg = "Inf", min = 1, max = "2", avgDesc = "x"))
  expect_true(is.na(cpcb_live_metrics(metrics)$avg))
})

test_that("Inf in sensor comparisons is dropped", {
  paired <- data.frame(sensor_id = "s1", reference = c(1:40, Inf), pm25 = c(2 + 1.1 * (1:40), 3))
  expect_equal(sensor_accuracy(paired)$days, 40L)

  hourly <- data.frame(sensor = c(10, Inf), reference = c(10, 10), rh = c(30, 35))
  expect_equal(ratio_by_humidity(hourly)$hours, 1L)

  daily <- data.frame(
    sensor_id = c("a", "b", "c"), date = as.Date("2026-01-01"), pm25 = c(Inf, 20, 30)
  )
  expect_equal(nrow(collocated_precision(daily)), 0L)
  expect_equal(nrow(peer_ratio(daily)[peer_ratio(daily)$days > 0, ]), 0L)
})

test_that("an empty sheet and footer rows do not break the daily parser", {
  out <- cpcb_tidy_daily(data.frame())
  expect_equal(nrow(out), 0L)
  expect_true(all(c("day", "month", "value") %in% names(out)))
  expect_equal(nrow(cpcb_tidy_daily(data.frame(), year = 2024)), 0L)

  sheet <- data.frame(
    Day = c("1", "2", "Min", "Max", "Average", NA),
    January = c(150, 160, 150, 160, 155, 158)
  )
  expect_equal(cpcb_tidy_daily(sheet)$day, 1:2)
  expect_equal(cpcb_tidy_daily(sheet, year = 2024)$date, as.Date(c("2024-01-01", "2024-01-02")))
})

test_that("February 29 is kept only in a leap year", {
  sheet <- data.frame(Day = c(28, 29, 30, 31), February = c(100, 120, 140, 160))
  expect_equal(cpcb_tidy_daily(sheet, year = 2024)$date, as.Date(c("2024-02-28", "2024-02-29")))
  expect_equal(cpcb_tidy_daily(sheet, year = 2023)$date, as.Date("2023-02-28"))
})

test_that("sensor accuracy flags are never NA", {
  stuck <- data.frame(sensor_id = "s1", reference = as.numeric(1:30), pm25 = 25)
  acc <- suppressWarnings(sensor_accuracy(stuck))
  expect_false(is.na(acc$r2_ok))
  expect_identical(acc$targets_met, 0L)

  # constant reference: the slope is undefined and every flag must still be logical
  flat <- data.frame(sensor_id = "s1", reference = rep(25, 30), pm25 = 25)
  acc <- suppressWarnings(sensor_accuracy(flat))
  expect_false(anyNA(acc[c("slope_ok", "intercept_ok", "r2_ok", "error_ok", "targets_met")]))
  expect_true(acc$targets_met %in% 0:4)
})

test_that("peer_ratio drops non-finite ratios and averages duplicates", {
  daily <- data.frame(sensor_id = c("a", "b", "c"), date = as.Date("2026-01-01"), pm25 = c(10, 0, 0))
  pr <- peer_ratio(daily)
  expect_false(is.infinite(pr$median_ratio[pr$sensor_id == "a"]))
  expect_equal(pr$days[pr$sensor_id == "a"], 0L)

  dup <- data.frame(
    sensor_id = c("a", "a", "a", "b", "c"), date = as.Date("2026-01-01"),
    pm25 = c(10, 20, 60, 30, 30)
  )
  expect_equal(peer_ratio(dup)$median_ratio[peer_ratio(dup)$sensor_id == "a"], 1)
  expect_equal(nrow(peer_ratio(dup[0, ])), 0L)
})

test_that("ratio_by_humidity keeps RH 0 in the first band", {
  out <- ratio_by_humidity(data.frame(sensor = c(15, 20), reference = c(10, 10), rh = c(0, 30)))
  expect_equal(out$hours[out$band == "0-40"], 2L)
})

test_that("clean_station_name keeps non-ASCII letters, like Python", {
  expect_equal(
    clean_station_name("Sector µ-2, Café - CPCB"),
    "Sector_µ_2_Café_CPCB"
  )
})

test_that("daily_record_summary is empty for an empty audit", {
  out <- daily_record_summary(.empty_records())
  expect_equal(nrow(out), 0L)
  expect_true(all(c("sensor_id", "year", "days", "clear_days") %in% names(out)))
})

test_that("stations without coordinates are kept, with NA", {
  cities <- list(list(
    cityName = "Delhi", cityID = "Delhi", stateID = "Delhi",
    stationsInCity = data.frame(
      id = c("site_1", "site_2"), name = c("Station 1", "Station 2"),
      latitude = c(28.6, NA), longitude = c(77.2, NA), live = TRUE, avg = c(100, 200),
      stringsAsFactors = FALSE
    )
  ))
  df <- stations_to_dataframe(cities)
  expect_equal(nrow(df), 2L)
  expect_true(is.na(df$latitude[2]))

  analysis <- analyze_station_data(cities)
  expect_equal(analysis$total_stations, 2L)
  expect_equal(analysis$live_stations, 2L)
  expect_equal(analysis$avg_aqi_overall, 150)
  expect_equal(analysis$max_aqi, 200)
})

test_that("analyze_station_data never returns Inf on empty input", {
  empty <- analyze_station_data(list())
  expect_true(is.na(empty$min_aqi))
  expect_true(is.na(empty$max_aqi))
  expect_true(is.na(empty$avg_aqi_overall))

  no_aqi <- list(list(
    cityName = "X", cityID = "X", stateID = "X",
    stationsInCity = data.frame(id = "s", name = "n", latitude = 1, longitude = 2, live = FALSE, avg = NA)
  ))
  expect_true(is.na(analyze_station_data(no_aqi)$min_aqi))
})

test_that("cached years ignore station IDs that look like a year", {
  expect_false(is.null(.cpcb_cache_name("raw/2022/site_2099_raw.csv")))
  expect_null(.cpcb_cache_name("live/site_2020_latest.csv"))
  expect_false(is.null(.cpcb_cache_name("data/delhi_2021.csv")))
  expect_null(.cpcb_cache_name("live/site_2021.csv"))
  # a range of years counts its later year
  expect_equal(.cpcb_cache_name("AQI_Bulletin/2020-2021/city.xlsx"), file.path("cpcb", "AQI_Bulletin", "2020-2021", "city.xlsx"))
  future <- as.integer(format(Sys.Date(), "%Y")) + 1L
  expect_null(.cpcb_cache_name(sprintf("AQI_Bulletin/2020-%d/city.xlsx", future)))
})

test_that("another year's files are never returned", {
  entries <- list(list(year = "2023", month = "January", filepath = "2023_jan.xlsx"))
  expect_error(.cpcb_combine_months(entries, year = 2025, month = NULL), "Data not found for year 2025")
  expect_error(.cpcb_combine_months(entries, year = 2025, month = "January"), "Data not found for year 2025")

  local_mocked_bindings(
    .cpcb_require_station = function(station_id, ...) {
      list(station_id = "site_1", station_name = "A", state = "S", city = "C")
    },
    cpcb_get_file_path = function(...) {
      list(list(filepath = "/x_2023.csv", year = "2023"))
    }
  )
  expect_error(cpcb_download_raw_station_data("site_1", 2024), "Raw data not found")
})

test_that("the daily AQI of 1 January uses 31 December of the previous year", {
  asked <- character(0)
  local_mocked_bindings(
    cpcb_download_raw_station_data = function(station_id, year, save_location = "",
                                              frequency = "15_minute", tidy = FALSE) {
      asked <<- c(asked, as.character(year))
      if (as.character(year) == "2023") {
        hours <- seq(as.POSIXct("2023-12-31 16:00:00", tz = "UTC"), by = "hour", length.out = 8)
      } else {
        hours <- seq(as.POSIXct("2024-01-01 00:00:00", tz = "UTC"), by = "hour", length.out = 10)
      }
      long_hours(hours, c("PM2.5" = 30, PM10 = 50, NO2 = 40))
    }
  )
  out <- cpcb_station_daily_aqi("site_1", 2024, day_ends_at = 16)
  expect_equal(out$aqi[out$date == as.Date("2024-01-01")], 50L)
  expect_setequal(asked, c("2023", "2024"))

  asked <- character(0)
  cpcb_station_daily_aqi("site_1", 2024)
  expect_equal(asked, "2024")
})

test_that("a missing previous year does not stop the daily AQI", {
  local_mocked_bindings(
    cpcb_download_raw_station_data = function(station_id, year, save_location = "",
                                              frequency = "15_minute", tidy = FALSE) {
      if (as.character(year) == "2023") stop("Raw data not found")
      hours <- seq(as.POSIXct("2024-01-01 00:00:00", tz = "UTC"), by = "hour", length.out = 24)
      long_hours(hours, c("PM2.5" = 30, PM10 = 50, NO2 = 40))
    }
  )
  out <- cpcb_station_daily_aqi("site_1", 2024, day_ends_at = 16)
  expect_true("2024-01-01" %in% format(out$date))
})

test_that("OAQ failures warn and name what failed, and keep partial results", {
  table <- data.frame(id = "1", name = "A", lat = 1, lon = 2, city = "X")
  local_mocked_bindings(
    oaq_stations_table = function(session, provider) table,
    oaq_get_monthly = function(...) stop("OAQ request failed: timeout"),
    oaq_get_annual = function(...) stop("Failed to parse OAQ response: corrupt"),
    oaq_get_daily = function(session, provider, sensor_id, year, month, day_of) {
      if (day_of == "02") stop("Failed to parse OAQ response: corrupt")
      list(data = data.frame(date = "2026-01-01T00:15:00+05:30", pm25 = 12))
    }
  )

  expect_warning(
    oaq_fetch_monthly_stations(list(), "cpcb", 2026, months = "01"), "1.*01.*timeout"
  )
  expect_warning(oaq_daily_records(list(), "x", "s9", 2026), "s9.*2026")

  expect_warning(
    out <- oaq_readings(list(), "x", "s9", c("2026-01-01", "2026-01-02")),
    "s9.*2026-01-02"
  )
  expect_equal(nrow(out), 1L)
  expect_warning(
    means <- oaq_daily_means(list(), "x", "s9", c("2026-01-01", "2026-01-02"), min_readings = 1),
    "s9.*2026-01-02"
  )
  expect_equal(nrow(means), 1L)
})

test_that("a 404 from OAQ means no data and stays silent", {
  local_mocked_bindings(
    oaq_get_daily = function(...) stop(http_404_error()),
    oaq_get_annual = function(...) stop(http_404_error())
  )
  expect_silent(oaq_daily_means(list(), "x", "s9", "2026-01-01"))
  expect_silent(oaq_readings(list(), "x", "s9", "2026-01-01"))
  expect_silent(oaq_daily_records(list(), "x", "s9", 2026))
})

test_that("bare NaN and -Infinity in OAQ JSON are sanitized", {
  parsed <- .oaq_parse('{"data": [{"pm25": NaN, "pm10": -Infinity, "no2": 12.5}]}')
  expect_true(is.na(parsed$data$pm25))
  expect_true(is.na(parsed$data$pm10))
  expect_equal(parsed$data$no2, 12.5)
})

nc_grid <- function(lons, lats, values) {
  skip_if_not_installed("ncdf4")
  lon_dim <- ncdf4::ncdim_def("lon", "degrees_east", lons)
  lat_dim <- ncdf4::ncdim_def("lat", "degrees_north", lats)
  var_def <- ncdf4::ncvar_def("GWRPM25", "ug/m3", list(lon_dim, lat_dim), -999)
  path <- tempfile(fileext = ".nc")
  nc <- ncdf4::nc_create(path, list(var_def))
  ncdf4::ncvar_put(nc, var_def, values)
  ncdf4::nc_close(nc)
  path
}

bbox_shape <- function(xmin, xmax, ymin, ymax) {
  sf::st_as_sf(data.frame(id = 1), geometry = lonlat_box(xmin, xmax, ymin, ymax))
}

test_that("pm25_load_netcdf_bbox keeps grid cells at their centres", {
  path <- nc_grid(c(77, 78), c(28, 29), matrix(c(10, 20, 30, 40), nrow = 2))
  on.exit(unlink(path), add = TRUE)
  r <- pm25_load_netcdf_bbox(path, bbox_shape(76.5, 78.5, 27.5, 29.5))
  expect_equal(as.vector(terra::res(r)), c(1, 1))
  expect_equal(as.vector(terra::ext(r)), c(xmin = 76.5, xmax = 78.5, ymin = 27.5, ymax = 29.5))
  # north row comes first
  expect_equal(as.vector(terra::values(r)), c(30, 40, 10, 20))
})

test_that("pm25_load_netcdf_bbox handles one row or column", {
  path <- nc_grid(c(77, 78, 79), c(28, 29), matrix(1:6, nrow = 3))
  on.exit(unlink(path), add = TRUE)
  r <- pm25_load_netcdf_bbox(path, bbox_shape(77.5, 78.5, 27.5, 29.5))
  expect_equal(dim(r)[1:2], c(2L, 1L))
  expect_equal(as.vector(terra::res(r)), c(1, 1))
  expect_equal(as.vector(terra::values(r)), c(5, 2))
})

test_that(".pm25_read_bbox uses the nearest cell between centres, and errors outside the grid", {
  path <- nc_grid(c(77, 78), c(28, 29), matrix(c(10, 20, 30, 40), nrow = 2))
  on.exit(unlink(path), add = TRUE)
  inside <- bbox_shape(77.1, 77.4, 28.1, 28.4)
  expect_equal(pm25_read_netcdf_bbox(path, inside), 10)
  expect_error(pm25_read_netcdf_bbox(path, bbox_shape(90, 91, 28, 29)), "outside the NetCDF grid")
})

test_that("pm25_get_stats_by_polygon uses the population SD", {
  r <- terra::rast(nrows = 4, ncols = 4, xmin = 76, xmax = 78, ymin = 28, ymax = 30, crs = "EPSG:4326")
  terra::values(r) <- seq_len(16) * 10
  names(r) <- "PM25"
  tif <- tempfile(fileext = ".tif")
  on.exit(unlink(tif), add = TRUE)
  terra::writeRaster(r, tif, overwrite = TRUE)

  poly <- bbox_shape(76.1, 77.4, 28.1, 28.9)
  geojson <- tempfile(fileext = ".geojson")
  on.exit(unlink(geojson), add = TRUE)
  sf::st_write(poly, geojson, quiet = TRUE)

  overall <- pm25_get_stats(geojson, nc_file = tif)
  by_poly <- pm25_get_stats_by_polygon(poly, nc_file = tif)
  expect_equal(by_poly$std[1], overall$std)
  # one cell has a spread of 0, as in Python
  expect_equal(pm25_get_stats_by_polygon(bbox_shape(76.1, 76.4, 28.1, 28.4), nc_file = tif)$std[1], 0)
})
