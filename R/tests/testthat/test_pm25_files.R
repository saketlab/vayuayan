aws_nc <- "https://satpmdata.s3.us-east-1.amazonaws.com/V6GL03/CNNPM25/Monthly/AS/V6GL03.CNNPM25.AS.202311-202311.nc"
aws_file <- "V6GL03.CNNPM25.AS.202311-202311.nc"

test_that("pm25_download_netcdf fetches from the WUSTL bucket into the cache", {
  dir <- tempfile("vayuayan-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(fake_response(200, raw(1024)))

  path <- suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS"))

  expect_equal(http$calls[[1]]$method, "GET")
  expect_equal(http$calls[[1]]$url, aws_nc)
  expect_equal(path, file.path(dir, aws_file))
  expect_equal(http$calls[[1]]$path, paste0(path, ".part"))
  expect_equal(file.size(path), 1024)
  expect_false(file.exists(paste0(path, ".part")))
})

test_that("pm25_download_netcdf uses the versions' own paths", {
  dir <- tempfile("vayuayan-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  http <- local_http(
    fake_response(200, raw(10)),
    fake_response(200, raw(10)),
    fake_response(200, raw(10))
  )
  suppressMessages({
    pm25_download_netcdf(2020, cache_dir = dir, version = "V6")
    pm25_download_netcdf(2020, 1, cache_dir = dir, version = "V5")
    pm25_download_netcdf(2020, 1, cache_dir = dir, region = "AS", version = "V5GL04")
  })
  bucket <- "https://satpmdata.s3.us-east-1.amazonaws.com/archive/"
  expect_equal(http$calls[[1]]$url, paste0(bucket, "V6GL0204/CNNPM25/Annual/GL/V6GL02.04.CNNPM25.GL.202001-202012.nc"))
  expect_equal(http$calls[[2]]$url, paste0(bucket, "V5GL0502/GWRPM25/Monthly/Global/V5GL0502.HybridPM25.Global.202001-202001.nc"))
  expect_equal(http$calls[[3]]$url, paste0(bucket, "V5GL04/GWRPM25/Monthly/Asia/V5GL04.HybridPM25.Asia.202001-202001.nc"))
})

test_that("pm25_download_netcdf goes to the package cache by default", {
  dir <- local_cpcb()
  local_http(fake_response(200, raw(10)))
  path <- suppressMessages(pm25_download_netcdf(2023, 11, region = "AS"))
  expect_equal(path, file.path(dir, "pm25", aws_file))
})

test_that("force_download replaces a cached file", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  cached <- file.path(dir, aws_file)
  writeBin(raw(2 * 1024 * 1024), cached)
  http <- local_http(fake_response(200, raw(4)))

  suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS", force_download = TRUE))
  expect_length(http$calls, 1)
  expect_equal(file.size(cached), 4)
})

test_that("a failed PM2.5 download leaves nothing behind", {
  dir <- tempfile("vayuayan-")
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)

  local_http(connection_error("Could not resolve host: satpmdata"))
  expect_error(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    "Failed to download NetCDF data: Could not resolve"
  )
  expect_equal(list.files(dir), character(0))

  local_http(fake_response(404, "NoSuchKey"))
  expect_error(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    class = "http_404"
  )
  expect_equal(list.files(dir), character(0))

  local_http(fake_response(403, "denied"))
  expect_error(
    suppressMessages(pm25_download_netcdf(2023, 11, cache_dir = dir, region = "AS")),
    class = "http_403"
  )
  expect_equal(list.files(dir), character(0))
})

test_that("PM2.5 arguments validate per version", {
  expect_error(.pm25_spec("V9"), "version must be one of: V6GL03, V6, V5, V5GL04")
  expect_equal(.pm25_spec("V5")$variable, "GWRPM25")
  # AF exists only in V6GL03
  expect_error(pm25_download_netcdf(2020, region = "AF", version = "V5", cache_dir = tempfile()), "region")
})

test_that("cached PM2.5 files are listed", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)

  expect_equal(suppressMessages(pm25_list_cached_files(dir)), character(0))
  expect_message(pm25_list_cached_files(dir), "No cached files")

  writeBin(raw(2 * 1024 * 1024), file.path(dir, "a.nc"))
  writeBin(raw(10), file.path(dir, "not_netcdf.txt"))
  expect_equal(suppressMessages(pm25_list_cached_files(dir)), file.path(dir, "a.nc"))
  expect_message(pm25_list_cached_files(dir), "a.nc \\(2 MB\\)")

  missing_dir <- file.path(dir, "absent")
  expect_message(out <- pm25_list_cached_files(missing_dir), "does not exist")
  expect_equal(out, character(0))
})

test_that("the package cache is the default PM2.5 directory", {
  dir <- local_cpcb()
  pm25 <- file.path(dir, "pm25")
  dir.create(pm25, recursive = TRUE)
  file.create(file.path(pm25, "x.nc"))
  expect_equal(suppressMessages(pm25_list_cached_files()), file.path(pm25, "x.nc"))

  suppressMessages(pm25_clear_cache())
  expect_equal(list.files(pm25), character(0))
})

test_that("the PM2.5 cache clears only NetCDF files", {
  dir <- tempfile("vayuayan-")
  dir.create(dir)
  on.exit(unlink(dir, recursive = TRUE), add = TRUE)
  file.create(file.path(dir, c("a.nc", "b.nc", "keep.txt")))

  expect_null(suppressMessages(pm25_clear_cache(dir)))
  expect_equal(list.files(dir), "keep.txt")
  expect_message(pm25_clear_cache(file.path(dir, "absent")), "does not exist")
  expect_true(file.exists(file.path(dir, "keep.txt")))
})
