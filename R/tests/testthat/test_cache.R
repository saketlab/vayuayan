test_that("the cache root follows the option, then VAYUAYAN_CACHE_DIR", {
  old_opt <- options(vayuayan.cache_dir = NULL)
  old_env <- Sys.getenv("VAYUAYAN_CACHE_DIR", unset = NA)

  Sys.setenv(VAYUAYAN_CACHE_DIR = "/tmp/shared-vayuayan")
  expect_equal(vayuayan_cache_dir(), "/tmp/shared-vayuayan")
  # the Python package uses the same variable
  expect_equal(vayuayan:::.python_cache_dir(), "/tmp/shared-vayuayan")

  options(vayuayan.cache_dir = "/tmp/opt-vayuayan")
  expect_equal(vayuayan_cache_dir(), "/tmp/opt-vayuayan")

  options(old_opt)
  if (is.na(old_env)) Sys.unsetenv("VAYUAYAN_CACHE_DIR") else Sys.setenv(VAYUAYAN_CACHE_DIR = old_env)
})

test_that("only past-year CPCB files are cached, under sanitised paths", {
  name <- vayuayan:::.cpcb_cache_name
  expect_equal(
    name("/AQI_daily/city_level/delhi/2022/delhi_2022.xlsx"),
    file.path("cpcb", "AQI_daily", "city_level", "delhi", "2022", "delhi_2022.xlsx")
  )
  this_year <- format(Sys.Date(), "%Y")
  expect_null(name(sprintf("/AQI_daily/%s/x_%s.xlsx", this_year, this_year)))
  expect_null(name("/no/year/here.xlsx"))
  expect_equal(basename(name("/raw/2021/Site A (x).csv")), "Site_A__x_.csv")
  expect_false(any(grepl("..", name("/../2020/f.csv"), fixed = TRUE)))
})

test_that("a PM2.5 file in the Python cache is used without downloading", {
  old_opt <- options(vayuayan.cache_dir = tempfile("r-cache-"))
  old_env <- Sys.getenv("VAYUAYAN_CACHE_DIR", unset = NA)
  old_xdg <- Sys.getenv("XDG_CACHE_HOME", unset = NA)
  Sys.unsetenv("VAYUAYAN_CACHE_DIR")
  xdg <- tempfile("xdg-")
  Sys.setenv(XDG_CACHE_HOME = xdg)

  py_dir <- file.path(xdg, "vayuayan", "pm25")
  dir.create(py_dir, recursive = TRUE)
  py_file <- file.path(py_dir, "V6GL03.CNNPM25.AS.202311-202311.nc")
  writeBin(raw(2 * 1024 * 1024), py_file)

  if (.Platform$OS.type != "windows") {
    expect_equal(
      normalizePath(suppressMessages(pm25_download_netcdf(2023, 11, region = "AS"))),
      normalizePath(py_file)
    )
  }

  options(old_opt)
  if (is.na(old_env)) Sys.unsetenv("VAYUAYAN_CACHE_DIR") else Sys.setenv(VAYUAYAN_CACHE_DIR = old_env)
  if (is.na(old_xdg)) Sys.unsetenv("XDG_CACHE_HOME") else Sys.setenv(XDG_CACHE_HOME = old_xdg)
  unlink(xdg, recursive = TRUE)
})
