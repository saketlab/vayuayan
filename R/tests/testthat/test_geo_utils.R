districts_sf <- function() {
  sf::st_sf(
    district_name = c("Mumbai", "Mumbai Suburban", "Pune"),
    state_name = c("Maharashtra", "Maharashtra", "Maharashtra"),
    geometry = c(
      lonlat_box(72, 73, 18, 19), lonlat_box(73, 74, 18, 19), lonlat_box(74, 75, 18, 19)
    )
  )
}

test_that("india_boundary reads the BharatViz layer once", {
  local_cpcb()
  urls <- character(0)
  local_mocked_bindings(
    st_read = function(dsn, quiet) {
      urls <<- c(urls, dsn)
      districts_sf()
    },
    .package = "sf"
  )

  one <- india_boundary(district = "Mumbai")
  expect_s3_class(one, "sfc")
  expect_equal(urls, "https://geo.bharatviz.org/geojsons/districts/India_LGD_districts.geojson")

  two <- india_boundary(district = c("Mumbai", "Mumbai Suburban"))
  expect_length(urls, 1)
  expect_equal(as.numeric(sf::st_bbox(two)[c("xmin", "xmax")]), c(72, 74))
  # district wins over state
  expect_equal(as.numeric(sf::st_bbox(india_boundary(district = "Pune", state = "Maharashtra"))["xmin"]), 74)

  state <- india_boundary(state = "Maharashtra")
  expect_equal(as.numeric(sf::st_bbox(state)[c("xmin", "xmax")]), c(72, 75))
  expect_error(india_boundary(state = "Atlantis"), "No BharatViz district matches")
})

test_that(".squish clamps to the range and keeps NA", {
  expect_equal(.squish(c(-1, 0.5, 2, NA)), c(0, 0.5, 1, NA))
  expect_equal(.squish(c(5, 50), range = c(10, 20)), c(10, 20))
})

test_that("pm25_map draws a raster and its outline", {
  skip_if_not_installed("ggplot2")
  skip_if_not_installed("tidyterra")
  r <- terra::rast(nrows = 3, ncols = 3, xmin = 77, xmax = 77.3, ymin = 28, ymax = 28.3, crs = "EPSG:4326", vals = 1:9)
  p <- pm25_map(r, boundary = lonlat_box(77, 77.3, 28, 28.3), title = "Delhi")
  expect_s3_class(p, "ggplot")
  expect_equal(p$labels$title, "Delhi")
  expect_match(p$labels$subtitle, "Mean: 5.0")
  expect_silent(ggplot2::ggplot_build(p))
})

test_that("pm25_map names the package it is missing", {
  skip_if(requireNamespace("tidyterra", quietly = TRUE), "tidyterra is installed")
  r <- terra::rast(nrows = 1, ncols = 1, vals = 1)
  expect_error(pm25_map(r), "Package 'tidyterra' is required for pm25_map")
})

test_that("vayuayan_welcome lists the main entry points", {
  lines <- cli::cli_fmt(vayuayan_welcome())
  expect_true(any(grepl("Vayuayan - Air quality data analysis", lines, fixed = TRUE)))
  expect_true(any(grepl(as.character(utils::packageVersion("vayuayan")), lines, fixed = TRUE)))
  expect_true(any(grepl("cpcb_get_state_list()", lines, fixed = TRUE)))
  expect_true(any(grepl("oaq_session()", lines, fixed = TRUE)))
  expect_null(suppressMessages(vayuayan_welcome()))
})

feed_cities <- function() {
  st <- function(id, lat, live, avg) {
    data.frame(id = id, name = paste("Station", id), latitude = lat, longitude = "77", live = live, avg = avg)
  }
  cities <- data.frame(cityName = c("Alpha", "Beta"), cityID = c("A", "B"), stateID = c("S1", "S2"))
  cities$stationsInCity <- list(
    rbind(st("a1", "28", TRUE, "120"), st("a2", "bad", TRUE, "90"), st("a3", "29", FALSE, "NA")),
    st("b1", "19", FALSE, "NA")
  )
  cities
}

test_that("stations_to_dataframe flattens the data-frame form of the feed", {
  out <- stations_to_dataframe(feed_cities())
  # a2 has no usable latitude: kept, with NA
  expect_equal(out$station_id, c("a1", "a2", "a3", "b1"))
  expect_equal(out$city_id, c("A", "A", "A", "B"))
  expect_equal(out$state_id, c("S1", "S1", "S1", "S2"))
  expect_equal(out$latitude, c(28, NA, 29, 19))
  expect_equal(out$avg_aqi, c(120, 90, NA, NA))
  expect_equal(out$status, c("Live", "Live", "Offline", "Offline"))
  expect_equal(out$aqi_category, c("Moderate", "Satisfactory", "No Data", "No Data"))
})

test_that("stations_to_dataframe skips cities without stations in both forms", {
  no_station <- list(list(cityName = "X", cityID = "X", stateID = "S", stationsInCity = NULL))
  expect_equal(nrow(stations_to_dataframe(no_station)), 0)
  expect_equal(nrow(stations_to_dataframe(feed_cities()[0, ])), 0)

  bad <- list(list(
    cityName = "X", cityID = "X", stateID = "S",
    stationsInCity = list(list(id = "a", latitude = "bad", longitude = "1"))
  ))
  expect_true(is.na(stations_to_dataframe(bad)$latitude))
})

test_that("stations_to_dataframe keeps infinite coordinates as NA in both forms", {
  cities <- feed_cities()
  cities$stationsInCity[[1]]$latitude[1] <- "Inf"
  cities$stationsInCity[[2]]$longitude <- "-Inf"
  expect_equal(stations_to_dataframe(cities)$station_id, c("a1", "a2", "a3", "b1"))
  expect_true(is.na(stations_to_dataframe(cities)$latitude[1]))

  listed <- list(list(
    cityName = "X", cityID = "X", stateID = "S",
    stationsInCity = list(
      list(id = "inf", latitude = "Inf", longitude = "77"),
      list(id = "ok", latitude = "28", longitude = "77")
    )
  ))
  expect_equal(stations_to_dataframe(listed)$station_id, c("inf", "ok"))
  expect_true(is.na(stations_to_dataframe(listed)$latitude[1]))
})

test_that("the real feed flattens through to the analysis", {
  local_cpcb()
  local_feed()
  cities <- cpcb_get_all_india()
  df <- stations_to_dataframe(cities)
  expect_equal(df$station_id, c("site_5392", "site_301", "site_feedonly"))
  expect_equal(df$status, c("Live", "Live", "Offline"))

  stats <- analyze_station_data(cities)
  expect_equal(stats$total_cities, 2)
  expect_equal(stats$total_stations, 3)
  expect_equal(stats$live_stations, 2)
  expect_equal(stats$offline_stations, 1)
  expect_equal(stats$stations_with_aqi_data, 2)
  expect_equal(stats$avg_aqi_overall, (95 + 180) / 2)
  expect_equal(stats$min_aqi, 95)
  expect_equal(stats$max_aqi, 180)
  expect_equal(stats$unique_states, c("Delhi", "Maharashtra"))
})

test_that("stations_to_city_summary reports each city's live stations", {
  out <- stations_to_city_summary(feed_cities())
  expect_named(out, c(
    "city_name", "city_id", "state_id", "total_stations", "live_stations",
    "offline_stations", "live_percentage", "avg_aqi", "min_aqi", "max_aqi",
    "stations_with_data"
  ))
  expect_equal(out$city_name, c("Alpha", "Beta"))
  expect_equal(out$total_stations, c(3, 1))
  expect_equal(out$live_stations, c(2, 0))
  expect_equal(out$offline_stations, c(1, 1))
  expect_equal(out$live_percentage, c(200 / 3, 0))
  expect_equal(out$avg_aqi, c(105, NA))
  expect_equal(out$min_aqi, c(90, NA))
  expect_equal(out$max_aqi, c(120, NA))
  expect_equal(out$stations_with_data, c(2L, 0L))
})

test_that("stations_to_city_summary reads the list form of the feed", {
  cities <- list(list(
    cityName = "Alpha", cityID = "A", stateID = "S",
    stationsInCity = list(
      list(id = "a", live = TRUE, avg = "50"),
      list(id = "b", live = FALSE, avg = NULL)
    )
  ))
  out <- stations_to_city_summary(cities)
  expect_equal(out$total_stations, 2)
  expect_equal(out$live_stations, 1)
  expect_equal(out$avg_aqi, 50)
})

test_that("cache lookups skip empty and undersized files", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  file.create(file.path(dir, "empty.nc"))
  expect_null(.cache_lookup(dir, "empty.nc"))
  expect_null(.cache_lookup(dir, "absent.nc"))

  writeBin(raw(100), file.path(dir, "small.nc"))
  expect_equal(.cache_lookup(dir, "small.nc"), file.path(dir, "small.nc"))
  expect_null(.cache_lookup(dir, "small.nc", min_size = 1024))
})

test_that("the default PM2.5 directories include the working directory cache", {
  dir <- local_cpcb()
  expect_equal(.pm25_default_dirs(), c(file.path(dir, "pm25"), file.path(.python_cache_dir(), "pm25"), "pm25_data"))
})
