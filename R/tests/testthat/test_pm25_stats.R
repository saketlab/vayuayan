# write_pm25_nc() grid: 10 in the west half (lon < 77.05), 30 in the east

local_grid <- function(env = parent.frame(), ...) {
  skip_if_not_installed("ncdf4")
  write_pm25_nc(tempfile("pm25-", fileext = ".nc"), ...)
}

whole <- function() lonlat_box(76.85, 77.25, 28.45, 28.75)
west <- function() lonlat_box(76.85, 77.05, 28.45, 28.75)
east <- function() lonlat_box(77.05, 77.25, 28.45, 28.75)

# GeoJSON file of named polygons
geojson_of <- function(...) {
  path <- tempfile(fileext = ".geojson")
  sf::st_write(sf::st_sf(...), path, quiet = TRUE)
  path
}

test_that(".pm25_find_variable knows both WUSTL names", {
  expect_equal(.pm25_find_variable(c(PM25 = 1, other = 2)), "PM25")
  expect_equal(.pm25_find_variable(c(GWRPM25 = 1)), "GWRPM25")
  expect_error(.pm25_find_variable(c(a = 1, b = 2)), "PM2.5 variable not found. Available variables: a, b")
})

test_that(".pop_sd divides by n", {
  expect_equal(.pop_sd(c(10, 30)), 10)
})

test_that(".pm25_layer reads the PM2.5 variable from a NetCDF file", {
  nc <- local_grid()
  r <- .pm25_layer(nc)
  expect_s4_class(r, "SpatRaster")
  expect_equal(terra::nlyr(r), 1)
  expect_equal(mean(terra::values(r), na.rm = TRUE), 20)
  expect_error(.pm25_layer(local_grid(var = "OTHER")), "PM2.5 variable not found")
})

test_that(".pm25_rast hides only terra's geotransform warning", {
  message_text <- "cannot be represented: no geotransform"
  local_mocked_bindings(
    rast = function(x) {
      warning(message_text, call. = FALSE)
      "raster"
    },
    .package = "terra"
  )
  expect_no_warning(got <- .pm25_rast("x.nc"))
  expect_equal(got, "raster")

  message_text <- "file is damaged"
  expect_warning(.pm25_rast("x.nc"), "file is damaged")
})

test_that(".pm25_load_and_crop trims the raster and rejects a bad box", {
  nc <- local_grid()
  # the box is the west half, plus a 0.1 degree buffer: 3 of 4 columns
  cropped <- .pm25_load_and_crop(nc, sf::st_bbox(west()))
  expect_equal(terra::ncol(cropped), 3)
  expect_equal(terra::nrow(cropped), 3)
  expect_equal(sort(unique(terra::values(cropped)[, 1])), c(10, 30))
  # sf reports an empty geometry's box as NA
  expect_error(.pm25_load_and_crop(nc, sf::st_bbox(sf::st_sfc(crs = 4326))), "invalid values")
})

test_that("pm25_get_stats summarises a region's pixels", {
  nc <- local_grid()
  geo <- geojson_of(region = "all", geometry = whole())
  stats <- suppressMessages(pm25_get_stats(geo, nc_file = nc))

  expect_equal(stats$mean, 20)
  expect_equal(stats$std, 10)
  expect_equal(stats$min, 10)
  expect_equal(stats$max, 30)
  expect_equal(stats$count, 12)
})

test_that("pm25_get_stats with a year downloads the file", {
  nc <- local_grid()
  geo <- geojson_of(region = "all", geometry = whole())
  asked <- NULL
  local_mocked_bindings(pm25_download_netcdf = function(year, month, cache_dir, region, version) {
    asked <<- list(year = year, month = month, region = region, version = version)
    nc
  })
  stats <- pm25_get_stats(geo, year = 2023, month = 11, region = "AS", version = "V5")
  expect_equal(asked, list(year = 2023, month = 11, region = "AS", version = "V5"))
  expect_equal(stats$count, 12)
})

test_that("a URL GeoJSON is handed to sf unchanged", {
  nc <- local_grid()
  url <- "https://geo.example/delhi.geojson"
  seen <- NULL
  local_mocked_bindings(
    st_read = function(dsn, quiet) {
      seen <<- dsn
      sf::st_sf(region = "all", geometry = whole())
    },
    .package = "sf"
  )
  stats <- pm25_get_stats(url, nc_file = nc)
  expect_equal(seen, url)
  expect_equal(stats$mean, 20)
})

test_that("pm25_get_stats validates its inputs", {
  geo <- geojson_of(region = "all", geometry = whole())
  expect_error(pm25_get_stats("/no/such.geojson", year = 2023), "GeoJSON file not found")
  expect_error(pm25_get_stats(geo), "Either 'year' or 'nc_file' must be supplied")
  expect_error(pm25_get_stats(geo, nc_file = "/no/such.nc"), "NetCDF file not found")
  nc <- local_grid()
  expect_error(pm25_get_stats(geo, nc_file = nc, group_by = "district"), "Column\\(s\\) district not found")
})

test_that("pm25_get_stats errors when a region has no pixels", {
  nc <- local_grid(values = rep(-9999, 12))
  geo <- geojson_of(region = "all", geometry = whole())
  expect_error(pm25_get_stats(geo, nc_file = nc), "No valid PM2.5 data")
})

test_that("pm25_get_stats errors on an empty geometry", {
  nc <- local_grid()
  gdf <- sf::st_sf(region = "x", geometry = sf::st_sfc(sf::st_polygon(), crs = 4326))
  geo <- tempfile(fileext = ".gpkg")
  sf::st_write(gdf, geo, quiet = TRUE)
  expect_error(pm25_get_stats(geo, nc_file = nc), "empty or invalid")
})

test_that("a union failure is retried after a GeoJSON round trip", {
  nc <- local_grid()
  geo <- geojson_of(region = "all", geometry = whole())
  union <- sf::st_union
  n <- 0
  local_mocked_bindings(
    st_union = function(x, ...) {
      n <<- n + 1
      if (n == 1) stop("TopologyException")
      union(x, ...)
    },
    .package = "sf"
  )
  expect_message(stats <- pm25_get_stats(geo, nc_file = nc), "Union failed")
  expect_gt(n, 1)
  expect_equal(stats$mean, 20)
})

test_that("pm25_get_stats groups by one column and by several", {
  nc <- local_grid()
  geo <- geojson_of(
    state = c("S", "S"), district = c("W", "E"), geometry = c(west(), east())
  )
  by_district <- pm25_get_stats(geo, nc_file = nc, group_by = "district")
  by_district <- by_district[order(by_district$district), ]
  expect_equal(by_district$district, c("E", "W"))
  expect_equal(by_district$mean, c(30, 10))
  expect_equal(by_district$std, c(0, 0))
  expect_equal(by_district$count, c(6, 6))

  by_both <- pm25_get_stats(geo, nc_file = nc, group_by = "state, district")
  expect_true(all(c("state", "district", "mean", "std", "min", "max", "count") %in% names(by_both)))
  expect_equal(nrow(by_both), 2)
  by_state <- pm25_get_stats(geo, nc_file = nc, group_by = "state")
  expect_equal(by_state$mean, 20)
  expect_equal(by_state$count, 12)
})

test_that("grouped statistics carry only the group columns and the statistics", {
  nc <- local_grid()
  geo <- geojson_of(state = c("S", "S"), district = c("W", "E"), geometry = c(west(), east()))
  out <- pm25_get_stats(geo, nc_file = nc, group_by = "district")
  expect_named(out, c("district", "mean", "std", "min", "max", "count"))
})

test_that("a group with no pixels is reported, not dropped", {
  # only the east half of the grid has data
  nc <- local_grid(values = rep(c(-9999, -9999, 30, 30), 3))
  geo <- geojson_of(district = c("W", "E"), geometry = c(west(), east()))
  out <- pm25_get_stats(geo, nc_file = nc, group_by = "district")
  out <- out[order(out$district), ]
  expect_equal(out$count, c(6, 0))
  expect_equal(out$mean, c(30, NA))
})

test_that("a group that fails is skipped with a warning alert", {
  nc <- local_grid()
  geo <- geojson_of(district = c("W", "E"), geometry = c(west(), east()))
  extract <- terra::extract
  n <- 0
  local_mocked_bindings(
    extract = function(...) {
      n <<- n + 1
      if (n == 1) stop("extract failed")
      extract(...)
    },
    .package = "terra"
  )
  expect_message(
    out <- pm25_get_stats(geo, nc_file = nc, group_by = "district"),
    "Error processing group: extract failed"
  )
  expect_equal(nrow(out), 1)
})

test_that("polygons count the cells whose centres fall inside", {
  nc <- local_grid()
  # the column at 77.0 (centre) is in; the column at 77.1 only touched
  box <- lonlat_box(76.95, 77.06, 28.45, 28.75)
  geo <- geojson_of(region = "x", geometry = box)
  stats <- pm25_get_stats(geo, nc_file = nc)
  expect_equal(stats$count, 3)
  expect_equal(stats$mean, 10)

  grouped <- pm25_get_stats(geo, nc_file = nc, group_by = "region")
  expect_equal(grouped$count, 3)

  by_polygon <- pm25_get_stats_by_polygon(sf::st_sf(name = "x", geometry = box), nc_file = nc)
  expect_equal(by_polygon$mean, 10)
})

test_that("a small polygon with no centre inside uses the cells it touches", {
  nc <- local_grid()
  # between the centres of the 77.0 and 77.1 columns
  tiny <- lonlat_box(77.02, 77.03, 28.53, 28.54)
  stats <- pm25_get_stats(geojson_of(region = "tiny", geometry = tiny), nc_file = nc)
  expect_equal(stats$count, 1)
  expect_equal(stats$mean, 10)
  by_polygon <- pm25_get_stats_by_polygon(sf::st_sf(name = "tiny", geometry = tiny), nc_file = nc)
  expect_equal(by_polygon$mean, 10)
  expect_equal(by_polygon$std, 0)
})

test_that("a polygon entirely outside the grid stops", {
  nc <- local_grid()
  far <- lonlat_box(10, 11, 10, 11)
  expect_error(pm25_get_stats(geojson_of(region = "far", geometry = far), nc_file = nc), "entirely outside")
  expect_error(pm25_get_stats_by_polygon(sf::st_sf(name = "far", geometry = far), nc_file = nc), "entirely outside")
  # inside the 0.1 degree buffer of the crop, but outside the grid
  near <- lonlat_box(77.26, 77.3, 28.5, 28.6)
  expect_error(pm25_get_stats(geojson_of(region = "near", geometry = near), nc_file = nc), "entirely outside")
})

test_that("pm25_get_point reads the cell at each point", {
  nc <- local_grid()
  expect_equal(pm25_get_point(c(28.6, 28.6), c(76.9, 77.2), nc_file = nc), c(10, 30))

  # outside the grid is NA, with a warning alert; GDAL warns as well
  expect_message(out <- suppressWarnings(pm25_get_point(0, 0, nc_file = nc)), "No PM2.5 data at 1 point")
  expect_true(is.na(out))
})

test_that("pm25_get_point downloads when no file is given", {
  nc <- local_grid()
  asked <- NULL
  local_mocked_bindings(pm25_download_netcdf = function(year, month, cache_dir, region, version) {
    asked <<- list(year, month, region, version)
    nc
  })
  expect_equal(pm25_get_point(28.6, 76.9, 2023, 11, version = "V6", region = "AS"), 10)
  expect_equal(asked, list(2023, 11, "AS", "V6"))
})

test_that("pm25_get_stats_by_polygon gives one row per feature", {
  nc <- local_grid()
  gdf <- sf::st_sf(NAME_1 = c("W", "E"), other = c("a", "b"), geometry = c(west(), east()))

  out <- pm25_get_stats_by_polygon(gdf, nc_file = nc)
  expect_named(out, c("NAME_1", "mean", "std"))
  expect_equal(out$NAME_1, c("W", "E"))
  expect_equal(out$mean, c(10, 30))
  expect_equal(out$std, c(0, 0))

  by_field <- pm25_get_stats_by_polygon(gdf, nc_file = nc, id_field = "other")
  expect_named(by_field, c("other", "mean", "std"))
  expect_equal(by_field$other, c("a", "b"))
})

test_that("the polygon id falls back to name, then the row number", {
  nc <- local_grid()
  named <- sf::st_sf(name = c("W", "E"), geometry = c(west(), east()))
  expect_named(pm25_get_stats_by_polygon(named, nc_file = nc), c("name", "mean", "std"))

  plain <- sf::st_sf(val = c(1, 2), geometry = c(west(), east()))
  out <- pm25_get_stats_by_polygon(plain, id_field = "absent", nc_file = nc)
  expect_named(out, c("index", "mean", "std"))
  expect_equal(out$index, 1:2)
})

test_that("pm25_get_stats_by_polygon reads a file and can download", {
  nc <- local_grid()
  geo <- geojson_of(name = "All", geometry = whole())
  asked <- NULL
  local_mocked_bindings(pm25_download_netcdf = function(year, month, cache_dir, region, version) {
    asked <<- list(year, month, region, version)
    nc
  })
  out <- pm25_get_stats_by_polygon(geo, 2023, 11, region = "AS", version = "V5")
  expect_equal(asked, list(2023, 11, "AS", "V5"))
  expect_equal(out$name, "All")
  expect_equal(out$mean, 20)
})
