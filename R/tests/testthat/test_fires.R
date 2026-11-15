# FIRMS fire detections: source routing and API requests, offline

viirs_nrt <- function(day) {
  paste0(
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight\n",
    "28.70,77.10,331.3,0.4,0.37,", day, ",825,N,nominal,2.0NRT,288.8,2.0,D\n",
    "28.70,77.10,331.3,0.4,0.37,", day, ",1930,N,h,2.0NRT,288.8,3.0,N\n"
  )
}

local_firms <- function(env = parent.frame()) {
  seen <- new.env()
  seen$urls <- character(0)
  today <- as.Date(format(Sys.time(), tz = "UTC", "%Y-%m-%d"))
  testthat::local_mocked_bindings(
    .firms_get_text = function(url, missing_ok = FALSE) {
      seen$urls <- c(seen$urls, url)
      if (grepl("/data/country/viirs-snpp/2025/", url, fixed = TRUE)) {
        return("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type\n")
      }
      if (grepl("/data/country/", url, fixed = TRUE)) {
        return(NULL)
      }
      if (grepl("/data_availability/", url, fixed = TRUE)) {
        return("data_id,min_date,max_date\nVIIRS_SNPP_SP,2012-01-20,2026-06-30\n")
      }
      if (grepl("/active_fire/", url, fixed = TRUE)) {
        return(viirs_nrt(format(today)))
      }
      ""
    },
    .env = env
  )
  seen
}

test_that("the archive is read from the cache", {
  old <- options(vayuayan.cache_dir = tempfile("fires"))
  on.exit(options(old), add = TRUE)
  dir.create(vayuayan_cache_dir())
  dir.create(file.path(vayuayan_cache_dir(), "fires"))
  writeLines(c(
    "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type",
    "30.84,74.66,318,1.1,1,2023-11-01,0457,Terra,MODIS,72,61.03,305,23.6,D,0",
    "12.00,80.00,318,1.1,1,2023-11-01,0800,Aqua,MODIS,90,61.03,305,99.0,D,0"
  ), file.path(vayuayan_cache_dir(), "fires", "modis_2023_India.csv"))
  for (country in c("Pakistan", "Afghanistan", "China")) {
    writeLines("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type", file.path(vayuayan_cache_dir(), "fires", sprintf("modis_2023_%s.csv", country)))
  }
  seen <- local_firms()
  got <- firms_fires("2023-11-01", bbox = c(73, 29, 78, 32.5), source = "modis")
  expect_equal(nrow(got), 1)
  expect_equal(format(got$datetime, "%Y-%m-%d %H:%M", tz = "UTC"), "2023-11-01 04:57")
  expect_type(got$confidence, "integer")
  expect_length(seen$urls, 0)
})

test_that("a past year reads the countries whose box meets bbox", {
  expect_equal(.firms_countries(c(73, 29, 78, 32.5)), c("India", "Pakistan", "Afghanistan", "China"))
  expect_length(.firms_countries(c(0, 0, 1, 1)), 0)
})

test_that("a range across New Year reads the archive, then the API", {
  old <- options(vayuayan.cache_dir = tempfile("fires"))
  on.exit(options(old), add = TRUE)
  seen <- local_firms()
  got <- firms_fires("2025-12-30", "2026-01-02", bbox = c(73, 29, 78, 32.5), map_key = "K")
  expect_equal(nrow(got), 0)
  api <- sub(".*/api/area/csv/K/", "", grep("/api/area/", seen$urls, value = TRUE, fixed = TRUE))
  expect_equal(api, "VIIRS_SNPP_SP/73,29,78,32.5/2/2026-01-01")
})

test_that("a FIRMS message is an error, not an empty table", {
  expect_error(.firms_parse("Invalid MAP_KEY."), "Invalid MAP_KEY")
})

test_that("day runs break on gaps and at the size", {
  runs <- .firms_day_runs(as.Date("2026-01-01") + c(0:6, 9), 5)
  expect_equal(vapply(runs, function(r) format(r$first), ""), c("2026-01-01", "2026-01-06", "2026-01-10"))
  expect_equal(vapply(runs, function(r) r$n, 1L), c(5L, 2L, 1L))
})

test_that("recent days come from the 7-day file without a key", {
  seen <- local_firms()
  today <- as.Date(format(Sys.time(), tz = "UTC", "%Y-%m-%d"))
  got <- firms_fires(today - 2, today, map_key = "")
  expect_equal(got$confidence, c("nominal", "high"))
  expect_true(all(grepl("/active_fire/", seen$urls, fixed = TRUE)))
})

test_that("older days of the current year need a key", {
  local_firms()
  old <- as.Date(format(Sys.time(), tz = "UTC", "%Y-%m-%d")) - 30
  expect_error(firms_fires(old, map_key = ""), "FIRMS_MAP_KEY")
})

test_that("API requests split at the SP/NRT boundary and in 5-day runs", {
  seen <- local_firms()
  .firms_api_frames("viirs-snpp", as.Date("2026-06-27") + 0:6, c(73, 29, 78, 32.5), "KEY")
  api <- sub(".*/api/area/csv/KEY/", "", grep("/api/area/", seen$urls, value = TRUE, fixed = TRUE))
  expect_equal(api, c("VIIRS_SNPP_SP/73,29,78,32.5/4/2026-06-27", "VIIRS_SNPP_NRT/73,29,78,32.5/3/2026-07-01"))
})

test_that("NOAA-21 has no archive, so past years use the API", {
  seen <- local_firms()
  firms_fires("2024-11-01", bbox = c(73, 29, 78, 32.5), source = "viirs-noaa21", map_key = "K")
  expect_true(any(grepl("/data/country/viirs-jpss2/2024/", seen$urls, fixed = TRUE)))
  api <- sub(".*/api/area/csv/K/", "", grep("/api/area/", seen$urls, value = TRUE, fixed = TRUE))
  expect_equal(api, "VIIRS_NOAA21_SP/73,29,78,32.5/1/2024-11-01")
})

test_that("bad arguments fail", {
  expect_error(firms_fires("2023-01-01", source = "goes"), "source")
  expect_error(firms_fires("2023-01-02", "2023-01-01"), "before")
})

test_that("daily counts fill days without fires", {
  fires <- .firms_parse(viirs_nrt("2026-11-05"))
  got <- fire_daily_counts(fires, 28.6, 77.2, radius_km = 50, end = "2026-11-07", tz = "UTC")
  expect_equal(format(got$date), c("2026-11-05", "2026-11-06", "2026-11-07"))
  expect_equal(got$n_fires, c(2L, 0L, 0L))
  expect_equal(got$frp_sum, c(5, 0, 0))
  ist <- fire_daily_counts(fires, 28.6, 77.2, radius_km = 50, end = "2026-11-07")
  expect_equal(ist$n_fires, c(1L, 1L, 0L)) # 19:30 UTC is 01:00 IST the next day
  fires$latitude[1] <- NA
  expect_equal(fire_daily_counts(fires, 28.6, 77.2, radius_km = 50)$frp_sum, c(0, 3))
  expect_error(fire_daily_counts(fires, 28.6, 77.2, start = "2026-11-07", end = "2026-11-05"), "before")
  expect_equal(nrow(fire_daily_counts(.firms_parse(""), 0, 0)), 0)
})
