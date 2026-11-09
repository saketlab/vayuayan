# The rolling median of sensor_plausibility, and label and mask details.

# The window rule written out, one reading at a time
one_by_one <- function(v, window) {
  before <- window %/% 2
  after <- window - before - 1
  vapply(seq_along(v), function(i) {
    w <- v[max(1, i - before):min(length(v), i + after)]
    if (length(w) >= before + 1) stats::median(w) else NA_real_
  }, numeric(1))
}

test_that(".centred_median equals the window rule for odd windows and all lengths", {
  set.seed(42)
  v <- round(stats::runif(60, 0, 50))
  for (window in c(1, 3, 5, 9, 11)) {
    for (n in c(1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 60)) {
      expect_identical(.centred_median(v[seq_len(n)], window), one_by_one(v[seq_len(n)], window),
        info = paste(window, n)
      )
    }
  }
})

test_that("even windows follow pandas: one more reading before than after", {
  expected <- c(NA, 2, 2.5, 6.5, 15, 25, 25, 30)
  expect_equal(.centred_median(c(1, 2, 3, 10, 20, 30, 100, 7), 4), expected)
  expect_equal(.centred_median(c(1, 2, 3, 4, 5, 6), 2), c(NA, 1.5, 2.5, 3.5, 4.5, 5.5))
})

test_that("too few readings give NA, and no reading gives nothing", {
  expect_equal(.centred_median(c(5, 1), 4), c(NA_real_, NA_real_))
  expect_equal(.centred_median(c(5, 1, 9), 9), rep(NA_real_, 3))
  expect_equal(.centred_median(numeric(0), 9), numeric(0))
})

test_that("sensor_plausibility is unchanged on readings with gaps", {
  set.seed(7)
  stamps <- as.POSIXct("2026-01-01", tz = "UTC") + 900 * sort(sample(4000, 2000))
  values <- stats::rlnorm(2000, 3, 1)
  values[sample(2000, 15)] <- 5000
  values[sample(2000, 100)] <- NA
  r <- data.frame(sensor_id = "s", timestamp = stamps, pm25 = values)
  out <- sensor_plausibility(r)
  v <- r$pm25[!is.na(r$pm25)]
  around <- one_by_one(v, 9)
  expect_equal(out$spikes_pct, 100 * mean(!is.na(around) & v > 10 * around & v > 100))
})

test_that("a daily window of a qualified SO2 label picks the 24-hour table", {
  expect_equal(
    us_aqi_pollutant_name(c("SO2 (24h) (ppb)", "SO2 24h", "SO2", "SO2 (ppb)", "SO2 (1h) (ppb)")),
    c("SO2_24h", "SO2_24h", "SO2", "SO2", "SO2")
  )
  # the last group is read as a unit, as in Python
  expect_equal(us_aqi_pollutant_name("SO2 (24h)"), "SO2")
  expect_equal(us_aqi_pollutant_name(c("CO (8hr) (ug/m3)", "PM2.5 (24h) (ug/m3)")), c("CO", "PM2.5"))
  expect_equal(us_aqi_pollutant_name(c(NA, "NH3")), c(NA_character_, NA_character_))
  expect_equal(us_aqi_sub_index("SO2 (24h) (ppb)", 305), 201)
})

test_that("a mask keeps the cells whose centres are inside the shape", {
  skip_if_not_installed("ncdf4")
  path <- write_pm25_nc(tempfile(fileext = ".nc"))
  on.exit(unlink(path), add = TRUE)
  # the triangle reaches into cells whose centres lie outside it
  shape <- sf::st_sfc(sf::st_polygon(list(rbind(
    c(76.85, 28.45), c(77.18, 28.45), c(76.85, 28.78), c(76.85, 28.45)
  ))), crs = 4326)
  full <- pm25_load_netcdf_bbox(path, shape, var = "PM25")
  masked <- pm25_load_netcdf_bbox(path, shape, var = "PM25", mask = TRUE)
  centres <- terra::xyFromCell(full, seq_len(terra::ncell(full)))
  inside <- lengths(sf::st_intersects(sf::st_as_sf(as.data.frame(centres), coords = c("x", "y"), crs = 4326), shape)) > 0
  expect_equal(!is.na(as.vector(terra::values(masked))), unname(inside))
  expect_lt(sum(inside), sum(!is.na(as.vector(terra::values(terra::mask(full, terra::vect(shape), touches = TRUE))))))
})
