test_that("station directory lookups work offline", {
  states <- cpcb_get_state_list()
  expect_true("Maharashtra" %in% states)

  expect_true("Mumbai" %in% cpcb_get_city_list("maharashtra"))
  expect_identical(cpcb_get_city_list("InvalidState123"), character(0))

  stations <- cpcb_get_station_list("Mumbai")
  expect_named(stations, c("label", "value"))
  expect_gt(nrow(stations), 10)
  expect_true(all(grepl("^site_", stations$value)))
  expect_equal(nrow(cpcb_get_station_list("InvalidCity123")), 0)
})

test_that("cities and stations resolve to CPCB's canonical names", {
  city <- vayuayan:::.cpcb_resolve_city("mumbai")
  expect_equal(city$city_name, "Mumbai")
  expect_equal(city$state_name, "Maharashtra")
  expect_null(vayuayan:::.cpcb_resolve_city("Mumbai", state = "Kerala"))

  station <- vayuayan:::.cpcb_resolve_station("site_5392")
  expect_equal(station$city, "Mumbai")
  expect_equal(station$state, "Maharashtra")
  expect_match(station$station_name, "Bandra Kurla Complex")
})

test_that("stations resolve by full or partial name", {
  resolve <- vayuayan:::.cpcb_resolve_station
  expect_equal(resolve("anand vihar, delhi - dpcc")$station_id, "site_301")
  expect_equal(resolve("Anand Vihar, Delhi")$station_id, "site_301")
  expect_error(resolve("Anand Vihar"), "matches 2 stations")
  expect_error(vayuayan:::.cpcb_require_station("site_000000"), "not found")
})

test_that("frequency names map to the codes the file-path API expects", {
  f <- vayuayan:::.cpcb_normalize_frequency
  expect_equal(f("daily"), "1D")
  expect_equal(f("Hourly"), "1H")
  expect_equal(f("15_minute"), "15M")
  expect_equal(f("1D"), "1D")
})

test_that("PM2.5 file names and URLs follow the V6.GL.03 layout", {
  expect_equal(
    vayuayan:::.pm25_get_aws_filename(2023, 11, "AS"),
    "V6GL03.CNNPM25.AS.202311-202311.nc"
  )
  expect_equal(
    vayuayan:::.pm25_get_aws_filename(2020),
    "V6GL03.CNNPM25.GL.202001-202012.nc"
  )
  expect_match(
    vayuayan:::.pm25_get_aws_url(2023, 1, "AS"),
    "/V6GL03/CNNPM25/Monthly/AS/V6GL03\\.CNNPM25\\.AS\\.202301-202301\\.nc$"
  )
  expect_match(
    vayuayan:::.pm25_get_aws_url(2023),
    "/V6GL03/CNNPM25/Annual/GL/"
  )
})

test_that("PM2.5 downloads validate their arguments before any request", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  expect_error(pm25_download_netcdf(1990, cache_dir = dir), "between 1998")
  expect_error(pm25_download_netcdf(2023, 13, cache_dir = dir), "month")
  expect_error(pm25_download_netcdf(2023, region = "XX", cache_dir = dir), "region")
  unlink(dir, recursive = TRUE)
})

test_that("a cached PM2.5 file is reused without downloading", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  cached <- file.path(dir, "V6GL03.CNNPM25.AS.202311-202311.nc")
  writeBin(raw(2 * 1024 * 1024), cached)
  expect_equal(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    cached
  )
  unlink(dir, recursive = TRUE)
})

test_that("get_aqi_categories always returns a character vector", {
  expect_identical(get_aqi_categories(numeric(0)), character(0))
  expect_identical(get_aqi_categories(c(10, NA)), c("Good", "No Data"))
})
