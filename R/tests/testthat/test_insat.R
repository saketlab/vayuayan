# INSAT fire previews: URLs, layout checks and blob positions, offline

fake_3s <- function(fires) {
  lay <- .insat_layouts[["2002x2242"]]
  img <- array(30L, c(2242, 2002, 3))
  img[, lay$grat[1] + 1, ] <- 200L
  img[lay$grat[2] + 1, , ] <- 200L
  for (f in fires) {
    x <- lay$x_lon[1] + (f[1] - lay$x_lon[2]) * (lay$x_lon[3] - lay$x_lon[1]) / (lay$x_lon[4] - lay$x_lon[2])
    m <- .insat_merc(f[2])
    a <- lay$y_lat
    y <- a[1] + (m - .insat_merc(a[2])) * (a[3] - a[1]) / (.insat_merc(a[4]) - .insat_merc(a[2]))
    rows <- (round(y) - 6):(round(y) + 5) + 1
    cols <- (round(x) - 6):(round(x) + 5) + 1
    img[rows, cols, 1] <- 230L
    img[rows, cols, 2] <- 20L
    img[rows, cols, 3] <- 20L
  }
  img
}

test_that("blobs land back on their coordinates", {
  got <- parse_insat_fire_array(fake_3s(list(c(75.8, 30.9), c(76.4, 30.3))))
  expect_equal(got$layout, "3S")
  b <- got$blobs[order(got$blobs$lon), ]
  expect_equal(b$lon, c(75.8, 76.4), tolerance = 0.04 / 76)
  expect_equal(b$lat, c(30.9, 30.3), tolerance = 0.04 / 30)
  expect_equal(b$area_px, c(144L, 144L))
})

test_that("a moved graticule or a new size is an error", {
  img <- fake_3s(list())
  img[, 474, ] <- 30L
  expect_error(parse_insat_fire_array(img), "graticule")
  expect_error(parse_insat_fire_array(array(0, c(100, 100, 3))), "layout")
})

test_that("URLs follow each satellite's minutes", {
  s <- insat_fire_urls("2026-11-01")
  expect_length(s, 48)
  expect_equal(s[36], "https://mosdac.gov.in/look/3S_IMG/preview/2026/01NOV/3SIMG_01NOV2026_1730_L2P_FIR_V01R00.jpg")
  expect_match(insat_fire_urls("2025-10-05", satellite = "3R")[1], "_0015_L2P_FIR_V01R00.jpg", fixed = TRUE)
  expect_match(insat_fire_urls("2016-11-01", satellite = "3D")[2], "_0030_L2P_FIR_V01R00.jpg", fixed = TRUE)
  expect_error(insat_fire_urls("2026-11-01", satellite = "GOES"), "satellite")
})

test_that("a missing slot or an HTML page is no image, and a JPEG is cached", {
  dir <- local_cpcb()
  jpg <- as.raw(c(0xff, 0xd8, 0xff, 0xe0, 1:8))
  http <- local_http(fake_response(404), fake_response(200, "<html>no image</html>"), fake_response(200, jpg))
  expect_null(.insat_download("https://x/MISSING.jpg"))
  expect_null(.insat_download("https://x/page.jpg"))
  path <- .insat_download("https://x/a.jpg")
  expect_equal(path, file.path(dir, "insat", "a.jpg"))
  expect_equal(readBin(path, "raw", 20), jpg)
  expect_equal(.insat_download("https://x/a.jpg"), path)
  expect_length(http$calls, 3) # the fourth read is from the cache
})

test_that("insat_fires reads each image, skips empty slots and keeps the box", {
  skip_if_not_installed("jpeg")
  path <- file.path(withr::local_tempdir(), "3SIMG_01NOV2026_1130_L2P_FIR_V01R00.jpg")
  jpeg::writeJPEG(fake_3s(list(c(75.8, 30.9), c(88.0, 22.5))) / 255, path, quality = 1)
  local_mocked_bindings(.insat_download = function(url) if (grepl("_1130_", url, fixed = TRUE)) path)
  all <- insat_fires("2026-11-01")
  expect_named(all, names(.insat_empty()))
  expect_equal(nrow(all), 2)
  got <- insat_fires("2026-11-01", bbox = c(73.5, 27.6, 77.8, 32.6)) # the Bengal fire is outside the box
  expect_equal(got$lon, 75.8, tolerance = 0.04 / 76)
  expect_equal(got$time_utc, as.POSIXct("2026-11-01 11:30:00", tz = "UTC"))
  expect_equal(nrow(insat_fires("2026-11-01", satellite = "3R")), 0) # no slot has an image
})
