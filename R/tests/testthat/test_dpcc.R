# DPCC hourly pages: parsing, request windows, caching and the tidy table (offline)

dpcc_page <- function(hours, values) {
  paste0(
    "<html>Search Result of PM <script>xAxis: {categories: [", paste0("'", hours, "'", collapse = ","),
    "],}, series: [{ /*name: 'Tokyo', data: [7.0, 6.9]}, {*/ name: 'PM', data: [",
    paste(values, collapse = ","), "] }]</script></html>"
  )
}

test_that("the page's live series is read and empty hours skipped", {
  got <- parse_dpcc_page(dpcc_page(
    c("2026-11-09 01:00:00", "2026-11-09 02:00:00", "2026-11-09 03:00:00"),
    c("3124.0", "null", "2690.0")
  ))
  expect_equal(got$hour, c("2026-11-09 01:00:00", "2026-11-09 03:00:00"))
  expect_equal(got$value, c(3124, 2690))
  expect_equal(nrow(parse_dpcc_page("<html>Search Result of x</html>")), 0)
  expect_error(parse_dpcc_page("<html>Advance Search form only</html>"), "changed")
})

test_that("windows are at most six days and join up", {
  w <- .dpcc_windows(as.Date("2026-11-01"), as.Date("2026-11-10"))
  expect_equal(format(w[[1]][[1]], tz = "UTC"), "2026-10-31 23:00:00")
  expect_equal(format(w[[length(w)]][[2]], tz = "UTC"), "2026-11-10 23:00:00")
  expect_true(all(vapply(w, function(x) as.numeric(x[[2]] - x[[1]], units = "days") <= 6, logical(1))))
})

test_that("dpcc_hourly is tidy and keeps only the days asked", {
  seen <- character(0)
  local_mocked_bindings(.dpcc_fetch = function(code, par, page, w0, w1) {
    seen <<- c(seen, paste(code, par, page))
    dpcc_page(c("2026-11-08 23:00:00", "2026-11-09 02:00:00", "2026-11-10 00:00:00"), c("1636", "3744", "400"))
  })
  got <- dpcc_hourly("mundka", "2026-11-09", parameters = c("PM2.5", "O3"))
  expect_named(got, c("station_id", "station_name", "city", "state", "timestamp", "pollutant", "unit", "value"))
  expect_equal(seen, c("Mundka PM25 AallAdvanceSearchMet", "Mundka O3 AallAdvanceSearchCconc"))
  pm <- got[got$pollutant == "PM2.5", ]
  expect_equal(pm$value, 3744)
  expect_equal(format(pm$timestamp, tz = "UTC"), "2026-11-09 02:00:00")
  expect_setequal(got$pollutant, c("PM2.5", "Ozone"))
})

test_that("bad arguments are errors", {
  expect_error(dpcc_hourly("Mundka", "2024-12-31"), "2025-01-01")
  expect_error(dpcc_hourly("Gurugram", "2026-11-09"), "unknown DPCC station")
  expect_error(dpcc_hourly("JNU", "2026-11-09", parameters = "PM1"), "unknown DPCC parameter")
  expect_error(dpcc_hourly("JNU", "2026-11-09", "2026-11-01"), "before start")
  expect_equal(nrow(dpcc_stations()), 31)
})

test_that("old windows are cached and the request is the site's form", {
  old <- options(vayuayan.dpcc_pause = 0)
  on.exit(options(old))
  calls <- list()
  local_mocked_bindings(
    RETRY = function(verb, url, body, ...) {
      calls[[length(calls) + 1]] <<- list(url = url, body = body)
      structure(list(), class = "fake_resp")
    },
    stop_for_status = function(...) invisible(NULL),
    content = function(...) dpcc_page("2025-01-01 00:00:00", "90"),
    .package = "httr"
  )
  w0 <- as.POSIXct("2025-01-01 00:00:00", tz = "UTC")
  for (i in 1:2) .dpcc_fetch("Jnu", "PM25", "AallAdvanceSearchMet", w0, w0 + 86400)
  expect_length(calls, 1)
  expect_equal(calls[[1]]$url, "https://www.dpccairdata.com/dpccairdata/display/AallAdvanceSearchMet.php?stName=Sm51")
  expect_equal(calls[[1]]$body$fDate, "2025-01-01 00:00")
})
