test_that("cpcb_tidy_daily reshapes a CPCB daily sheet", {
  sheet <- data.frame(
    Day = 1:3,
    January = c(180, NA, 170),
    February = c(150, 140, NA),
    Notes = c("a", "b", "c")
  )
  out <- cpcb_tidy_daily(sheet)

  expect_named(out, c("day", "month", "value"))
  expect_equal(nrow(out), 4)
  expect_equal(out$month, c(1L, 1L, 2L, 2L))
  expect_equal(out$value, c(180, 170, 150, 140))

  path <- tempfile(fileext = ".csv")
  utils::write.csv(sheet, path, row.names = FALSE)
  expect_equal(cpcb_tidy_daily(path), out)
  unlink(path)
})

test_that("cached city and station files are read without downloading", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  sheet <- data.frame(Day = 1:2, January = c(100, 120))
  utils::write.csv(sheet, file.path(dir, "delhi_aqi_2022.csv"), row.names = FALSE)
  utils::write.csv(sheet, file.path(dir, "site_1_2022.csv"), row.names = FALSE)

  city <- cpcb_city_daily("Delhi", 2022, cache_dir = dir)
  expect_equal(unique(city$city), "Delhi")
  expect_equal(city$value, c(100, 120))

  station <- cpcb_station_daily("site_1", 2022, cache_dir = dir)
  expect_equal(unique(station$station_id), "site_1")
  expect_equal(nrow(station), 2)
  unlink(dir, recursive = TRUE)
})

# 4 x 3 grid over 76.9-77.2 E, 28.5-28.7 N with a known value per month
local_pm25_files <- function(dir, months) {
  lon <- ncdf4::ncdim_def("lon", "degrees_east", c(76.9, 77.0, 77.1, 77.2))
  lat <- ncdf4::ncdim_def("lat", "degrees_north", c(28.5, 28.6, 28.7))
  var <- ncdf4::ncvar_def("GWRPM25", "ug/m3", list(lon, lat), NA)
  for (m in months) {
    nc <- ncdf4::nc_create(pm25_v5gl04_path(2022, m, dir), var)
    ncdf4::ncvar_put(nc, var, matrix(m * 10, 4, 3))
    ncdf4::nc_close(nc)
  }
}

square <- function() {
  sf::st_sfc(sf::st_polygon(list(rbind(
    c(76.85, 28.45), c(77.25, 28.45), c(77.25, 28.75),
    c(76.85, 28.75), c(76.85, 28.45)
  ))), crs = 4326)
}

test_that("pm25_monthly returns one mean per month", {
  skip_if_not_installed("ncdf4")
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  local_pm25_files(dir, 1:3)
  local_mocked_bindings(
    pm25_download_netcdf = function(year, month, ...) pm25_v5gl04_path(year, month, dir)
  )

  out <- pm25_monthly(square(), 2022, months = 1:3, version = "V5GL04")
  expect_named(out, c("month", "pm25"))
  expect_equal(out$pm25, c(10, 20, 30))
  unlink(dir, recursive = TRUE)
})

test_that("pm25_load_netcdf_bbox masks pixels outside the shape", {
  skip_if_not_installed("ncdf4")
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  local_pm25_files(dir, 1)
  path <- pm25_v5gl04_path(2022, 1, dir)
  # triangle covering the west half of the grid
  tri <- sf::st_sfc(sf::st_polygon(list(rbind(
    c(76.85, 28.45), c(77.05, 28.45), c(76.85, 28.75), c(76.85, 28.45)
  ))), crs = 4326)

  full <- pm25_load_netcdf_bbox(path, square())
  masked <- pm25_load_netcdf_bbox(path, tri, mask = TRUE)
  expect_false(anyNA(terra::values(full)))
  expect_true(anyNA(terra::values(masked)))
  unlink(dir, recursive = TRUE)
})

test_that("india_boundary needs a selection", {
  expect_error(india_boundary(), "district or state")
})
